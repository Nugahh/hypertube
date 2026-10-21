import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# PostgreSQL in Docker (see docker-compose.yml); SQLite when running without it
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hypertube.db")

# PostgreSQL: a row lock held by a request that is waiting (on TMDb, Jackett…) must make the next writer fail after 5 s with an
# error, not wait forever: the database calls run in the event loop, so one waiting writer froze the whole server
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {"options": "-c lock_timeout=5000"},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session


def init_db():
    from app import models  # registers the tables on Base

    # shortcut: no migrations, create_all only creates missing tables; add Alembic when the schema has to evolve
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":  # the one change so far: source_id was 500 long, too short for a magnet link (a no-op once done)
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE movies ALTER COLUMN source_id TYPE VARCHAR({models.SOURCE_ID_LENGTH})"))
