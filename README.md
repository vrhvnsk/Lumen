# Lumen

**Forgot the title? Describe the movie.** A semantic movie search engine: type what happens in a film, or pick a mood, and it finds matches by *meaning* rather than keywords. Click any result to explore a graph of similar movies.

<!-- Add a screenshot or GIF here once the app is running:
![Lumen](docs/screenshot.png)
-->

## Features

- **Search by description.** "a man slowly loses his grip on reality" can find films that never use those words.
- **Search by mood.** Four sliders (happy, dark, romantic, fast-paced) blend into one search, with an optional theme on top.
- **Similarity web.** Open a movie and see a web of 19 to 61 related films: its closest matches, and the films closest to each of those. Hover to preview, click to jump there and keep exploring, and switch between Few, More and Most.
- **Popular films first, if you want.** A switch above the results (Best match, Balanced, Popular first) blends how well known a film is into the ranking. The default is Balanced.
- **Finds films by name too.** Type a title ("Forrest Gump"), even with a typo or a year ("forest gump 1994"), and that film comes first, followed by films similar to it. Longer descriptions still search purely by meaning.
- **Hide obscure films.** One click removes the least-known films from the results. It uses ratings and vote counts when the dataset has them, and otherwise keeps the best-known 40 %.
- **Adjustable weights.** A Fine-tune panel sets how much popularity and title matching count against meaning. Title matching is decided automatically unless you override it.
- **Simple explanations.** Each result shows its similarity and which of its genres/themes overlap with your query. This is a transparent text-overlap heuristic, not a second model.
- **No build step.** The website is plain HTML, CSS and JavaScript, served by the same FastAPI app as the API.

## How it works

```
data/movies_seed.json   9,034 movies from TMDB
        │  one text per movie: overview + genres + keywords + director + cast
        ▼
embeddings              sentence-transformers (meaning)  |  offline TF-IDF/LSA fallback
        ▼
FAISS index             cosine similarity over normalised vectors
        │
        ├── POST /api/search        description → embed → nearest movies
        ├── POST /api/mood-search   slider weights → blended vector → nearest movies
        └── GET  /api/graph/{id}    a movie's stored vector → its neighbours, and theirs
```

Searching embeds your text with the same model that embedded the movies, then asks FAISS for the closest vectors. If popularity is switched on, FAISS returns a larger pool of close matches (at least 300) and each film's similarity (rescaled within that pool) is blended with its popularity percentile before the final top results are chosen. The percentages shown on the cards are always the real similarities; only the order changes. A title in the query is matched separately, on the film's name (typo-tolerant, using character trigrams), because titles are not part of the text that gets embedded. The final score is a weighted mix of meaning, title match and popularity. When the query clearly names one film, that film's own vector is used for the rest of the list, so the results are films like it. Mood search embeds one short phrase per mood (for example "a bleak, disturbing, grim, unsettling story"), mixes them by slider weight and searches with the result.

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

## Deploy it permanently

The repository includes a `Dockerfile` and a docker-compose setup with automatic HTTPS. See [`docs/DEPLOY.md`](docs/DEPLOY.md) for server sizing (plan for about 2 GB of RAM with the default model), step-by-step instructions and a checklist for going public.

## Rebuild the dataset from TMDB

The repository includes a ready-to-use dataset. To fetch a fresh one you need a free [TMDB API key](https://www.themoviedb.org/settings/api):

```bash
cd backend
export TMDB_API_KEY=your_key_here          # PowerShell: $env:TMDB_API_KEY="your_key_here"
python -m scripts.tmdb_loader --pages 500  # up to 10,000 movies, takes about an hour
python build_index.py
```

The key is only read from the environment and must never be committed. See [`backend/data/README.md`](backend/data/README.md) for the data format and cleaning rules.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Status, number of indexed movies, embedding backend in use |
| `POST` | `/api/search` | Body `{"query": "...", "k": 20, "popularity": 0, "title_weight": null, "min_popularity": 0, "min_votes": 0, "min_rating": 0}`. Movies closest in meaning to the text, with title matching. `popularity` (0 to 1) favours well-known films. `title_weight` (0 to 1, or `null` for automatic) sets how much the film's name counts. The `min_*` options hide obscure films (the vote and rating limits are ignored if the dataset has no such data). The response includes the `weights` that were used and an `anchor` film when the query names one |
| `POST` | `/api/mood-search` | Body `{"happy": 0-1, "dark": 0-1, "romantic": 0-1, "fast_paced": 0-1, "base_query": "", "k": 20, "popularity": 0}` plus the same `min_*` options. Needs at least one slider above 0 or a base query |
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
├── Dockerfile               one image with the API, the website and a built index
├── deploy/                  docker-compose.yml + Caddyfile (HTTPS) for a single server
├── docs/DEPLOY.md           how to run it permanently on a website
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

## Limitations

- **Search quality depends on the embedding backend.** With the offline fallback results are noticeably weaker than with sentence-transformers.
- **The dataset is a snapshot of TMDB's most popular movies.** It includes many non-English and recent or upcoming titles, and mature content is not specifically filtered beyond TMDB's default.
- **"Hide obscure films" is crude on the bundled data.** Without ratings it can only use the popularity rank, so it also hides good but little-known films. Re-downloading the data with the current loader adds ratings and vote counts, which the filter then uses.
- **Title search only knows the titles in the dataset.** A film that is not among the roughly 9,000 included (for example the 2002 Spider-Man) cannot be found by name.
- **Popularity in the bundled dataset is its download order.** The file was fetched sorted by TMDB popularity and keeps that order, so a movie's position stands in for its popularity rank. It is a snapshot, not live data. Running `scripts/tmdb_loader.py` stores TMDB's real `popularity` value, which the search then uses instead.
- **Explanations are heuristics.** "Matched themes" shows overlapping words, not why a model ranked a movie.
- **Similarity is cosine similarity, not a probability.** Typical values are well below 100%.
- **Everything is loaded in memory.** Fine for ten thousand movies; a much larger catalogue would need a different index.

## Ideas for next steps

- Filters (year, genre, language) on top of semantic search.
- A global 2D map of all movies (UMAP) instead of one neighbourhood at a time.
- A re-ranking step or an LLM-written explanation of why a movie matches.
- Docker image and a hosted demo.

## Credits and licence

Movie data and posters come from [TMDB](https://www.themoviedb.org/). This product uses the TMDB API but is not endorsed or certified by TMDB.

Code is released under the Apache License 2.0, see [LICENSE](LICENSE). The TMDB data is subject to TMDB's own terms of use.
