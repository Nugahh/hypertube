"""The member's settings, kept in the database: how long a film that was only streamed stays in the cache."""
import os
from typing import Annotated

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


class SettingsIn(BaseModel):
    cache_days: Annotated[int, Field(ge=0, le=365)]


def _out(db, engine):
    # in Docker the folder is mounted: LIBRARY_LABEL says where it is on the machine
    return {"cache_days": cache_days(db), "library_dir": os.getenv("LIBRARY_LABEL") or str(engine.library_dir)}


@router.get("")
def read(db: Session = Depends(get_db), engine=Depends(get_engine)):
    return _out(db, engine)


@router.patch("")
def update(data: SettingsIn, db: Session = Depends(get_db), engine=Depends(get_engine)):
    db.merge(Setting(key=CACHE_DAYS, value=str(data.cache_days)))
    db.commit()
    return _out(db, engine)
