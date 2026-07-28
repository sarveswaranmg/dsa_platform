from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

import boto3

from app.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient


class QueuePublisher(Protocol):
    def send(self, queue: str, body: str) -> None: ...


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
    # Idempotent: returns the existing queue if it already exists. Called
    # directly (not just internally) by the test-case factory's on-demand
    # variant to create its throwaway per-request reply queue upfront.
    return str(_client().create_queue(QueueName=name)["QueueUrl"])


class SqsPublisher:
    def send(self, queue: str, body: str) -> None:
        _client().send_message(QueueUrl=queue_url(queue), MessageBody=body)


def receive(queue: str, *, wait_seconds: int = 20, max_messages: int = 5) -> list[dict[str, str]]:
    response = _client().receive_message(
        QueueUrl=queue_url(queue),
        WaitTimeSeconds=wait_seconds,
        MaxNumberOfMessages=max_messages,
    )
    return [
        {"receipt_handle": m["ReceiptHandle"], "body": m["Body"]}
        for m in response.get("Messages", [])
    ]


def delete(queue: str, receipt_handle: str) -> None:
    _client().delete_message(QueueUrl=queue_url(queue), ReceiptHandle=receipt_handle)


def delete_queue(name: str) -> None:
    """Tears down a throwaway reply queue (the test-case factory's on-demand
    variant creates one per synchronous request)."""
    _client().delete_queue(QueueUrl=queue_url(name))
    queue_url.cache_clear()


def get_publisher() -> QueuePublisher:
    # FastAPI dependency; overridden in tests with a capturing fake.
    return SqsPublisher()
