"""Single source of truth for exam's Redis key shapes.

All keys are prefixed `ex:` so the service can share one logical Redis
database with other services (ElastiCache cluster mode has no numeric DB
indexes) without colliding on keyspace.
"""

import uuid


def session_key(session_id: uuid.UUID) -> str:
    return f"ex:session:{session_id}"


def invite_key(jti: str) -> str:
    return f"ex:invite:{jti}"
