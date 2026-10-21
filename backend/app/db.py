import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# PostgreSQL in Docker (see docker-compose.yml); SQLite when running without it
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hypertube.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session


def init_db():
    from app import models  # noqa: F401  (registers the tables on Base)

    # shortcut: no migrations, create_all only creates missing tables; add Alembic when the schema has to evolve
    Base.metadata.create_all(engine)
