import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Email, Name, Password, UserOut, Username, current_user
from app.db import get_db
from app import security
from app.models import User, Welcomed

# every route here is for authenticated users
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


class UserBrief(BaseModel):
    id: int
    username: str


class UserListed(UserBrief):
    avatar_url: str | None


class PublicUser(UserBrief):
    first_name: str
    last_name: str
    avatar_url: str | None


# the site's own default pictures (frontend/public/avatars): a plain file name, nothing that climbs or leaves the folder
DEFAULT_AVATAR = re.compile(r"/avatars/[a-z0-9-]{1,30}\.(svg|png|webp|jpg)")


def _check_avatar_url(v):
    if DEFAULT_AVATAR.fullmatch(v):
        return v
    # https only: a javascript: or data: URL has no business in an <img>, and http would be mixed content
    if not (v.startswith("https://") and len(v) <= 500 and not re.search(r"\s", v)):
        raise ValueError("an https:// URL of at most 500 characters, or one of the site's own pictures")
    return v


AvatarUrl = Annotated[str, AfterValidator(_check_avatar_url)]


class UserPatch(BaseModel):
    # only these fields can be changed: anything else in the body is ignored
    username: Username | None = None
    password: Password | None = None
    avatar_url: AvatarUrl | None = None
    email: Email | None = None
    first_name: Name | None = None
    last_name: Name | None = None
    language: Literal["en", "fr"] | None = None
    welcomed: Literal[True] | None = None  # the first-login page is done; it cannot be undone


@router.get("/users", response_model=list[UserListed])
def list_users(db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.get("/users/{user_id}", response_model=UserOut | PublicUser)
def get_user(user_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # the email is private: only its owner gets it
    return UserOut.model_validate(user) if user.id == me.id else PublicUser.model_validate(user, from_attributes=True)


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, data: UserPatch, me: User = Depends(current_user), db: Session = Depends(get_db)):
    if user_id != me.id:
        raise HTTPException(status_code=403, detail="You can only edit your own profile")
    changes = data.model_dump(exclude_none=True)
    if changes.pop("welcomed", False) and not me.welcomed:
        me.welcome = Welcomed()
    if "password" in changes:
        me.password_hash = security.hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(me, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already taken")
    return me
