import hashlib
import random
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import QuestionRef, QuestionServiceClient
from app.core.exceptions import InsufficientQuestionPool
from app.schemas.sampling import SampleResponse, TopicSelection
from app.services import blueprints as blueprints_service


def _seed(blueprint_version_id: uuid.UUID, candidate_key: str, entry_index: int) -> int:
    # hashlib (not the salted builtin hash()) so the seed is stable across
    # processes and runs — the guarantee candidate reproducibility relies on.
    payload = f"{blueprint_version_id}:{candidate_key}:{entry_index}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def choose[T](
    pool_sorted: list[T],
    *,
    blueprint_version_id: uuid.UUID,
    candidate_key: str,
    entry_index: int,
    count: int,
) -> list[T]:
    """Deterministically pick `count` items from a stably-ordered pool. Shared
    by the examiner sample preview and the candidate session assignment so both
    reproduce the same per-candidate selection. Caller sorts the pool."""
    if len(pool_sorted) < count:
        raise InsufficientQuestionPool(
            f"pool has {len(pool_sorted)} questions but {count} are required"
        )
    rng = random.Random(_seed(blueprint_version_id, candidate_key, entry_index))
    return rng.sample(pool_sorted, count)


async def sample_blueprint(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    blueprint_id: uuid.UUID,
    candidate_key: str,
    authorization: str,
    client: QuestionServiceClient,
) -> SampleResponse:
    _, version = await blueprints_service.get_blueprint(
        session, org_id=org_id, blueprint_id=blueprint_id
    )

    selections: list[TopicSelection] = []
    total_questions = 0
    for index, entry in enumerate(version.topic_mix):
        topic_id = uuid.UUID(str(entry["topic_id"]))
        d_min = int(entry["difficulty_min"])
        d_max = int(entry["difficulty_max"])
        count = int(entry["question_count"])

        # Fan out one call per difficulty in the range; union, dedup by id.
        pool: dict[uuid.UUID, QuestionRef] = {}
        for difficulty in range(d_min, d_max + 1):
            for ref in await client.list_published_questions(
                authorization=authorization, topic_id=topic_id, difficulty=difficulty
            ):
                pool[ref.id] = ref

        # Sort by id so question-service ordering can't perturb the sample.
        ordered = sorted(pool.values(), key=lambda r: r.id)
        chosen = choose(
            ordered,
            blueprint_version_id=version.id,
            candidate_key=candidate_key,
            entry_index=index,
            count=count,
        )
        selections.append(
            TopicSelection(
                topic_id=topic_id,
                difficulty_min=d_min,
                difficulty_max=d_max,
                question_ids=sorted(r.id for r in chosen),
            )
        )
        total_questions += count

    return SampleResponse(
        blueprint_id=blueprint_id,
        blueprint_version_id=version.id,
        candidate_key=candidate_key,
        total_duration_minutes=version.total_duration_minutes,
        total_questions=total_questions,
        selections=selections,
    )
