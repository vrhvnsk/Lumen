"""Title matching, adjustable weights and the 'hide obscure films' filters."""
import numpy as np

from app.search import SearchEngine, _norm, _trigrams, split_year


# ---------- small pure functions ----------

def test_split_year():
    assert split_year("Forrest Gump 1994") == ("Forrest Gump", 1994)
    assert split_year("forrest gump (1994)") == ("forrest gump", 1994)
    assert split_year("1917") == ("", 1917)
    assert split_year("a man loses his grip on reality") == ("a man loses his grip on reality", None)
    assert split_year("room 12345")[1] is None          # not a year


def test_norm_strips_accents_and_keeps_other_scripts():
    assert _norm("Amélie: Le Fabuleux!") == "amelie le fabuleux"
    assert _norm("Брат 2") == "брат 2"                    # prepared for non-English titles
    assert len(_trigrams("heat")) > 3


# ---------- ranking with filters, on engines built by hand (no index needed) ----------

def _engine(n=10, with_votes=False):
    e = SearchEngine.__new__(SearchEngine)
    e.movies = [{"id": i, "title": f"Film {i}"} for i in range(n)]
    e.popularity = (1 - np.arange(n) / (n - 1)).astype("float32")      # id 0 = most popular
    e.has_votes = with_votes
    e.votes = np.arange(n, 0, -1).astype("float32") * 100               # 1000 ... 100
    e.ratings = np.linspace(9, 3, n).astype("float32")
    e._allowed_cache = {}
    return e


def test_allowed_ids_popularity_percentile():
    e = _engine()
    assert e._allowed_ids() is None
    assert list(e._allowed_ids(min_popularity=0.7)) == [0, 1, 2]       # best-known third


def test_allowed_ids_votes_and_rating_only_when_data_exists():
    # Without vote data these limits are ignored, so no filtering happens at all.
    assert _engine(with_votes=False)._allowed_ids(min_votes=900, min_rating=8) is None

    e = _engine(with_votes=True)
    assert list(e._allowed_ids(min_votes=800)) == [0, 1, 2]
    assert list(e._allowed_ids(min_rating=8)) == [0, 1]                 # ratings 9.0, 8.33, 7.67 ...
    assert list(e._allowed_ids(min_votes=800, min_rating=8)) == [0, 1]


def test_pick_anchor():
    pick = SearchEngine._pick_anchor
    assert pick({}) is None
    assert pick({7: 1.0, 9: 0.5}) == 7
    assert pick({7: 0.88, 9: 0.52}) == 7              # a typo, but clearly this film
    assert pick({7: 0.88, 9: 0.80}) is None           # ambiguous between two films
    assert pick({7: 0.74}) is None                    # too weak to be sure
    assert pick({9: 1.0, 7: 0.99}) == 9               # near-perfect wins
    assert pick({9: 1.0, 7: 1.0}) == 7                # tie: the more popular (lower id) film


def test_auto_title_weight():
    auto = SearchEngine._auto_title_weight
    assert auto(1.0, 3) == 1.0                    # exact title
    assert auto(0.3, 3) == 0.0                    # nothing like a title
    assert auto(1.0, 12) == 0.0                   # long descriptive query: ignore titles
    assert 0 < auto(0.7, 3) < 1


# ---------- through the API ----------

def _movie(client, movie_id):
    return client.get(f"/api/movie/{movie_id}").json()


def test_exact_title_finds_the_film_even_though_titles_are_not_embedded(client):
    target = _movie(client, 3)
    r = client.post("/api/search", json={"query": target["title"], "k": 5}).json()
    assert r["results"][0]["id"] == 3
    assert r["results"][0]["explanation"]["matched_title"] is True
    assert r["weights"]["title"] > 0.4            # decided automatically


