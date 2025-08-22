from pydantic import BaseModel, Field
from typing import List, Literal

class WillResponse(BaseModel):
    decision: Literal['approve', 'violation']
    reason: str

class ConscienceEvaluation(BaseModel):
    value: str
    score: float = Field(..., ge=-1, le=1)
    confidence: float = Field(..., ge=0, le=1)
    reason: str

class ConscienceResponse(BaseModel):
    evaluations: List[ConscienceEvaluation]
