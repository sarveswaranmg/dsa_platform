# Import all models so Base.metadata (and Alembic autogenerate) sees them.
from app.models.question import Question, QuestionStatus, question_topics
from app.models.question_version import QuestionVersion
from app.models.test_case import TestCase
from app.models.topic import Topic

__all__ = [
    "Question",
    "QuestionStatus",
    "QuestionVersion",
    "TestCase",
    "Topic",
    "question_topics",
]
