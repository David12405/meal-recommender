# 06 — API (FastAPI layer)

Thư mục: [`app/api/`](../app/api/) + [`app/main.py`](../app/main.py)

Tầng mỏng nhất: map HTTP request → gọi service → map exception thành HTTP code.
Không có business logic ở đây.

## [`main.py`](../app/main.py) — App factory

```python
def create_app() -> FastAPI:
    configure_logging()                # loguru setup trước
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.include_router(router)
    return app

app = create_app()                     # uvicorn import cái này
```

Chạy:
```bash
uvicorn app.main:app --reload --port 8000
```

OpenAPI docs tự sinh ở http://localhost:8000/docs.

## [`dependencies.py`](../app/api/dependencies.py) — DI

Chỉ 1 hàm wrapper:
```python
def get_cache() -> DBCache:
    return _get_cache()        # trả singleton từ core/cache.py
```

Có vẻ thừa nhưng là pattern tốt: test có thể override DI bằng `app.dependency_overrides`
mà không cần monkeypatch module.

## [`routes.py`](../app/api/routes.py) — 3 endpoint

### `GET /health`

```python
async def health():
    return {
        "status": "ok",
        "cacheLoaded": cache.is_loaded(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

- Liveness probe — luôn 200.
- `cacheLoaded` cho phép monitoring biết service đã ready (đã có data) hay chưa.

### `POST /update-db`

```
Request  UpdateDBRequest { dishesUrl, ingredientsUrl }
            │
            ▼
  await db_loader.load_from_urls(...)
            │
   ┌────────┴────────┐
   │                 │
  OK              DBLoadError
   │                 │
   │                 └──► HTTP 502 {detail: "..."}
   ▼
  cache.replace(dishes, ingredients)       atomic
  backup_to_disk(...)                      ghi data/*.json
   │
   ▼
Response UpdateDBResponse {
    status, dishesCount, ingredientsCount, updatedAt
}
```

Note: `response_model_by_alias=True` → serialize ra `dishesCount` (camel) chứ không phải
`dishes_count`.

### `POST /recommend`

```
Request  RecommendRequest  (Pydantic validate → 422 nếu sai)
            │
            ▼
  cache.get()                       → CacheNotLoadedError → 503
            │
            ▼
  recommend(payload, snapshot, NO_REPEAT_DAYS)
            │
   ┌────────┴────────┬────────────────────┐
  OK                InvalidIngredient    MealRecommenderError khác
   │                  │                    │
   │                  └─► 400              └─► 500
   ▼
Response MealPlanResponse
```

**Mapping exception → HTTP code** (§15 #5 chốt FastAPI default envelope):
| Exception | Code |
|---|---|
| Pydantic ValidationError (tự động) | 422 |
| `CacheNotLoadedError` | 503 |
| `InvalidIngredientError` | 400 |
| `DBLoadError` | 502 |
| `MealRecommenderError` khác | 500 |
| `SolverInfeasibleError` / `SolverTimeoutError` trong `recommend()` | không raise lên — caught trong `recommend.py` → trả `status: "failed"` |

Body chuẩn FastAPI:
```json
{ "detail": "DB not loaded, call /update-db first" }
```

## Test endpoint — `TestClient`

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.get("/health")
assert r.status_code == 200
```

Xem [`tests/integration/test_recommend_endpoint.py`](../tests/integration/test_recommend_endpoint.py).

## Sơ đồ tầng

```
  Client (backend / app / curl)
          │  HTTP
          ▼
  ┌────────────────────────────┐
  │  FastAPI                   │
  │  ├─ main.py app factory    │
  │  └─ routes.py              │
  │       ├─ /health           │
  │       ├─ /update-db        │
  │       │    └─ db_loader    │
  │       │    └─ cache.replace
  │       └─ /recommend        │
  │            └─ cache.get    │
  │            └─ recommend()  │ ◄── entry vào solver
  └────────────────────────────┘
          │
          ▼
  Response (Pydantic model → JSON, camelCase)
```
