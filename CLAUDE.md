# 🍽️ Meal Recommendation System — Claude Code Instructions (v3)

> **File này là "contract" giữa bạn (developer) và Claude Code.**
> Claude Code PHẢI đọc kỹ file này TRƯỚC khi viết bất kỳ dòng code nào.
> Schema input/output đã được **CHỐT với team app** — KHÔNG tự ý thêm/bớt field.

---

## 0. Context — Bối cảnh dự án

Hệ thống **Meal Recommendation Service** là một microservice Python độc lập, nhận input từ backend (web/app) qua REST API, sinh kế hoạch ăn uống N ngày (1–14) đáp ứng các ràng buộc về:

1. **Cấu trúc bữa ăn** do user chỉ định (mainDish/soup/vegetable mỗi bữa).
2. **Nguyên liệu trong tủ lạnh** (ưu tiên nguyên liệu sắp hết hạn).
3. **Năng lượng & macro** theo mục tiêu (giảm / duy trì / tăng cân).
4. **Không lặp món** trong N ngày gần nhất (chống nhàm chán).

### Nguyên tắc kiến trúc (BẮT BUỘC)

- Service **KHÔNG** kết nối trực tiếp database của backend.
- Backend POST JSON tới `/update-db` → service download file JSON và cache in-memory (singleton).
- Service chỉ phục vụ request `/recommend` dựa trên cache đó.
- **62 classes nguyên liệu** là giới hạn cứng từ CV model. Mọi `ingredientId` trong `fridge` phải thuộc tập này.

```
┌─────────────┐  POST /update-db   ┌──────────────────────┐
│  Backend    │ ──(dishesUrl,      │  Meal Recommender    │
│  (Web/App)  │     ingredientsUrl)│  (FastAPI)           │
└─────────────┘                    └──────────────────────┘
      │                                       │
      │                                       │ httpx download
      │                                       │ → validate
      │                                       │ → cache in-memory
      │                                       ▼
      │                              ┌──────────────────┐
      │                              │  dishes.json     │
      │                              │  ingredients.json│
      │                              │  (62 classes)    │
      │                              └──────────────────┘
      │                                       │
      │       POST /recommend                 │
      └──────────(input.json)─────────────────┤
                                              ▼
                                   ┌─────────────────────┐
                                   │  CP-SAT Solver      │
                                   │  (OR-Tools)         │
                                   └─────────────────────┘
                                              │
                                              ▼
                                        output.json
```

---

## 1. Tech Stack (CHỐT)

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Language | **Python 3.11+** | Type hints hiện đại, match OR-Tools |
| Framework | **FastAPI** | Async, Pydantic integration, auto OpenAPI docs |
| Validation | **Pydantic v2** | Validate input/output schema chặt chẽ |
| Solver | **OR-Tools CP-SAT** | Constraint programming cho meal planning |
| HTTP Client | **httpx** (async) | Download JSON từ backend URL |
| Logging | **loguru** | Cấu hình đơn giản, format đẹp |
| Testing | **pytest + pytest-cov + pytest-benchmark** | Unit test + coverage + perf |

**requirements.txt chính:**
```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.9.0
pydantic-settings>=2.5.0
httpx>=0.27.0
ortools>=9.11.0
loguru>=0.7.0
pytest>=8.3.0
pytest-asyncio>=0.24.0
pytest-cov>=5.0.0
pytest-benchmark>=4.0.0
```

---

## 2. Cấu trúc thư mục (BẮT BUỘC)

```
meal-recommender/
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                # /recommend, /update-db, /health
│   │   └── dependencies.py          # Dependency injection (get_cache)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                # Pydantic Settings (env vars)
│   │   ├── cache.py                 # In-memory cache (singleton)
│   │   ├── logging_config.py        # Loguru setup
│   │   └── exceptions.py            # Custom exceptions
│   ├── models/
│   │   ├── __init__.py
│   │   ├── input.py                 # RecommendRequest, UpdateDBRequest
│   │   ├── output.py                # MealPlanResponse, ShoppingItem
│   │   ├── domain.py                # Dish, Ingredient, MealLogEntry
│   │   └── enums.py                 # Role, Unit
│   ├── services/
│   │   ├── __init__.py
│   │   ├── db_loader.py             # Download + parse JSON from URL
│   │   ├── constraints/
│   │   │   ├── __init__.py
│   │   │   ├── structural.py        # C1 meal structure
│   │   │   ├── repetition.py        # C2 no-repeat
│   │   │   ├── calorie.py           # C3 calorie target
│   │   │   └── macro.py             # C4 macro ratios
│   │   ├── cp_sat_solver.py         # OR-Tools CP-SAT model builder
│   │   ├── objective.py             # Weighted objective function
│   │   ├── shopping_list.py         # Build shopping list
│   │   ├── missing_ingredient.py    # Tính missingIngredient per dish
│   │   └── unit_converter.py        # NUMBER ↔ GAM conversion
│   └── utils/
│       ├── __init__.py
│       ├── nutrition.py             # Macro target calculator
│       └── date_utils.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── sample_dishes.json
│   │   ├── sample_ingredients.json
│   │   ├── sample_input.json        # Copy từ input.json thực tế
│   │   └── sample_output.json       # Copy từ output.json thực tế
│   ├── unit/
│   │   ├── test_constraints.py
│   │   ├── test_solver.py
│   │   ├── test_shopping_list.py
│   │   ├── test_missing_ingredient.py
│   │   └── test_unit_converter.py
│   ├── integration/
│   │   ├── test_recommend_endpoint.py
│   │   └── test_update_db_endpoint.py
│   └── benchmarks/
│       └── test_solver_performance.py
├── data/                            # JSON cache (gitignored)
│   ├── dishes.json
│   └── ingredients.json
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── Makefile
└── README.md
```

