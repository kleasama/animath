from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import ConfigDict, JsonValue

from animath.core.schemas import Model

F64 = NDArray[np.float64]
C128 = NDArray[np.complexfloating[Any, Any]]
Result = tuple[dict[str, NDArray[Any]], dict[str, JsonValue]]


class Kernel(Model, ABC):
    """Validated parameters of one data kind; `run` is pure and deterministic."""

    model_config = ConfigDict(allow_inf_nan=False)

    @abstractmethod
    def run(self) -> Result: ...
