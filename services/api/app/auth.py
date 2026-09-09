"""Caller identity and district authorization.

App Service Easy Auth validates the token and injects the validated principal
as a header, so this module never parses a JWT or fetches signing keys.
Owning JWKS caching and key rollover in application code would be a liability
with no upside here.

The important half is authorization, not authentication. Before this existed
a caller chose their own `district_id` in the request body, so district
scoping was a suggestion. Retrieval-layer filtering cannot fix that: it
faithfully returns whichever district the caller asked for.

Unassigned identities get NO districts. A default grant would hand every
account in the tenant access to a district's data, which is the failure this
module exists to prevent.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request

# Injected by App Service Easy Auth after it has validated the token.
PRINCIPAL_HEADER = "x-ms-client-principal"
PRINCIPAL_ID_HEADER = "x-ms-client-principal-id"
PRINCIPAL_NAME_HEADER = "x-ms-client-principal-name"

AUTH_MODE_ENTRA = "entra"
AUTH_MODE_DISABLED = "disabled"

# Used only when auth is disabled for local development.
LOCAL_DEV_PRINCIPAL_ID = "local-dev"


@dataclass(frozen=True)
class Principal:
    """An authenticated caller and the districts they may act on."""

    object_id: str
    tenant_id: str
    display_name: str
    districts: frozenset[str] = field(default_factory=frozenset)
    is_facilitator: bool = False

    def may_access(self, district_id: str) -> bool:
        return self.is_facilitator or district_id in self.districts

    def visible_districts(self, known: frozenset[str]) -> frozenset[str]:
        return known if self.is_facilitator else self.districts & known


def api_auth_mode() -> str:
    """`entra` unless explicitly disabled. Terraform always sets `entra`."""

    mode = os.environ.get("API_AUTH_MODE", AUTH_MODE_ENTRA).strip().lower()
    return AUTH_MODE_DISABLED if mode == AUTH_MODE_DISABLED else AUTH_MODE_ENTRA


def _parse_assignments(raw: str) -> dict[str, frozenset[str]]:
    """Parse `oid=DIST-A|DIST-B,oid2=DIST-C` into a lookup.

    Keyed on object id: it is immutable and unique within the tenant, unlike
    a UPN which can be reassigned to a different person.
    """

    assignments: dict[str, frozenset[str]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        key, _, districts = entry.partition("=")
        allowed = {d.strip() for d in districts.split("|") if d.strip()}
        if key.strip() and allowed:
            assignments[key.strip().lower()] = frozenset(allowed)
    return assignments


def district_assignments() -> dict[str, frozenset[str]]:
    return _parse_assignments(os.environ.get("DISTRICT_ASSIGNMENTS", ""))


def facilitator_ids() -> frozenset[str]:
    raw = os.environ.get("FACILITATOR_OBJECT_IDS", "")
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def _decode_principal_header(encoded: str) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        parsed = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Malformed client principal.") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=401, detail="Malformed client principal.")
    return parsed


def _claim(claims: list[dict[str, Any]], *names: str) -> str:
    wanted = {n.lower() for n in names}
    for claim in claims:
        typ = str(claim.get("typ") or claim.get("type") or "").lower()
        if typ in wanted or typ.rsplit("/", 1)[-1] in wanted:
            return str(claim.get("val") or claim.get("value") or "")
    return ""


def principal_from_request(request: Request) -> Principal:
    """Build the caller's principal, or 401.

    Easy Auth has already validated signature, issuer, audience and expiry by
    the time the request reaches the app; these headers only exist on a
    validated request.
    """

    if api_auth_mode() == AUTH_MODE_DISABLED:
        # Local development only. Terraform never sets this for a deployed app,
        # and /api/health/details reports the mode so an unauthenticated
        # deployment is visible from outside.
        every = frozenset(district_assignments().get(LOCAL_DEV_PRINCIPAL_ID, frozenset()))
        return Principal(
            object_id=LOCAL_DEV_PRINCIPAL_ID,
            tenant_id="local",
            display_name="local development",
            districts=every,
            is_facilitator=True,
        )

    encoded = request.headers.get(PRINCIPAL_HEADER, "").strip()
    if not encoded:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_principal_header(encoded)
    claims = payload.get("claims") or []
    if not isinstance(claims, list):
        claims = []

    object_id = (
        _claim(claims, "oid", "objectidentifier") or request.headers.get(PRINCIPAL_ID_HEADER, "")
    ).strip()
    tenant_id = _claim(claims, "tid", "tenantid").strip()
    display_name = (
        _claim(claims, "name", "preferred_username", "upn")
        or request.headers.get(PRINCIPAL_NAME_HEADER, "")
    ).strip()

    if not object_id:
        raise HTTPException(status_code=401, detail="Principal has no object id.")

    key = object_id.lower()
    facilitator = key in facilitator_ids()
    districts = district_assignments().get(key, frozenset())

    return Principal(
        object_id=object_id,
        tenant_id=tenant_id,
        display_name=display_name or object_id,
        districts=districts,
        is_facilitator=facilitator,
    )


def require_district(principal: Principal, district_id: str) -> None:
    """403 unless the caller is assigned this district.

    Deliberately does not distinguish "no such district" from "not yours":
    that difference would let a caller enumerate which districts exist.
    """

    if not principal.may_access(district_id):
        raise HTTPException(
            status_code=403,
            detail=f"Not authorized for district {district_id}.",
        )