---

## 3. Input / Output Schema (CHỐT — đã thống nhất với team app)

> 🔒 **RẤT QUAN TRỌNG:** Schema dưới đây đã được **chốt với team backend/app**.
> KHÔNG tự thêm field như `preferences`, `dietType`, `warnings`, `meta`, etc.
> Nếu cần bổ sung → PHẢI hỏi user và xác nhận với team app TRƯỚC khi sửa.

### 3.1 Input — `POST /recommend`

```json
{
  "userId": "user_001",
  "tdee": 2150,
  "weight": 68,

  "goal": {
    "targetKg": -0.5
  },

  "mealStructure": {
    "breakfast": {
      "mainDish": 1,
      "soup": 0,
      "vegetable": 1
    },
    "lunch": {
      "mainDish": 1,
      "soup": 1,
      "vegetable": 1
    },
    "dinner": {
      "mainDish": 1,
      "soup": 1,
      "vegetable": 1
    }
  },

  "planDays": 5,
  "startDate": "2026-04-21T00:00:00.000Z",

  "recentMealLog": [
    {
      "dishId": 101,
      "date": "2026-04-18T12:00:00.000Z"
    }
  ],

  "fridge": [
    {
      "ingredientId": 1,
      "quantity": 500,
      "unit": "GAM",
      "dueDate": "2026-04-23T00:00:00.000Z"
    }
  ],

  "lockedPicks": [
    {
      "day": 3,
      "meal": "lunch",
      "role": "MAINDISH",
      "dishId": 112
    }
  ]
}
```

> ✍️ **`lockedPicks`** (optional, default `[]`) — pin các slot không cho solver thay đổi.
> Dùng cho **replan flow**: user đã có plan từ /recommend trước đó, muốn đổi 1 món hoặc giữ
> một số slot cố định. Empty list ⇒ flow recommend bình thường. Xem [docs/07-replan.md](docs/07-replan.md).

> ⚠️ **LƯU Ý về `targetKg`:**
> Dù tên là `targetKg` (không có suffix "PerWeek"), giá trị này **LUÔN LÀ kg/tuần**.
> Backend giữ tên này vì đã chuẩn hóa trong app.
> Range cố định: **[-0.5, +0.5]** theo khuyến nghị dinh dưỡng bền vững.
> Công thức: `weekly_delta = targetKg × 7700` (KHÔNG chia cho số ngày plan).

**Pydantic validation rules:**

| Field | Type | Validation |
|---|---|---|
| `userId` | string | required, non-empty |
| `tdee` | float | range [800, 5000] |
| `weight` | float | range [30, 300] |
| `goal.targetKg` | float | range [-0.5, +0.5] kg/tuần |
| `mealStructure.{breakfast,lunch,dinner}.{mainDish,soup,vegetable}` | int | range [0, 3] |
| `planDays` | int | range [1, 14] |
| `startDate` | ISO datetime | required |
| `recentMealLog` | list | optional (default []) |
| `recentMealLog[].dishId` | int | required |
| `recentMealLog[].date` | ISO datetime | required |
| `fridge` | list | optional (default []) |
| `fridge[].ingredientId` | int | PHẢI ∈ 62 classes đã load |
| `fridge[].quantity` | float | > 0 |
| `fridge[].unit` | enum | `"GAM"` hoặc `"NUMBER"` |
| `fridge[].dueDate` | ISO datetime | required |
| `lockedPicks` | list | optional (default []) |
| `lockedPicks[].day` | int | range [1, planDays] |
| `lockedPicks[].meal` | enum | `"breakfast"` / `"lunch"` / `"dinner"` |
| `lockedPicks[].role` | enum | `"MAINDISH"` / `"SOUP"` / `"VEGETABLE"` |
| `lockedPicks[].dishId` | int | dish phải tồn tại trong cache, role phải khớp dish.role (→ 400) |
| `lockedPicks` cross-rules | — | (day, meal, role) unique; số lock cho slot ≤ `mealStructure[meal][role]` (→ 422) |

### 3.2 Output — `POST /recommend` response

```json
{
  "status": "success",
  "plan": [
    {
      "day": 1,
      "date": "2026-04-21T00:00:00.000Z",
      "meals": {
        "breakfast": [
          {
            "dishId": 101,
            "role": "MAINDISH",
            "missingIngredient": [
              {
                "ingredientId": 11,
                "unit": "GAM",
                "quantity": 150
              }
            ]
          },
          {
            "dishId": 102,
            "role": "VEGETABLE",
            "missingIngredient": []
          }
        ],
        "lunch": [
          {
            "dishId": 201,
            "role": "MAINDISH",
            "missingIngredient": []
          },
          {
            "dishId": 202,
            "role": "SOUP",
            "missingIngredient": []
          },
          {
            "dishId": 203,
            "role": "VEGETABLE",
            "missingIngredient": []
          }
        ],
        "dinner": [
          {
            "dishId": 301,
            "role": "MAINDISH",
            "missingIngredient": []
          },
          {
            "dishId": 302,
            "role": "SOUP",
            "missingIngredient": []
          },
          {
            "dishId": 303,
            "role": "VEGETABLE",
            "missingIngredient": []
          }
        ]
      },
      "nutrition": {
        "calories": 1980,
        "protein": 110,
        "carb": 230,
        "fat": 55
      }
    }
  ],
  "summary": {
    "avgDailyCalories": 2043.33,
    "targetCalories": 14350,
    "deviation": -0.32,
    "avgDailyProtein": 115,
    "avgDailyCarbs": 238.33,
    "avgDailyFat": 57.67
  },
  "shoppingList": [
    {
      "ingredientId": 7,
      "quantity": 200,
      "unit": "GAM"
    }
  ]
}
```

