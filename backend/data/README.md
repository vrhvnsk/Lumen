# Data

## `movies_seed.json`

A list of movies in this format (UTF-8 JSON):

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Equals the movie's position in the list (the search code relies on this) |
| `title` | string | |
| `year` | integer or null | Release year |
| `genres` | list of strings | |
| `director` | string or null | |
| `actors` | list of strings | Top-billed cast, up to 5 |
| `keywords` | list of strings | TMDB keywords (themes) |
| `overview` | string | Plot summary, at least 30 characters after cleaning |
| `poster_url` | string or null | TMDB image URL |
| `popularity` | number or null | TMDB popularity score at download time. Only present in data downloaded with the current loader |
| `vote_count` | integer or null | Same as above |
| `vote_average` | number or null | TMDB user rating, 0 to 10. Same as above |
| `original_language` | string or null | Language code such as `en` or `ko`. Same as above |

**Ratings without the fields:** "Hide obscure films" uses `vote_count` and `vote_average` when the dataset has them. Without them it falls back to the popularity rank.

**Popularity without the field:** if a dataset has no `popularity` values, the search treats the movie's position (its `id`) as its popularity rank, because `tmdb_loader.py` downloads movies sorted by popularity and the cleaning keeps that order. The bundled file works this way.

Source: [TMDB](https://www.themoviedb.org/), fetched with `scripts/tmdb_loader.py`. This product uses the TMDB API but is not endorsed or certified by TMDB. TMDB's terms of use apply to this data; check them before reusing or redistributing it.

## Cleaning

`python -m scripts.clean_seed` (run from `backend/`) removes:

- movies whose overview is missing or shorter than 30 characters (there is nothing to search on),
- exact duplicates (same title, year and overview),

and renumbers the ids. Different films that share a title, such as remakes, are kept. The loader runs the same cleaning automatically.

## Generated files (git-ignored)

`build_index.py` creates these next to the dataset. Delete and regenerate them whenever you like:

- `faiss.index`: one vector per movie
- `index_info.json`: which embedding backend built the index
- `tfidf_lsa.pkl`: only for `--offline` builds
- `movies.db`: only if you run the optional `seed_db.py`
