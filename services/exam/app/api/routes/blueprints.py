import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.db.session import get_db
from app.models.blueprint import Blueprint
from app.models.blueprint_version import BlueprintVersion
from app.models.examiner import Role
from app.schemas.blueprint import (
    BlueprintCreate,
    BlueprintResponse,
    BlueprintUpdate,
    BlueprintVersionResponse,
)
from app.schemas.sampling import SampleRequest, SampleResponse
from app.services import blueprints as blueprints_service
from app.services import sampling as sampling_service

router = APIRouter(prefix="/blueprints", tags=["blueprints"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]
QuestionClient = Annotated[QuestionServiceClient, Depends(get_question_client)]


def _detail(blueprint: Blueprint, version: BlueprintVersion) -> BlueprintResponse:
    return BlueprintResponse(
        id=blueprint.id,
        org_id=blueprint.org_id,
        name=blueprint.name,
        current_version=BlueprintVersionResponse.model_validate(version),
    )


@router.post("", response_model=BlueprintResponse, status_code=201)
async def create_blueprint(
    body: BlueprintCreate, ctx: WriterCtx, session: DB
) -> BlueprintResponse:
    blueprint, version = await blueprints_service.create_blueprint(
        session,
        org_id=ctx.org_id,
        name=body.name,
        target_role=body.target_role,
        experience_band=body.experience_band,
        total_duration_minutes=body.total_duration_minutes,
        topic_mix=body.topic_mix,
    )
    return _detail(blueprint, version)


@router.get("", response_model=list[BlueprintResponse])
async def list_blueprints(ctx: ReaderCtx, session: DB) -> list[BlueprintResponse]:
    rows = await blueprints_service.list_blueprints(session, org_id=ctx.org_id)
    return [_detail(b, v) for b, v in rows]


@router.get("/{blueprint_id}", response_model=BlueprintResponse)
async def get_blueprint(
    blueprint_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> BlueprintResponse:
    blueprint, version = await blueprints_service.get_blueprint(
        session, org_id=ctx.org_id, blueprint_id=blueprint_id
    )
    return _detail(blueprint, version)


@router.patch("/{blueprint_id}", response_model=BlueprintResponse)
async def update_blueprint(
    blueprint_id: uuid.UUID, body: BlueprintUpdate, ctx: WriterCtx, session: DB
) -> BlueprintResponse:
    blueprint, version = await blueprints_service.update_blueprint(
        session,
        org_id=ctx.org_id,
        blueprint_id=blueprint_id,
        name=body.name,
        target_role=body.target_role,
        experience_band=body.experience_band,
        total_duration_minutes=body.total_duration_minutes,
        topic_mix=body.topic_mix,
    )
    return _detail(blueprint, version)


@router.get("/{blueprint_id}/versions", response_model=list[BlueprintVersionResponse])
async def list_versions(
    blueprint_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> list[BlueprintVersionResponse]:
    versions = await blueprints_service.list_versions(
        session, org_id=ctx.org_id, blueprint_id=blueprint_id
    )
    return [BlueprintVersionResponse.model_validate(v) for v in versions]


@router.post("/{blueprint_id}/sample", response_model=SampleResponse)
async def sample_blueprint(
    blueprint_id: uuid.UUID,
    body: SampleRequest,
    ctx: ReaderCtx,
    session: DB,
    client: QuestionClient,
    request: Request,
) -> SampleResponse:
    # Forward the caller's bearer token so the question service applies its own
    # org scoping and role checks (already validated on this request).
    authorization = request.headers["authorization"]
    return await sampling_service.sample_blueprint(
        session,
        org_id=ctx.org_id,
        blueprint_id=blueprint_id,
        candidate_key=body.candidate_key,
        authorization=authorization,
        client=client,
    )
