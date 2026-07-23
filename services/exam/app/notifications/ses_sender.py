from functools import lru_cache
from typing import TYPE_CHECKING

import boto3

from app.core.config import get_settings
from app.notifications.email import EmailMessage

if TYPE_CHECKING:
    from mypy_boto3_ses import SESClient


@lru_cache
def _client() -> "SESClient":
    # No explicit credentials: let boto3's default chain do env vars (dev/CI)
    # or an ECS task/instance role (prod) — unlike messaging/sqs.py, which
    # always passes explicit credentials for localstack.
    return boto3.client("ses", region_name=get_settings().aws_region)


class SesEmailSender:
    """Production email delivery via AWS SES. Requires a verified sender
    identity (settings.ses_from_address) and AWS credentials — either
    explicit (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) or an instance/task
    role in prod."""

    async def send(self, message: EmailMessage) -> None:
        _client().send_email(
            Source=get_settings().ses_from_address,
            Destination={"ToAddresses": [message.to]},
            Message={
                "Subject": {"Data": message.subject},
                "Body": {"Text": {"Data": message.body}},
            },
        )
