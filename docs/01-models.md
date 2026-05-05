# 01 — Models (Pydantic)

Thư mục: [`app/models/`](../app/models/)

Tầng này định nghĩa **hình dạng dữ liệu** mà service nhận, trả về, và lưu trong bộ nhớ.
Không có logic — chỉ shape + validation.

## Vì sao dùng Pydantic v2?

- **Validate tự động**: nếu request thiếu field hoặc sai kiểu, FastAPI trả 422 mà không cần try/except.
- **Type hints chặt**: IDE autocomplete, `mypy` bắt lỗi trước khi chạy.
- **Camel ↔ snake**: backend dùng `userId`, Python dùng `user_id`. Dùng `alias` để map.

## Quy ước `populate_by_name=True`

```python
model_config = ConfigDict(populate_by_name=True, extra="ignore")
field: int = Field(alias="camelCaseName", serialization_alias="camelCaseName")
```

Ý nghĩa:
- `populate_by_name=True` → có thể parse từ cả `user_id` lẫn `userId`.
- `serialization_alias` → lúc dump ra JSON luôn là `userId`.
- `extra="ignore"` → backend thêm field mới không phá request.

## [`enums.py`](../app/models/enums.py) — các enum dùng chung

| Enum | Giá trị | Dùng ở đâu |
|---|---|---|
| `Role` | `MAINDISH`, `SOUP`, `VEGETABLE` | phân loại dish & meal slot |
| `Unit` | `GAM`, `NUMBER` | đơn vị fridge/dish/shoppingList |
| `MealType` | `breakfast`, `lunch`, `dinner` | tên bữa |

Thêm 2 tuple tiện lợi: `ROLES` và `MEAL_TYPES` để iterate trong solver.

## [`domain.py`](../app/models/domain.py) — shape cache JSON

> ⚠️ **Update 2026-04-24**: Schema này đã align với DB backend thực tế (xem CLAUDE.md §4.1–§4.5). Backend xuất shape flat; `ingredients[]`, `nutrition_per_serving`, `meal_types[]` được `db_loader` tự fill sau khi load.

Input từ backend (3 file JSON):

```
dishes.json             FLAT
├── id                  alias → dish_id
├── name
├── type                "MAIN_DISH"|"SOUP"|"VEGETABLE" → normalize qua Role._missing_
└── calories            (còn lại service tự compute)

ingredients.json        FLAT (≤ 62 classes)
├── id                  alias → ingredient_id
├── name
├── unit                alias → default_unit (GAM | NUMBER)
├── numberToGam         alias → number_to_gam (null khi không convert được)
├── protein             per 100g
├── carb                per 100g
└── fat                 per 100g

dish_ingredients.json   junction table
├── dishId
├── ingredientId
├── amount              lượng công thức, đơn vị gốc
├── gramsEquivalent     backend đã convert sẵn về GAM
└── unit                GAM | NUMBER
```

Sau khi `db_loader` chạy merge + compute, runtime model trông như:

```
Dish (runtime, đã merge)
├── dish_id
├── name
├── role                Role.MAINDISH | SOUP | VEGETABLE
├── calories
├── servings            default 1
├── ingredients[]       DishIngredient
│   ├── ingredient_id
│   ├── quantity        (= row.amount)
│   ├── unit            GAM | NUMBER
│   └── grams_equivalent
├── nutrition_per_serving (service compute)
│   ├── calories        trust backend
│   ├── protein         Σ ingredient.protein × grams_equivalent / 100
│   ├── carb            tương tự
│   └── fat             tương tự
└── meal_types[]        default theo type (§4.4): SOUP→lunch+dinner, còn lại→all
```

**Quan trọng**:
- `nutrition_per_serving` chỉ có giá trị sau khi `db_loader` chạy. Model type là `NutritionPerServing | None` nhưng cache luôn đảm bảo non-None.
- `number_to_gam = None` nghĩa là không convert NUMBER → GAM được (ví dụ gạo). Nếu fridge cố dùng NUMBER với ingredient như vậy → `InvalidIngredientError` (400).
- `meal_types` rule có thể override trong tương lai nếu backend thêm field.

`MealLogEntry` cũng ở đây (dishId + date) vì nó là dữ liệu "đã xảy ra", dùng để exclude dish
đã ăn gần đây.

## [`input.py`](../app/models/input.py) — request đến service

```
RecommendRequest
├── user_id          str, min_length=1
├── tdee             float, [800, 5000]
├── weight           float, [30, 300]  kg
├── goal
│   └── target_kg    float, [-0.5, +0.5]  kg/TUẦN (tên không có "PerWeek")
├── meal_structure
│   ├── breakfast    { main_dish, soup, vegetable } mỗi field ∈ [0, 3]
│   ├── lunch
│   └── dinner
├── plan_days        int, [1, 14]
├── start_date       datetime (ISO)
├── recent_meal_log  list[MealLogEntry]  (default [])
└── fridge[]         FridgeItem
    ├── ingredient_id
    ├── quantity     > 0
    ├── unit         GAM | NUMBER
    └── due_date

UpdateDBRequest
├── dishes_url       HttpUrl
└── ingredients_url  HttpUrl
```

**Pydantic tự lo**:
- `HttpUrl` → từ chối URL sai format
- `ge`/`le` → 422 nếu range sai
- `datetime` → parse ISO 8601, giữ timezone

## [`output.py`](../app/models/output.py) — response

```
MealPlanResponse
├── status               "success" | "failed"
├── plan[]               DayPlan
│   ├── day              1-indexed
│   ├── date             startDate + (day-1) ngày
│   ├── meals
│   │   ├── breakfast[]  MealDishEntry
│   │   ├── lunch[]
│   │   └── dinner[]
│   └── nutrition        tổng cả ngày
├── summary              avg + target + deviation
└── shopping_list[]      dedup qua cả plan

MealDishEntry
├── dish_id
├── role
└── missing_ingredient[] nguyên liệu dish này cần mua (đã trừ stock)

MissingIngredient / ShoppingItem
├── ingredient_id
├── unit      giữ đơn vị gốc của công thức (§15 #2)
└── quantity
```

**Quan trọng về serialization**:
- Tất cả field ra JSON bằng camelCase: `missingIngredient`, `shoppingList`, `targetCalories`, …
- Route handler dùng `response_model_by_alias=True` để bật cái này.
- `missing_ingredient` ban đầu = `[]`, được fill lúc chạy `compute_missing_per_dish()`.

## Sơ đồ quan hệ

```
RecommendRequest ─────────┐
                          │
Dish (cache) ──┐          ▼
               ├──→ recommend() ──→ MealPlanResponse
Ingredient ────┘                           │
                                           └── contains DayPlan[]
                                                        │
                                                        └── contains MealDishEntry[]
                                                                      │
                                                                      └── contains MissingIngredient[]
```
