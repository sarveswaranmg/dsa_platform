from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.db.session import get_db
from app.llm.client import LLMClient, get_llm_client
from app.schemas.blueprint import BlueprintGenerateRequest, BlueprintGenerateResponse
from app.services import blueprint_proposal as blueprint_proposal_service

router = APIRouter(prefix="/blueprints", tags=["blueprints"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
LLM = Annotated[LLMClient, Depends(get_llm_client)]


@router.post("/generate", response_model=BlueprintGenerateResponse)
async def generate_blueprint(
    body: BlueprintGenerateRequest, ctx: WriterCtx, session: DB, llm_client: LLM
) -> BlueprintGenerateResponse:
    spec = await blueprint_proposal_service.propose_blueprint(
        session,
        org_id=ctx.org_id,
        candidate_profile_id=body.candidate_profile_id,
        target_role=body.target_role,
        seniority_band=body.seniority_band,
        available_topics=body.available_topics,
        llm_client=llm_client,
    )
    return BlueprintGenerateResponse(
        topic_mix=spec.topic_mix,
        total_duration_minutes=spec.total_duration_minutes,
        rationale=spec.rationale,
    )
