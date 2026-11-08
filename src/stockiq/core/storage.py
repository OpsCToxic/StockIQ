"""Raw-payload object storage (MinIO/S3). Raw payloads are immutable once written."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from stockiq.core.config import Settings


@dataclass(frozen=True)
class StoredRaw:
    uri: str
    hash: str


class RawStore(Protocol):
    def put(
        self, source: str, source_id: str, ext: str, body: bytes, fetched_at: datetime
    ) -> StoredRaw: ...

    def get(self, uri: str) -> bytes: ...


def raw_key(source: str, source_id: str, ext: str, fetched_at: datetime) -> str:
    return f"raw/{source}/{fetched_at:%Y/%m/%d}/{source_id}.{ext}"


class S3RawStore:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password.get_secret_value(),
        )
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def put(
        self, source: str, source_id: str, ext: str, body: bytes, fetched_at: datetime
    ) -> StoredRaw:
        key = raw_key(source, source_id, ext, fetched_at)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body)
        return StoredRaw(uri=f"s3://{self._bucket}/{key}", hash=hashlib.sha256(body).hexdigest())

    def get(self, uri: str) -> bytes:
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        return self._client.get_object(Bucket=bucket, Key=key)["Body"].read()  # type: ignore[no-any-return]
