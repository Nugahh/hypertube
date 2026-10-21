import os

# must be set before the app is imported
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, finder, main, movies, sources

USER = {
    "email": "Ada@Example.com",
    "username": "Ada_L",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "password": "Correct horse 42!",
}


@pytest.fixture(autouse=True)
def fresh_caches():
    sources._cache.clear()
    sources._down_until = 0
    finder._cache.clear()
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
    assert client.post("/api/auth/register", json=USER).status_code == 201
    return client
