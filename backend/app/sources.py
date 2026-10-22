"""The search sources (Jackett indexers) the member can add or remove, so that nothing has to be set up in Jackett's own pages.

Jackett's web API needs a session cookie (the dashboard sets it) and, by default, no admin password.
"""
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from app import jackett
from app.auth import current_user

router = APIRouter(prefix="/api/sources", dependencies=[Depends(current_user)])

Id = Path(pattern=r"^[A-Za-z0-9_.-]{1,60}$")
SIMPLE = {"inputstring", "inputbool", "inputselect", "inputpassword"}  # the fields the form can show; others are sent back as they are


def _client():
    return httpx.AsyncClient(base_url=jackett.JACKETT_URL, follow_redirects=True, timeout=45)


async def _call(method, path, **kwargs):
    """One call to Jackett's API: its JSON (None when it answers nothing). 502 when it cannot be asked or refuses."""
    try:
        async with _client() as client:
            await client.get("/UI/Dashboard")  # the session cookie
            res = await client.request(method, f"/api/v2.0/indexers{path}", **kwargs)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Jackett is unreachable")
    if res.status_code >= 400:
        detail = ""
        try:
            detail = (res.json().get("error") or "").splitlines()[0]
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail or f"Jackett answered {res.status_code}")
    return res.json() if res.content else None


@router.get("")
async def listing():
    """Every indexer Jackett knows, configured or not."""
    found = await _call("GET", "")
    return [
        {k: i.get(k) for k in ("id", "name", "description", "language", "type", "configured")}
        for i in sorted(found, key=lambda i: i["name"].lower())
    ]


@router.get("/{indexer}/config")
async def config(indexer: str = Id):
    fields = await _call("GET", f"/{indexer}/config")
    return [
        {"id": f["id"], "name": f.get("name", f["id"]), "type": f["type"], "value": f.get("value"), "options": f.get("options")}
        for f in fields
        if f.get("type") in SIMPLE and f["id"] != "sitelink"
    ]


class Values(BaseModel):
    values: dict[str, Any] = {}


@router.put("/{indexer}", status_code=204)
async def add(data: Values, indexer: str = Id):
    """Configure (add) an indexer with the values of its form; the fields not in the form keep Jackett's defaults."""
    fields = await _call("GET", f"/{indexer}/config")
    known = {f["id"] for f in fields}
    body = [{"id": f["id"], "value": data.values.get(f["id"], f.get("value"))} for f in fields if f["id"] in known]
    await _call("POST", f"/{indexer}/config", json=body)


@router.delete("/{indexer}", status_code=204)
async def remove(indexer: str = Id):
    await _call("DELETE", f"/{indexer}")


@router.post("/{indexer}/test")
async def test(indexer: str = Id):
    """Whether the indexer answers right now."""
    try:
        await _call("POST", f"/{indexer}/test")
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    return {"ok": True}
