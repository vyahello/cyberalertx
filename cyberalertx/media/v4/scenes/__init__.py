"""Scene library. One function per scene id of `brief.CATALOGUE`:

    def scene(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None

A scene draws the whole frame (background included); `render.render` adds the
shared grain, vignette and signature afterwards.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable

SCENES: dict[str, Callable[..., None]] = {}


def scene(name: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    def deco(fn: Callable[..., None]) -> Callable[..., None]:
        SCENES[name] = fn
        return fn
    return deco


def load_all() -> dict[str, Callable[..., Any]]:
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
    return SCENES
