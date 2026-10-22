"""The member's settings, kept in the database: how long a film that was only streamed stays in the cache."""
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.engine import get_engine
from app.models import Setting

router = APIRouter(prefix="/api/settings", dependencies=[Depends(current_user)])

CACHE_DAYS = "cache_days"
DEFAULT_CACHE_DAYS = int(os.getenv("CACHE_DAYS", "3"))


def cache_days(db):
    """Days a film only streamed stays in the cache after it was last watched; 0: never cleaned up."""
    row = db.get(Setting, CACHE_DAYS)
    return int(row.value) if row else DEFAULT_CACHE_DAYS


# the keys of the services the app uses, typed in the settings (kept in the database, given to the code through the environment)
KEYS = {
    "tmdb_api_key": "TMDB_API_KEY",
    "opensubtitles_api_key": "OPENSUBTITLES_API_KEY",
    "opensubtitles_username": "OPENSUBTITLES_USERNAME",
    "opensubtitles_password": "OPENSUBTITLES_PASSWORD",
}
SHOWN = {"opensubtitles_username"}  # the others are secrets: only whether they are set is told


def load_keys(db):
    """At startup: what the member typed wins over the environment (an empty field leaves the environment alone)."""
    for name, variable in KEYS.items():
        row = db.get(Setting, name)
        if row and row.value:
            os.environ[variable] = row.value


class SettingsIn(BaseModel):
    cache_days: Annotated[int, Field(ge=0, le=365)] | None = None
    keys: dict[Literal["tmdb_api_key", "opensubtitles_api_key", "opensubtitles_username", "opensubtitles_password"], Annotated[str, Field(max_length=200)]] | None = None


def _out(db, engine):
    # in Docker the folder is mounted: LIBRARY_LABEL says where it is on the machine
    return {
        "cache_days": cache_days(db),
        "library_dir": os.getenv("LIBRARY_LABEL") or str(engine.library_dir),
        "keys": {name: (os.getenv(variable, "") if name in SHOWN else bool(os.getenv(variable))) for name, variable in KEYS.items()},
    }


@router.get("")
def read(db: Session = Depends(get_db), engine=Depends(get_engine)):
    return _out(db, engine)


@router.patch("")
def update(data: SettingsIn, db: Session = Depends(get_db), engine=Depends(get_engine)):
    if data.cache_days is not None:
        db.merge(Setting(key=CACHE_DAYS, value=str(data.cache_days)))
    for name, value in (data.keys or {}).items():
        value = value.strip()
        db.merge(Setting(key=name, value=value))
        if value:
            os.environ[KEYS[name]] = value
        else:
            os.environ.pop(KEYS[name], None)  # an emptied field clears the key
    db.commit()
    return _out(db, engine)
