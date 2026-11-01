"""The search engine: free-text search, mood search, similarity graph."""
import json
import re

import faiss
import numpy as np

from app import config
from app.embeddings import load_backend

# Each mood slider is represented by a short phrase that gets embedded; the
# sliders then blend those phrase vectors into one query vector.
MOOD_PHRASES = {
    "happy": "an uplifting, joyful, warm-hearted, feel-good story",
    "dark": "a bleak, disturbing, grim, unsettling story",
    "romantic": "a tender, passionate, love-focused story",
    "fast_paced": "a fast-paced, high-energy, tense, propulsive story",
}

_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "about", "where", "who",
    "what", "when", "his", "her", "their", "its", "into", "has", "have", "are",
    "was", "were", "but", "not", "you", "your", "movie", "film", "story",
}


def _tokens(text: str) -> set:
    """Lower-case content words of a text (no stopwords, no tiny words)."""
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS}


class IndexNotBuiltError(RuntimeError):
    """Raised when the search index has not been generated yet."""


class SearchEngine:
    def __init__(self):
        if not config.INDEX_PATH.exists() or not config.INFO_PATH.exists():
            raise IndexNotBuiltError(
                "Search index not found. Build it first:  python build_index.py "
                "(add --offline to skip the model download)."
            )

        with open(config.SEED_PATH, encoding="utf-8") as f:
            self.movies = json.load(f)
        with open(config.INFO_PATH, encoding="utf-8") as f:
            info = json.load(f)

        self.index = faiss.read_index(str(config.INDEX_PATH))
        if not (len(self.movies) == self.index.ntotal == info["count"]):
            raise IndexNotBuiltError(
                "The dataset and the search index do not match "
                f"({len(self.movies)} movies vs {self.index.ntotal} vectors). "
                "Run python build_index.py again."
            )

        # Ids equal list positions (checked in build_index.py), so lookups are O(1).
        self.backend_name = info["backend"]
        self.backend = load_backend(self.backend_name)
        self._mood_vecs = None  # computed on first use

    # ------------------------------------------------------------------ helpers

    @property
    def mood_vecs(self) -> dict:
        if self._mood_vecs is None:
            vecs = self.backend.encode(list(MOOD_PHRASES.values()))
            self._mood_vecs = dict(zip(MOOD_PHRASES.keys(), vecs))
        return self._mood_vecs

    def get_movie(self, movie_id: int):
        if 0 <= movie_id < len(self.movies):
            return self.movies[movie_id]
        return None

    def _search_vec(self, vec: np.ndarray, k: int):
        vec = np.asarray(vec, dtype="float32").reshape(1, -1)
        scores, idxs = self.index.search(vec, min(k, self.index.ntotal))
        return scores[0], idxs[0]

    @staticmethod
    def explain(query_text: str, movie: dict, score: float) -> dict:
        """Simple, inspectable explanation: cosine similarity plus the movie's own
        genres/keywords that share words with the query. A heuristic, not a model."""
        query_lower = query_text.lower()
        query_words = _tokens(query_text)

        matched_themes = [
            kw for kw in movie.get("keywords", [])
            if kw.lower() in query_lower or (_tokens(kw) & query_words)
        ]
        matched_genres = [g for g in movie.get("genres", []) if g.lower() in query_lower]

        return {
            "similarity_pct": round(float(score) * 100, 1),
            "matched_genres": matched_genres[:4],
            "matched_themes": list(dict.fromkeys(matched_themes))[:5],
        }

    # ------------------------------------------------------------------ public API

    def search(self, query_text: str, k: int = 20) -> list:
        """Movies whose meaning is closest to a free-text description."""
        scores, idxs = self._search_vec(self.backend.encode_one(query_text), k)
        return [
            {**self.movies[i], "explanation": self.explain(query_text, self.movies[i], s)}
            for s, i in zip(scores, idxs) if i >= 0
        ]

    def mood_search(self, sliders: dict, k: int = 20, base_query: str = "") -> list:
        """Blend mood directions (weights 0..1) and an optional text query.

        Raises ValueError if there is no signal at all (all sliders at zero and
        no text), because there would be nothing to search for.
        """
        vec = np.zeros(self.index.d, dtype="float32")
        total = 0.0

        for mood, weight in sliders.items():
            if mood in MOOD_PHRASES and weight > 0:
                vec += weight * self.mood_vecs[mood]
                total += weight

        if base_query.strip():
            vec += self.backend.encode_one(base_query)
            total += 1.0

        if total == 0:
            raise ValueError("Move at least one mood slider or add a short description.")

        vec /= np.linalg.norm(vec) or 1.0

        scores, idxs = self._search_vec(vec, k)
        return [
            {
                **self.movies[i],
                "explanation": {
                    "similarity_pct": round(float(s) * 100, 1),
                    "matched_genres": self.movies[i].get("genres", [])[:3],
                    "matched_themes": self.movies[i].get("keywords", [])[:4],
                },
            }
            for s, i in zip(scores, idxs) if i >= 0
        ]

    def neighbors(self, movie_id: int, k: int = 6) -> list:
        """The k movies most similar to movie_id (excluding itself)."""
        if self.get_movie(movie_id) is None:
            return []
        # The movie's own vector is already stored in the index; no need to re-embed.
        vec = self.index.reconstruct(movie_id)
        scores, idxs = self._search_vec(vec, k + 1)  # +1: the movie matches itself
        out = [
            {"movie": self.movies[i], "similarity_pct": round(float(s) * 100, 1)}
            for s, i in zip(scores, idxs) if i >= 0 and i != movie_id
        ]
        return out[:k]

    def graph(self, movie_id: int, depth: int = 1, k: int = 5, k_outer: int = None) -> dict:
        """Nodes and edges around a movie.

        depth=1: the movie and its k nearest neighbours (ring 1).
        depth=2: also, for each neighbour, its k_outer nearest movies that are
        not in the graph yet (ring 2). Links between movies that are already in
        the graph are kept too, so the result is a web rather than a tree. Every node carries its ``ring``
        (0 = the movie itself, 1 = direct neighbour, 2 = neighbour of a neighbour).
        """
        k_outer = k if k_outer is None else k_outer

        def node(m, ring):
            return {"id": m["id"], "title": m["title"], "year": m.get("year"),
                    "genres": m.get("genres", []), "poster_url": m.get("poster_url"),
                    "ring": ring}

        nodes = {movie_id: node(self.movies[movie_id], 0)}
        edges = {}
        frontier = [movie_id]

        for level in range(depth):
            next_frontier = []
            for mid in frontier:
                want = k if level == 0 else k_outer
                # Look further than `want`: close neighbours are often already in the
                # graph, and we want `want` *new* movies per node to keep the web growing.
                candidates = self.neighbors(mid, k=want + len(nodes) + 5)
                added = 0
                for rank, n in enumerate(candidates):
                    nid = n["movie"]["id"]
                    is_new = nid not in nodes
                    if is_new and added < want:
                        nodes[nid] = node(n["movie"], level + 1)
                        next_frontier.append(nid)
                        added += 1
                    elif is_new or rank >= want:
                        continue  # too far down the list to draw a link to
                    # else: already in the graph and among the closest -> keep as a cross-link
                    edges.setdefault(
                        tuple(sorted((mid, nid))),
                        {"source": mid, "target": nid, "weight": n["similarity_pct"]},
                    )
                    if added >= want and rank >= want:
                        break
            frontier = next_frontier

        return {"nodes": list(nodes.values()), "edges": list(edges.values())}


_engine = None


def get_engine() -> SearchEngine:
    """Return the shared engine (created on first use)."""
    global _engine
    if _engine is None:
        _engine = SearchEngine()
    return _engine
