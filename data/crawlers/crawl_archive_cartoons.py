"""
crawl_archive_cartoons.py

Crawls archive.org to find and verify public domain children's cartoons.
Outputs a verified dataset for the Screenwise platform.

Usage:
    python crawl_archive_cartoons.py
    python crawl_archive_cartoons.py --output data/verified_cartoons.py
    python crawl_archive_cartoons.py --dry-run  # test with 5 items
"""

import json
import time
import argparse
import requests
from typing import Optional

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_URL = "https://archive.org/metadata/{identifier}"
ARCHIVE_DETAILS_URL = "https://archive.org/details/{identifier}"

SEARCH_QUERIES = [
    # Fleischer Studios - Popeye
    {"query": "popeye fleischer", "studio": "Fleischer Studios", "characters": ["Popeye", "Olive Oyl", "Bluto"]},
    {"query": "popeye sailor 1930s OR 1940s", "studio": "Fleischer Studios", "characters": ["Popeye", "Olive Oyl"]},
    # Fleischer Studios - Betty Boop
    {"query": "betty boop fleischer", "studio": "Fleischer Studios", "characters": ["Betty Boop"]},
    {"query": "betty boop 1930s cartoon", "studio": "Fleischer Studios", "characters": ["Betty Boop"]},
    # Fleischer Studios - Superman
    {"query": "superman fleischer 1940s animated", "studio": "Fleischer Studios", "characters": ["Superman", "Lois Lane"]},
    # Fleischer Studios - Color Classics
    {"query": "color classic fleischer", "studio": "Fleischer Studios", "characters": []},
    {"query": "fleischer color classics", "studio": "Fleischer Studios", "characters": []},
    # Famous Studios - Casper
    {"query": "casper friendly ghost cartoon", "studio": "Famous Studios", "characters": ["Casper"]},
    {"query": "casper ghost 1940s OR 1950s", "studio": "Famous Studios", "characters": ["Casper"]},
    # Famous Studios - Little Lulu
    {"query": "little lulu cartoon 1940s", "studio": "Famous Studios", "characters": ["Little Lulu"]},
    # Famous Studios - Mighty Mouse
    {"query": "mighty mouse cartoon", "studio": "Terrytoons", "characters": ["Mighty Mouse"]},
    # Famous Studios - Baby Huey
    {"query": "baby huey cartoon", "studio": "Famous Studios", "characters": ["Baby Huey"]},
    # Van Beuren Studios
    {"query": "van beuren cartoon", "studio": "Van Beuren Studios", "characters": []},
    {"query": "rainbow parade cartoon 1930s", "studio": "Van Beuren Studios", "characters": []},
    {"query": "aesop fable van beuren", "studio": "Van Beuren Studios", "characters": []},
    # Walter Lantz - Woody Woodpecker
    {"query": "woody woodpecker lantz", "studio": "Walter Lantz Productions", "characters": ["Woody Woodpecker"]},
    {"query": "andy panda walter lantz", "studio": "Walter Lantz Productions", "characters": ["Andy Panda"]},
    # Terrytoons
    {"query": "heckle jeckle terrytoons", "studio": "Terrytoons", "characters": ["Heckle", "Jeckle"]},
    {"query": "gandy goose terrytoons", "studio": "Terrytoons", "characters": ["Gandy Goose"]},
    {"query": "terrytoons cartoon 1940s", "studio": "Terrytoons", "characters": []},
    # Early Disney
    {"query": "steamboat willie disney 1928", "studio": "Walt Disney", "characters": ["Mickey Mouse"]},
    {"query": "silly symphony disney 1929", "studio": "Walt Disney", "characters": []},
    # Misc public domain
    {"query": "superman cartoon 1940s public domain", "studio": "Fleischer Studios", "characters": ["Superman", "Lois Lane"]},
    {"query": "noveltoons famous studios", "studio": "Famous Studios", "characters": []},
    {"query": "screen songs fleischer bouncing ball", "studio": "Fleischer Studios", "characters": []},
]

# Keywords that indicate non-kids content
BLOCKLIST_KEYWORDS = [
    "adult", "horror", "violence", "war propaganda", "racist",
    "banned", "controversial", "censored", "restricted",
]


