"""Internal, service-to-service endpoints — NOT exposed through the gateway
(Slice 9 keeps the /internal prefix off the public route table). No examiner
auth: reachable only on the trusted compose network. Used by the exam service
to resolve test-case S3 keys for a pinned question version when building a
judge submission job, and by the ai service (Phase 2 Slices 2-3) to create a
question and attach AI-generated test cases from background jobs that have
no live examiner bearer token to forward.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.db.session import get_db
from app.repositories import questions as questions_repo
from app.repositories import test_cases as test_cases_repo
from app.services import questions as questions_service
from app.services import test_cases as test_cases_service

router = APIRouter(prefix="/internal", tags=["internal"])

DB = Annotated[AsyncSession, Depends(get_db)]


class InternalTestCase(BaseModel):
    ordinal: int
    is_sample: bool
    input_s3_key: str
    expected_output_s3_key: str


class InternalPublishedQuestion(BaseModel):
    question_id: uuid.UUID
    published_version_id: uuid.UUID
    difficulty: int


class InternalVersionContent(BaseModel):
    version_id: uuid.UUID
    question_id: uuid.UUID
    version_number: int
    title: str
    statement_md: str
    constraints_md: str
    difficulty: int
    time_limit_ms: int
    memory_limit_mb: int
    starter_code: dict[str, str]


@router.get(
    "/question-versions/{version_id}/test-cases",
    response_model=list[InternalTestCase],
)
async def list_version_test_cases(
    version_id: uuid.UUID, org_id: uuid.UUID, session: DB
) -> list[InternalTestCase]:
    # org_id is still required — multi-tenancy is structural even internally.
    rows = await test_cases_repo.list_by_version(
        session, org_id=org_id, question_version_id=version_id
    )
    return [
        InternalTestCase(
            ordinal=tc.ordinal,
            is_sample=tc.is_sample,
            input_s3_key=tc.input_s3_key,
            expected_output_s3_key=tc.expected_output_s3_key,
        )
        for tc in rows
    ]


@router.get("/published-questions", response_model=list[InternalPublishedQuestion])
async def list_published_questions(
    org_id: uuid.UUID, topic_id: uuid.UUID, difficulty: int, session: DB
) -> list[InternalPublishedQuestion]:
    rows = await questions_repo.list_published_by_topic_difficulty(
        session, org_id=org_id, topic_id=topic_id, difficulty=difficulty
    )
    return [
        InternalPublishedQuestion(
            question_id=qid, published_version_id=vid, difficulty=diff
        )
        for qid, vid, diff in rows
    ]


@router.get(
    "/question-versions/{version_id}", response_model=InternalVersionContent
)
async def get_version_content(
    version_id: uuid.UUID, org_id: uuid.UUID, session: DB
) -> InternalVersionContent:
    version = await questions_repo.get_version(
        session, org_id=org_id, version_id=version_id
    )
    if version is None:
        raise NotFound("Question version not found")
    return InternalVersionContent(
        version_id=version.id,
        question_id=version.question_id,
        version_number=version.version_number,
        title=version.title,
        statement_md=version.statement_md,
        constraints_md=version.constraints_md,
        difficulty=version.difficulty,
        time_limit_ms=version.time_limit_ms,
        memory_limit_mb=version.memory_limit_mb,
        starter_code=version.starter_code,
    )


class InternalQuestionCreate(BaseModel):
    org_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    statement_md: str = Field(min_length=1)
    constraints_md: str = ""
    difficulty: int = Field(ge=1, le=5)
    time_limit_ms: int = Field(ge=100, le=30_000)
    memory_limit_mb: int = Field(ge=16, le=4_096)
    starter_code: dict[str, str] = Field(default_factory=dict)
    topic_ids: list[uuid.UUID] = Field(default_factory=list)


class InternalQuestionCreated(BaseModel):
    question_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int


@router.post("/questions", response_model=InternalQuestionCreated, status_code=201)
async def create_question(body: InternalQuestionCreate, session: DB) -> InternalQuestionCreated:
    # Same content shape and validation (topics must exist in the org) as the
    # examiner-facing POST /questions — created in draft status, same as any
    # manually-authored question.
    question, version, _topic_ids = await questions_service.create_question(
        session,
        org_id=body.org_id,
        title=body.title,
        statement_md=body.statement_md,
        constraints_md=body.constraints_md,
        difficulty=body.difficulty,
        time_limit_ms=body.time_limit_ms,
        memory_limit_mb=body.memory_limit_mb,
        starter_code=body.starter_code,
        topic_ids=body.topic_ids,
    )
    return InternalQuestionCreated(
        question_id=question.id,
        version_id=version.id,
        version_number=version.version_number,
    )


class InternalTestCaseCreate(BaseModel):
    org_id: uuid.UUID
    is_sample: bool = False


class InternalTestCaseCreated(BaseModel):
    id: uuid.UUID
    ordinal: int
    upload_input_url: str
    upload_output_url: str


@router.post(
    "/questions/{question_id}/test-cases",
    response_model=InternalTestCaseCreated,
    status_code=201,
)
async def create_test_case(
    question_id: uuid.UUID, body: InternalTestCaseCreate, session: DB
) -> InternalTestCaseCreated:
    # Same function the examiner-facing POST /questions/{id}/test-cases
    # calls — identical ordinal assignment and copy-on-write behavior via
    # ensure_mutable_version, just reachable without a bearer token (Phase 2
    # Slice 3's test-case factory).
    test_case, upload_input_url, upload_output_url = await test_cases_service.create_test_case(
        session,
        org_id=body.org_id,
        question_id=question_id,
        ordinal=None,
        is_sample=body.is_sample,
    )
    return InternalTestCaseCreated(
        id=test_case.id,
        ordinal=test_case.ordinal,
        upload_input_url=upload_input_url,
        upload_output_url=upload_output_url,
    )
