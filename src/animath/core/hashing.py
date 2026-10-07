import hashlib
import json
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def canonical(obj: BaseModel | Any) -> bytes:
    data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_of(obj: BaseModel | Any) -> str:
    return digest(canonical(obj))
