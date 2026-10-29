from scripts.clean_seed import clean_movies
from scripts.tmdb_loader import parse_movie
from app.textutil import movie_to_text


def _movie(title="A", year=2000, overview="x" * 40, **kw):
    return {"title": title, "year": year, "overview": overview, "id": 99, **kw}


def test_clean_drops_short_overviews_and_exact_duplicates():
    movies = [
        _movie("Keep"),
        _movie("Keep"),                       # exact duplicate
        _movie("Empty", overview=""),         # nothing to search on
        _movie("Short", overview="too short"),
        _movie("Keep", year=2010),            # same title, different film: kept
        _movie("Keep", overview="y" * 40),    # same title and year, different film: kept
    ]
    cleaned, stats = clean_movies(movies)
    assert [m["title"] for m in cleaned] == ["Keep", "Keep", "Keep"]
    assert stats == {"input": 6, "dropped_short_overview": 2, "dropped_duplicates": 1, "output": 3}


def test_clean_renumbers_ids_to_positions_and_is_idempotent():
    cleaned, _ = clean_movies([_movie("A"), _movie("B", overview="z" * 50)])
    assert [m["id"] for m in cleaned] == [0, 1]
    again, stats = clean_movies(cleaned)
    assert again == cleaned and stats["dropped_duplicates"] == 0


def test_parse_movie_from_tmdb_payload():
    payload = {
        "title": "Example",
        "release_date": "2010-07-16",
        "genres": [{"id": 1, "name": "Drama"}, {"id": 2, "name": "Thriller"}],
        "overview": "A story.",
        "poster_path": "/abc.jpg",
        "credits": {
            "cast": [{"name": f"Actor {i}"} for i in range(8)],
            "crew": [{"name": "Writer", "job": "Writer"}, {"name": "Dir", "job": "Director"}],
        },
        "keywords": {"keywords": [{"id": 5, "name": "dream"}]},
    }
    m = parse_movie(payload)
    assert m["year"] == 2010
    assert m["genres"] == ["Drama", "Thriller"]
    assert m["director"] == "Dir"
    assert m["actors"] == [f"Actor {i}" for i in range(5)]
    assert m["keywords"] == ["dream"]
    assert m["poster_url"] == "https://image.tmdb.org/t/p/w500/abc.jpg"


def test_parse_movie_handles_missing_fields():
    m = parse_movie({"title": "Bare"})
    assert m["year"] is None and m["director"] is None and m["poster_url"] is None
    assert m["genres"] == [] and m["actors"] == [] and m["keywords"] == []


def test_movie_to_text_skips_empty_parts_and_keeps_colons_in_overview():
    text = movie_to_text({"overview": "Note: it begins.", "genres": [], "keywords": ["a", "b"]})
    assert text == "Note: it begins. Themes: a, b."
