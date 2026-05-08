from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.routes import router
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.models.output import MealPlanResponse
from app.services.db_loader import load_from_local_files


# Map các loại lỗi Pydantic phổ biến → câu tiếng Việt thân thiện.
# Key: `type` field trong Pydantic v2 ValidationError.
_VN_ERROR_TEMPLATES: dict[str, str] = {
    "missing": "Thiếu trường '{field}'. Vui lòng nhập đầy đủ.",
    "greater_than_equal": "Trường '{field}' phải lớn hơn hoặc bằng {ge}.",
    "less_than_equal": "Trường '{field}' phải nhỏ hơn hoặc bằng {le}.",
    "greater_than": "Trường '{field}' phải lớn hơn {gt}.",
    "less_than": "Trường '{field}' phải nhỏ hơn {lt}.",
    "string_type": "Trường '{field}' phải là chuỗi.",
    "int_type": "Trường '{field}' phải là số nguyên.",
    "float_type": "Trường '{field}' phải là số.",
    "bool_type": "Trường '{field}' phải là true/false.",
    "list_type": "Trường '{field}' phải là danh sách.",
    "dict_type": "Trường '{field}' phải là object.",
    "datetime_parsing": "Trường '{field}' phải đúng định dạng ngày giờ ISO.",
    "datetime_type": "Trường '{field}' phải là ngày giờ hợp lệ.",
    "enum": "Trường '{field}' không phải giá trị được chấp nhận.",
    "value_error": "Trường '{field}' không hợp lệ.",
}


def _vn_field_message(err: dict[str, Any]) -> str:
    loc_parts = [str(x) for x in err.get("loc", ()) if x != "body"]
    field = ".".join(loc_parts) if loc_parts else "input"
    err_type = err.get("type", "")
    ctx = err.get("ctx") or {}
    template = _VN_ERROR_TEMPLATES.get(err_type)
    if template:
        try:
            return template.format(field=field, **ctx)
        except (KeyError, IndexError):
            pass
    # Fallback cho ValueError trong @model_validator (trả message tiếng Việt
    # đã có sẵn ở input.py) hoặc loại lỗi không có template.
    raw_msg = err.get("msg", "")
    if raw_msg.startswith("Value error, "):
        return raw_msg.removeprefix("Value error, ")
    return f"Trường '{field}' không hợp lệ."


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


def _failed_payload(message: str) -> dict[str, Any]:
    """Serialize unified failure schema (giống output.py MealPlanResponse) sang
    dict với camelCase aliases — dùng trong global exception handlers.
    """
    return MealPlanResponse(
        status="failed",
        message=message,
        plan=[],
        summary=None,
        shoppingList=[],
    ).model_dump(by_alias=True, mode="json")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=_lifespan,
    )
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Override default 422 envelope `{"detail":[...]}` → unified schema VN.

        Lý do: chốt với team app 2026-05-08 — mọi lỗi (kể cả input schema sai)
        đều trả format giống response success, status code 200, message tiếng Việt.
        """
        errors = exc.errors()
        message = (
            _vn_field_message(errors[0])
            if errors
            else "Dữ liệu đầu vào không hợp lệ."
        )
        if len(errors) > 1:
            message += f" (và {len(errors) - 1} lỗi khác)"
        logger.info("Input validation failed: {n} error(s) → {msg}",
                    n=len(errors), msg=message)
        return JSONResponse(status_code=200, content=_failed_payload(message))

    return app


app = create_app()
