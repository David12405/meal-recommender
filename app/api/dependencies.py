from __future__ import annotations

from app.core.cache import DBCache, get_cache as _get_cache


def get_cache() -> DBCache:
    return _get_cache()
