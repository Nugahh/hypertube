import os
import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import mail, security
from app.db import get_db
from app.models import ApiClient, User

COOKIE = "session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false") == "true"  # true once the site is served over HTTPS
APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")  # where the reset link in the email points

router = APIRouter(prefix="/api/auth")


def _check_password(v):
    if not (8 <= len(v) <= 128 and re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
        raise ValueError("8 to 128 characters with at least one letter and one digit")
    return v


def _check_name(v):
    v = v.strip()
    if not 1 <= len(v) <= 50:
        raise ValueError("1 to 50 characters")
    return v


def _check_username(v):
    v = v.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,30}", v):
        raise ValueError("3 to 30 characters: letters, digits, underscore")
    return v


# shared with the profile update (users.py)
Username = Annotated[str, AfterValidator(_check_username)]
Password = Annotated[str, AfterValidator(_check_password)]
Name = Annotated[str, AfterValidator(_check_name)]
Email = Annotated[EmailStr, AfterValidator(str.lower)]


class RegisterIn(BaseModel):
    email: Email
    username: Username
    first_name: Name
    last_name: Name
    password: Password


class LoginIn(BaseModel):
    username: str = Field(max_length=30)
    password: str = Field(max_length=128)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(max_length=2000)
    password: Password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    first_name: str
    last_name: str
    language: str
    avatar_url: str | None


def start_session(response, user):
    response.set_cookie(
        COOKIE,
        security.create_token(user.id),
        max_age=security.SESSION_DAYS * 86400,
        httponly=True,  # not readable from JavaScript, so an XSS cannot steal it
        samesite="lax",  # not sent on cross-site POSTs: CSRF protection
        secure=COOKIE_SECURE,
    )


def session_user(session: str | None = Cookie(None), db: Session = Depends(get_db)):
    """The member of the website session cookie, else None."""
    user_id = security.read_token(session) if session else None
    return db.get(User, user_id) if user_id else None


def optional_user(
    session: str | None = Cookie(None), authorization: str | None = Header(None), db: Session = Depends(get_db)
):
    """The member making the request: a program with a Bearer token (see clients.py), else the website session."""
    if authorization is None:
        return session_user(session, db)
    scheme, _, token = authorization.partition(" ")
    claims = security.read_api_token(token.strip()) if scheme.lower() == "bearer" else None
    client = db.get(ApiClient, claims[1]) if claims else None
    # deleting the client revokes its tokens
    return db.get(User, claims[0]) if client and client.user_id == claims[0] else None


def current_user(user: User | None = Depends(optional_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def web_user(user: User | None = Depends(session_user)):
    """Like current_user but only the website session counts: a Bearer token cannot mint more credentials."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/register", status_code=201, response_model=UserOut)
def register(data: RegisterIn, response: Response, db: Session = Depends(get_db)):
    user = User(
        email=data.email,
        username=data.username,
        first_name=data.first_name,
        last_name=data.last_name,
        password_hash=security.hash_password(data.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # the unique constraints also cover two simultaneous sign-ups
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already taken")
    start_session(response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username.strip().lower()))
    stored = user.password_hash if user and user.password_hash else security.DUMMY_HASH
    if not security.verify_password(stored, data.password) or user is None or not user.password_hash:
        # same answer for an unknown user and a wrong password
        raise HTTPException(status_code=401, detail="Invalid credentials")
    start_session(response, user)
    return user


RESET_MAIL = {
    "en": ("Reset your Hypertube password", "Hello {name},\n\nChoose a new password here (valid for 1 hour):\n{link}\n\nIf you did not ask for this, ignore this email."),
    "fr": ("Réinitialise ton mot de passe Hypertube", "Bonjour {name},\n\nChoisis un nouveau mot de passe ici (valable 1 heure) :\n{link}\n\nSi tu n'es pas à l'origine de cette demande, ignore cet email."),
}


@router.post("/forgot", status_code=202)
def forgot(data: ForgotIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user:
        link = f"{APP_URL}/reset-password?token={security.create_reset_token(user)}"
        subject, body = RESET_MAIL.get(user.language, RESET_MAIL["en"])
        # sent after the response: the answer takes the same time whether or not the account exists
        background.add_task(mail.send_email, user.email, subject, body.format(name=user.first_name, link=link))
    return {"detail": "If an account exists for this email, a message was sent"}


@router.post("/reset", status_code=204)
def reset(data: ResetIn, db: Session = Depends(get_db)):
    claims = security.read_reset_token(data.token)
    user = db.get(User, claims[0]) if claims else None
    if user is None or claims[1] != security.fingerprint(user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    # shortcut: sessions already open stay valid after a reset; add a session version on the user to revoke them
    user.password_hash = security.hash_password(data.password)
    db.commit()


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=COOKIE_SECURE)


# null (not 401) for a visitor: the front asks on every page load and a 401 would log an error in the console
@router.get("/me", response_model=UserOut | None)
def me(user: User | None = Depends(optional_user)):
    return user
