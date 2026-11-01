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


## Cleaning

`python -m scripts.clean_seed` (run from `backend/`) removes:

- movies whose overview is missing or shorter than 30 characters (there is nothing to search on),
- exact duplicates (same title, year and overview),

and renumbers the ids. Different films that share a title, such as remakes, are kept. The loader runs the same cleaning automatically.

