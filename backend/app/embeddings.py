"""Embedding backends: turn text into vectors that can be compared.

Two interchangeable backends share the same interface (``encode``,
``encode_one``, ``dim``, ``name``):

* ``SentenceTransformerBackend``: real semantic embeddings. Understands meaning,
  so "a man slowly goes insane" finds films that never use those words.
  Needs a one-time model download.
* ``TfidfLsaBackend``: offline fallback. Word statistics compressed with SVD
  (LSA). Works without internet or a large model, but only captures shared
  vocabulary and themes, not true meaning.

Vectors are L2-normalised, so the FAISS inner product equals cosine similarity.
"""
import os
import pickle

import numpy as np

from app import config

ST_NAME = "sentence-transformers"
LSA_NAME = "tfidf-lsa"
LSA_DIM = 128


class SentenceTransformerBackend:
    name = ST_NAME

    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts, show_progress: bool = False):
        vecs = self.model.encode(
            texts,
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
        )
        return np.asarray(vecs, dtype="float32")

    def encode_one(self, text):
        return self.encode([text])[0]


class TfidfLsaBackend:
    """Offline fallback: TF-IDF over the movie texts reduced with truncated SVD."""

    name = LSA_NAME

    def __init__(self, dim: int = LSA_DIM):
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.dim = dim
        self.vectorizer = TfidfVectorizer(
            max_features=20000, ngram_range=(1, 2), stop_words="english"
        )
        self.svd = TruncatedSVD(n_components=dim, random_state=42)
        self._fitted = False

    def fit(self, corpus):
        from sklearn.decomposition import TruncatedSVD

        tfidf = self.vectorizer.fit_transform(corpus)
        # SVD cannot use more components than the data has rows/columns.
        n_comp = max(2, min(self.dim, tfidf.shape[0] - 1, tfidf.shape[1] - 1))
        if n_comp != self.svd.n_components:
            self.svd = TruncatedSVD(n_components=n_comp, random_state=42)
        self.svd.fit(tfidf)
        self.dim = self.svd.n_components
        self._fitted = True

    @staticmethod
    def _normalize(mat):
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        return (mat / norms).astype("float32")

    def encode(self, texts, show_progress: bool = False):
        if not self._fitted:
            self.fit(texts)
        return self._normalize(self.svd.transform(self.vectorizer.transform(texts)))

    def encode_one(self, text):
        return self.encode([text])[0]

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump({"vectorizer": self.vectorizer, "svd": self.svd, "dim": self.dim}, f)

    @classmethod
    def load(cls, path):
        # The file is produced locally by build_index.py; never load pickles
        # from sources you do not trust.
        with open(path, "rb") as f:
            state = pickle.load(f)
        obj = cls(dim=state["dim"])
        obj.vectorizer = state["vectorizer"]
        obj.svd = state["svd"]
        obj._fitted = True
        return obj


def build_backend(corpus, prefer_offline: bool = False):
    """Create the backend used to *build* an index.

    Tries sentence-transformers first; if the package or model is unavailable
    (or ``prefer_offline`` is set) it fits the offline TF-IDF/LSA backend on
    ``corpus`` and saves it next to the index.
    """
    if not prefer_offline:
        try:
            return SentenceTransformerBackend()
        except Exception as e:  # missing package, no internet, ...
            print(f"[embeddings] sentence-transformers unavailable ({e}); "
                  f"using the offline TF-IDF/LSA backend instead.")

    backend = TfidfLsaBackend()
    backend.fit(corpus)
    os.makedirs(os.path.dirname(config.EMBEDDER_PATH), exist_ok=True)
    backend.save(config.EMBEDDER_PATH)
    return backend


def load_backend(name: str):
    """Load the backend that was used to build the existing index."""
    if name == ST_NAME:
        return SentenceTransformerBackend()
    if name == LSA_NAME:
        if not config.EMBEDDER_PATH.exists():
            raise FileNotFoundError(
                f"{config.EMBEDDER_PATH} is missing. Run `python build_index.py --offline` again."
            )
        return TfidfLsaBackend.load(config.EMBEDDER_PATH)
    raise ValueError(f"Unknown embedding backend in index_info.json: {name!r}")
