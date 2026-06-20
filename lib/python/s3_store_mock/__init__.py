"""A stand-in S3 client for unit tests -- no boto3/botocore needed.

Shared by every endpoint's tests so the fake isn't duplicated per file (which the
copy-paste check would flag). The handlers catch ``client.exceptions.NoSuchKey``;
this fake exposes the same attribute so a missing object behaves like real S3.
"""

from types import SimpleNamespace
from typing import Any


class NoSuchKey(Exception):
    """Stand-in for the S3 client's NoSuchKey exception."""


def fake_s3(objects: dict[str, bytes], keys: list[str] | None = None) -> Any:
    """Build a stand-in S3 client serving canned objects and a canned listing."""

    def get_object(**kwargs: Any) -> dict[str, Any]:
        """Return a canned object body, or raise NoSuchKey when absent."""
        key = kwargs["Key"]
        if key not in objects:
            raise NoSuchKey()
        return {"Body": SimpleNamespace(read=lambda: objects[key])}

    def list_objects_v2(**_kwargs: Any) -> dict[str, Any]:
        """Return a canned listing of object keys."""
        return {"Contents": [{"Key": key} for key in (keys or [])]}

    return SimpleNamespace(
        get_object=get_object,
        list_objects_v2=list_objects_v2,
        exceptions=SimpleNamespace(NoSuchKey=NoSuchKey),
    )
