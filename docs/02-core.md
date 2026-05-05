# 02 — Core (Infrastructure)

Thư mục: [`app/core/`](../app/core/)

Hạ tầng dùng xuyên suốt: config, cache, logging, exception taxonomy.
Không có business logic ở đây — chỉ "gluing".

## [`config.py`](../app/core/config.py) — Settings

`pydantic-settings` đọc env vars (tự load `.env` nếu có) thành object type-safe.

```python
class Settings(BaseSettings):
    solver_timeout_seconds: float = 5.0
    calorie_delta: int = 100
    no_repeat_days: int = 2
    weight_fridge: int = 3
    weight_expiry: int = 5
    ...
    kcal_per_kg: int = 7700          # hằng số vật lý — 1 kg mỡ ≈ 7700 kcal
```

Truy cập ở bất cứ đâu:
```python
from app.core.config import get_settings
settings = get_settings()           # @lru_cache → tạo 1 lần, cached
```

**Vì sao không dùng biến module level?**
Test cần override được → `get_settings()` kiểu factory dễ monkeypatch.

## [`cache.py`](../app/core/cache.py) — DBCache singleton

Bài toán: `/update-db` tải dishes/ingredients một lần, `/recommend` đọc nhiều lần. Service
không có DB riêng → phải cache in-memory. Phải thread-safe vì FastAPI chạy đa luồng.

```
DBCache (singleton, RLock protected)
  └── snapshot: DBSnapshot | None
          ├── dishes[]              list[Dish]
          ├── ingredients[]         list[Ingredient]
          ├── updated_at
          ├── dishes_by_id          dict[int, Dish]       ← index, O(1) lookup
          └── ingredients_by_id     dict[int, Ingredient]
```

API:
- `cache.replace(dishes, ingredients)` — atomic swap, trả snapshot mới.
- `cache.get()` — trả snapshot; **raise `CacheNotLoadedError`** nếu chưa load.
- `cache.is_loaded()` — true/false, không raise.

FastAPI lấy cache qua DI:
```python
from app.api.dependencies import get_cache

@router.post("/recommend")
async def recommend_endpoint(cache: Annotated[DBCache, Depends(get_cache)]):
    snapshot = cache.get()          # raise → route map về 503
```

**Vì sao RLock chứ không Lock?**
Reentrant — phòng trường hợp code gọi cache lồng nhau (chưa cần nhưng an toàn là chính).

## [`logging_config.py`](../app/core/logging_config.py) — loguru setup

Loại bỏ handler mặc định của `loguru`, thêm handler stderr với format đẹp + màu + có
`time | level | file:func:line | message`.

Dùng:
```python
from loguru import logger
logger.info("Solver pass: status={s}", s=status_name)     # dùng placeholder, KHÔNG f-string
```

**Quy tắc**:
- Không `print()` trong production code. CLAUDE.md §10 cấm.
- Dùng placeholder `{x}` + `x=value` thay vì f-string — để `loguru` xử lý lazy formatting
  (nhanh hơn khi log bị filter).

## [`exceptions.py`](../app/core/exceptions.py) — taxonomy

```
MealRecommenderError                  (base, để except gom 1 chỗ)
├── CacheNotLoadedError              → /recommend chưa có data → 503
├── InvalidIngredientError           → fridge ingredient ngoài whitelist / không có NUMBER_TO_GAM → 400
├── SolverInfeasibleError            → relax hết vẫn không giải được → return status="failed"
├── SolverTimeoutError               → CP-SAT UNKNOWN sau retry → return status="failed"
└── DBLoadError                      → httpx fail / JSON sai schema → 502
```

Routes map từng loại về HTTP code tương ứng (xem [`06-api.md`](06-api.md)).

**Vì sao có base `MealRecommenderError`?**
Để `except MealRecommenderError` ở tầng orchestrator gom hết lỗi nghiệp vụ của service, để
lọt lỗi hệ thống (`KeyError`, `TypeError`, ...) lên cho FastAPI xử lý 500.

## Sơ đồ phụ thuộc

```
  config.py  ◄─── logging_config.py
      ▲               ▲
      │               │
      │         (mọi service logger.info(...))
      │
      └───── mọi module import get_settings()

  exceptions.py ────── raise từ services ────── catch ở routes.py
  cache.py      ────── replace() từ /update-db
                ────── get()     từ /recommend
```
