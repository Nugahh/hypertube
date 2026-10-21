import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SECRET_KEY = os.environ["SECRET_KEY"]  # no default: a guessable key would let anyone forge sessions
SESSION_DAYS = 7
API_TOKEN_SECONDS = 3600

_hasher = PasswordHasher()  # argon2id, library defaults
# checked when the username does not exist, so a failed login takes as long either way
DUMMY_HASH = _hasher.hash("dummy password")


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password_hash, password):
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _encode(purpose, user_id, lifetime, **extra):
    expires = datetime.now(timezone.utc) + lifetime
    return jwt.encode(
        {"sub": str(user_id), "purpose": purpose, "exp": expires, **extra}, SECRET_KEY, algorithm="HS256"
    )


def _decode(token, purpose):
    # a token only works for the purpose it was issued for: a reset link is not a session, nor the reverse
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("purpose") == purpose else None


def create_token(user_id):
    return _encode("session", user_id, timedelta(days=SESSION_DAYS))


def read_token(token):
    """The user id a valid, unexpired session token was issued for, else None."""
    claims = _decode(token, "session")
    return int(claims["sub"]) if claims else None


def create_api_token(user_id, client_id):
    """What /api/oauth/token hands to a program: a Bearer token for one member, tied to the client that asked for it."""
    return _encode("api", user_id, timedelta(seconds=API_TOKEN_SECONDS), cid=client_id)


def read_api_token(token):
    """(user id, client id) of a valid, unexpired API token, else None."""
    claims = _decode(token, "api")
    return (int(claims["sub"]), int(claims["cid"])) if claims else None


def fingerprint(password_hash):
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


def create_reset_token(user):
    # bound to the current password: once it is changed the link stops working, so it is single use
    return _encode("reset", user.id, timedelta(hours=1), pw=fingerprint(user.password_hash))


def read_reset_token(token):
    """(user id, password fingerprint) of a valid, unexpired reset link, else None."""
    claims = _decode(token, "reset")
    return (int(claims["sub"]), claims.get("pw")) if claims else None
