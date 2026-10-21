from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AfterValidator, BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import Comment, Movie, User

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _text(v):
    v = v.strip()
    if not 1 <= len(v) <= 1000:
        raise ValueError("1 to 1000 characters")
    return v


Text = Annotated[str, AfterValidator(_text)]


class NewComment(BaseModel):
    comment: Text


class NewCommentOnMovie(NewComment):
    movie_id: int


class EditComment(NewComment):
    username: str | None = None


def out(c):
    return {
        "id": c.id,
        "movie_id": c.movie_id,
        "user_id": c.user_id,
        "username": c.user.username,
        "avatar_url": c.user.avatar_url,
        "date": c.created_at,
        "content": c.content,
        "edited": c.updated_at is not None,
    }


def _comment(db, comment_id):
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


def _movie_exists(db, movie_id):
    if db.get(Movie, movie_id) is None:
        raise HTTPException(status_code=404, detail="Movie not found")


def _create(db, user, movie_id, text, response):
    _movie_exists(db, movie_id)
    comment = Comment(movie_id=movie_id, user_id=user.id, content=text)
    db.add(comment)
    db.commit()
    response.status_code = 201
    response.headers["Location"] = f"/api/comments/{comment.id}"
    return out(comment)


@router.get("/comments")
def latest(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return [out(c) for c in db.scalars(select(Comment).order_by(Comment.id.desc()).limit(limit))]


@router.post("/comments")
def create(data: NewCommentOnMovie, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _create(db, user, data.movie_id, data.comment, response)


@router.get("/comments/{comment_id}")
def read(comment_id: int, db: Session = Depends(get_db)):
    return out(_comment(db, comment_id))


@router.patch("/comments/{comment_id}")
def edit(comment_id: int, data: EditComment, user: User = Depends(current_user), db: Session = Depends(get_db)):
    comment = _comment(db, comment_id)
    # the username in the payload cannot be used to edit as someone else
    if comment.user_id != user.id or (data.username is not None and data.username.strip().lower() != user.username):
        raise HTTPException(status_code=403, detail="Not your comment")
    comment.content, comment.updated_at = data.comment, datetime.now(timezone.utc)
    db.commit()
    return out(comment)


@router.delete("/comments/{comment_id}", status_code=204)
def delete(comment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    comment = _comment(db, comment_id)
    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your comment")
    db.delete(comment)
    db.commit()


@router.get("/movies/{movie_id}/comments")
def of_movie(movie_id: int, db: Session = Depends(get_db)):
    _movie_exists(db, movie_id)
    return [out(c) for c in db.scalars(select(Comment).where(Comment.movie_id == movie_id).order_by(Comment.id.desc()))]


@router.post("/movies/{movie_id}/comments")
def create_on_movie(movie_id: int, data: NewComment, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _create(db, user, movie_id, data.comment, response)
