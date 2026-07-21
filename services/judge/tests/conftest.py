import shutil
import subprocess
import uuid
from collections.abc import Iterator

import boto3
import pytest
from botocore.client import Config as BotoConfig

from app.config import get_settings


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(["docker", "info"], capture_output=True)
    return result.returncode == 0


@pytest.fixture(scope="session")
def docker_or_skip() -> None:
    if not _docker_available():
        pytest.skip("docker socket not available")


@pytest.fixture(scope="session")
def s3_bucket() -> None:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


@pytest.fixture
def upload_case(s3_bucket: None) -> Iterator["_Uploader"]:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )
    uploader = _Uploader(client, settings.s3_bucket)
    yield uploader


class _Uploader:
    def __init__(self, client: object, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def __call__(self, stdin: bytes, expected: bytes) -> tuple[str, str]:
        prefix = f"test/{uuid.uuid4()}"
        input_key = f"{prefix}/input"
        output_key = f"{prefix}/output"
        self._client.put_object(Bucket=self._bucket, Key=input_key, Body=stdin)  # type: ignore[attr-defined]
        self._client.put_object(Bucket=self._bucket, Key=output_key, Body=expected)  # type: ignore[attr-defined]
        return input_key, output_key
