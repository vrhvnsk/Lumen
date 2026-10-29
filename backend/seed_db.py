"""Load data/movies_seed.json into the configured SQL database (optional).

Search works without this step. See app/database.py for how to switch to PostgreSQL.

    python seed_db.py
"""
import json

from app import config
from app.database import Movie, SessionLocal, init_db


def main():
    init_db()
    with open(config.SEED_PATH, encoding="utf-8") as f:
        movies = json.load(f)

    with SessionLocal() as db:
        db.query(Movie).delete()
        db.add_all(
            Movie(
                id=m["id"], title=m["title"], year=m.get("year"),
                director=m.get("director"), overview=m.get("overview"),
                poster_url=m.get("poster_url"), genres=m.get("genres", []),
                actors=m.get("actors", []), keywords=m.get("keywords", []),
            )
            for m in movies
        )
        db.commit()

    print(f"Loaded {len(movies)} movies into the database.")


if __name__ == "__main__":
    main()
