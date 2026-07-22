"""The edge route table.

Every request is matched by longest path prefix, which decides three things:
which upstream serves it, which token plane may reach it, and whether it is
refused outright. Anything not listed is refused — the table is an allow-list,
so a new internal endpoint downstream is never exposed by accident.
"""

import enum
from dataclasses import dataclass


class Upstream(enum.StrEnum):
    EXAM = "exam"
    QUESTION = "question"


class Policy(enum.StrEnum):
    PUBLIC = "public"  # no token (login, invite exchange)
    EXAMINER = "examiner"  # examiner_access tokens only
    CANDIDATE = "candidate"  # candidate_exam tokens only
    BLOCKED = "blocked"  # never reachable from the edge


@dataclass(frozen=True)
class Route:
    prefix: str
    upstream: Upstream | None
    policy: Policy
    #: Tight rate-limit budget (brute-force surfaces).
    strict_rate_limit: bool = False


ROUTES: tuple[Route, ...] = (
    # Service-to-service only: these are unauthenticated by design and must
    # never be reachable from outside the compose network.
    Route("/internal", None, Policy.BLOCKED),
    # Public auth surfaces.
    Route("/auth", Upstream.EXAM, Policy.PUBLIC, strict_rate_limit=True),
    Route("/candidate/auth", Upstream.EXAM, Policy.PUBLIC, strict_rate_limit=True),
    # Candidate plane.
    Route("/candidate", Upstream.EXAM, Policy.CANDIDATE),
    # Examiner plane — exam service.
    Route("/examiners", Upstream.EXAM, Policy.EXAMINER),
    Route("/blueprints", Upstream.EXAM, Policy.EXAMINER),
    Route("/exams", Upstream.EXAM, Policy.EXAMINER),
    Route("/submissions", Upstream.EXAM, Policy.EXAMINER),
    # Examiner plane — question service.
    Route("/topics", Upstream.QUESTION, Policy.EXAMINER),
    Route("/questions", Upstream.QUESTION, Policy.EXAMINER),
)


def match_route(path: str) -> Route | None:
    """Longest-prefix match so `/candidate/auth` beats `/candidate`."""
    best: Route | None = None
    for route in ROUTES:
        matches = path == route.prefix or path.startswith(route.prefix + "/")
        if matches and (best is None or len(route.prefix) > len(best.prefix)):
            best = route
    return best
