from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config as BotoConfig

from app.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@lru_cache
def _client() -> "S3Client":
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )


def get_object(key: str) -> bytes:
    settings = get_settings()
    response = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    body: bytes = response["Body"].read()
    return body
