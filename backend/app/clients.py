"""OAuth2 for programs: a member creates a client id and secret, a program trades them for a Bearer token (client credentials)."""
import base64
import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import security
from app.auth import web_user
from app.db import get_db
from app.models import ApiClient, User

MAX_CLIENTS = 5

router = APIRouter(prefix="/api")


def _name(v):
    v = v.strip()
    if not 1 <= len(v) <= 50:
        raise ValueError("1 to 50 characters")
    return v


class NewClient(BaseModel):
    name: Annotated[str, AfterValidator(_name)]


def _hash(secret):
    # sha256 is enough: the secret is 256 random bits, there is nothing to brute-force (unlike a password)
    return hashlib.sha256(secret.encode()).hexdigest()


def _out(client, secret=None):
    return {"id": client.id, "name": client.name, "client_id": client.client_id, "created_at": client.created_at, **({"client_secret": secret} if secret else {})}


@router.post("/clients", status_code=201)
def create(data: NewClient, response: Response, user: User = Depends(web_user), db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(ApiClient).where(ApiClient.user_id == user.id)) >= MAX_CLIENTS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_CLIENTS} API clients")
    secret = secrets.token_urlsafe(32)
    client = ApiClient(user_id=user.id, name=data.name, client_id=secrets.token_hex(16), secret_hash=_hash(secret))
    db.add(client)
    db.commit()
    response.headers["Location"] = f"/api/clients/{client.id}"
    return _out(client, secret)  # the only time the secret is visible


@router.get("/clients")
def list_clients(user: User = Depends(web_user), db: Session = Depends(get_db)):
    return [_out(c) for c in db.scalars(select(ApiClient).where(ApiClient.user_id == user.id).order_by(ApiClient.id))]


@router.delete("/clients/{client_id}", status_code=204)
def delete(client_id: int, user: User = Depends(web_user), db: Session = Depends(get_db)):
    client = db.get(ApiClient, client_id)
    if client is None or client.user_id != user.id:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()


def _error(status, error):
    # RFC 6749: token errors are {"error": code} and are never cached
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/oauth/token")
def token(
    grant_type: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """Client id + secret in, Bearer token out. They come in the form, or in an HTTP Basic header."""
    if authorization and authorization.lower().startswith("basic "):
        try:
            client_id, _, client_secret = base64.b64decode(authorization[6:]).decode().partition(":")
        except ValueError:
            return _error(400, "invalid_request")
    if grant_type != "client_credentials":
        return _error(400, "unsupported_grant_type")
    if not client_id or not client_secret:
        return _error(400, "invalid_request")
    client = db.scalar(select(ApiClient).where(ApiClient.client_id == client_id))
    # same answer for an unknown client and a wrong secret
    if client is None or not hmac.compare_digest(client.secret_hash, _hash(client_secret)):
        return _error(401, "invalid_client")
    return JSONResponse(
        {"access_token": security.create_api_token(client.user_id, client.id), "token_type": "Bearer", "expires_in": security.API_TOKEN_SECONDS},
        headers={"Cache-Control": "no-store"},
    )
