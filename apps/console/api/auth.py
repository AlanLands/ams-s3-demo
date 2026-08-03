"""Login/logout/me + the `require_identity` dependency every other router
depends on. Wraps `common.roster.authenticate()` — the fictional
roster/passcode scheme — and enforces it server-side: a missing/invalid
session cookie 401s before any other router's handler body runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from apps.console.api.session import (
    SESSION_COOKIE_NAME,
    create_session,
    destroy_session,
    get_session_data,
)
from common.roster import (
    MANAGER_NAME,
    ROSTER,
    Identity,
    authenticate,
    group_for_engineer,
    role_for,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    name: str
    passcode: str


class IdentityResponse(BaseModel):
    name: str
    role: str
    group: str | None


def _identity_response(identity: Identity) -> IdentityResponse:
    return IdentityResponse(name=identity.name, role=identity.role, group=identity.group)


@router.get("/roster")
def roster() -> list[str]:
    """Name choices for the login form's dropdown — same roster the
    Streamlit login form already lists."""
    return [*ROSTER, MANAGER_NAME]


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> IdentityResponse:
    if not authenticate(payload.name, payload.passcode):
        raise HTTPException(status_code=401, detail="Name/passcode didn't match.")
    role = role_for(payload.name)
    identity = Identity(name=payload.name, role=role, group=group_for_engineer(payload.name))
    session_id = create_session()
    session = get_session_data(session_id)
    assert session is not None
    session["identity"] = identity
    response.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="lax", path="/")
    return _identity_response(identity)


@router.post("/logout")
def logout(
    response: Response,
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict:
    destroy_session(session_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


def require_identity(
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Identity:
    session = get_session_data(session_id)
    if session is None or "identity" not in session:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return session["identity"]


def require_manager(identity: Identity = Depends(require_identity)) -> Identity:
    """Manager-only gate, layered on the identity dependency.

    Lives here rather than in one router because two now need it, and because
    "which routes are manager-only" has to be answerable by grep rather than by
    reading every handler body.

    The reason this is server-side at all is the same reason the commit gate
    and the release record's approvals are (see CLAUDE.md): a role the client
    asserts is a role the client can claim. Assignment decides who owns a
    ticket and whose name lands in its event log, so a UI-only manager check
    means any authenticated caller can reassign any ticket by hand.
    """
    if identity.role != "manager":
        raise HTTPException(status_code=403, detail="Manager role required.")
    return identity


def require_session_id(
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> str:
    if session_id is None or get_session_data(session_id) is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return session_id


@router.get("/me")
def me(identity: Identity = Depends(require_identity)) -> IdentityResponse:
    return _identity_response(identity)
