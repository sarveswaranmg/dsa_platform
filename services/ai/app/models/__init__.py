# Import all models so Base.metadata (and Alembic autogenerate) sees them.
from app.models.candidate_profile import CandidateProfile, ProfileStatus
from app.models.generation_job import GenerationJob, GenerationStatus
from app.models.test_case_generation_job import TestCaseGenerationJob, TestCaseGenerationStatus

__all__ = [
    "CandidateProfile",
    "GenerationJob",
    "GenerationStatus",
    "ProfileStatus",
    "TestCaseGenerationJob",
    "TestCaseGenerationStatus",
]
