# Lumen

**Forgot the title? Describe the movie.** A semantic movie search engine: type what happens in a film, or pick a mood, and it finds matches by *meaning* rather than keywords. Click any result to explore a graph of similar movies.

<img width="1731" height="3513" alt="Снимок экрана_29-10-2026_192942_127 0 0 1" src="https://github.com/user-attachments/assets/c69b51c2-1172-43d7-b6b7-c08e373b3d52" />

## Features

- **Search by description.** "a man slowly loses his grip on reality" can find films that never use those words.
- **Search by mood.** Four sliders (happy, dark, romantic, fast-paced) blend into one search, with an optional theme on top.
- **Similarity web.** Open a movie and see a web of 19 to 61 related films: its closest matches, and the films closest to each of those. Hover to preview, click to jump there and keep exploring, and switch between Few, More and Most.
- **Simple explanations.** Each result shows its similarity and which of its genres/themes overlap with your query. This is a transparent text-overlap heuristic, not a second model.
- **No build step.** The website is plain HTML, CSS and JavaScript, served by the same FastAPI app as the API.


<img width="1731" height="1669" alt="example" src="https://github.com/user-attachments/assets/d04aff19-0fa0-4d95-acd5-9c4fb29fa6a8" />
<img width="1867" height="977" alt="Снимок экрана_29-10-2026_193224_127 0 0 1" src="https://github.com/user-attachments/assets/e2229415-1e71-4253-ad5e-f21297922758" />

## How it works

```
data/movies_seed.json   about 9000 movies from TMDB
        │  one text per movie: overview + genres + keywords + director + cast
        ▼
embeddings              sentence-transformers (meaning)  |  offline TF-IDF/LSA fallback
        ▼
FAISS index             cosine similarity over normalised vectors
        │
        ├── POST /api/search        description --> embed --> nearest movies
        ├── POST /api/mood-search   slider weights --> blended vector --> nearest movies
        └── GET  /api/graph/{id}    a movie's stored vector --> its neighbours and theirs etc.
```

Searching embeds your text with the same model that embedded the movies, then asks FAISS for the closest vectors. Mood search embeds one short phrase per mood (for example "a bleak, disturbing, grim, unsettling story"), mixes them by slider weight and searches with the result.

## Quick start

You need Python 3.10+.

```bash
git clone https://github.com/vrhvnsk/lumen.git
cd lumen/backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# python build_index.py             # a ready-made index is already included, it'd rebuild the index from zero (around 2 hours for 9k movies)
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. API docs are at <http://127.0.0.1:8000/docs>.

**About `build_index.py`:** the first run downloads the embedding model (`all-mpnet-base-v2`, roughly 420 MB) and embedding 9,000 movies on a CPU can take several minutes. For a smaller download use `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python build_index.py`.

**No internet or no big download?** `python build_index.py --offline` builds the index with a TF-IDF/LSA fallback in a few seconds. It only matches shared vocabulary and themes, so results are clearly weaker than real semantic embeddings. It is meant for development and tests.

If you start the server without building the index, it stops with a message telling you to run `build_index.py`.

## Rebuild the dataset from TMDB

The repository includes a ready-to-use dataset. To fetch a fresh one you need a free [TMDB API key](https://www.themoviedb.org/settings/api):

```bash
cd backend
export TMDB_API_KEY=your_key_here          # PowerShell: $env:TMDB_API_KEY="your_key_here"
python -m scripts.tmdb_loader --pages 500  # up to 10,000 movies, takes about two hours
python build_index.py
```

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Status, number of indexed movies, embedding backend in use |
| `POST` | `/api/search` | Body `{"query": "...", "k": 20}`. Movies closest in meaning to the text |
| `POST` | `/api/mood-search` | Body `{"happy": 0-1, "dark": 0-1, "romantic": 0-1, "fast_paced": 0-1, "base_query": "", "k": 20}`. Needs at least one slider above 0 or a base query |
| `GET` | `/api/movies?offset=0&limit=50` | Browse the dataset page by page |
| `GET` | `/api/movie/{id}` | One movie |
| `GET` | `/api/graph/{id}?depth=2&k=8&k_outer=3` | A web around a movie: `k` direct neighbours (1-12) and, with `depth=2`, `k_outer` new neighbours around each (1-6). Nodes carry a `ring` (0, 1 or 2); edges carry a similarity `weight` |

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "friends reunite for one last road trip", "k": 5}'
```

## Project structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI app: endpoints, serves the website
│   │   ├── search.py        SearchEngine: search, mood search, neighbours, similarity web
│   │   ├── embeddings.py    sentence-transformers backend + offline fallback
│   │   ├── textutil.py      builds the text that is embedded for each movie
│   │   ├── config.py        paths and settings (environment variables)
│   │   └── database.py      optional SQL layer (not used by search)
│   ├── scripts/
│   │   ├── tmdb_loader.py   download movies from the TMDB API
│   │   └── clean_seed.py    drop empty/duplicate entries, renumber ids
│   ├── data/
│   │   └── movies_seed.json the dataset (generated files land here too, git-ignored)
│   ├── tests/               pytest suite (runs offline, no model download)
│   ├── build_index.py       builds the FAISS index
│   ├── seed_db.py           optional: load the dataset into SQL
│   └── requirements*.txt
├── frontend/                index.html, styles.css, app.js (no build step, no dependencies)
└── .github/workflows/       CI: runs the tests on every push
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `EMBEDDING_MODEL` | `sentence-transformers/all-mpnet-base-v2` | Model used by `build_index.py` and the server (rebuild the index after changing it) |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Extra browser origins allowed to call the API. The bundled website is same-origin and needs none |
| `MOVIE_DATA_DIR` | `backend/data` | Where the dataset and generated index live |
| `TMDB_API_KEY` | none | Only for `scripts/tmdb_loader.py` |
| `DATABASE_URL` | local SQLite file | Only for the optional database layer |

## Tests

```bash
cd backend
pip install -r requirements-ci.txt   # light: no PyTorch
pytest
```

The tests build a small offline index in a temporary folder and cover every API endpoint, input validation, the similarity web, the data cleaning and the TMDB response parser. They do not call the TMDB API and do not test the quality of real semantic embeddings.

## Ideas for next steps

- Filters (year, genre, language) on top of semantic search.
- A global 2D map of all movies (UMAP) instead of one neighbourhood at a time.
- A re-ranking step or an LLM-written explanation of why a movie matches.
- Docker image and a hosted demo.

## Credits and licence

Movie data and posters come from [TMDB](https://www.themoviedb.org/). This product uses the TMDB API but is not endorsed or certified by TMDB.

Code is released under the Apache License 2.0, see [LICENSE](LICENSE). The TMDB data is subject to TMDB's own terms of use.