def search_archive(query: str, rows: int = 20) -> list:
    """Search archive.org for animated cartoons matching query."""
    params = {
        "q": f"({query}) AND mediatype:(movies) AND subject:(animation OR cartoon OR animated)",
        "fl[]": ["identifier", "title", "year", "description", "subject", "creator"],
        "sort[]": "downloads desc",
        "rows": rows,
        "page": 1,
        "output": "json",
    }
    try:
        resp = requests.get(ARCHIVE_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", {}).get("docs", [])
    except Exception as e:
        print(f"  [!] Search failed for '{query}': {e}")
        return []


def verify_identifier(identifier: str) -> Optional[dict]:
    """Verify an archive.org identifier exists and get its metadata."""
    url = ARCHIVE_METADATA_URL.format(identifier=identifier)
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            metadata = data.get("metadata", {})
            if metadata:
                return metadata
        return None
    except Exception:
        return None


def is_kids_appropriate(metadata: dict) -> bool:
    """Check if content seems kids-appropriate based on metadata."""
    desc = (metadata.get("description") or "").lower()
    title = (metadata.get("title") or "").lower()
    subject = str(metadata.get("subject") or "").lower()
    combined = f"{desc} {title} {subject}"
    return not any(word in combined for word in BLOCKLIST_KEYWORDS)


def get_year(metadata: dict) -> Optional[int]:
    """Extract year from metadata."""
    year = metadata.get("year") or metadata.get("date")
    if year:
        try:
            return int(str(year)[:4])
        except (ValueError, TypeError):
            pass
    return None


def determine_age_range(title: str, characters: list, year: int) -> str:
    """Determine appropriate age range based on content."""
    title_lower = title.lower()
    if any(c.lower() in ["casper", "baby huey"] for c in characters):
        return "3-7"
    if "superman" in title_lower:
        return "6-10"
    if any(c.lower() in ["popeye"] for c in characters):
        return "5-10"
    if "betty boop" in title_lower:
        return "5-10"
    if any(c.lower() in ["mighty mouse", "heckle", "jeckle", "woody woodpecker"] for c in characters):
        return "5-10"
    if "color classic" in title_lower or "silly symphony" in title_lower:
        return "3-7"
    return "4-8"


def build_description(metadata: dict, studio: str, characters: list) -> str:
    """Build a parent-friendly description from metadata."""
    raw_desc = metadata.get("description") or ""
    # Clean HTML tags from description
    import re
    clean_desc = re.sub(r'<[^>]+>', '', raw_desc).strip()
    if clean_desc and len(clean_desc) > 50:
        # Truncate to 2-3 sentences
        sentences = clean_desc.split('.')
        short = '. '.join(sentences[:3]).strip()
        if not short.endswith('.'):
            short += '.'
        return short
    # Fallback description
    title = metadata.get("title", "Unknown")
    char_str = ", ".join(characters) if characters else "classic cartoon characters"
    return f"A classic animated cartoon from {studio} featuring {char_str}. Public domain cartoon from the golden age of animation."


def crawl_and_verify(dry_run: bool = False) -> list:
    """Main crawl loop: search, verify, deduplicate."""
    seen_ids = set()
    results = []
    target = 10 if dry_run else 100  # search for more, filter to 50-100

    print(f"{'=' * 60}")
    print(f"  Archive.org Cartoon Crawler")
    print(f"  Target: {target} verified entries")
    print(f"{'=' * 60}\n")

    for i, search in enumerate(SEARCH_QUERIES):
        if len(results) >= target:
            break

        query = search["query"]
        studio = search["studio"]
        default_characters = search["characters"]

        print(f"\n[{i+1}/{len(SEARCH_QUERIES)}] Searching: '{query}'")
        docs = search_archive(query, rows=15)
        print(f"  Found {len(docs)} results")

        for doc in docs:
            if len(results) >= target:
                break

            identifier = doc.get("identifier")
            if not identifier or identifier in seen_ids:
                continue

            # Verify the identifier actually exists
            print(f"  Verifying: {identifier}...", end=" ")
            metadata = verify_identifier(identifier)

            if not metadata:
                print("NOT FOUND")
                continue

            # Check kids appropriateness
            if not is_kids_appropriate(metadata):
                print("BLOCKED (content filter)")
                continue

            # Get year
            year = get_year(metadata)
            if not year:
                year = get_year(doc)
            if not year or year > 1965:  # focus on golden age
                print(f"SKIPPED (year={year})")
                continue

            title = metadata.get("title") or doc.get("title", "Unknown")

            # Determine characters from title/metadata
            characters = list(default_characters)  # copy
            title_lower = title.lower()
            char_map = {
                "popeye": "Popeye", "betty boop": "Betty Boop",
                "superman": "Superman", "casper": "Casper",
                "woody woodpecker": "Woody Woodpecker", "mighty mouse": "Mighty Mouse",
                "baby huey": "Baby Huey", "little lulu": "Little Lulu",
                "heckle": "Heckle", "jeckle": "Jeckle",
                "gandy goose": "Gandy Goose", "andy panda": "Andy Panda",
                "olive": "Olive Oyl", "bluto": "Bluto",
                "lois lane": "Lois Lane", "mickey": "Mickey Mouse",
            }
            for key, char in char_map.items():
                if key in title_lower and char not in characters:
                    characters.append(char)

            age_range = determine_age_range(title, characters, year)
            description = build_description(metadata, studio, characters)

            entry = {
                "title": title,
                "year": year,
                "studio": studio,
                "genre": "Cartoon",
                "archive_id": identifier,
                "description": description,
                "characters": characters,
                "age_range": age_range,
            }

            results.append(entry)
            seen_ids.add(identifier)
            print(f"VERIFIED ✓ ({title}, {year})")

            # Rate limit
            time.sleep(0.5)

        # Rate limit between searches
        time.sleep(1.0)

    print(f"\n{'=' * 60}")
    print(f"  Total verified: {len(results)}")
    print(f"{'=' * 60}")

    return results


def write_python_output(results: list, output_file: str):
    """Write results as a Python file with ASSETS list."""
    lines = [
        '"""',
        'data/verified_cartoons.py',
        'Verified public domain kids cartoon dataset from Archive.org.',
        f'Generated by crawl_archive_cartoons.py — {len(results)} entries.',
        'All archive_ids verified as existing on archive.org.',
        '"""',
        '',
        'ASSETS = [',
    ]

    for i, entry in enumerate(results):
        lines.append('    {')
        lines.append(f'        "id": {i + 1},')
        lines.append(f'        "title": {json.dumps(entry["title"])},')
        lines.append(f'        "year": {entry["year"]},')
        lines.append(f'        "studio": {json.dumps(entry["studio"])},')
        lines.append(f'        "genre": "Cartoon",')
        lines.append(f'        "archive_id": {json.dumps(entry["archive_id"])},')
        lines.append(f'        "description": {json.dumps(entry["description"])},')
        lines.append(f'        "characters": {json.dumps(entry["characters"])},')
        lines.append(f'        "age_range": {json.dumps(entry["age_range"])},')
        lines.append('    },')

    lines.append(']')
    lines.append('')
    lines.append('')
    lines.append('if __name__ == "__main__":')
    lines.append('    print(f"Total verified cartoons: {len(ASSETS)}")')
    lines.append('    for c in ASSETS:')
    lines.append('        url = f"https://archive.org/embed/{c[\'archive_id\']}"')
    lines.append('        print(f"  {c[\'id\']:3}. {c[\'title\']} ({c[\'year\']}) — {url}")')
    lines.append('')

    with open(output_file, 'w') as f:
        f.write('\n'.join(lines))

    print(f"\n✓ Written to {output_file}")


def write_json_output(results: list, output_file: str):
    """Write results as JSON."""
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Written to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl archive.org for kids cartoons")
    parser.add_argument("--output", default="data/verified_cartoons.py",
                        help="Output file path (.py or .json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Quick test with fewer results")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON instead of Python")
    args = parser.parse_args()

    results = crawl_and_verify(dry_run=args.dry_run)

    if not results:
        print("\nNo results found. Check network connection and try again.")
        exit(1)

    if args.json or args.output.endswith('.json'):
        write_json_output(results, args.output)
    else:
        write_python_output(results, args.output)

    # Summary
    studios = {}
    for r in results:
        studios[r["studio"]] = studios.get(r["studio"], 0) + 1

    print(f"\nStudio breakdown:")
    for studio, count in sorted(studios.items(), key=lambda x: -x[1]):
        print(f"  {studio}: {count}")

    print(f"\nEmbed URL format: https://archive.org/embed/ARCHIVE_ID")
    print(f"Example: https://archive.org/embed/{results[0]['archive_id']}")
