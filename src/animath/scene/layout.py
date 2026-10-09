from dataclasses import dataclass
from itertools import combinations
from typing import Literal

Region = Literal["title", "main", "left", "right", "footer"]

GRID: dict[Region, tuple[float, float, float, float]] = {
    "title": (0.04, 0.86, 0.96, 0.97),
    "main": (0.04, 0.14, 0.96, 0.84),
    "left": (0.04, 0.14, 0.49, 0.84),
    "right": (0.51, 0.14, 0.96, 0.84),
    "footer": (0.04, 0.03, 0.96, 0.12),
}
MIN_SCALE = 0.4
EPS = 1e-6


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    def overlaps(self, o: "Box") -> bool:
        return min(self.x1, o.x1) - max(self.x0, o.x0) > EPS and (
            min(self.y1, o.y1) - max(self.y0, o.y0) > EPS
        )

    def within(self, o: "Box") -> bool:
        return (
            self.x0 >= o.x0 - EPS
            and self.y0 >= o.y0 - EPS
            and self.x1 <= o.x1 + EPS
            and self.y1 <= o.y1 + EPS
        )


def frame(width: float, height: float) -> Box:
    return Box(-width / 2, -height / 2, width / 2, height / 2)


def cell(region: Region, f: Box) -> Box:
    u0, v0, u1, v1 = GRID[region]
    return Box(f.x0 + u0 * f.width, f.y0 + v0 * f.height, f.x0 + u1 * f.width, f.y0 + v1 * f.height)


@dataclass(frozen=True)
class Placement:
    name: str
    box: Box
    t0: float
    t1: float
    scale: float = 1.0


def violations(ps: list[Placement], f: Box) -> list[str]:
    """Placements off the frame `f`, scaled below MIN_SCALE, or overlapping while both live."""
    out = [f"{p.name}: off-frame" for p in ps if not p.box.within(f)]
    out += [f"{p.name}: scale {p.scale:.2f} < {MIN_SCALE}" for p in ps if p.scale < MIN_SCALE]
    out += [
        f"{a.name} overlaps {b.name}"
        for a, b in combinations(ps, 2)
        if min(a.t1, b.t1) > max(a.t0, b.t0) and a.box.overlaps(b.box)
    ]
    return out
