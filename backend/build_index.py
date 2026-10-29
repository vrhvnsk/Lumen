"""Build the FAISS search index from the movie dataset.

Run this once after cloning, and again whenever ``data/movies_seed.json`` changes:

    python build_index.py            # real semantic embeddings (first run downloads a model)
    python build_index.py --offline  # no download: TF-IDF/LSA fallback (weaker results)

Creates in ``data/`` (all git-ignored, they can be regenerated at any time):
    faiss.index       the vectors, one per movie, in dataset order
    index_info.json   which embedding backend was used, vector size, movie count
    tfidf_lsa.pkl     only for --offline: the fitted TF-IDF/LSA model
"""
import argparse
import json

import faiss

from app import config
from app.embeddings import build_backend
from app.textutil import movie_to_text


def main(prefer_offline: bool = False) -> None:
    if not config.SEED_PATH.exists():
        raise SystemExit(f"Dataset not found: {config.SEED_PATH}")

    with open(config.SEED_PATH, encoding="utf-8") as f:
        movies = json.load(f)

    # The search code finds a movie by its position in the list, so ids must
    # equal positions.
    if any(m["id"] != i for i, m in enumerate(movies)):
        raise SystemExit("Movie ids must equal list positions. Run scripts/clean_seed.py first.")

    texts = [movie_to_text(m) for m in movies]

    backend = build_backend(corpus=texts, prefer_offline=prefer_offline)
    print(f"[build_index] embedding backend: {backend.name} (dim={backend.dim})")

    vectors = backend.encode(texts, show_progress=True)  # (n_movies, dim), L2-normalised

    index = faiss.IndexFlatIP(vectors.shape[1])  # inner product on unit vectors = cosine
    index.add(vectors)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(config.INDEX_PATH))
    with open(config.INFO_PATH, "w", encoding="utf-8") as f:
        json.dump({"backend": backend.name, "dim": int(vectors.shape[1]), "count": len(movies)}, f)

    print(f"[build_index] indexed {len(movies)} movies -> {config.INDEX_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true",
                        help="skip the sentence-transformers download and use the TF-IDF/LSA fallback")
    main(prefer_offline=parser.parse_args().offline)
