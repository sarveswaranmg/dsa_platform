"""Mid-exam proctor follow-ups (Phase 2 Slice 6). A proctor edits a
question's constraints mid-session; this forks an immutable question
version via question service's copy-on-write, generates+validates new
test cases for it via ai's lineage-based factory, re-points the session's
assigned question at the new version, and tells the candidate via a
`followup_pushed` event. See docs/design-live-proctoring.md."""

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai_service import AiServiceClient
from app.clients.question_service import QuestionServiceClient
from app.core.exceptions import NotFound
from app.models.session_event import SessionEvent
from app.repositories import sessions as sessions_repo
from app.services import session_events

logger = logging.getLogger("exam.followups")


async def push_followup(
    session: AsyncSession,
    redis: Redis,
    question_client: QuestionServiceClient,
    ai_client: AiServiceClient,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    ordinal: int,
    modified_constraints_md: str,
) -> SessionEvent:
    assigned = await sessions_repo.get_question(
        session, org_id=org_id, session_id=session_id, ordinal=ordinal
    )
    if assigned is None:
        raise NotFound("Question not found in this session")
    previous_version_id = assigned.question_version_id

    # Fork (or mutate in place, if already unpublished) — deliberately not
    # published yet, so attaching test cases below doesn't trigger a second,
    # unwanted fork (see docs/design-live-proctoring.md). The fork already
    # copies the prior version's test cases forward (copy-on-write reuses
    # their S3 keys) — the factory below only replaces them with freshly
    # generated+validated ones when the question has AI-generation lineage.
    draft = await question_client.create_followup_draft(
        org_id=org_id,
        question_id=assigned.question_id,
        constraints_md=modified_constraints_md,
    )

    try:
        await ai_client.run_followup_factory(
            org_id=org_id,
            question_version_id=draft.version_id,
            source_question_id=assigned.question_id,
        )
    except Exception:
        # No AI-generation lineage (a manually-authored question — same
        # restriction Slice 3 already established) or the factory failed for
        # some other reason. Never blocks the follow-up: the draft already
        # has the prior version's test cases carried forward unchanged.
        logger.info(
            "follow-up test-case factory unavailable for question %s; "
            "keeping the prior version's test cases",
            assigned.question_id,
        )

    published_version_id = await question_client.publish_version(
        org_id=org_id, question_id=assigned.question_id
    )

    await sessions_repo.update_question_version(
        session,
        org_id=org_id,
        session_id=session_id,
        ordinal=ordinal,
        question_version_id=published_version_id,
    )
    await session.commit()

    return await session_events.emit(
        session,
        redis,
        org_id=org_id,
        session_id=session_id,
        type="followup_pushed",
        payload={
            "previous_version_id": str(previous_version_id),
            "new_version_id": str(published_version_id),
            "summary": modified_constraints_md,
        },
        question_version_id=published_version_id,
    )