**Output field specs:**

| Field | Type | Ý nghĩa |
|---|---|---|
| `status` | string | `"success"` hoặc `"failed"` |
| `plan[]` | list | Một item cho mỗi ngày trong plan |
| `plan[].day` | int | 1-indexed (không phải 0) |
| `plan[].date` | ISO datetime | `startDate + (day-1) × 1 day` |
| `plan[].meals.{breakfast,lunch,dinner}` | list | Các dish trong bữa đó |
| `plan[].meals.*[].dishId` | int | ID của dish |
| `plan[].meals.*[].role` | enum | `"MAINDISH"` / `"SOUP"` / `"VEGETABLE"` |
| `plan[].meals.*[].missingIngredient[]` | list | Nguyên liệu **của dish này** mà fridge không có đủ |
| `plan[].nutrition` | object | Tổng dinh dưỡng của NGÀY đó (cộng tất cả dishes) |
| `summary.avgDailyCalories` | float | Trung bình calo/ngày qua cả plan |
| `summary.targetCalories` | int | = `(tdee + daily_delta) × planDays` |
| `summary.deviation` | float | **% lệch** giữa actual vs target. Công thức: `(avg × planDays - targetCalories) / targetCalories` |
| `summary.avgDailyProtein/Carbs/Fat` | float | Trung bình macro |
| `shoppingList[]` | list | Tổng nguyên liệu cần mua cho cả plan (dedup) |

**`missingIngredient` logic:**
- Là nguyên liệu của **riêng dish đó** mà **fridge không có hoặc không đủ** TẠI THỜI ĐIỂM NẤU.
- Có tính đến nguyên liệu đã bị các dish trước trong plan tiêu thụ.
- Nếu fridge đủ → `missingIngredient: []`.

**`shoppingList` logic:**
- Là tổng hợp **dedup** của tất cả `missingIngredient` qua toàn bộ plan.
- Cùng một `ingredientId` xuất hiện nhiều lần → cộng quantity.

### 3.3 Endpoint `POST /update-db`

**Request:**
```json
{
  "dishesUrl": "https://backend.com/export/dishes.json",
  "ingredientsUrl": "https://backend.com/export/ingredients.json",
  "dishIngredientsUrl": "https://backend.com/export/dish_ingredients.json"
}
```

**Logic:**
1. Download cả 3 file bằng `httpx` (async, timeout 30s).
2. Validate schema bằng Pydantic (models/domain.py).
3. Validate: `len(ingredients) ≤ 62`; mọi `dishId` trong `dishIngredients` phải thuộc tập dish valid. `ingredientId` trong `dishIngredients` **không bắt buộc** nằm trong 62-class (cho phép gia vị ngoài whitelist — chỉ log info, không raise).
4. **Merge** `dishIngredients` → `dish.ingredients[]` (group by `dishId`).
5. **Compute** `dish.nutrition_per_serving` (protein/carb/fat) từ ingredient-level macros × `gramsEquivalent` / 100. Dish `calories` lấy trực tiếp từ backend (không tính lại).
6. **Apply** default `mealTypes` theo `type` (xem §4.4).
7. Nếu OK → replace cache in-memory (atomic), ghi file backup tại `data/`.
8. Nếu fail → giữ cache cũ, return lỗi chi tiết.

**Response:**
```json
{
  "status": "success",
  "dishesCount": 512,
  "ingredientsCount": 62,
  "dishIngredientsCount": 2130,
  "updatedAt": "2026-04-24T10:30:00.000Z"
}
```

---

## 4. JSON Schema nội bộ của Dish & Ingredient (cache)

> ✍️ **Update 2026-04-24**: Schema §4 đã được align với DB thực tế của backend. `dishes.json` giờ chỉ chứa field flat; `nutritionPerServing`, `ingredients[]`, `mealTypes[]` được service compute lúc load từ `ingredients.json` + `dish_ingredients.json`.

### 4.1 `dishes.json` — export từ bảng Dish

```json
[
  {
    "id": 101,
    "name": "Cơm tấm sườn nướng",
    "type": "MAIN_DISH",
    "calories": 620
  }
]
```

**Field bắt buộc**: `id`, `name`, `type`, `calories`.

**Field backend có thể gửi kèm (service ignore)**: `description`, `images`, `instructions`, `prepTimeMin`, `cookTimeMin`, `difficulty`, `createdAt`, `updatedAt`. Backend PHẢI filter `isDeleted=false` trước khi export.

**`type`**: enum `MAIN_DISH | SOUP | VEGETABLE`. Service tự normalize `MAIN_DISH → MAINDISH` (bỏ underscore) để khớp với `Role` enum dùng trong output API §3.2.

### 4.2 `ingredients.json` — export từ bảng Ingredient (≤ 62 classes)

```json
[
  {
    "id": 1,
    "name": "Thịt heo",
    "unit": "GAM",
    "numberToGam": null,
    "protein": 23,
    "carb": 0,
    "fat": 17
  },
  {
    "id": 2,
    "name": "Trứng gà",
    "unit": "NUMBER",
    "numberToGam": 55,
    "protein": 12.6,
    "carb": 1.1,
    "fat": 10.6
  }
]
```

**Field bắt buộc**: `id`, `name`, `unit`, `protein`, `carb`, `fat`. `numberToGam` bắt buộc có, nhưng được phép null (khi ingredient không quy đổi NUMBER sang GAM hợp lý được — vd gạo).

**Quy ước đơn vị macro**: `protein`, `carb`, `fat` là **grams per 100g** của ingredient (chuẩn dinh dưỡng).

