from types import SimpleNamespace
from typing import Any


class NoSuchKey(Exception):
    pass


def fake_s3(objects: dict[str, bytes], keys: list[str] | None = None) -> Any:
    def get_object(**kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in objects:
            raise NoSuchKey()
        return {"Body": SimpleNamespace(read=lambda: objects[key])}

    def put_object(**kwargs: Any) -> dict[str, Any]:
        objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def delete_object(**kwargs: Any) -> dict[str, Any]:
        objects.pop(kwargs["Key"], None)
        return {}

    def list_objects_v2(**kwargs: Any) -> dict[str, Any]:
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
    def invoke(**kwargs: Any) -> dict[str, Any]:
        invocations.append(kwargs)
        return {"StatusCode": 202}

    return SimpleNamespace(invoke=invoke)
