"""Optional SQL database layer (SQLite by default, PostgreSQL if configured).

Search does NOT use this: it runs from the JSON dataset and the FAISS index.
The table is a starting point if you later want accounts, ratings or saved
searches.

To use PostgreSQL instead of the default SQLite file:

    pip install -r requirements-postgres.txt
    export DATABASE_URL=postgresql://user:password@localhost:5432/moviesearch
    python seed_db.py
"""
import os

from sqlalchemy import JSON, Column, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app import config

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{config.DATA_DIR / 'movies.db'}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    year = Column(Integer)
    director = Column(String)
    overview = Column(Text)
    poster_url = Column(String)
    genres = Column(JSON)      # list of strings
    actors = Column(JSON)      # list of strings
    keywords = Column(JSON)    # list of strings


def init_db():
    Base.metadata.create_all(bind=engine)
