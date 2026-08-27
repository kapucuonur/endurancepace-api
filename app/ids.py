"""Prefixed opaque IDs — `ath_<hex>`, `pln_<hex>`, `evt_<hex>`, `wko_<hex>`,
`st_<hex>`. The frontend treats these as opaque strings; the prefix just aids
debugging and mirrors the mock layer's `uid('wko')` style.
"""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
