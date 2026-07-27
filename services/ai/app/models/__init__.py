# Import all models so Base.metadata (and Alembic autogenerate) sees them.
from app.models.candidate_profile import CandidateProfile, ProfileStatus

__all__ = [
    "CandidateProfile",
    "ProfileStatus",
]
