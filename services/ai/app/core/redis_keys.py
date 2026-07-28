"""Single source of truth for ai's Redis key shapes.

All keys are prefixed `ai:` so the service can share one logical Redis
database with other services (ElastiCache cluster mode has no numeric DB
indexes) without colliding on keyspace — mirrors exam's `ex:` convention.
"""

import uuid


def difficulty_key(session_id: uuid.UUID) -> str:
    return f"ai:diff:{session_id}"
