import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, main, movies, tmdb


@pytest.fixture(autouse=True)
def fresh_caches():
    tmdb._genres.clear()
    movies._audio_cache.clear()


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def client(session_factory):
    def get_db():
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[db.get_db] = get_db
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client):
    """Nobody logs in: the one member exists from the first request (kept under this name by the tests)."""
    assert client.get("/api/auth/me").status_code == 200
    return client
