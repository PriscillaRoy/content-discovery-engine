"""
store/generate_asset_metadata.py

Generates AI metadata for each cartoon using local Ollama (llama3.2).
Scores each title on:
  - calmness_score (0-100)
  - visual_stimulation (low/medium/high)
  - audio_intensity (low/medium/high)
  - emotional_intensity (low/medium/high)
  - conflict_level (low/medium/high)
  - educational_value (low/medium/high)
  - age_range (2-4 / 5-7 / 8-10 / 11+)
  - bedtime_friendly (true/false)
  - tags (list of descriptive tags)

Run once to generate metadata, then use insert_assets.py to seed DB.

Usage:
    python store/generate_asset_metadata.py
    python store/generate_asset_metadata.py --dry-run  # test one entry
"""

import json
import time
import argparse
import requests
from data.asset_seed_data import ASSETS

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"
OUTPUT_FILE = "data/asset_metadata.json"

SYSTEM_PROMPT = """You are a child development expert and animation historian.
You analyze children's cartoons and rate them on sensory, emotional, and educational dimensions.
You always respond with valid JSON only. No explanation, no markdown, no extra text."""

def build_prompt(asset: dict) -> str:
    return f"""Analyze this children's cartoon and rate it on the following dimensions.

Title: {asset['title']}
Year: {asset['year']}
Description: {asset['description']}

Return ONLY a JSON object with exactly these fields:
{{
  "calmness_score": <integer 0-100, where 100 is extremely calm/soothing>,
  "visual_stimulation": <"low" | "medium" | "high">,
  "audio_intensity": <"low" | "medium" | "high">,
  "emotional_intensity": <"low" | "medium" | "high">,
  "conflict_level": <"low" | "medium" | "high">,
  "educational_value": <"low" | "medium" | "high">,
  "age_range": <"2-4" | "5-7" | "8-10" | "11+">,
  "bedtime_friendly": <true | false>,
  "tags": [<3-5 short descriptive tags like "slapstick", "musical", "adventure", "friendship", "nature">],
  "ai_summary": "<one sentence parent-friendly summary of what makes this appropriate or notable>"
}}

Base your ratings on:
- calmness_score: pacing, visual chaos, loud sounds, conflict intensity
- visual_stimulation: how fast scenes change, how busy/colorful the visuals are
- audio_intensity: music volume, sound effects, shouting
- emotional_intensity: scary moments, sad moments, tension
- conflict_level: fighting, chasing, danger
- educational_value: learning opportunities, moral lessons, creativity
- bedtime_friendly: calm enough for bedtime viewing (calmness > 70, no scary elements)"""


def call_ollama(prompt: str) -> dict:
    """Call local Ollama API and parse JSON response."""
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.1,  # low temp for consistent structured output
                "top_p": 0.9,
            }
        },
        timeout=60
    )
    response.raise_for_status()
    raw = response.json()["response"].strip()

    # strip markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


def generate_metadata(assets: list, dry_run: bool = False) -> list:
    """Generate metadata for all assets."""
    results = []
    targets = assets[:1] if dry_run else assets

    for i, asset in enumerate(targets):
        print(f"\n[{i+1}/{len(targets)}] Scoring: {asset['title']} ({asset['year']})")

        try:
            prompt = build_prompt(asset)
            metadata = call_ollama(prompt)

            # merge with original asset data
            enriched = {**asset, **metadata}
            results.append(enriched)

            print(f"  ✓ calmness={metadata['calmness_score']} "
                  f"visual={metadata['visual_stimulation']} "
                  f"audio={metadata['audio_intensity']} "
                  f"bedtime={metadata['bedtime_friendly']}")
            print(f"  → {metadata['ai_summary']}")

            # small delay to not overwhelm Ollama
            if not dry_run:
                time.sleep(0.5)

        except json.JSONDecodeError as e:
            print(f"  ✗ JSON parse error: {e}")
            print(f"    Skipping {asset['title']} — add manually")
            results.append(asset)  # keep original without metadata

        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append(asset)

    return results


def save_results(results: list, output_file: str):
    """Save enriched asset data to JSON file."""
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Saved {len(results)} assets to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Test with first asset only")
    parser.add_argument("--output", default=OUTPUT_FILE,
                        help="Output JSON file path")
    args = parser.parse_args()

    print(f"Generating metadata for {len(ASSETS)} assets using {MODEL}...")
    print(f"Dry run: {args.dry_run}\n")

    results = generate_metadata(ASSETS, dry_run=args.dry_run)
    save_results(results, args.output)

    if args.dry_run:
        print("\n--- Sample output ---")
        print(json.dumps(results[0], indent=2))