**Field backend có thể gửi kèm (service ignore)**: `categoryId`, `description`, `images`, `createdAt`, `updatedAt`. Backend PHẢI filter `isDeleted=false`.

**Unit conversion rule**:
- Nội bộ service luôn so sánh bằng GAM. Fridge unit=NUMBER được convert bằng `numberToGam`.
- `numberToGam = null` + fridge gửi unit=NUMBER cho ingredient đó → `InvalidIngredientError` (400).
- Output `missingIngredient`/`shoppingList` giữ đơn vị **gốc của công thức dish** (xem §4.3 `unit` field).

### 4.3 `dish_ingredients.json` — junction table

```json
[
  { "id": 1, "dishId": 4, "ingredientId": 1, "amount": 200, "gramsEquivalent": 200, "unit": "GAM" },
  { "id": 2, "dishId": 93, "ingredientId": 2, "amount": 2,   "gramsEquivalent": 110, "unit": "NUMBER" }
]
```

**Field bắt buộc**: `dishId`, `ingredientId`, `amount`, `gramsEquivalent`, `unit`.

- `amount` + `unit`: lượng công thức, đơn vị gốc (hiển thị cho user). Service dùng cặp này để build `missingIngredient.quantity` + `missingIngredient.unit` khi thiếu.
- `gramsEquivalent`: **backend đã convert sẵn** về GAM. Service dùng trường này để trừ stock và tính macro dish → khỏi phải gọi `numberToGam` lần nữa.

### 4.4 Default mealTypes rule (service tự áp)

Do backend chưa có column `mealTypes`, service áp rule mặc định theo `type`:

| `type` | `mealTypes` áp dụng |
|---|---|
| `MAIN_DISH` | `["breakfast", "lunch", "dinner"]` |
| `SOUP` | `["lunch", "dinner"]` |
| `VEGETABLE` | `["breakfast", "lunch", "dinner"]` |

Backend có thể override trong tương lai bằng cách thêm field `mealTypes` vào `dishes.json` — service sẽ ưu tiên dùng nếu có.

### 4.5 Công thức compute dish macros (service tự chạy)

```python
for dish in dishes:
    protein_sum = carb_sum = fat_sum = 0
    for di in dish.ingredients:   # đã merge từ junction
        meta = ingredients_map[di.ingredient_id]
        factor = di.grams_equivalent / 100.0
        protein_sum += meta.protein * factor
        carb_sum    += meta.carb    * factor
        fat_sum     += meta.fat     * factor
    dish.nutrition_per_serving = {
        "calories": dish.calories,          # trust backend
        "protein":  round(protein_sum, 1),
        "carb":     round(carb_sum, 1),
        "fat":      round(fat_sum, 1),
    }
```

**Lý do tính lại protein/carb/fat chứ không trust `dish.calories`**: backend chỉ store calories; macros chỉ có ở level ingredient. Calories backend đã tính (áp yield/retention) thì trust.

---

## 5. Ràng buộc bài toán (Constraints)

### 5.1 Hard constraints (CP-SAT encode trực tiếp)

**C1 — Cấu trúc bữa ăn (Structural):**
```
Với mỗi ngày d, mỗi bữa m, mỗi role r:
  Σ x[d,m,r,dish] = mealStructure[m][r]

Trong đó x[d,m,r,dish] ∈ {0, 1} là biến quyết định.
```

**C2 — Không lặp món (Repetition):**
```
Với mỗi cặp (d, d') sao cho |d - d'| ≤ N (default N=2):
  Một dish chỉ xuất hiện tối đa 1 lần trong cửa sổ N+1 ngày liên tiếp.

Mở rộng cho recentMealLog: dish đã ăn trong [startDate-N, startDate-1]
cũng bị exclude cho những ngày đầu của plan.
```

**C3 — Calo (Calorie):**
```python
# targetKg là kg/TUẦN (dù tên không có suffix "PerWeek")
weekly_delta = target_kg * 7700             # kcal/tuần
daily_delta  = weekly_delta / 7             # kcal/ngày
target_cal   = tdee + daily_delta           # âm → deficit, dương → surplus

# Trong CP-SAT:
for d in range(plan_days):
    cal_d = sum(x[d,m,r,dish] * dish.calories for ...)
    model.Add(cal_d >= target_cal - DELTA)
    model.Add(cal_d <= target_cal + DELTA)
```

Default `DELTA = 100` kcal. Nếu INFEASIBLE → relax lên 200 → 300.

**Ví dụ tính toán:**
- `tdee=2150, targetKg=-0.5` → `daily_delta=-550` → `target_cal=1600` kcal/ngày
- `tdee=2150, targetKg=+0.5` → `target_cal=2700` kcal/ngày  
- `tdee=2150, targetKg=0` → `target_cal=2150` kcal/ngày (duy trì)

**C4 — Macro (chốt theo ISSN/ACSM):**

```python
MACRO_TARGETS = {
    "weight_loss": {
        "protein_g_per_kg": (1.6, 2.2),   # ISSN for cutting
        "carb_pct":  (0.45, 0.55),
        "fat_pct":   (0.20, 0.30)
    },
    "maintain": {
        "protein_g_per_kg": (1.2, 1.6),
        "carb_pct":  (0.45, 0.60),
        "fat_pct":   (0.25, 0.35)
    },
    "weight_gain": {
        "protein_g_per_kg": (1.4, 2.0),   # ISSN for muscle gain
        "carb_pct":  (0.50, 0.60),
        "fat_pct":   (0.20, 0.30)
    }
}
```

