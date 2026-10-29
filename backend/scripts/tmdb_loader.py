"""Download movies from the TMDB API and write data/movies_seed.json.

You need a free TMDB API key (https://www.themoviedb.org/settings/api). Never
put it in the code; pass it through the environment:

    export TMDB_API_KEY=your_key_here        # Windows (PowerShell): $env:TMDB_API_KEY="your_key_here"
    python -m scripts.tmdb_loader --pages 500

Each discover page holds 20 movies and TMDB serves at most 500 pages, so
--pages 500 gives up to 10,000 movies. Expect roughly an hour because the
script stays below TMDB's rate limit. The result is cleaned automatically
(see scripts/clean_seed.py).

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from scripts.clean_seed import clean_movies

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "movies_seed.json"
PAUSE_SECONDS = 0.25  # keeps us comfortably below TMDB's rate limit


class TMDBClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def get(self, path: str, **params):
        """GET with the API key and a few retries (also handles HTTP 429 'slow down')."""
        params["api_key"] = self.api_key
        for attempt in range(5):
            r = self.session.get(f"{BASE}{path}", params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 2)) + attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"TMDB kept rate-limiting {path}")


def parse_movie(details: dict) -> dict:
    """Turn a TMDB 'movie details' response (with credits and keywords appended)
    into the record format used by this project."""
    credits = details.get("credits") or {}
    director = next(
        (c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"), None
    )
    release = details.get("release_date") or ""
    poster = details.get("poster_path")

    return {
        "title": details.get("title"),
        "year": int(release[:4]) if release[:4].isdigit() else None,
        "genres": [g["name"] for g in details.get("genres", [])],
        "director": director,
        "actors": [c["name"] for c in credits.get("cast", [])[:5]],
        "keywords": [k["name"] for k in (details.get("keywords") or {}).get("keywords", [])],
        "overview": details.get("overview") or "",
        "poster_url": f"{IMAGE_BASE}{poster}" if poster else None,
    }


def fetch_movie_ids(client: TMDBClient, pages: int) -> list:
    ids = []
    for page in range(1, pages + 1):
        data = client.get("/discover/movie", page=page, sort_by="popularity.desc", include_adult="false", language="en-US")
        ids.extend(m["id"] for m in data["results"])
        print(f"Fetched ID page {page}/{pages}", end="\r")
        time.sleep(PAUSE_SECONDS)
    print()
    return list(dict.fromkeys(ids))  # remove repeated ids, keep order


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", type=int, default=500, help="discover pages to read (20 movies each, max 500)")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        sys.exit("Set the TMDB_API_KEY environment variable first (see the top of this file).")

    client = TMDBClient(api_key)
    ids = fetch_movie_ids(client, min(args.pages, 500))
    print(f"Found {len(ids)} movie ids. Downloading details...")

    movies = []
    for i, movie_id in enumerate(ids, start=1):
        try:
            # One request returns details, cast/crew and keywords together.
            details = client.get(f"/movie/{movie_id}", append_to_response="credits,keywords", language="en-US")
            movies.append(parse_movie(details))
        except Exception as e:
            print(f"\nSkipped movie {movie_id}: {e}")
        time.sleep(PAUSE_SECONDS)
        if i % 100 == 0:
            print(f"Processed {i}/{len(ids)}", end="\r")
    print()

    movies, stats = clean_movies(movies)  # also assigns the positional ids
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Saved {stats['output']} movies to {args.output} ({stats})")
    print("Next: python build_index.py")


if __name__ == "__main__":
    main()
