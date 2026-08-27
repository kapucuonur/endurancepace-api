"""`sanitize_for_json` — port of ai-coach `backend/utils.py`.

Garmin payloads contain NaN / Infinity floats and date objects that break
`json`/Pydantic. Recursively coerce to JSON-safe values.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


def sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