**Phân loại goal từ `targetKg` (kg/tuần):**
- `< -0.1`: `weight_loss`
- `[-0.1, +0.1]`: `maintain`
- `> +0.1`: `weight_gain`

**Lưu ý về fiber:** KHÔNG đưa vào ràng buộc cứng. Đã đảm bảo bởi `mealStructure.vegetable >= 1` do user chỉ định.

**CP-SAT encoding macro (phải scale integer):**
```python
# Protein (g) — scale *10 để tránh float
protein_min = int(target.protein_g_per_kg[0] * weight * 10)
protein_max = int(target.protein_g_per_kg[1] * weight * 10)
protein_d_scaled = sum(x[d,m,r,i] * int(dish.protein * 10) for ...)
model.Add(protein_d_scaled >= protein_min)
model.Add(protein_d_scaled <= protein_max)

# Carb % — nhân chéo để tránh chia:
# carb_pct_min * cal_d <= 4 * carb_d <= carb_pct_max * cal_d
model.Add(4 * carb_d * 100 >= int(carb_pct_min * 100) * cal_d)
model.Add(4 * carb_d * 100 <= int(carb_pct_max * 100) * cal_d)
```

### 5.2 Soft constraints (đưa vào Objective)

| Symbol | Mô tả | Trọng số đề xuất |
|---|---|---|
| S1 | Ưu tiên dùng nguyên liệu trong fridge | 3 |
| S2 | Ưu tiên nguyên liệu sắp hết hạn (due ≤ 2 ngày) | 5 |
| S3 | Đa dạng món (không lặp cùng "protein source" 2 ngày liên tiếp) | 2 |
| S4 | Giảm kích thước shopping list | 3 |

Trọng số đọc từ env vars (`WEIGHT_FRIDGE=3`, ...).

---

## 6. OR-Tools CP-SAT Model (CHI TIẾT)

### 6.1 Decision variables

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()

# x[d, meal, role, dish_idx] ∈ {0, 1}
x = {}
for d in range(plan_days):
    for meal in ["breakfast", "lunch", "dinner"]:
        for role in ["MAINDISH", "SOUP", "VEGETABLE"]:
            for i, dish in enumerate(candidate_dishes[role]):
                x[(d, meal, role, i)] = model.NewBoolVar(f"x_{d}_{meal}_{role}_{i}")
```

### 6.2 Hard constraint encoding

```python
# C1 — Meal structure
for d in range(plan_days):
    for meal in ["breakfast", "lunch", "dinner"]:
        for role in ["MAINDISH", "SOUP", "VEGETABLE"]:
            required = meal_structure[meal][role.lower()]  # API dùng camelCase
            model.Add(
                sum(x[(d, meal, role, i)] for i in range(len(candidate_dishes[role])))
                == required
            )

# C2 — No repeat within N days
N = 2
for dish_id, var_list in dish_to_vars.items():
    for d in range(plan_days):
        window_vars = [v for (dd, v) in var_list if abs(dd - d) <= N]
        if len(window_vars) > 1:
            model.Add(sum(window_vars) <= 1)

# Recent meal log: exclude những dish đã ăn trong [startDate-N, startDate-1]
for log_entry in recent_meal_log:
    days_until_start = (start_date - log_entry.date).days
    if days_until_start <= N:
        forbidden_days = range(0, N - days_until_start + 1)
        for d in forbidden_days:
            for var in get_vars_for_dish(log_entry.dish_id, day=d):
                model.Add(var == 0)

# C3 — Calorie
for d in range(plan_days):
    cal_d = sum(
        x[(d, m, r, i)] * int(dish.calories)
        for (m, r, i), dish in all_dishes_by_key.items()
    )
    model.Add(cal_d >= target_cal - DELTA)
    model.Add(cal_d <= target_cal + DELTA)

# C4 — Macro (xem §5.1)
```

### 6.3 Objective function

```python
objective_terms = []

# S1 — fridge usage
for (d, m, r, i), dish in all_dishes_by_key.items():
    bonus = sum(W_FRIDGE for ing in dish.ingredients if ing.ingredient_id in fridge_ids)
    if bonus > 0:
        objective_terms.append(x[(d, m, r, i)] * bonus)

# S2 — expiry urgency (ưu tiên cao nhất)
for (d, m, r, i), dish in all_dishes_by_key.items():
    urgency = 0
    for ing in dish.ingredients:
        if ing.ingredient_id in expiring_soon:
            days_to_expire = (expiring_soon[ing.ingredient_id] - day_date(d)).days
            if days_to_expire <= 2:
                urgency += W_EXPIRY * max(1, 3 - days_to_expire)
    if urgency > 0:
        objective_terms.append(x[(d, m, r, i)] * urgency)

# S3 — diversity, S4 — shopping list size (tương tự)

model.Maximize(sum(objective_terms))
```

### 6.4 Solver configuration

```python
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 5.0
solver.parameters.num_search_workers = 4
solver.parameters.random_seed = hash(user_id) % 1000
solver.parameters.log_search_progress = False

