from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """One provider interface; SES/SendGrid impls slot in behind it later."""

    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Dev stub — prints the email (including the invite link) to stdout so
    it's visible in the container console; never delivers."""

    async def send(self, message: EmailMessage) -> None:
        print(
            f"\n----- DEV EMAIL -----\n"
            f"to: {message.to}\nsubject: {message.subject}\n\n{message.body}\n"
            f"---------------------\n",
            flush=True,
        )


def get_email_sender() -> EmailSender:
    # FastAPI dependency; overridden in tests to capture sent messages.
    backend = get_settings().email_backend
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "ses":
        from app.notifications.ses_sender import SesEmailSender

        return SesEmailSender()
    raise ValueError(f"Unknown EMAIL_BACKEND: {backend!r}")
