"""Pydantic models for the congruence-closure audit API."""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

# A term is either a constant name (string) or ["f", child, ...] (list).
Term = Any
StepType = Literal["push", "pop", "eq", "neq", "claim"]


class Signature(BaseModel):
    constants: List[str] = Field(default_factory=list)
    functions: dict[str, int] = Field(default_factory=dict)


class ProofStep(BaseModel):
    index: Optional[int] = None
    type: StepType
    left: Optional[Term] = None
    right: Optional[Term] = None


class ProofPayload(BaseModel):
    audit_id: str = Field(min_length=1)
    signature: Signature = Field(default_factory=Signature)
    steps: List[ProofStep] = Field(default_factory=list)


class Justification(BaseModel):
    rule: str
    detail: str
    children: List["Justification"] = Field(default_factory=list)


class CongruencePair(BaseModel):
    left: Term
    right: Term


class StepResult(BaseModel):
    index: int
    type: StepType
    ok: bool
    scope_depth: int
    left: Optional[Term] = None
    right: Optional[Term] = None
    declared_equal: bool = False
    declared_unequal: bool = False
    justification: Optional[Justification] = None
    congruence_pairs: List[CongruencePair] = Field(default_factory=list)
    error: Optional[str] = None
    error_position: Optional[str] = None


class ReplayInfo(BaseModel):
    replayed: bool
    frozen: bool


class ProofResponse(BaseModel):
    audit_id: str
    accepted: bool
    verdict: Literal["valid", "contradiction", "invalid"]
    failure_step: Optional[int] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    error_position: Optional[str] = None
    scope_depth: int
    steps: List[StepResult]
    replay: ReplayInfo


class HealthResponse(BaseModel):
    status: str
    service: str


Justification.model_rebuild()