status = solver.Solve(model)
```

### 6.5 Status handling

| CP-SAT status | Xử lý |
|---|---|
| `OPTIMAL` | Return plan, `status: "success"` |
| `FEASIBLE` | Return plan, `status: "success"` (đã có kết quả dù không tối ưu tuyệt đối) |
| `INFEASIBLE` | Relax constraints theo §7 rồi solve lại |
| `MODEL_INVALID` | Log error, return 500 |
| `UNKNOWN` | Timeout, relax và thử lại 1 lần, sau đó `status: "failed"` |

---

## 7. Fallback & Edge Cases

### 7.1 Relaxation strategy khi INFEASIBLE

Relax theo thứ tự sau, solve lại mỗi lần:

| Lần | Relax |
|---|---|
| 1 | `DELTA_calorie`: 100 → 200 |
| 2 | `DELTA_calorie`: 200 → 300 |
| 3 | `N_no_repeat`: 2 → 1 |
| 4 | `N_no_repeat`: 1 → 0 |
| 5 | Relax macro bounds ±15% |
| 6 | Vẫn INFEASIBLE → return `status: "failed"` |

> **Lưu ý:** Output schema hiện KHÔNG có field `warnings[]`. Nếu cần log các lần relax, chỉ log ở server-side (loguru) để debug, không expose ra response.

### 7.2 Edge cases

| Tình huống | Xử lý |
|---|---|
| Cache chưa load (cold start) | `/recommend` return 503 "DB not loaded, call /update-db first" |
| Fridge rỗng | Skip S1/S2 objective terms, vẫn solve bình thường |
| `planDays > 14` | Pydantic reject ở validation layer (400) |
| Dish có ingredient ngoài 62 classes | **Giữ dish**, chỉ skip ingredient lạ trong nutrition/stock/shopping (coi như gia vị user tự túc). Log info. *(chốt 2026-04-25)* |
| Fridge ingredient ngoài 62 classes | Return 400, message rõ ràng |
| `recentMealLog` rỗng | Không sao, chỉ apply C2 trong phạm vi plan |
| Không tìm được plan sau khi relax hết | Return `status: "failed"` |

---

## 8. Shopping List & Missing Ingredient Logic

### 8.1 Missing Ingredient (per dish)

Với mỗi dish trong plan, tính **nguyên liệu còn thiếu** so với fridge TẠI THỜI ĐIỂM NẤU:

```python
def compute_missing_ingredients(plan, fridge, dishes_map, ingredients_map):
    """Duyệt plan theo thứ tự thời gian, trừ dần fridge."""
    # Copy fridge (đã convert về GAM) để mutate an toàn
    stock = {}
    for f in fridge:
        meta = ingredients_map[f.ingredient_id]
        stock[f.ingredient_id] = convert_to_gam(f.quantity, f.unit, meta)

    # Duyệt plan theo day ascending, meal theo thứ tự breakfast→lunch→dinner
    for day in sorted(plan, key=lambda p: p.day):
        for meal_name in ["breakfast", "lunch", "dinner"]:
            for dish_entry in day.meals[meal_name]:
                dish = dishes_map[dish_entry.dish_id]
                missing = []
                for ing in dish.ingredients:
                    meta = ingredients_map[ing.ingredient_id]
                    need_gam = convert_to_gam(ing.quantity, ing.unit, meta)
                    have_gam = stock.get(ing.ingredient_id, 0)
                    
                    if have_gam >= need_gam:
                        stock[ing.ingredient_id] = have_gam - need_gam
                    else:
                        deficit_gam = need_gam - have_gam
                        stock[ing.ingredient_id] = 0
                        # Convert deficit về đơn vị gốc của công thức
                        missing.append(build_missing_item(ing, deficit_gam, meta))
                
                dish_entry.missingIngredient = missing
```

**Quan trọng:**
- `missingIngredient` của mỗi dish được tính SAU KHI đã trừ những dish chạy trước nó.
- Unit trong `missingIngredient` nên khớp với `unit` mà công thức dish yêu cầu (NUMBER hay GAM).

### 8.2 Shopping List (toàn plan)

```python
def build_shopping_list(plan, ingredients_map):
    """Gộp tất cả missingIngredient qua toàn plan."""
    totals = defaultdict(lambda: {"GAM": 0.0, "NUMBER": 0.0})
    
    for day in plan:
        for meal in day.meals.values():
            for dish_entry in meal:
                for mi in dish_entry.missingIngredient:
                    totals[mi.ingredient_id][mi.unit] += mi.quantity

    shopping = []
    for ing_id, by_unit in totals.items():
        meta = ingredients_map[ing_id]
        # Nếu có cả GAM và NUMBER → gộp về default_unit của ingredient
        if by_unit["GAM"] > 0 and by_unit["NUMBER"] > 0:
            # Convert về GAM rồi nếu default là NUMBER thì ceil chia ngược
            total_gam = by_unit["GAM"] + by_unit["NUMBER"] * meta.unitConversions.NUMBER_TO_GAM
            if meta.defaultUnit == "NUMBER" and meta.unitConversions.NUMBER_TO_GAM:
                qty = math.ceil(total_gam / meta.unitConversions.NUMBER_TO_GAM)
                shopping.append({"ingredientId": ing_id, "quantity": qty, "unit": "NUMBER"})
            else:
                shopping.append({"ingredientId": ing_id, "quantity": math.ceil(total_gam), "unit": "GAM"})
        elif by_unit["GAM"] > 0:
            shopping.append({"ingredientId": ing_id, "quantity": math.ceil(by_unit["GAM"]), "unit": "GAM"})
        else:
            shopping.append({"ingredientId": ing_id, "quantity": int(by_unit["NUMBER"]), "unit": "NUMBER"})

    return sorted(shopping, key=lambda x: x["ingredientId"])
```

---

## 9. Summary calculation

```python
def build_summary(plan, target_cal_per_day, plan_days):
    total_cal    = sum(d.nutrition.calories for d in plan)
    total_prot   = sum(d.nutrition.protein for d in plan)
    total_carb   = sum(d.nutrition.carb for d in plan)
    total_fat    = sum(d.nutrition.fat for d in plan)
    
    target_total = target_cal_per_day * plan_days
    deviation    = (total_cal - target_total) / target_total  # có thể âm hoặc dương

    return {
        "avgDailyCalories": round(total_cal / plan_days, 2),
        "targetCalories":   target_total,
        "deviation":        round(deviation, 2),
        "avgDailyProtein":  round(total_prot / plan_days, 2),
        "avgDailyCarbs":    round(total_carb / plan_days, 2),
        "avgDailyFat":      round(total_fat / plan_days, 2)
    }
