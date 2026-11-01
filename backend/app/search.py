"""The search engine: free-text search, mood search, similarity graph."""
import json
import re
import unicodedata
from collections import Counter, defaultdict

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


def _norm(text: str) -> str:
    """Lower-case, strip accents, keep letters/digits of any script, collapse the rest to spaces."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def _trigrams(norm: str) -> set:
    """Character trigrams of a normalised string; padding makes word starts count."""
    padded = f"  {norm} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


_YEAR = re.compile(r"(?<!\d)(18|19|20)\d{2}(?!\d)")
_FILLER = {"movie", "film"}


def split_year(query: str):
    """'Forrest Gump 1994' -> ('Forrest Gump', 1994). The year is optional."""
    match = _YEAR.search(query)
    if not match:
        return query.strip(), None
    cleaned = (query[:match.start()] + " " + query[match.end():]).replace("()", " ")
    return re.sub(r"\s+", " ", cleaned).strip(" ,-()"), int(match.group())


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
        self.popularity = self._popularity_scores()

        # Optional quality data (only present in datasets downloaded with the current loader).
        self.has_votes = any(m.get("vote_count") is not None for m in self.movies)
        self.votes = np.array([m.get("vote_count") or 0 for m in self.movies], dtype="float32")
        self.ratings = np.array([m.get("vote_average") or 0 for m in self.movies], dtype="float32")
        self._allowed_cache = {}

        self._build_title_index()

    # ------------------------------------------------------------------ helpers

    @property
    def mood_vecs(self) -> dict:
        if self._mood_vecs is None:
            vecs = self.backend.encode(list(MOOD_PHRASES.values()))
            self._mood_vecs = dict(zip(MOOD_PHRASES.keys(), vecs))
        return self._mood_vecs

    def _popularity_scores(self) -> np.ndarray:
        """One number per movie in 0..1 (1 = most popular), used to favour popular films.

        If the dataset carries TMDB's ``popularity`` value it is turned into a
        percentile (so a handful of blockbusters cannot dominate the scale).
        Older datasets have no such field, but they were downloaded sorted by
        popularity, so a movie's position (= its id) is its popularity rank.
        """
        n = len(self.movies)
        if n < 2:
            return np.ones(n, dtype="float32")
        if all(m.get("popularity") is not None for m in self.movies):
            order = np.argsort(np.argsort([m["popularity"] for m in self.movies]))
            return (order / (n - 1)).astype("float32")
        return (1 - np.arange(n) / (n - 1)).astype("float32")

    def get_movie(self, movie_id: int):
        if 0 <= movie_id < len(self.movies):
            return self.movies[movie_id]
        return None

    # ---------------------------------------------------------------- filters

    def _allowed_ids(self, min_popularity: float = 0.0, min_votes: int = 0, min_rating: float = 0.0):
        """Ids of movies that pass the "hide obscure films" filters, or None for no filtering.

        min_popularity is a percentile (0.6 keeps the best-known 40 %). The vote and
        rating limits only apply when the dataset has that data; otherwise they are ignored.
        """
        use_votes = self.has_votes and (min_votes > 0 or min_rating > 0)
        if min_popularity <= 0 and not use_votes:
            return None

        key = (round(min_popularity, 3), int(min_votes) if use_votes else 0, round(min_rating, 2) if use_votes else 0)
        if key not in self._allowed_cache:
            mask = self.popularity >= min_popularity
            if use_votes:
                mask &= self.votes >= min_votes
                mask &= self.ratings >= min_rating
            self._allowed_cache[key] = np.nonzero(mask)[0].astype("int64")
        return self._allowed_cache[key]

    def _faiss(self, vec: np.ndarray, n: int, allowed=None):
        """Exact nearest neighbours, optionally restricted to the ids in ``allowed``."""
        vec = np.asarray(vec, dtype="float32").reshape(1, -1)
        if allowed is None:
            scores, idxs = self.index.search(vec, min(n, self.index.ntotal))
        elif len(allowed) == 0:
            return np.array([], dtype="float32"), np.array([], dtype="int64")
        else:
            params = faiss.SearchParameters()
            selector = faiss.IDSelectorBatch(allowed)
            params.sel = selector
            scores, idxs = self.index.search(vec, min(n, len(allowed)), params=params)
        scores, idxs = scores[0], idxs[0]
        keep = idxs >= 0
        return scores[keep], idxs[keep]

    def _search_vec(self, vec: np.ndarray, k: int, popularity: float = 0.0, allowed=None):
        """Nearest movies to ``vec``.

        ``popularity`` (0..1) blends in how well known a movie is. With 0 the
        order is pure similarity. With a higher value we look at a larger pool of
        similar movies and re-rank it, so a slightly less similar but much more
        popular film can move up. The returned scores are always the real cosine
        similarities, only the order changes.
        """
        pool = k if popularity <= 0 else max(k * 10, 300)
        scores, idxs = self._faiss(vec, pool, allowed)
        if popularity <= 0 or len(idxs) == 0:
            return scores[:k], idxs[:k]

        spread = scores.max() - scores.min()
        similarity = (scores - scores.min()) / spread if spread > 0 else np.ones_like(scores)
        blended = (1 - popularity) * similarity + popularity * self.popularity[idxs]
        order = np.argsort(-blended)[:k]
        return scores[order], idxs[order]

    # ---------------------------------------------------------------- title matching

    def _build_title_index(self) -> None:
        """Character-trigram index of the titles, so typos and partial titles still match."""
        self._title_norm = [_norm(m["title"]) for m in self.movies]
        self._title_grams = [_trigrams(t) if t else set() for t in self._title_norm]
        self._title_inverted = defaultdict(list)
        for i, grams in enumerate(self._title_grams):
            for g in grams:
                self._title_inverted[g].append(i)

    def _title_matches(self, title_query: str, allowed=None, limit: int = 25, floor: float = 0.45) -> dict:
        """{movie id: title similarity 0..1} for the titles closest to the query (Dice on trigrams)."""
        words = _norm(title_query).split()
        if len(words) > 1:
            words = [w for w in words if w not in _FILLER] or words  # "heat movie" -> "heat"
        query_norm = " ".join(words)
        if len(query_norm) < 2:
            return {}

        grams = _trigrams(query_norm)
        shared = Counter()
        for g in grams:
            for i in self._title_inverted.get(g, ()):
                shared[i] += 1

        allowed_set = None if allowed is None else set(allowed.tolist())
        scored = []
        for i, count in shared.items():
            if allowed_set is not None and i not in allowed_set:
                continue
            dice = 2 * count / (len(grams) + len(self._title_grams[i]))
            if self._title_norm[i] == query_norm:
                dice = 1.0
            if dice >= floor:
                scored.append((dice, -i, i))  # ties: the more popular (lower id) film first
        scored.sort(reverse=True)
        return {i: d for d, _, i in scored[:limit]}

    @staticmethod
    def _pick_anchor(scores: dict):
        """The film the query clearly names, or None.

        Either a near-perfect title match, or a strong one (so typos still count) that
        beats the runner-up by a clear margin. Ties go to the more popular film (lower id).
        """
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        top_id, top = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        if top >= 0.95 or (top >= 0.8 and top - runner_up >= 0.15):
            return top_id
        return None

    @staticmethod
    def _auto_title_weight(best_title: float, n_words: int) -> float:
        """How much to trust titles when the user did not choose (0..1).
        A query that closely matches a title and is short looks like a title search."""
        if n_words > 8 or best_title < 0.5:
            return 0.0
        return min(1.0, (best_title - 0.5) / 0.4)

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

    def search(self, query_text: str, k: int = 20, popularity: float = 0.0, **options) -> list:
        """Convenience wrapper around :meth:`search_full` that returns only the results."""
        return self.search_full(query_text, k=k, popularity=popularity, **options)["results"]

    def search_full(
        self,
        query_text: str,
        k: int = 20,
        popularity: float = 0.0,
        title_weight=None,
        min_popularity: float = 0.0,
        min_votes: int = 0,
        min_rating: float = 0.0,
    ) -> dict:
        """Hybrid search: meaning + title match + popularity, with adjustable weights.

        * meaning: how close the description is to the film's plot (embeddings)
        * title: how close the query is to the film's title (typo-tolerant). A year
          in the query ("forrest gump 1994") favours films from that year.
        * popularity: how well known the film is.

        ``popularity`` is 0..1. ``title_weight`` is 0..1 (0 = ignore titles, 1 = titles
        dominate) or None to decide automatically from the query. Films that fail the
        filters (min_popularity / min_votes / min_rating) are left out completely.
        Returns {"results": [...], "weights": {meaning, title, popularity}, "anchor": ...}.
        The weights are the shares that were actually used. ``anchor`` is the film the
        query named (when it is a near-exact title), in which case the other results
        are films similar to it; otherwise None.
        """
        allowed = self._allowed_ids(min_popularity, min_votes, min_rating)
        vec = np.asarray(self.backend.encode_one(query_text), dtype="float32")

        title_query, year = split_year(query_text)
        hits = self._title_matches(title_query, allowed)
        best_title = max(hits.values(), default=0.0)
        if title_weight is None:
            title_weight = self._auto_title_weight(best_title, len(query_text.split()))

        # A near-exact title match means "that film". Use its own vector as the meaning
        # query, so the rest of the list is films like it instead of unrelated filler.
        anchor_id = None
        if title_weight > 0 and hits and len(query_text.split()) <= 8:
            adjusted = {i: d * (0.7 if year is not None and self.movies[i].get("year") != year else 1.0)
                        for i, d in hits.items()}
            anchor_id = self._pick_anchor(adjusted)
            if anchor_id is not None:
                vec = np.asarray(self.index.reconstruct(anchor_id), dtype="float32")
                # The film is clearly named: other films only keep a title boost if their
                # title is nearly as good a match (sequels, "Spider-Man 2"), not for sharing a word.
                hits = {i: d for i, d in hits.items() if i == anchor_id or d >= 0.85}
        anchor = None if anchor_id is None else {"id": anchor_id, "title": self.movies[anchor_id]["title"]}

        w_pop = float(popularity)
        w_meaning = 1.0 - w_pop
        w_title = 2.0 * float(title_weight)   # title_weight 0.5 = as important as meaning
        total = w_meaning + w_title + w_pop
        weights = {"meaning": round(w_meaning / total, 3), "title": round(w_title / total, 3),
                   "popularity": round(w_pop / total, 3)}

        if w_title <= 0 and w_pop <= 0:       # plain similarity: the fast path
            scores, idxs = self._search_vec(vec, k, 0.0, allowed)
            return {"weights": weights, "anchor": anchor, "results": [
                {**self.movies[i], "explanation": self.explain(query_text, self.movies[i], s)}
                for s, i in zip(scores, idxs)
            ]}

        # Candidates: the closest by meaning plus the closest by title.
        pool_scores, pool_idxs = self._faiss(vec, max(k * 10, 300), allowed)
        cosine = dict(zip(pool_idxs.tolist(), pool_scores.tolist()))
        if len(pool_scores):
            lo, hi = float(pool_scores.min()), float(pool_scores.max())
        else:
            lo = hi = 0.0
        for i in hits:
            if i not in cosine:
                cosine[i] = float(np.dot(self.index.reconstruct(i), vec))

        ranked = []
        for i, cos in cosine.items():
            meaning = min(1.0, max(0.0, (cos - lo) / (hi - lo))) if hi > lo else 1.0
            title = hits.get(i, 0.0)
            if year is not None and self.movies[i].get("year") != year:
                title *= 0.7                  # wrong year: still a candidate, but less likely
            final = (w_meaning * meaning + w_title * title + w_pop * float(self.popularity[i])) / total
            ranked.append((final, -i, i, cos))
        ranked.sort(reverse=True)

        results = []
        for _, _, i, cos in ranked[:k]:
            explanation = self.explain(query_text, self.movies[i], cos)
            dice = hits.get(i, 0.0)
            if dice >= 0.7:
                explanation["matched_title"] = True
                explanation["title_match_pct"] = round(dice * 100)
            results.append({**self.movies[i], "explanation": explanation})
        return {"weights": weights, "anchor": anchor, "results": results}

    def mood_search(self, sliders: dict, k: int = 20, base_query: str = "", popularity: float = 0.0,
                    min_popularity: float = 0.0, min_votes: int = 0, min_rating: float = 0.0) -> list:
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

        allowed = self._allowed_ids(min_popularity, min_votes, min_rating)
        scores, idxs = self._search_vec(vec, k, popularity, allowed)
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
