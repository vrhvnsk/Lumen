"""FastAPI application: JSON API under /api plus the static website at /."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.search import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()  # load the index at start-up so problems show up immediately
    yield


app = FastAPI(title="Lumen: semantic movie search API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=20, ge=1, le=100)


class MoodSearchRequest(BaseModel):
    happy: float = Field(default=0.0, ge=0, le=1)
    dark: float = Field(default=0.0, ge=0, le=1)
    romantic: float = Field(default=0.0, ge=0, le=1)
    fast_paced: float = Field(default=0.0, ge=0, le=1)
    base_query: str = Field(default="", max_length=500)
    k: int = Field(default=20, ge=1, le=100)


@app.get("/api/health")
def health():
    engine = get_engine()
    return {"status": "ok", "movies_indexed": len(engine.movies), "backend": engine.backend_name}


@app.get("/api/movies")
def list_movies(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    """Browse the dataset page by page."""
    movies = get_engine().movies
    return {"total": len(movies), "offset": offset, "movies": movies[offset:offset + limit]}


@app.get("/api/movie/{movie_id}")
def get_movie(movie_id: int):
    movie = get_engine().get_movie(movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


@app.post("/api/search")
def search(req: SearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    return {"query": query, "results": get_engine().search(query, k=req.k)}


@app.post("/api/mood-search")
def mood_search(req: MoodSearchRequest):
    sliders = {"happy": req.happy, "dark": req.dark, "romantic": req.romantic,
               "fast_paced": req.fast_paced}
    try:
        results = get_engine().mood_search(sliders, k=req.k, base_query=req.base_query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"sliders": sliders, "results": results}


@app.get("/api/graph/{movie_id}")
def graph(
    movie_id: int,
    depth: int = Query(1, ge=1, le=2),
    k: int = Query(5, ge=1, le=12, description="neighbours of the movie itself"),
    k_outer: int = Query(None, ge=1, le=6, description="neighbours of each neighbour (depth 2); default: same as k"),
):
    engine = get_engine()
    if engine.get_movie(movie_id) is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return engine.graph(movie_id, depth=depth, k=k, k_outer=k_outer)


# Serve the website last, so it never shadows an /api route.
if config.FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "Lumen semantic movie search API. See /docs for the interactive API docs."}