```

**Verify với sample output:**
- `avgDailyCalories = 2043.33` và `planDays = 3` (trong sample chỉ có 3 ngày được hiển thị)
- `targetCalories = 14350` → target per day = `14350 / ??? = ?`
- Tra ngược: nếu `tdee=2150, targetKg=-0.5 → target_cal=1600/ngày`. Nhưng `14350/7 = 2050` — không khớp với 1600.
- **Gợi ý:** Có thể `targetCalories` trong sample được tính cho cả planDays=7 (input gốc có thể khác). Hoặc công thức tính là `tdee × planDays` (bỏ qua deficit).
- **→ CÂU HỎI CHO USER (§15 #6):** Công thức chính xác của `summary.targetCalories` là gì?

---

## 10. Coding Rules

### BẮT BUỘC

- ✅ Python 3.11+ type hints everywhere.
- ✅ Pydantic v2 cho toàn bộ I/O validation.
- ✅ Docstring Google-style cho mọi public function.
- ✅ Logging với `loguru`, KHÔNG dùng `print`.
- ✅ Config qua env vars + `pydantic-settings`, KHÔNG hardcode.
- ✅ `async def` cho I/O endpoints, `def` sync cho CPU-bound solver.
- ✅ Dependency injection qua FastAPI `Depends(get_cache)`.
- ✅ **Output JSON alias field names:** Pydantic models dùng snake_case Python nội bộ nhưng **serialize ra camelCase** khớp với schema app (dùng `Field(alias=...)` và `model_config = ConfigDict(populate_by_name=True)`).

### CẤM

- ❌ `from module import *`
- ❌ `except Exception: pass` — luôn log.
- ❌ `requests` library — dùng `httpx`.
- ❌ Global mutable state ngoài cache singleton có lock.
- ❌ Magic numbers trong solver — mọi constant phải có tên trong `core/config.py`.
- ❌ **Tự thêm field vào output schema** (như `warnings`, `meta`, `solverTime`). Nếu cần → hỏi user.

### Custom exceptions

```python
# app/core/exceptions.py
class MealRecommenderError(Exception): ...
class CacheNotLoadedError(MealRecommenderError): ...
class InvalidIngredientError(MealRecommenderError): ...
class SolverInfeasibleError(MealRecommenderError): ...
class SolverTimeoutError(MealRecommenderError): ...
```

---

## 11. Thứ tự deliverables (BẮT BUỘC theo thứ tự)

1. **Setup project skeleton** (pyproject.toml, requirements.txt, .env.example, .gitignore, Makefile).
2. **Pydantic models** (`app/models/`):
   - `enums.py`: Role, Unit
   - `domain.py`: Dish, Ingredient
   - `input.py`: RecommendRequest, UpdateDBRequest
   - `output.py`: MealPlanResponse, DayPlan, MealDishEntry, MissingIngredient, ShoppingItem, Summary
   - **PHẢI test serialization** bằng cách load sample input/output và verify match byte-by-byte.
3. **Core infrastructure** (config, cache, logging, exceptions).
4. **DB Loader** (`services/db_loader.py`).
5. **Endpoints `/health` và `/update-db`** — test bằng curl.
6. **Constraint modules** (`services/constraints/`) — mỗi file một constraint + unit test.
7. **Unit converter** (`services/unit_converter.py`) — unit test 100%.
8. **CP-SAT Solver** (`services/cp_sat_solver.py`) — core + relaxation logic.
9. **Missing ingredient calculator** (`services/missing_ingredient.py`).
10. **Shopping list builder** (`services/shopping_list.py`).
11. **Endpoint `/recommend`** — ráp tất cả.
12. **Integration tests** (dùng sample_input.json / sample_output.json).
13. **Benchmark + optimization**.
14. **README.md**.

### Sau mỗi bước

- Chạy `pytest -v` và PHẢI pass.
- Chạy `ruff check` và `mypy app/`.
- Commit: `feat(<module>): <what>` hoặc `test(<module>): <what>`.

---

## 12. Environment Variables (.env.example)

```bash
# App
APP_NAME=meal-recommender
APP_VERSION=0.1.0
LOG_LEVEL=INFO

# Solver
SOLVER_TIMEOUT_SECONDS=5.0
SOLVER_NUM_WORKERS=4
CALORIE_DELTA=100
NO_REPEAT_DAYS=2

# Objective weights
WEIGHT_FRIDGE=3
WEIGHT_EXPIRY=5
WEIGHT_DIVERSITY=2
WEIGHT_SHOPPING_PENALTY=3

