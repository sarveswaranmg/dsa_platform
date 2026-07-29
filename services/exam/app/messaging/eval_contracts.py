"""Wire contract for the session-complete event, consumed by ai's evaluation
pipeline (Phase 2 Slice 7). Independent copy of ai's
`app/messaging/eval_contracts.py` — services never import each other's code
(hard rule); the two copies are kept in sync by field name."""

import uuid

from pydantic import BaseModel


class SessionCompleteEvent(BaseModel):
    org_id: uuid.UUID
    session_id: uuid.UUID
    exam_id: uuid.UUID
