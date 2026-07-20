from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@lru_cache
def _client(endpoint_url: str) -> "S3Client":
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        # Path-style so presigned URLs work against localstack/MinIO.
        config=BotoConfig(s3={"addressing_style": "path"}),
    )


def presign_put(key: str) -> str:
    # Presigning is pure local computation — no network I/O.
    settings = get_settings()
    return _client(settings.s3_presign_endpoint_url).generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.s3_presign_ttl_seconds,
    )


def presign_get(key: str) -> str:
    settings = get_settings()
    return _client(settings.s3_presign_endpoint_url).generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.s3_presign_ttl_seconds,
    )


def ensure_bucket() -> None:
    """Create the bucket if missing. Dev/test bootstrap only — never called
    in a request path."""
    settings = get_settings()
    client = _client(settings.s3_endpoint_url)
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)
