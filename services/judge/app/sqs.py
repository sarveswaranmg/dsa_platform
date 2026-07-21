from functools import lru_cache
from typing import TYPE_CHECKING

import boto3

from app.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient


@lru_cache
def _client() -> "SQSClient":
    settings = get_settings()
    return boto3.client(
        "sqs",
        endpoint_url=settings.sqs_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )


@lru_cache
def queue_url(name: str) -> str:
    # Idempotent: create_queue returns the existing queue if it already exists.
    return _client().create_queue(QueueName=name)["QueueUrl"]


def send(name: str, body: str) -> None:
    _client().send_message(QueueUrl=queue_url(name), MessageBody=body)


def receive(name: str, *, wait_seconds: int = 20, max_messages: int = 1) -> list[dict[str, str]]:
    response = _client().receive_message(
        QueueUrl=queue_url(name),
        WaitTimeSeconds=wait_seconds,
        MaxNumberOfMessages=max_messages,
    )
    return [
        {"receipt_handle": m["ReceiptHandle"], "body": m["Body"]}
        for m in response.get("Messages", [])
    ]


def delete(name: str, receipt_handle: str) -> None:
    _client().delete_message(QueueUrl=queue_url(name), ReceiptHandle=receipt_handle)
