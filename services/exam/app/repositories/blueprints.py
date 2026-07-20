import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blueprint import Blueprint
from app.models.blueprint_version import BlueprintVersion


async def create_blueprint(
    session: AsyncSession, *, org_id: uuid.UUID, name: str
) -> Blueprint:
    blueprint = Blueprint(org_id=org_id, name=name)
    session.add(blueprint)
    await session.flush()
    return blueprint


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, blueprint_id: uuid.UUID
) -> Blueprint | None:
    result = await session.execute(
        select(Blueprint).where(
            Blueprint.id == blueprint_id, Blueprint.org_id == org_id
        )
    )
    return result.scalar_one_or_none()


async def list_by_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> Sequence[tuple[Blueprint, BlueprintVersion]]:
    stmt = (
        select(Blueprint, BlueprintVersion)
        .join(BlueprintVersion, Blueprint.current_version_id == BlueprintVersion.id)
        .where(Blueprint.org_id == org_id)
        .order_by(Blueprint.created_at)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def create_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    blueprint_id: uuid.UUID,
    version_number: int,
    target_role: str,
    experience_band: str,
    total_duration_minutes: int,
    topic_mix: list[dict[str, Any]],
) -> BlueprintVersion:
    version = BlueprintVersion(
        org_id=org_id,
        blueprint_id=blueprint_id,
        version_number=version_number,
        target_role=target_role,
        experience_band=experience_band,
        total_duration_minutes=total_duration_minutes,
        topic_mix=topic_mix,
    )
    session.add(version)
    await session.flush()
    return version


async def get_version(
    session: AsyncSession, *, org_id: uuid.UUID, version_id: uuid.UUID
) -> BlueprintVersion | None:
    result = await session.execute(
        select(BlueprintVersion).where(
            BlueprintVersion.id == version_id, BlueprintVersion.org_id == org_id
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    session: AsyncSession, *, org_id: uuid.UUID, blueprint_id: uuid.UUID
) -> Sequence[BlueprintVersion]:
    result = await session.execute(
        select(BlueprintVersion)
        .where(
            BlueprintVersion.blueprint_id == blueprint_id,
            BlueprintVersion.org_id == org_id,
        )
        .order_by(BlueprintVersion.version_number)
    )
    return result.scalars().all()
