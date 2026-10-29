"""Test setup: build a small offline index in a temp folder so the tests need
neither internet access nor the large embedding model."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Must happen before any `app` module is imported (config reads these at import).
_tmp = Path(tempfile.mkdtemp(prefix="movie_search_test_"))
os.environ["MOVIE_DATA_DIR"] = str(_tmp)
os.environ["MOVIE_FRONTEND_DIR"] = str(BACKEND.parent / "frontend")

with open(BACKEND / "data" / "movies_seed.json", encoding="utf-8") as f:
    _subset = json.load(f)[:600]
for _i, _m in enumerate(_subset):
    _m["id"] = _i
with open(_tmp / "movies_seed.json", "w", encoding="utf-8") as f:
    json.dump(_subset, f)


@pytest.fixture(scope="session")
def client():
    import build_index
    from fastapi.testclient import TestClient

    build_index.main(prefer_offline=True)

    from app.main import app
    with TestClient(app) as c:  # the context manager runs the start-up code
        yield c
