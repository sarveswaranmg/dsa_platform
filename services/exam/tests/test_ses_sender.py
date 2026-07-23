import os

import pytest

from app.notifications.email import EmailMessage, get_email_sender

pytestmark = pytest.mark.integration


def _ses_env_ready() -> bool:
    return (
        os.environ.get("EMAIL_BACKEND") == "ses"
        and bool(os.environ.get("SES_FROM_ADDRESS"))
        and bool(os.environ.get("AWS_ACCESS_KEY_ID"))
        and bool(os.environ.get("AWS_SECRET_ACCESS_KEY"))
    )


@pytest.mark.skipif(
    not _ses_env_ready(), reason="EMAIL_BACKEND=ses and SES sandbox credentials not set"
)
async def test_send_via_ses_sandbox() -> None:
    # SES sandbox accounts can only deliver to verified identities, so send
    # from the verified address to itself — no extra recipient identity
    # needs to be provisioned just for this test.
    from_address = os.environ["SES_FROM_ADDRESS"]
    sender = get_email_sender()
    await sender.send(
        EmailMessage(
            to=from_address,
            subject="dsa-platform SES sandbox test",
            body="Integration test send — safe to ignore.",
        )
    )
