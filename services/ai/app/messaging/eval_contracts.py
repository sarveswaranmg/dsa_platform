"""Wire contracts for the session-evaluation lane (Phase 2 Slice 7).
`SessionCompleteEvent` is an independent copy of exam's
`app/messaging/eval_contracts.py` — services never import each other's code
(hard rule); the two copies are kept in sync by field name.
"""

import uuid

from pydantic import BaseModel


class SessionCompleteEvent(BaseModel):
    org_id: uuid.UUID
    session_id: uuid.UUID
    exam_id: uuid.UUID


class EvaluationCompleteEvent(BaseModel):
    org_id: uuid.UUID
    session_id: uuid.UUID
