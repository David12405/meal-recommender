from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
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


def _failed_response(message: str) -> MealPlanResponse:
    """Schema chuẩn cho mọi lỗi (chốt với team app 2026-05-08): luôn 200 OK +
    cùng shape với success, chỉ khác `status="failed"` và `message` chứa lý do
    user-facing tiếng Việt.
    """
    return MealPlanResponse(
        status="failed",
        message=message,
        plan=[],
        summary=None,
        shoppingList=[],
    )


@router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, object]:
    # HEAD: dùng cho frontend "wake-up ping" lúc user mở màn hình tạo plan —
    # FastAPI tự strip body, chỉ giữ status + headers. GET: monitoring/debug.
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
    except CacheNotLoadedError:
        return _failed_response(
            "Hệ thống chưa sẵn sàng (dữ liệu món ăn chưa được tải). "
            "Vui lòng thử lại sau ít phút."
        )

    settings = get_settings()
    try:
        return recommend(payload, snapshot, settings.no_repeat_days)
    except InvalidIngredientError as exc:
        # Message đã là tiếng Việt thân thiện do recommend.py / unit_converter.py
        # đã raise với chuỗi VN — pass thẳng cho user.
        return _failed_response(str(exc))
    except MealRecommenderError:
        logger.exception("Recommend failed (MealRecommenderError)")
        return _failed_response(
            "Đã xảy ra lỗi khi tạo kế hoạch ăn. "
            "Vui lòng thử lại với thông tin khác hoặc liên hệ hỗ trợ."
        )
    except Exception:
        # Last resort: bug ngoài dự kiến. Không leak stacktrace ra cho user.
        logger.exception("Recommend failed (unexpected)")
        return _failed_response(
            "Hệ thống gặp lỗi không xác định. "
            "Vui lòng thử lại sau hoặc liên hệ hỗ trợ."
        )
