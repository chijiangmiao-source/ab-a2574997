"""FastAPI application: scoped congruence-closure proof audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .engine import run_proof
from .models import HealthResponse, ProofPayload, ProofResponse

# audit_id -> {"hash": payload hash, "response": frozen response dict}
_STORE: Dict[str, Dict[str, Any]] = {}

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(
    title="深空载荷同余闭包审查 API",
    description="按作用域精确维护可回滚的同余闭包，校验等式/不等式/矛盾声称轨迹。",
    version="1.0.0",
)


def _payload_hash(payload: ProofPayload) -> str:
    """Hash of everything except the audit id (signature + steps, canonical)."""
    canonical = {
        "signature": payload.signature.model_dump(),
        "steps": [s.model_dump(exclude_none=True) for s in payload.steps],
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _freeze(payload: ProofPayload, replayed: bool) -> dict[str, Any]:
    outcome = run_proof(payload.model_dump())
    response = {
        "audit_id": payload.audit_id,
        "accepted": outcome["accepted"],
        "verdict": outcome["verdict"],
        "failure_step": outcome.get("failure_step"),
        "error": outcome.get("error"),
        "error_code": outcome.get("error_code"),
        "error_position": outcome.get("error_position"),
        "scope_depth": outcome["scope_depth"],
        "steps": outcome["steps"],
        "replay": {"replayed": replayed, "frozen": True},
    }
    return response


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="congruence-audit")


@app.post("/api/proofs", response_model=ProofResponse)
def submit_proof(payload: ProofPayload) -> JSONResponse:
    digest = _payload_hash(payload)
    existing = _STORE.get(payload.audit_id)
    if existing is not None:
        if existing["hash"] != digest:
            return JSONResponse(
                status_code=409,
                content={
                    "accepted": False,
                    "verdict": "invalid",
                    "error": (
                        f"审计标识 “{payload.audit_id}” 已存在且载荷不同："
                        "改换载荷被明确拒绝，请使用新的审计标识重传"
                    ),
                    "error_code": "payload_conflict",
                    "error_position": "audit_id",
                    "failure_step": None,
                    "scope_depth": 0,
                    "steps": [],
                    "replay": {"replayed": False, "frozen": False},
                    "audit_id": payload.audit_id,
                },
            )
        # Same id + same payload: replay returns the frozen result verbatim.
        frozen = dict(existing["response"])
        frozen["replay"] = {"replayed": True, "frozen": True}
        return JSONResponse(status_code=200, content=frozen)

    response = _freeze(payload, replayed=False)
    _STORE[payload.audit_id] = {"hash": digest, "response": response}
    return JSONResponse(status_code=200, content=response)


@app.get("/api/proofs/{audit_id}", response_model=ProofResponse)
def get_proof(audit_id: str) -> JSONResponse:
    existing = _STORE.get(audit_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"审计标识 “{audit_id}” 不存在")
    return JSONResponse(status_code=200, content=existing["response"])


@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc: ValidationError):  # pragma: no cover
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# Serve the built React page when present (container image / local build).
if FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIST), html=True),
        name="frontend",
    )
