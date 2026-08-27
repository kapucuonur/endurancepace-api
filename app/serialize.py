"""Helpers for persisting nested Pydantic structures as JSON columns.

Nested blobs (`structure`, `completed`, `thresholds`, zone lists) are stored the
way the app's mock layer stores them: camelCase keys, `undefined`/`None` dropped
(mirrors `JSON.stringify`). Top-level response fields are still always emitted
(see schemas.py).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


def dump(model: Optional[BaseModel]) -> Optional[dict[str, Any]]:
    if model is None:
        return None
    return model.model_dump(by_alias=True, exclude_none=True, mode="json")


def dump_list(models: Optional[list[BaseModel]]) -> Optional[list[dict[str, Any]]]:
    if models is None:
        return None
    return [m.model_dump(by_alias=True, exclude_none=True, mode="json") for m in models]
