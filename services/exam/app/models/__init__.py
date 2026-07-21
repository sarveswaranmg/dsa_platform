# Import all models so Base.metadata (and Alembic autogenerate) sees them.
from app.models.blueprint import Blueprint
from app.models.blueprint_version import BlueprintVersion
from app.models.case_verdict import CaseVerdict
from app.models.exam import Exam, ExamStatus
from app.models.examiner import Examiner, Role
from app.models.invite import Invite, InviteStatus
from app.models.org import Org
from app.models.refresh_token import RefreshToken
from app.models.submission import Submission, SubmissionStatus

__all__ = [
    "Blueprint",
    "BlueprintVersion",
    "CaseVerdict",
    "Exam",
    "ExamStatus",
    "Examiner",
    "Invite",
    "InviteStatus",
    "Org",
    "RefreshToken",
    "Role",
    "Submission",
    "SubmissionStatus",
]