def test_exact_title_then_films_similar_to_it(client):
    target = _movie(client, 3)
    r = client.post("/api/search", json={"query": target["title"], "k": 8}).json()
    assert r["anchor"] == {"id": 3, "title": target["title"]}
    ids = [m["id"] for m in r["results"]]
    assert ids[0] == 3
    # The rest are the film's own nearest neighbours, not unrelated filler.
    graph = client.get("/api/graph/3", params={"depth": 1, "k": 12}).json()
    neighbours = {e["target"] if e["source"] == 3 else e["source"] for e in graph["edges"]}
    assert len(set(ids[1:]) & neighbours) >= 4

    # Without title matching there is no anchor.
    plain = client.post("/api/search", json={"query": target["title"], "title_weight": 0}).json()
    assert plain["anchor"] is None


def test_descriptive_query_has_no_anchor(client):
    r = client.post("/api/search", json={"query": "a man slowly loses his grip on reality"}).json()
    assert r["anchor"] is None


def test_title_with_year_and_with_a_typo(client):
    target = _movie(client, 3)
    with_year = client.post("/api/search", json={"query": f"{target['title']} {target['year']}", "k": 5}).json()
    assert with_year["results"][0]["id"] == 3

    typo = target["title"][:-1]                    # last letter missing
    r = client.post("/api/search", json={"query": typo, "k": 5}).json()
    assert 3 in [m["id"] for m in r["results"][:3]]


def test_title_search_works_with_every_popularity_setting(client):
    target = _movie(client, 20)
    for popularity in (0, 0.35, 0.7, 1):
        r = client.post("/api/search", json={"query": target["title"], "k": 5, "popularity": popularity}).json()
        assert r["results"][0]["id"] == 20, popularity


def test_descriptive_queries_do_not_use_title_weight(client):
    r = client.post("/api/search", json={"query": "a man slowly loses his grip on reality", "k": 5}).json()
    assert r["weights"] == {"meaning": 1.0, "title": 0.0, "popularity": 0.0}


def test_title_weight_can_be_set_by_hand(client):
    target = _movie(client, 3)
    off = client.post("/api/search", json={"query": target["title"], "title_weight": 0}).json()
    assert off["weights"]["title"] == 0.0
    assert not any(m["explanation"].get("matched_title") for m in off["results"])

    strong = client.post("/api/search", json={"query": target["title"], "title_weight": 1}).json()
    assert strong["weights"]["title"] > 0.6
    assert strong["results"][0]["id"] == 3

    assert client.post("/api/search", json={"query": "x", "title_weight": 2}).status_code == 422


def test_weights_add_up_to_one(client):
    r = client.post("/api/search", json={"query": "heist", "popularity": 0.35, "title_weight": 0.5}).json()
    assert abs(sum(r["weights"].values()) - 1.0) < 0.01


def test_hide_obscure_keeps_only_well_known_films(client):
    # In the test data a lower id means more popular; 0.9 keeps roughly the best-known tenth.
    r = client.post("/api/search", json={"query": "a story about love", "k": 10, "min_popularity": 0.9}).json()
    assert len(r["results"]) == 10
    assert all(m["id"] <= 60 for m in r["results"])

    unfiltered = client.post("/api/search", json={"query": "a story about love", "k": 10}).json()
    assert any(m["id"] > 60 for m in unfiltered["results"])   # the filter really changed something


def test_filters_apply_to_mood_search_and_to_title_matches(client):
    r = client.post("/api/mood-search", json={"dark": 1, "k": 8, "min_popularity": 0.9}).json()
    assert len(r["results"]) == 8 and all(m["id"] <= 60 for m in r["results"])

    # An obscure film searched by its exact title is hidden when the filter excludes it.
    obscure = _movie(client, 500)
    r = client.post("/api/search", json={"query": obscure["title"], "min_popularity": 0.9}).json()
    assert 500 not in [m["id"] for m in r["results"]]


def test_vote_filters_are_ignored_without_vote_data_and_validated(client):
    assert client.get("/api/health").json()["has_votes"] is False
    r = client.post("/api/search", json={"query": "love", "min_votes": 100000, "min_rating": 9.9, "k": 5})
    assert r.status_code == 200 and len(r.json()["results"]) == 5
    assert client.post("/api/search", json={"query": "x", "min_rating": 11}).status_code == 422
    assert client.post("/api/search", json={"query": "x", "min_popularity": 2}).status_code == 422
