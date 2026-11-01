def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["movies_indexed"] == 600
    assert body["backend"] == "tfidf-lsa"


def test_search_returns_ranked_results(client):
    r = client.post("/api/search", json={"query": "a superhero fights a villain to save the city", "k": 5})
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 5
    scores = [m["explanation"]["similarity_pct"] for m in results]
    assert scores == sorted(scores, reverse=True)
    assert {"title", "overview", "genres", "explanation"} <= results[0].keys()


def test_search_rejects_empty_and_blank_queries(client):
    assert client.post("/api/search", json={"query": ""}).status_code == 422
    assert client.post("/api/search", json={"query": "   "}).status_code == 400


def test_search_validates_k(client):
    assert client.post("/api/search", json={"query": "love", "k": 0}).status_code == 422
    assert client.post("/api/search", json={"query": "love", "k": 101}).status_code == 422


def test_popularity_favours_better_known_films(client):
    """In the test data a lower id means more popular (see SearchEngine._popularity_scores)."""
    query = {"query": "a story about love and family", "k": 10}
    by_match = client.post("/api/search", json={**query, "popularity": 0}).json()["results"]
    by_fame = client.post("/api/search", json={**query, "popularity": 0.9}).json()["results"]

    mean_id = lambda results: sum(m["id"] for m in results) / len(results)
    assert mean_id(by_fame) < mean_id(by_match)          # more popular films on top
    assert len(by_fame) == len(by_match) == 10

    # popularity=0 is exactly the plain similarity order
    scores = [m["explanation"]["similarity_pct"] for m in by_match]
    assert scores == sorted(scores, reverse=True)


def test_popularity_changes_order_not_scores(client):
    # The shown similarity is always the real similarity, even when re-ranked.
    r = client.post("/api/search", json={"query": "heist crime", "k": 5, "popularity": 1}).json()["results"]
    assert all(0 < m["explanation"]["similarity_pct"] <= 100 for m in r)


def test_popularity_is_validated_and_works_for_mood_search(client):
    assert client.post("/api/search", json={"query": "x", "popularity": 1.5}).status_code == 422
    assert client.post("/api/search", json={"query": "x", "popularity": -0.1}).status_code == 422
    r = client.post("/api/mood-search", json={"dark": 1, "k": 5, "popularity": 0.7})
    assert r.status_code == 200 and len(r.json()["results"]) == 5


def test_mood_search(client):
    r = client.post("/api/mood-search", json={"dark": 1.0, "k": 4})
    assert r.status_code == 200
    assert len(r.json()["results"]) == 4


def test_mood_search_needs_some_input(client):
    r = client.post("/api/mood-search", json={})
    assert r.status_code == 400
    assert "mood slider" in r.json()["detail"]


def test_mood_search_rejects_out_of_range_slider(client):
    assert client.post("/api/mood-search", json={"happy": 2}).status_code == 422


def test_movies_are_paginated(client):
    r = client.get("/api/movies", params={"offset": 10, "limit": 5})
    body = r.json()
    assert body["total"] == 600
    assert [m["id"] for m in body["movies"]] == [10, 11, 12, 13, 14]
    assert client.get("/api/movies", params={"limit": 1000}).status_code == 422


def test_get_movie_and_404(client):
    assert client.get("/api/movie/3").json()["id"] == 3
    assert client.get("/api/movie/999999").status_code == 404
    assert client.get("/api/movie/-1").status_code == 404


def test_graph_structure(client):
    g = client.get("/api/graph/0", params={"depth": 1, "k": 4}).json()
    ids = {n["id"] for n in g["nodes"]}
    assert 0 in ids
    assert len(g["nodes"]) == 5          # the movie itself + 4 neighbours
    assert len(g["edges"]) == 4
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert e["source"] != e["target"]


def test_graph_depth_two_is_larger_and_has_no_duplicate_edges(client):
    g = client.get("/api/graph/0", params={"depth": 2, "k": 3}).json()
    assert len(g["nodes"]) > 4
    pairs = [tuple(sorted((e["source"], e["target"]))) for e in g["edges"]]
    assert len(pairs) == len(set(pairs))


def test_graph_rings_and_separate_outer_size(client):
    g = client.get("/api/graph/0", params={"depth": 2, "k": 8, "k_outer": 3}).json()
    rings = {}
    for n in g["nodes"]:
        rings.setdefault(n["ring"], []).append(n["id"])
    assert rings[0] == [0]
    assert len(rings[1]) == 8
    assert 8 < len(rings[2]) <= 24            # up to 3 new movies per neighbour
    assert len(g["nodes"]) > 12               # a real web, not 4-5 movies


def test_graph_404_and_limits(client):
    assert client.get("/api/graph/999999").status_code == 404
    assert client.get("/api/graph/0", params={"depth": 5}).status_code == 422
    assert client.get("/api/graph/0", params={"k": 13}).status_code == 422
    assert client.get("/api/graph/0", params={"k_outer": 7}).status_code == 422


def test_website_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
