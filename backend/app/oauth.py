import logging
import os
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import APP_URL, COOKIE_SECURE, start_session
from app.db import get_db
from app.models import OAuthAccount, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth")

STATE_COOKIE = "oauth_state"
STATE_PATH = "/api/auth"


class Unverified(Exception):
    pass


def _read_42(p):
    # the school checked the email address
    return dict(subject=str(p["id"]), email=p["email"], verified=True, username=p["login"],
                first_name=p.get("first_name"), last_name=p.get("last_name"), avatar=(p.get("image") or {}).get("link"))


def _read_google(p):
    return dict(subject=p["sub"], email=p["email"], verified=p.get("email_verified") is True, username=p["email"].split("@")[0],
                first_name=p.get("given_name"), last_name=p.get("family_name"), avatar=p.get("picture"))


PROVIDERS = {
    "42": dict(
        env="FORTYTWO",
        authorize="https://api.intra.42.fr/oauth/authorize",
        token="https://api.intra.42.fr/oauth/token",
        profile="https://api.intra.42.fr/v2/me",
        scope="public",
        read=_read_42,
    ),
    "google": dict(
        env="GOOGLE",
        authorize="https://accounts.google.com/o/oauth2/v2/auth",
        token="https://oauth2.googleapis.com/token",
        profile="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
        read=_read_google,
    ),
}


def _http():
    return httpx.Client(timeout=10)


def _provider(name):
    if name not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    return PROVIDERS[name]


def _credentials(p):
    return os.getenv(f"{p['env']}_CLIENT_ID", ""), os.getenv(f"{p['env']}_CLIENT_SECRET", "")


def _redirect_uri(name):
    return f"{APP_URL}/api/auth/{name}/callback"


def _back(error=None):
    """Back to the site; the front shows the error, if any. The state is single use."""
    response = RedirectResponse(f"{APP_URL}/" + (f"?oauth_error={error}" if error else ""))
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


@router.get("/{provider}/login")
def oauth_login(provider: str):
    p = _provider(provider)
    client_id, secret = _credentials(p)
    if not client_id or not secret:
        return _back("unavailable")
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {"client_id": client_id, "redirect_uri": _redirect_uri(provider), "response_type": "code", "scope": p["scope"], "state": state}
    )
    response = RedirectResponse(f"{p['authorize']}?{query}")
    # the callback must come back to the browser that started the flow, or anyone could push their own code into a victim's session
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=COOKIE_SECURE, path=STATE_PATH)
    return response


def _fetch_profile(name, p, code):
    client_id, secret = _credentials(p)
    with _http() as http:
        token = http.post(
            p["token"],
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(name), "client_id": client_id, "client_secret": secret},
        )
        token.raise_for_status()
        profile = http.get(p["profile"], headers={"Authorization": f"Bearer {token.json()['access_token']}"})
        profile.raise_for_status()
        return p["read"](profile.json())


def _free_username(db, hint):
    base = re.sub(r"[^a-z0-9_]", "_", hint.lower())[:24].ljust(3, "_")
    username, n = base, 0
    while db.scalar(select(User.id).where(User.username == username)):
        n += 1
        username = f"{base}_{n}"
    return username


def _member(db, name, info):
    """The member this provider identity belongs to: known identity, else the account with the same verified email, else a new one."""
    account = db.scalar(select(OAuthAccount).where(OAuthAccount.provider == name, OAuthAccount.subject == info["subject"]))
    if account:
        return db.get(User, account.user_id)
    if not info["verified"]:
        # an unverified email proves nothing: joining the account that owns it would let anyone take it over
        raise Unverified
    email = info["email"].strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        username = _free_username(db, info["username"])
        avatar = info["avatar"]
        user = User(
            email=email,
            username=username,
            first_name=(info["first_name"] or "").strip()[:50] or username,
            last_name=(info["last_name"] or "").strip()[:50] or username,
            avatar_url=avatar if avatar and avatar.startswith("https://") and len(avatar) <= 500 else None,
        )
        db.add(user)
        db.flush()
    db.add(OAuthAccount(provider=name, subject=info["subject"], user_id=user.id))
    db.commit()
    return user


@router.get("/{provider}/callback")
def oauth_callback(
    provider: str,
    state: str = "",
    code: str = "",
    error: str = "",
    oauth_state: str | None = Cookie(None),
    db: Session = Depends(get_db),
):
    p = _provider(provider)
    if not oauth_state or not secrets.compare_digest(oauth_state.encode(), state.encode()):
        return _back("failed")
    if error:
        return _back("denied")
    try:
        if not code:
            raise ValueError("no code")
        user = _member(db, provider, _fetch_profile(provider, p, code))
    except Unverified:
        return _back("unverified")
    except Exception as e:  # provider down, bad answer, constraint: always the same generic message, never the details
        db.rollback()
        log.warning("oauth %s failed: %s", provider, type(e).__name__)
        return _back("failed")
    response = _back()
    start_session(response, user)
    return response
