from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from app.api.routes import router
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.services.db_loader import load_from_local_files


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Auto-load data từ folder `data/` lúc service boot.

    Lý do: service không có /update-db endpoint — data bundle trong code
    (folder `data/` commit vào git). Mỗi lần Render redeploy hoặc cold start
    wake-up, hook này chạy → cache luôn có data, /recommend hoạt động ngay.
    Lỗi đọc data → log error, cache giữ trạng thái rỗng → /recommend trả 503.
    """
    try:
        dishes, ingredients, derived_n2g, rows_count = load_from_local_files()
        get_cache().replace(
            dishes=dishes,
            ingredients=ingredients,
            derived_number_to_gam=derived_n2g,
        )
        logger.info(
            "Cache loaded on startup: dishes={d}, ingredients={i}, "
            "junction_rows={r}, derived_n2g={n} entries",
            d=len(dishes),
            i=len(ingredients),
            r=rows_count,
            n=len(derived_n2g),
        )
    except Exception as exc:
        logger.error(
            "Auto-load cache failed on startup: {exc}. "
            "/recommend sẽ trả 503 cho đến khi data được fix.",
            exc=str(exc),
        )
    yield
    # No teardown needed — in-memory cache cleaned up by GC


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=_lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
