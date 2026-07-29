#!/usr/bin/env python3
"""
Screenwise Archive.org cartoon crawler + verifier + feature enricher.

What this does:
1. Searches Internet Archive for public-domain / classic children's cartoons.
2. Verifies each archive_id through https://archive.org/metadata/{identifier}.
3. Confirms each item has a playable video file.
4. Builds https://archive.org/embed/{identifier}.
5. Produces Screenwise metadata:
   - studio
   - characters
   - age_range
   - public_domain_basis
   - calmness_score
   - visual_stimulation
   - audio_intensity
   - emotional_intensity
   - conflict_level
   - educational_value
   - bedtime_friendly
   - tags
6. Optional: uses ffmpeg/ffprobe against Archive.org video URLs to estimate
   scene cuts per minute and audio intensity.
7. Optional: uses local Ollama to generate parent-friendly summaries.

Install:
    pip install requests tqdm

Optional video analysis:
    brew install ffmpeg        # macOS
    sudo apt install ffmpeg    # Ubuntu

Optional AI summaries:
    ollama pull llama3.2
    ollama serve

Examples:
    python screenwise_archive_crawler.py --target 50 --output screenwise_assets.json
    python screenwise_archive_crawler.py --target 100 --analyze-video --max-video-analyze 20
    python screenwise_archive_crawler.py --seed-only --input-seed asset_seed_data.py --verify-seed

    python3 -m data.crawlers.screenwise_archive_crawler --target 50 --output screenwise_assets.json --output-py screenwise_assets.py --output-csv screenwise_assets.csv

Notes:
- Copyright/public-domain status is hard to prove automatically. This script gives a
  public_domain_basis and marks needs_legal_review=True unless the item metadata/year
  strongly supports public-domain status.
- Archive.org metadata availability does not equal legal clearance. For production,
  keep a human review step for rights.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests
try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = lambda x, **kwargs: x

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_URL = "https://archive.org/metadata/{identifier}"
ARCHIVE_DETAILS_URL = "https://archive.org/details/{identifier}"
ARCHIVE_EMBED_URL = "https://archive.org/embed/{identifier}"
ARCHIVE_DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"

VIDEO_FORMATS = {
    "h.264", "h264", "mpeg4", "512kb mpeg4", "mpeg2", "mpeg1", "ogv", "matroska",
    "quicktime", "mp4", "movie", "item tile", "animated gif"
}
VIDEO_EXTS = (".mp4", ".m4v", ".ogv", ".webm", ".mov", ".avi", ".mpg", ".mpeg", ".mkv")
BAD_EXTS = ("_thumbs.zip", "_files.xml", "_meta.xml", "_archive.torrent", ".gif")

SEARCH_QUERIES = [
    # General public domain cartoon searches.
    '(mediatype:movies) AND (subject:"public domain" OR title:"public domain") AND (cartoon OR animation OR animated)',
    '(mediatype:movies) AND collection:animationandcartoons AND (subject:"public domain" OR description:"public domain")',

    # Studios / characters requested for Screenwise.
    '(mediatype:movies) AND (Popeye OR Fleischer) AND (cartoon OR animation)',
    '(mediatype:movies) AND ("Betty Boop" OR "Color Classics" OR "Fleischer Studios")',
    '(mediatype:movies) AND (Superman AND Fleischer AND cartoon)',
    '(mediatype:movies) AND (Casper OR "Little Lulu" OR "Baby Huey" OR Noveltoons)',
    '(mediatype:movies) AND ("Van Beuren" OR "Aesop" OR "Rainbow Parade")',
    '(mediatype:movies) AND ("Woody Woodpecker" OR "Andy Panda" OR "Walter Lantz")',
    '(mediatype:movies) AND (Terrytoons OR "Mighty Mouse" OR "Heckle and Jeckle" OR "Gandy Goose")',
    '(mediatype:movies) AND ("Felix the Cat" OR "Koko the Clown" OR "Out of the Inkwell")',
    '(mediatype:movies) AND ("Silly Symphony" OR "Steamboat Willie" OR "Oswald the Lucky Rabbit")',
]

ADULT_OR_BAD_TERMS = [
    "adult", "erotic", "sex", "nude", "nudity", "pin-up", "pinup", "burlesque",
    "racist", "propaganda", "suicide", "horror", "gore", "drug", "marijuana",
]

STUDIO_RULES = [
    ("Fleischer", "Fleischer Studios"),
    ("Popeye", "Fleischer Studios"),
    ("Betty Boop", "Fleischer Studios"),
    ("Superman", "Fleischer Studios"),
    ("Color Classic", "Fleischer Studios"),
    ("Famous Studios", "Famous Studios"),
    ("Casper", "Famous Studios"),
    ("Little Lulu", "Famous Studios"),
    ("Baby Huey", "Famous Studios"),
    ("Noveltoons", "Famous Studios"),
    ("Van Beuren", "Van Beuren Studios"),
    ("Aesop", "Van Beuren Studios"),
    ("Rainbow Parade", "Van Beuren Studios"),
    ("Walter Lantz", "Walter Lantz Productions"),
    ("Woody Woodpecker", "Walter Lantz Productions"),
    ("Andy Panda", "Walter Lantz Productions"),
    ("Terrytoons", "Terrytoons"),
    ("Mighty Mouse", "Terrytoons"),
    ("Heckle", "Terrytoons"),
    ("Jeckle", "Terrytoons"),
    ("Gandy Goose", "Terrytoons"),
    ("Disney", "Walt Disney Studio"),
    ("Steamboat Willie", "Walt Disney Studio"),
    ("Silly Symphony", "Walt Disney Studio"),
    ("Iwerks", "Iwerks Studio"),
    ("Felix", "Pat Sullivan / Otto Messmer"),
]

CHARACTER_RULES = [
    ("Popeye", ["Popeye", "Olive Oyl", "Bluto"]),
    ("Sindbad", ["Popeye", "Olive Oyl", "Wimpy", "Sindbad"]),
    ("Ali Baba", ["Popeye", "Olive Oyl", "Wimpy", "Abu Hassan"]),
    ("Betty Boop", ["Betty Boop"]),
    ("Grampy", ["Betty Boop", "Grampy"]),
    ("Superman", ["Superman", "Lois Lane"]),
    ("Casper", ["Casper"]),
    ("Little Lulu", ["Little Lulu"]),
    ("Lulu", ["Little Lulu"]),
    ("Baby Huey", ["Baby Huey"]),
    ("Woody", ["Woody Woodpecker"]),
    ("Andy Panda", ["Andy Panda"]),
    ("Mighty Mouse", ["Mighty Mouse"]),
    ("Heckle", ["Heckle", "Jeckle"]),
    ("Jeckle", ["Heckle", "Jeckle"]),
    ("Gandy Goose", ["Gandy Goose"]),
    ("Felix", ["Felix the Cat"]),
    ("Koko", ["Koko the Clown"]),
    ("Oswald", ["Oswald the Lucky Rabbit"]),
    ("Mickey", ["Mickey Mouse", "Minnie Mouse"]),
]
REJECT_CONTENT_KEYWORDS = [
    "bonanza",
    "rifleman",
    "wagon train",
    "western television",
    "western tv",
    "crime drama",
    "feature film",
    "tv episode",
    "television program",
    "live action",
]

REQUIRE_CARTOON_KEYWORDS = [
    "cartoon",
    "animation",
    "animated",
    "popeye",
    "betty boop",
    "casper",
    "superman",
    "woody woodpecker",
    "andy panda",
    "mighty mouse",
    "heckle",
    "jeckle",
    "terrytoons",
    "fleischer",
    "famous studios",
    "van beuren",
    "color classics",
    "noveltoons",
    "felix",
]

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_year(*values: Any) -> Optional[int]:
    for value in values:
        text = clean_text(value)
        match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", text)
        if match:
            return int(match.group(1))
    return None


def archive_get_json(url: str, params: Optional[dict] = None, timeout: int = 30) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "ScreenwiseCrawler/1.0"})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def search_archive(query: str, rows: int = 50, page: int = 1) -> List[dict]:
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "date", "year", "creator", "description", "subject", "collection"],
        "rows": rows,
        "page": page,
        "output": "json",
        "sort[]": "downloads desc",
    }
    data = archive_get_json(ARCHIVE_SEARCH_URL, params=params)
    if not data:
        return []
    return data.get("response", {}).get("docs", []) or []


def choose_video_file(files: List[dict]) -> Optional[dict]:
    candidates = []
    for f in files:
        name = f.get("name", "")
        fmt = clean_text(f.get("format", "")).lower()
        if not name or name.lower().endswith(BAD_EXTS):
            continue
        is_video = name.lower().endswith(VIDEO_EXTS) or any(v in fmt for v in VIDEO_FORMATS)
        if not is_video:
            continue
        # Prefer mp4/h264/webm over huge legacy formats.
        score = 0
        lname = name.lower()
        if lname.endswith(".mp4"):
            score += 50
        if "h.264" in fmt or "h264" in fmt:
            score += 40
        if lname.endswith(".webm"):
            score += 30
        if lname.endswith(".ogv"):
            score += 20
        try:
            size = int(f.get("size", 0))
        except Exception:
            size = 0
        if size > 0:
            score += min(20, int(math.log10(size)))
        candidates.append((score, f))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]


def verify_item(identifier: str) -> Optional[dict]:
    data = archive_get_json(ARCHIVE_METADATA_URL.format(identifier=quote(identifier)))
    if not data or "metadata" not in data:
        return None
    metadata = data.get("metadata") or {}
    files = data.get("files") or []
    video_file = choose_video_file(files)
    if not video_file:
        return None
    return {"metadata": metadata, "files": files, "video_file": video_file}


def classify_studio(blob: str) -> str:
    low = blob.lower()
    for key, studio in STUDIO_RULES:
        if key.lower() in low:
            return studio
    return "Unknown"


def extract_characters(blob: str) -> List[str]:
    found = []
    low = blob.lower()
    for key, chars in CHARACTER_RULES:
        if key.lower() in low:
            for c in chars:
                if c not in found:
                    found.append(c)
    return found or ["Unknown"]


def family_filter(blob: str) -> bool:
    low = blob.lower()

    if any(term in low for term in ADULT_OR_BAD_TERMS):
        return False

    if any(term in low for term in REJECT_CONTENT_KEYWORDS):
        return False

    if not any(term in low for term in REQUIRE_CARTOON_KEYWORDS):
        return False

    return True


def public_domain_basis(metadata: dict, year: Optional[int], blob: str) -> Tuple[str, bool, float]:
    low = blob.lower()
    licenseurl = clean_text(metadata.get("licenseurl")).lower()
    rights = clean_text(metadata.get("rights")).lower()
    subjects = clean_text(metadata.get("subject")).lower()

    if year and year <= 1928:
        return "Pre-1929 publication; likely U.S. public domain by age.", False, 0.95
    if "public domain" in low or "public domain" in rights or "public domain" in subjects:
        return "Archive metadata/description/subjects mention public domain.", True, 0.80
    if "creativecommons.org/publicdomain" in licenseurl or "cc0" in licenseurl:
        return "Archive item has public-domain/CC0-style license URL.", False, 0.90
    if year and year <= 1963:
        return "Published 1929-1963; may be public domain if copyright was not renewed. Needs rights review.", True, 0.45
    return "No automatic public-domain basis found. Needs rights review.", True, 0.20


def infer_age_range(blob: str, studio: str) -> str:
    low = blob.lower()
    if any(x in low for x in ["casper", "baby huey", "tubby", "rudolph", "mother goose", "little dutch", "song of the birds"]):
        return "3-7"
    if any(x in low for x in ["superman", "scientist", "monster", "volcano", "earthquake", "war", "thieves"]):
        return "6-10"
    if any(x in low for x in ["popeye", "woody", "heckle", "jeckle", "mighty mouse"]):
        return "5-10"
    return "4-8"


def heuristic_features(title: str, description: str, studio: str, year: Optional[int]) -> dict:
    blob = f"{title} {description} {studio}".lower()
    calmness = 72
    conflict = "low"
    visual = "medium"
    audio = "medium"
    emotional = "low"
    educational = "medium"
    tags = []

    def add_tag(t: str):
        if t not in tags:
            tags.append(t)

    if any(x in blob for x in ["casper", "mother goose", "tubby", "little dutch", "song of the birds", "rudolph"]):
        calmness += 12
        visual = "low"
        audio = "low"
        conflict = "low"
        add_tag("gentle")
    if any(x in blob for x in ["popeye", "woody", "heckle", "jeckle", "mighty mouse", "tom and jerry"]):
        calmness -= 18
        visual = "high"
        conflict = "medium"
        add_tag("slapstick")
    if any(x in blob for x in ["superman", "monster", "villain", "thieves", "mad scientist", "earthquake", "volcano", "war", "battle", "danger"]):
        calmness -= 24
        conflict = "high"
        emotional = "medium"
        visual = "high"
        add_tag("adventure")
    if any(x in blob for x in ["music", "song", "sing", "tuba", "birds", "symphony"]):
        educational = "medium"
        add_tag("musical")
    if any(x in blob for x in ["invention", "inventor", "science", "einstein", "school"]):
        educational = "high"
        add_tag("learning")
    if any(x in blob for x in ["friend", "kindness", "loneliness", "different", "acceptance"]):
        educational = "medium"
        add_tag("friendship")

    calmness = max(15, min(95, calmness))
    if calmness >= 78:
        visual = "low" if visual != "high" else "medium"
        audio = "low" if audio != "high" else "medium"
    if not tags:
        tags = ["classic", "cartoon", "family"]
    bedtime = calmness >= 75 and conflict == "low" and emotional != "high"

    return {
        "calmness_score": calmness,
        "visual_stimulation": visual,
        "audio_intensity": audio,
        "emotional_intensity": emotional,
        "conflict_level": conflict,
        "educational_value": educational,
        "bedtime_friendly": bedtime,
        "tags": tags[:5],
    }


def run_cmd(args: List[str], timeout: int = 90) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)


def ffprobe_duration(video_url: str) -> Optional[float]:
    if not shutil.which("ffprobe"):
        return None
    code, out, err = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_url
    ], timeout=60)
    if code == 0:
        try:
            return float(out.strip())
        except Exception:
            pass
    return None


def ffmpeg_scene_cuts(video_url: str, duration: Optional[float]) -> Optional[float]:
    if not shutil.which("ffmpeg") or not duration:
        return None
    # Analyze a max 10-minute window to avoid huge runs.
    analyze_seconds = min(duration, 600)
    code, out, err = run_cmd([
        "ffmpeg", "-hide_banner", "-ss", "0", "-t", str(int(analyze_seconds)), "-i", video_url,
        "-filter:v", "select='gt(scene,0.35)',showinfo", "-an", "-f", "null", "-"
    ], timeout=180)
    text = out + err
    cuts = len(re.findall(r"showinfo", text))
    if analyze_seconds <= 0:
        return None
    return round(cuts / (analyze_seconds / 60.0), 2)


def ffmpeg_audio_intensity(video_url: str, duration: Optional[float]) -> Optional[str]:
    if not shutil.which("ffmpeg") or not duration:
        return None
    analyze_seconds = min(duration, 300)
    code, out, err = run_cmd([
        "ffmpeg", "-hide_banner", "-ss", "0", "-t", str(int(analyze_seconds)), "-i", video_url,
        "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-"
    ], timeout=120)
    text = out + err
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", text)
    if not m:
        return None
    mean_db = float(m.group(1))
    if mean_db > -18:
        return "high"
    if mean_db > -28:
        return "medium"
    return "low"


def apply_video_features(asset: dict) -> dict:
    video_url = asset.get("download_url")
    if not video_url:
        return asset
    duration = ffprobe_duration(video_url)
    if duration:
        asset["runtime_minutes"] = round(duration / 60.0, 1)
        cuts_per_minute = ffmpeg_scene_cuts(video_url, duration)
        if cuts_per_minute is not None:
            asset["scene_cuts_per_minute"] = cuts_per_minute
            if cuts_per_minute < 5:
                asset["visual_stimulation"] = "low"
            elif cuts_per_minute < 12:
                asset["visual_stimulation"] = "medium"
            else:
                asset["visual_stimulation"] = "high"
            # Adjust calmness based on actual cuts.
            penalty = min(25, max(0, int((cuts_per_minute - 5) * 2)))
            asset["calmness_score"] = max(10, min(98, int(asset.get("calmness_score", 70)) - penalty))
        actual_audio = ffmpeg_audio_intensity(video_url, duration)
        if actual_audio:
            asset["audio_intensity"] = actual_audio
            if actual_audio == "high":
                asset["calmness_score"] = max(10, int(asset.get("calmness_score", 70)) - 8)
    asset["bedtime_friendly"] = bool(asset.get("calmness_score", 0) >= 75 and asset.get("conflict_level") == "low" and asset.get("audio_intensity") != "high")
    return asset


def ollama_summary(asset: dict) -> Optional[dict]:
    prompt = f"""Return ONLY valid JSON for this children's cartoon.

