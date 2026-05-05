# 00 — Tổng quan (Overview)

## Service này làm gì?

Nhận request kế hoạch ăn uống từ backend, trả về lịch ăn N ngày (1–14) thỏa mãn:
1. **Cấu trúc bữa** (bữa nào có mấy mainDish/soup/vegetable — user quyết định).
2. **Mục tiêu calo + macro** (dựa vào TDEE và targetKg).
3. **Không lặp món** trong cửa sổ N ngày (chống nhàm chán).
4. **Ưu tiên nguyên liệu trong tủ lạnh** (nhất là sắp hết hạn).

Lõi bài toán là **Constraint Programming** giải bằng **OR-Tools CP-SAT**.

## Hai endpoint chính

```
POST /update-db   → tải dishes.json + ingredients.json từ backend, cache in-memory
POST /recommend   → giải bài toán, trả kế hoạch + shoppingList
GET  /health      → liveness + check cache đã load chưa
```

## Dòng chảy của một request `/recommend`

```
RecommendRequest (input.py)
        │
        ▼
 ┌────────────────────────────────────────────────────────┐
 │ app/services/recommend.py   orchestrator               │
 │                                                        │
 │  1. validate fridge ingredientId (≤ 62 classes)        │
 │  2. filter dish có ingredient ngoài whitelist          │
 │  3. drop recentMealLog cũ hơn NO_REPEAT_DAYS           │
 │  4. tính target_cal_per_day = TDEE + daily_delta       │
 │  5. phân loại goal (weight_loss / maintain / gain)     │
 │  6. build SolveInput và gọi solve()                    │
 │  7. nếu success → build DayPlan[] + tính nutrition/ngày│
 │  8. compute_missing_per_dish(plan, fridge, ...)        │
 │  9. build_shopping_list(plan, ...)                     │
 │ 10. build Summary theo công thức §15 #6 đã chốt        │
 │                                                        │
 │      thành phần được gọi:                              │
 │      ├── services/cp_sat_solver.py                     │
 │      │     ├── constraints/structural.py  (C1)         │
 │      │     ├── constraints/repetition.py  (C2)         │
 │      │     ├── constraints/calorie.py     (C3)         │
 │      │     ├── constraints/macro.py       (C4)         │
 │      │     └── objective.py          (S1/S2/S4)        │
 │      ├── services/missing_ingredient.py                │
 │      ├── services/shopping_list.py                     │
 │      ├── services/unit_converter.py                    │
 │      └── utils/nutrition.py                            │
 └────────────────────────────────────────────────────────┘
        │
        ▼
 MealPlanResponse (output.py) — serialize ra camelCase
```

## Bắt đầu đọc code từ đâu

Theo thứ tự học:

1. **[01-models.md](01-models.md)** — hiểu shape của input/output (contract với team app)
2. **[02-core.md](02-core.md)** — config, cache, exceptions (hạ tầng)
3. **[05-utils.md](05-utils.md)** — công thức dinh dưỡng thuần toán (dễ, không có I/O)
4. **[03-services-data.md](03-services-data.md)** — db_loader, unit_converter, missing_ingredient, shopping_list (logic nghiệp vụ không có solver)
5. **[04-services-solver.md](04-services-solver.md)** — tim của hệ thống: constraints, objective, CP-SAT, relaxation
6. **[06-api.md](06-api.md)** — FastAPI routes (mỏng, chỉ map request/response)

## Nguyên tắc kiến trúc

- Service **không** kết nối trực tiếp DB backend. Backend push URL → service tải JSON.
- Cache **in-memory** (`DBCache` singleton, thread-safe). Backup xuống `data/` để debug.
- **62 classes nguyên liệu** là giới hạn cứng từ CV model. Mọi ingredient phải nằm trong tập này.
- Mọi magic number → [`core/config.py`](../app/core/config.py) (đọc từ env).
- Pydantic dùng snake_case nội bộ, serialize ra camelCase qua `alias` + `serialization_alias`.
