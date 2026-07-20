class DomainError(Exception):
    status_code = 400
    detail = "Bad request"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class InvalidCredentials(DomainError):
    status_code = 401
    detail = "Invalid credentials"


class InvalidTOTP(DomainError):
    status_code = 401
    detail = "Invalid TOTP code"


class TOTPNotEnabled(DomainError):
    status_code = 403
    detail = "TOTP enrollment must be verified before login"


class TokenInvalid(DomainError):
    status_code = 401
    detail = "Invalid or expired token"


class Forbidden(DomainError):
    status_code = 403
    detail = "Insufficient permissions"


class EmailTaken(DomainError):
    status_code = 409
    detail = "Email is already registered"


class NotFound(DomainError):
    status_code = 404
    detail = "Resource not found"


class InsufficientQuestionPool(DomainError):
    status_code = 409
    detail = "Not enough published questions to satisfy the blueprint"


class UpstreamServiceError(DomainError):
    status_code = 502
    detail = "Question service is unavailable"
