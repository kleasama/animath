import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from pydantic import Field

from animath.core.errors import ComputeError
from animath.numerics.base import Kernel, Result


class Npz(Kernel):
    """Numeric arrays of a user-supplied .npz pinned by SHA-256; a 0-d `meta` member holds a JSON
    object. Never planned from source text: path and hash come from the user."""

    path: str = Field(pattern=r"^/.+\.npz$", description="absolute path of the .npz")
    sha256: str = Field(pattern="^[0-9a-f]{64}$")

    def run(self) -> Result:
        where = f"data.npz {self.path}"
        try:
            raw = Path(self.path).read_bytes()
        except OSError as e:
            raise ComputeError(f"{where}: {e}") from e
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ComputeError(f"{where}: sha256 mismatch")
        try:
            z = np.load(io.BytesIO(raw), allow_pickle=False)
            if not isinstance(z, np.lib.npyio.NpzFile):
                raise ValueError("not an .npz archive")
            with z:
                arrays = {k: z[k] for k in z.files}
            meta = json.loads(arrays.pop("meta", np.array("{}")).item())
        except (ValueError, TypeError, EOFError, zipfile.BadZipFile) as e:
            raise ComputeError(f"{where}: {e}") from e
        if bad := sorted(k for k, a in arrays.items() if a.dtype.kind not in "biufc"):
            raise ComputeError(f"{where}: non-numeric arrays {bad}")
        if not isinstance(meta, dict):
            raise ComputeError(f"{where}: meta is not a JSON object")
        return arrays, meta
