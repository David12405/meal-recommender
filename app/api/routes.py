from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from app.api.dependencies import get_cache
from app.core.cache import DBCache
from app.core.config import get_settings
from app.core.exceptions import (
    CacheNotLoadedError,
    InvalidIngredientError,
    MealRecommenderError,
)
from app.models.input import RecommendRequest
from app.models.output import MealPlanResponse
from app.services.recommend import recommend

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    cache = get_cache()
    return {
        "status": "ok",
        "cacheLoaded": cache.is_loaded(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/recommend", response_model=MealPlanResponse, response_model_by_alias=True)
async def recommend_endpoint(
    payload: RecommendRequest,
    cache: Annotated[DBCache, Depends(get_cache)],
) -> MealPlanResponse:
    try:
        snapshot = cache.get()
    except CacheNotLoadedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    settings = get_settings()
    try:
        return recommend(payload, snapshot, settings.no_repeat_days)
    except InvalidIngredientError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except MealRecommenderError as exc:
        logger.exception("Recommend failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
