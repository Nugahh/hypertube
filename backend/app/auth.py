"""One person uses the app, on their own machine: nobody logs in. The only member is created the first time it is needed."""
import getpass
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/auth")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    language: str
    avatar_url: str | None


def _name():
    try:
        name = re.sub(r"[^a-z0-9_]", "", getpass.getuser().lower())
    except Exception:  # no login name known to the system
        name = ""
    return name[:30] if len(name) >= 3 else "me"


def current_user(db: Session = Depends(get_db)):
    user = db.scalars(select(User).order_by(User.id)).first()
    if user is None:
        name = _name()
        user = User(email=f"{name}@hypertube.local", username=name, first_name=name, last_name=name)
        db.add(user)
        db.commit()
    return user


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
