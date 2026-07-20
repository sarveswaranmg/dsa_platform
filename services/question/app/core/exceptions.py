class DomainError(Exception):
    status_code = 400
    detail = "Bad request"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class TokenInvalid(DomainError):
    status_code = 401
    detail = "Invalid or expired token"


class Forbidden(DomainError):
    status_code = 403
    detail = "Insufficient permissions"


class NotFound(DomainError):
    status_code = 404
    detail = "Resource not found"


class Conflict(DomainError):
    status_code = 409
    detail = "Conflicting state"
