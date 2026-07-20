import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.models.blueprint import Blueprint
from app.models.blueprint_version import BlueprintVersion
from app.repositories import blueprints as blueprints_repo
from app.schemas.blueprint import TopicMixEntry


def _mix_to_json(topic_mix: Sequence[TopicMixEntry]) -> list[dict[str, object]]:
    return [
        {
            "topic_id": str(e.topic_id),
            "weight": e.weight,
            "difficulty_min": e.difficulty_min,
            "difficulty_max": e.difficulty_max,
            "question_count": e.question_count,
        }
        for e in topic_mix
    ]


async def _require_blueprint(
    session: AsyncSession, *, org_id: uuid.UUID, blueprint_id: uuid.UUID
) -> Blueprint:
    blueprint = await blueprints_repo.get_by_id(
        session, org_id=org_id, blueprint_id=blueprint_id
    )
    if blueprint is None:
        raise NotFound("Blueprint not found")
    return blueprint


async def _current_version(
    session: AsyncSession, blueprint: Blueprint
) -> BlueprintVersion:
    assert blueprint.current_version_id is not None
    version = await blueprints_repo.get_version(
        session, org_id=blueprint.org_id, version_id=blueprint.current_version_id
    )
    assert version is not None
    return version


async def create_blueprint(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    target_role: str,
    experience_band: str,
    total_duration_minutes: int,
    topic_mix: Sequence[TopicMixEntry],
) -> tuple[Blueprint, BlueprintVersion]:
    blueprint = await blueprints_repo.create_blueprint(session, org_id=org_id, name=name)
    version = await blueprints_repo.create_version(
        session,
        org_id=org_id,
        blueprint_id=blueprint.id,
        version_number=1,
        target_role=target_role,
        experience_band=experience_band,
        total_duration_minutes=total_duration_minutes,
        topic_mix=_mix_to_json(topic_mix),
    )
    blueprint.current_version_id = version.id
    await session.commit()
    return blueprint, version


async def get_blueprint(
    session: AsyncSession, *, org_id: uuid.UUID, blueprint_id: uuid.UUID
) -> tuple[Blueprint, BlueprintVersion]:
    blueprint = await _require_blueprint(session, org_id=org_id, blueprint_id=blueprint_id)
    version = await _current_version(session, blueprint)
    return blueprint, version


async def list_blueprints(
    session: AsyncSession, *, org_id: uuid.UUID
) -> Sequence[tuple[Blueprint, BlueprintVersion]]:
    return await blueprints_repo.list_by_org(session, org_id=org_id)


async def update_blueprint(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    blueprint_id: uuid.UUID,
    name: str | None,
    target_role: str,
    experience_band: str,
    total_duration_minutes: int,
    topic_mix: Sequence[TopicMixEntry],
) -> tuple[Blueprint, BlueprintVersion]:
    blueprint = await _require_blueprint(session, org_id=org_id, blueprint_id=blueprint_id)
    current = await _current_version(session, blueprint)
    # Copy-on-write: every edit is a new immutable version; the old one stays.
    version = await blueprints_repo.create_version(
        session,
        org_id=org_id,
        blueprint_id=blueprint.id,
        version_number=current.version_number + 1,
        target_role=target_role,
        experience_band=experience_band,
        total_duration_minutes=total_duration_minutes,
        topic_mix=_mix_to_json(topic_mix),
    )
    blueprint.current_version_id = version.id
    if name is not None:
        blueprint.name = name
    await session.commit()
    return blueprint, version


async def list_versions(
    session: AsyncSession, *, org_id: uuid.UUID, blueprint_id: uuid.UUID
) -> Sequence[BlueprintVersion]:
    await _require_blueprint(session, org_id=org_id, blueprint_id=blueprint_id)
    return await blueprints_repo.list_versions(
        session, org_id=org_id, blueprint_id=blueprint_id
    )