Title: {asset.get('title')}
Year: {asset.get('year')}
Studio: {asset.get('studio')}
Description: {asset.get('description')}
Current features: calmness={asset.get('calmness_score')}, conflict={asset.get('conflict_level')}, visual={asset.get('visual_stimulation')}

JSON fields:
{{
  "description": "2 parent-friendly sentences, no spoilers, mention tone and suitability",
  "ai_summary": "one short parent-facing sentence",
  "tags": ["3-5 short tags"]
}}
"""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "system": "You are a child-development-aware animation curator. Return JSON only.",
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].replace("json", "", 1).strip()
        return json.loads(raw)
    except Exception:
        return None


def build_asset(identifier: str, verified: dict, search_doc: Optional[dict] = None) -> Optional[dict]:
    metadata = verified["metadata"]
    video_file = verified["video_file"]
    title = clean_text(metadata.get("title") or (search_doc or {}).get("title") or identifier)
    description = clean_text(metadata.get("description") or (search_doc or {}).get("description") or "Classic public-domain cartoon from the golden age of animation.")
    year = parse_year(metadata.get("date"), metadata.get("year"), title, description)
    blob = " ".join([
        title, description, clean_text(metadata.get("creator")), clean_text(metadata.get("subject")),
        clean_text(metadata.get("collection")), identifier,
    ])
    if not family_filter(blob):
        return None

    studio = classify_studio(blob)
    chars = extract_characters(blob)
    basis, needs_review, confidence = public_domain_basis(metadata, year, blob)
    features = heuristic_features(title, description, studio, year)
    filename = video_file.get("name")
    download_url = ARCHIVE_DOWNLOAD_URL.format(identifier=quote(identifier), filename=quote(filename)) if filename else None

    asset = {
        "title": title,
        "year": year,
        "studio": studio,
        "archive_id": identifier,
        "details_url": ARCHIVE_DETAILS_URL.format(identifier=identifier),
        "embed_url": ARCHIVE_EMBED_URL.format(identifier=identifier),
        "download_url": download_url,
        "video_filename": filename,
        "description": description[:800],
        "characters": chars,
        "age_range": infer_age_range(blob, studio),
        "runtime_minutes": None,
        "public_domain_basis": basis,
        "public_domain_confidence": confidence,
        "needs_legal_review": needs_review,
        "verified": True,
        **features,
    }
    return asset


def dedupe_assets(assets: List[dict]) -> List[dict]:
    seen_ids = set()
    seen_title_year = set()
    out = []
    for a in assets:
        aid = a.get("archive_id")
        key = (re.sub(r"\W+", "", (a.get("title") or "").lower()), a.get("year"))
        if aid in seen_ids or key in seen_title_year:
            continue
        seen_ids.add(aid)
        seen_title_year.add(key)
        out.append(a)
    return out


def load_seed(path: str) -> List[dict]:
    spec = importlib.util.spec_from_file_location("screenwise_seed", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not import seed file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    if hasattr(module, "ASSETS"):
        return list(module.ASSETS)
    if hasattr(module, "CARTOONS"):
        return list(module.CARTOONS)
    raise RuntimeError("Seed file must define ASSETS or CARTOONS")


def crawl(args: argparse.Namespace) -> List[dict]:
    candidates: Dict[str, dict] = {}

    if args.input_seed:
        for item in load_seed(args.input_seed):
            identifier = item.get("archive_id")
            if identifier:
                candidates[identifier] = item

    if not args.seed_only:
        for query in SEARCH_QUERIES:
            for page in range(1, args.pages_per_query + 1):
                docs = search_archive(query, rows=args.rows_per_page, page=page)
                for doc in docs:
                    identifier = doc.get("identifier")
                    if identifier and identifier not in candidates:
                        candidates[identifier] = doc
                time.sleep(args.delay)

    print(f"Found {len(candidates)} candidate identifiers. Verifying...")
    assets = []
    analyzed_count = 0

    for identifier, doc in tqdm(list(candidates.items())):
        if len(assets) >= args.target:
            break
        verified = verify_item(identifier)
        if not verified:
            continue
        asset = build_asset(identifier, verified, doc)
        if not asset:
            continue
        if args.analyze_video and analyzed_count < args.max_video_analyze:
            asset = apply_video_features(asset)
            analyzed_count += 1
        if args.use_ollama:
            enriched = ollama_summary(asset)
            if enriched:
                for k in ["description", "ai_summary", "tags"]:
                    if k in enriched:
                        asset[k] = enriched[k]
        else:
            asset["ai_summary"] = f"A classic {asset['studio']} cartoon with {asset['visual_stimulation']} visual stimulation and {asset['conflict_level']} conflict."
        assets.append(asset)
        assets = dedupe_assets(assets)
        time.sleep(args.delay)

    assets = sorted(assets, key=lambda x: (x.get("year") or 9999, x.get("title") or ""))
    for i, a in enumerate(assets, start=1):
        a["id"] = i
    return assets[: args.target]


def save_outputs(assets: List[dict], output_json: str, output_py: Optional[str] = None, output_csv: Optional[str] = None) -> None:
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(assets, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON: {output_json} ({len(assets)} assets)")

    if output_py:
        with open(output_py, "w", encoding="utf-8") as f:
            f.write("# Auto-generated by screenwise_archive_crawler.py\n")
            f.write("ASSETS = ")
            f.write(json.dumps(assets, indent=2, ensure_ascii=False))
            f.write("\n")
        print(f"Saved Python module: {output_py}")

    if output_csv:
        if not assets:
            return
        fields = list(assets[0].keys())
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for a in assets:
                row = dict(a)
                for k, v in row.items():
                    if isinstance(v, (list, dict)):
                        row[k] = json.dumps(v, ensure_ascii=False)
                writer.writerow(row)
        print(f"Saved CSV: {output_csv}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Screenwise Archive.org cartoon crawler")
    parser.add_argument("--target", type=int, default=50, help="Number of verified assets to output")
    parser.add_argument("--output", default="screenwise_assets.json", help="Output JSON file")
    parser.add_argument("--output-py", default="screenwise_assets.py", help="Output Python ASSETS module")
    parser.add_argument("--output-csv", default="screenwise_assets.csv", help="Output CSV file")
    parser.add_argument("--input-seed", default=None, help="Optional seed Python file with ASSETS or CARTOONS")
    parser.add_argument("--seed-only", action="store_true", help="Only verify/enrich seed records; do not crawl search")
    parser.add_argument("--verify-seed", action="store_true", help="Alias behavior: seed IDs are always verified if provided")
    parser.add_argument("--pages-per-query", type=int, default=2)
    parser.add_argument("--rows-per-page", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between Archive.org calls")
    parser.add_argument("--analyze-video", action="store_true", help="Use ffmpeg/ffprobe to estimate runtime, scene cuts, and audio")
    parser.add_argument("--max-video-analyze", type=int, default=10, help="Max videos for ffmpeg analysis")
    parser.add_argument("--use-ollama", action="store_true", help="Use local Ollama for parent descriptions/summaries")
    args = parser.parse_args()

    assets = crawl(args)
    save_outputs(assets, args.output, args.output_py, args.output_csv)

    if len(assets) < args.target:
        print(f"WARNING: requested {args.target}, produced {len(assets)} verified assets. Increase pages/query or loosen filters.")


if __name__ == "__main__":
    main()
