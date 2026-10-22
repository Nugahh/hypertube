from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import UserOut, current_user
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


class LanguageIn(BaseModel):
    language: Literal["en", "fr"]


@router.patch("/users/me", response_model=UserOut)
def set_language(data: LanguageIn, me: User = Depends(current_user), db: Session = Depends(get_db)):
    me.language = data.language
    db.commit()
    return me
