"""Stand-in AWS clients for unit tests -- no boto3/botocore needed.

Shared by every endpoint's tests so the fakes aren't duplicated per file (which the
copy-paste check would flag). The handlers catch ``client.exceptions.NoSuchKey``;
the S3 fake exposes the same attribute so a missing object behaves like real S3.
"""

from types import SimpleNamespace
from typing import Any


class NoSuchKey(Exception):
    """Stand-in for the S3 client's NoSuchKey exception."""


def fake_s3(objects: dict[str, bytes], keys: list[str] | None = None) -> Any:
    """Build a stand-in S3 client serving (and storing) canned objects.

    ``objects`` is the live store: ``get_object`` reads from it and ``put_object``
    writes to it, so a test can POST and then GET. ``keys`` overrides the listing
    when the caller wants a listing that differs from the stored objects.
    """

    def get_object(**kwargs: Any) -> dict[str, Any]:
        """Return a canned object body, or raise NoSuchKey when absent."""
        key = kwargs["Key"]
        if key not in objects:
            raise NoSuchKey()
        return {"Body": SimpleNamespace(read=lambda: objects[key])}

    def put_object(**kwargs: Any) -> dict[str, Any]:
        """Store an object body so a later get_object serves it."""
        objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def delete_object(**kwargs: Any) -> dict[str, Any]:
        """Drop a stored object (a no-op when it is already absent)."""
        objects.pop(kwargs["Key"], None)
        return {}

    def list_objects_v2(**kwargs: Any) -> dict[str, Any]:
        """Return a canned listing of object keys, narrowed by ``Prefix`` as S3 narrows it.

        A handler that lists ``carriers/lumen/`` and deletes what comes back is judged on
        the store afterwards, so a listing that hands it every key makes a delete of the
        whole collection indistinguishable from a delete of the one carrier. With no
        ``Prefix`` the filter is the empty string and the whole listing comes back.
        """
        prefix = kwargs.get("Prefix", "")
        listed = keys if keys is not None else list(objects)
        return {"Contents": [{"Key": key} for key in listed if key.startswith(prefix)]}

    return SimpleNamespace(
        get_object=get_object,
        put_object=put_object,
        delete_object=delete_object,
        list_objects_v2=list_objects_v2,
        exceptions=SimpleNamespace(NoSuchKey=NoSuchKey),
    )


def fake_lambda(invocations: list[dict[str, Any]]) -> Any:
    """Build a stand-in Lambda client that records each invoke into ``invocations``."""

    def invoke(**kwargs: Any) -> dict[str, Any]:
        """Record the invoke request and return a canned async (202) response."""
        invocations.append(kwargs)
        return {"StatusCode": 202}

    return SimpleNamespace(invoke=invoke)
