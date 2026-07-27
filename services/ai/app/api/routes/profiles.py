import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.clients.github import GitHubClient, get_github_client
from app.db.session import get_db
from app.llm.client import LLMClient, get_llm_client
from app.schemas.profiles import ProfileCreate, ProfileCreated, ProfileResponse, UploadUrlResponse
from app.services import profiles as profiles_service

router = APIRouter(prefix="/profiles", tags=["profiles"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]
LLM = Annotated[LLMClient, Depends(get_llm_client)]
GitHub = Annotated[GitHubClient, Depends(get_github_client)]


@router.post("/uploads", response_model=UploadUrlResponse, status_code=201)
async def create_upload_url(ctx: WriterCtx) -> UploadUrlResponse:
    resume_s3_key, upload_url = profiles_service.create_upload_url()
    return UploadUrlResponse(resume_s3_key=resume_s3_key, upload_url=upload_url)


@router.post("", response_model=ProfileCreated, status_code=201)
async def create_profile(
    body: ProfileCreate, ctx: WriterCtx, session: DB, llm_client: LLM, github_client: GitHub
) -> ProfileCreated:
    profile = await profiles_service.create_profile(
        session,
        org_id=ctx.org_id,
        resume_s3_key=body.resume_s3_key,
        github_handle=body.github_handle,
        llm_client=llm_client,
        github_client=github_client,
    )
    return ProfileCreated(id=profile.id, status=profile.status)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: uuid.UUID, ctx: ReaderCtx, session: DB) -> ProfileResponse:
    profile = await profiles_service.get_profile(session, org_id=ctx.org_id, profile_id=profile_id)
    return ProfileResponse.model_validate(profile)
