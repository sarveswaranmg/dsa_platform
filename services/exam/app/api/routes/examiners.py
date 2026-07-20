from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.db.session import get_db
from app.models.examiner import Role
from app.schemas.examiner import (
    ExaminerCreateRequest,
    ExaminerCreateResponse,
    ExaminerResponse,
)
from app.services import examiners as examiners_service

router = APIRouter(prefix="/examiners", tags=["examiners"])

DB = Annotated[AsyncSession, Depends(get_db)]
AdminCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
AnyExaminerCtx = Annotated[AuthContext, Depends(require_role())]


@router.get("", response_model=list[ExaminerResponse])
async def list_examiners(ctx: AdminCtx, session: DB) -> list[ExaminerResponse]:
    examiners = await examiners_service.list_examiners(session, org_id=ctx.org_id)
    return [ExaminerResponse.model_validate(e) for e in examiners]


@router.post("", response_model=ExaminerCreateResponse, status_code=201)
async def create_examiner(
    body: ExaminerCreateRequest, ctx: AdminCtx, session: DB
) -> ExaminerCreateResponse:
    return await examiners_service.create_examiner(
        session, org_id=ctx.org_id, email=body.email, password=body.password, role=body.role
    )


@router.get("/me", response_model=ExaminerResponse)
async def get_me(ctx: AnyExaminerCtx, session: DB) -> ExaminerResponse:
    examiner = await examiners_service.get_examiner(
        session, org_id=ctx.org_id, examiner_id=ctx.examiner_id
    )
    return ExaminerResponse.model_validate(examiner)
