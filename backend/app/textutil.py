"""Turns a movie record into the text that gets embedded."""


def movie_to_text(movie: dict) -> str:
    """Combine overview, genres, keywords, director and cast into one text blob.

    The same function is used when building the index and when looking up a
    movie, so both sides always see identical text. Empty fields are skipped.
    """
    parts = []

    if (movie.get("overview") or "").strip():
        parts.append(movie["overview"].strip())
    if movie.get("genres"):
        parts.append("Genres: " + ", ".join(movie["genres"]))
    if movie.get("keywords"):
        parts.append("Themes: " + ", ".join(movie["keywords"]))
    if movie.get("director"):
        parts.append("Director: " + movie["director"])
    if movie.get("actors"):
        parts.append("Starring: " + ", ".join(movie["actors"]))

    # End every part with punctuation so the parts read as separate sentences.
    return " ".join(p if p[-1] in ".!?" else p + "." for p in parts)
