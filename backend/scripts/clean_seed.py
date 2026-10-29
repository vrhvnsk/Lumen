"""Clean the movie dataset.

Rules:
  * drop movies with a missing or very short overview (nothing to search on),
  * drop exact duplicates (same title, year and overview),
  * renumber ids so that id == position in the list (the search code relies on it).

Different films that merely share a title (remakes, for example) are kept.

Usage (from the backend folder):
    python -m scripts.clean_seed                # cleans data/movies_seed.json in place
    python -m scripts.clean_seed --input a.json --output b.json
"""
import argparse
import json
from pathlib import Path

MIN_OVERVIEW_CHARS = 30
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "movies_seed.json"


def clean_movies(movies: list) -> tuple:
    """Return (cleaned list, stats dict). Safe to run repeatedly."""
    kept, seen = [], set()
    stats = {"input": len(movies), "dropped_short_overview": 0, "dropped_duplicates": 0}

    for m in movies:
        overview = (m.get("overview") or "").strip()
        if len(overview) < MIN_OVERVIEW_CHARS:
            stats["dropped_short_overview"] += 1
            continue

        key = (m.get("title"), m.get("year"), overview)
        if key in seen:
            stats["dropped_duplicates"] += 1
            continue
        seen.add(key)

        kept.append({**m, "overview": overview})

    for i, m in enumerate(kept):
        m["id"] = i

    stats["output"] = len(kept)
    return kept, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--output", type=Path, default=None, help="default: overwrite the input file")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        movies = json.load(f)

    cleaned, stats = clean_movies(movies)

    with open(args.output or args.input, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, separators=(",", ":"))

    print(stats)


if __name__ == "__main__":
    main()
