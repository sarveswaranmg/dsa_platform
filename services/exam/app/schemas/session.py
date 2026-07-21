import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.models.exam_session import ExamSession
from app.models.session_question import SessionQuestion


class AssignedQuestion(BaseModel):
    ordinal: int
    question_id: uuid.UUID
    question_version_id: uuid.UUID


class SessionResponse(BaseModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    status: str
    started_at: datetime
    deadline_at: datetime
    remaining_seconds: int
    questions: list[AssignedQuestion]

    @classmethod
    def build(
        cls, exam_session: ExamSession, questions: list[SessionQuestion]
    ) -> "SessionResponse":
        remaining = int((exam_session.deadline_at - datetime.now(UTC)).total_seconds())
        return cls(
            id=exam_session.id,
            exam_id=exam_session.exam_id,
            status=exam_session.status,
            started_at=exam_session.started_at,
            deadline_at=exam_session.deadline_at,
            remaining_seconds=max(0, remaining),
            questions=[
                AssignedQuestion(
                    ordinal=q.ordinal,
                    question_id=q.question_id,
                    question_version_id=q.question_version_id,
                )
                for q in questions
            ],
        )


class QuestionContentResponse(BaseModel):
    ordinal: int
    question_id: uuid.UUID
    question_version_id: uuid.UUID
    title: str
    statement_md: str
    constraints_md: str
    difficulty: int
    time_limit_ms: int
    memory_limit_mb: int
    starter_code: dict[str, str]


class SessionSubmitRequest(BaseModel):
    language: str = Field(pattern="^(python|java|cpp)$")
    source: str = Field(min_length=1, max_length=200_000)
