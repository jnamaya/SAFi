from pydantic import BaseModel, Field
from typing import List, Literal


class WillResponse(BaseModel):
    """
    Schema for responses produced by the WillGate.
    - decision: whether the draft is approved or marked as a violation
    - reason: short explanation of the decision
    """
    decision: Literal['approve', 'violation']
    reason: str


class ConscienceEvaluation(BaseModel):
    """
    Schema for a single conscience evaluation result.
    - value: the ethical value being scored
    - score: numeric alignment score (-1 to 1)
    - confidence: model’s confidence in this score (0 to 1)
    - reason: explanation of why this score was assigned
    """
    value: str
    score: float = Field(..., ge=-1, le=1)
    confidence: float = Field(..., ge=0, le=1)
    reason: str


class ConscienceResponse(BaseModel):
    """
    Schema for the full conscience audit response.
    - evaluations: list of individual value-level evaluations
    """
    evaluations: List[ConscienceEvaluation]