# DB cache
DATA_DIR=./data
HTTPX_TIMEOUT=30.0
```

---

## 13. README.md template

Khi hoàn tất, README phải có đầy đủ:

1. Project overview (mục đích, tech stack)
2. Architecture diagram (ASCII art theo §0)
3. Quick start: clone → install → run
4. API documentation (link `/docs` + 3 curl examples)
5. Environment variables (link `.env.example`)
6. Testing: `pytest -v --cov`
7. Performance benchmarks (kết quả thực đo)
8. Troubleshooting (5 vấn đề phổ biến)
9. Academic references (ISSN, ACSM, OR-Tools)

---

## 14. Definition of Done

- [ ] `pytest -v` — 100% pass
- [ ] `pytest --cov=app` — coverage ≥ 80% (≥ 90% cho constraints/solver)
- [ ] `ruff check app/` — 0 error
- [ ] `mypy app/ --strict` — 0 error
- [ ] `/health` response < 10ms
- [ ] `/update-db` load 500 dishes + 62 ingredients < 2s
- [ ] `/recommend` 7-day plan < 5s
- [ ] **Output JSON EXACT match schema §3.2** — test bằng cách so sánh structure với `sample_output.json` từ team app
- [ ] README.md đầy đủ 9 mục §13
- [ ] Không có `TODO` / `FIXME` / `print()` trong code production
- [ ] `.env.example` đầy đủ mọi env var

---

## 15. Câu hỏi cần làm rõ — đã chốt

> ✅ Tất cả đã được user chốt (2026-04-22 và 2026-04-24). Lưu lại để tra cứu.

1. **Backend export `nutritionPerServing` không?** — **KHÔNG**. Backend chỉ export `calories` cho dish + macro per-100g cho ingredient. Service tự compute dish macros lúc load (xem §4.5). *(chốt 2026-04-24)*
2. **`numberToGam` trong ingredients có populate không?** — **CÓ**, backend lo phần này. Field flat `numberToGam: float | null` ở top-level ingredient (không nested như ban đầu thiết kế). *(chốt 2026-04-24)*
3. **Mismatch fridge `unit=NUMBER` vs công thức `unit=GAM`?** — Convert về GAM nội bộ bằng `numberToGam`. Output `missingIngredient`/`shoppingList` giữ đơn vị gốc công thức. `numberToGam=null` + fridge NUMBER → `InvalidIngredientError`. *(chốt 2026-04-22)*
4. **User ăn chay?** — **Bỏ qua v1**, input schema không có field. *(chốt 2026-04-22)*
5. **Error response format?** — ~~FastAPI default `{"detail": "..."}`. Pydantic 422 giữ nguyên.~~ ❌ **OVERRIDE 2026-05-08**: theo yêu cầu team app, **mọi lỗi** (validation 422, infeasible solver, cache chưa load, internal error) đều trả **HTTP 200 + schema unified** giống `MealPlanResponse` success — `{status:"failed", message:"<vn>", plan:[], summary:null, shoppingList:[]}`. Message phải là tiếng Việt thân thiện với end-user. Lỗi calo/macro infeasible kèm gợi ý `targetKg` cụ thể (vd 0.5 → 0.3) qua `_suggest_target_kg`. *(chốt 2026-04-22, override 2026-05-08)*
6. **`summary.targetCalories` formula?** — **(b)** `(TDEE + daily_delta) × planDays`, với `daily_delta = targetKg × 7700 / 7`. Sample output trong §3.2 là stale, tin công thức. *(chốt 2026-04-22)*
7. **`recentMealLog` stale?** — Silently drop entry cũ hơn `NO_REPEAT_DAYS` ngày so với `startDate`. *(chốt 2026-04-22)*

**Câu hỏi phát sinh khi align với backend thực tế (2026-04-24)**:

8. **Dish ↔ Ingredient junction?** — **CÓ** bảng `DishIngredient(id, dishId, ingredientId, amount, gramsEquivalent, unit)`. Backend export riêng thành `dish_ingredients.json`; `/update-db` nhận thêm URL `dishIngredientsUrl`.
9. **Per-dish macros?** — Service compute (hướng b). Công thức ở §4.5.
10. **`mealTypes` per dish?** — Default rule theo `type` (hướng b). Bảng ở §4.4.
11. **NUMBER_TO_GAM source?** — Backend populate (đã merge vào #2).

---

## 16. Tham chiếu học thuật (để trích dẫn trong report đồ án)

### Protein
- **ISSN Position Stand (Jäger et al., 2017)** — khuyến nghị 1.4–2.0 g/kg/ngày cho người vận động; 2.3–3.1 g/kg khi cutting.
- **Examine.com Protein Guide** — 1.2–1.6 g/kg tối ưu khi người thừa cân ăn hypocaloric.
- **NASM Review** — ~1.6 g/kg là target để bảo toàn lean body mass khi giảm cân.

### Carbohydrate
- **ACSM Complete Guide to Fitness & Health** — AMDR 45–65% tổng năng lượng từ carb.

### Fat
- **WHO Guideline on Total Fat Intake** — giới hạn ≤ 30% tổng năng lượng.
- **ACSM Position Stand (2009)** — không có tỷ lệ macro duy nhất cho giảm cân; portion control > distribution.

### Tốc độ giảm cân
- **ACSM khuyến nghị** ≤ 2 lb (0.9 kg)/tuần cho giảm cân an toàn.
- **Giảm 0.5 kg/tuần là tối ưu** để giữ cơ và duy trì lâu dài → lý do giới hạn `targetKg ∈ [-0.5, +0.5]`.
- **1 kg mỡ ≈ 7700 kcal** → căn cứ công thức `weekly_delta = targetKg × 7700`.

### Solver
- **OR-Tools CP-SAT Documentation** — https://developers.google.com/optimization/cp/cp_solver
- **Constraint Programming handbook** — Rossi, Van Beek, Walsh (2006).

---

## 📌 Cuối cùng — Nhắc nhở cho Claude Code

1. Đọc **TOÀN BỘ** file này trước khi gõ dòng code đầu tiên.
2. Schema input/output ở §3 đã được **CHỐT với team app** — KHÔNG tự thêm/sửa field.
3. Nếu có điểm mơ hồ → hỏi user (§15), KHÔNG tự quyết.
4. Code theo thứ tự §11, mỗi bước xong PHẢI chạy test.
5. Test integration PHẢI dùng `sample_input.json` và `sample_output.json` làm golden file.
6. Mọi magic number phải nằm trong `config.py`.

**Chúc code vui! 🚀**
