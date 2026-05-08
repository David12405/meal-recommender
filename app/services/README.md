# `app/services/` — Workflow tour

Doc này đi từ **đầu đến cuối 1 request `/recommend`** để bạn nắm được pieces khớp với nhau ra sao. Khi cần deep-dive từng file thì xem:
- [`docs/03-services-data.md`](../../docs/03-services-data.md) — db_loader, unit_converter, missing_ingredient, shopping_list
- [`docs/04-services-solver.md`](../../docs/04-services-solver.md) — CP-SAT, constraints, objective
- [`docs/09-unit-conversion.md`](../../docs/09-unit-conversion.md) — quy tắc GAM ↔ NUMBER chi tiết

---

## 0. Cấu trúc folder

```
services/
├── recommend.py          ← Orchestrator. Entry point của /recommend.
├── cp_sat_solver.py      ← Build & run CP-SAT model. Có relaxation ladder.
├── objective.py          ← Hàm mục tiêu (soft constraints): fridge use, expiry, shopping penalty.
├── constraints/          ← Hard constraints — mỗi file 1 file constraint riêng.
│   ├── structural.py     ← C1: số dish trên mỗi (ngày, bữa, role) phải đúng meal_structure.
│   ├── repetition.py     ← C2: 1 dish không lặp trong cửa sổ N+1 ngày + recentMealLog.
│   ├── calorie.py        ← C3: tổng calo/ngày ∈ [target-δ, target+δ].
│   └── macro.py          ← C4: protein/carb/fat per day theo goal (loss/maintain/gain).
├── missing_ingredient.py ← Stock walk: trừ fridge dần theo thứ tự (day, meal) → missing/dish.
├── shopping_list.py      ← Aggregate dedup missing toàn plan → shoppingList output.
├── unit_converter.py     ← Helper GAM ↔ NUMBER (dùng `number_to_gam` derived hoặc raw).
└── db_loader.py          ← Đọc data/*.json → populate cache. Chạy lúc app boot, KHÔNG gọi mỗi request.
```

---

## 1. Bird's-eye flow của `POST /recommend`

```
                         ┌─────────────────┐
   client (app/web)  ──► │  routes.py      │  ← validate Pydantic
                         │  recommend_…    │  ← lấy snapshot từ cache
                         └────────┬────────┘
                                  │ recommend(req, snapshot, no_repeat_days)
                                  ▼
                    ┌──────────────────────────────┐
                    │  recommend.py                │
                    │  (orchestrator — bộ não)     │
                    └──────────────────────────────┘
                                  │
   ┌──────────────────────────────┼─────────────────────────────────┐
   │                              │                                 │
   ▼                              ▼                                 ▼
 validate                   solve(SolveInput)                  hậu xử lý
 fridge / lock              ─────────────────                  ───────────
                            cp_sat_solver.py                   missing_ingredient
                                  │                            shopping_list
                                  ▼                            build_summary
                            relaxation loop:
                              build_model + run_solver
                                  │
                                  │ uses
                                  ▼
                       constraints/{structural,
                                    repetition,
                                    calorie,
                                    macro}.py
                       + objective.py
                                  │
                                  ▼
                           SolveResult{picks}
```

---

## 2. Trace request thật (đi từng bước)

### Bước 1 — Route nhận request
**File:** [`app/api/routes.py`](../api/routes.py) — `recommend_endpoint()`

- Pydantic validate input → nếu sai, FastAPI raise `RequestValidationError` → bị catch ở [`app/main.py`](../main.py) handler trả 200 + schema unified VN. Không vào tới services.
- Lấy snapshot cache (`cache.get()`). Nếu cache rỗng → return failed.
- Gọi `recommend(payload, snapshot, settings.no_repeat_days)`.

### Bước 2 — `recommend()` orchestrate
**File:** [`recommend.py`](recommend.py) — hàm `recommend()` ở cuối file.

```python
recommend(req, snapshot, no_repeat_days):
    _validate_fridge(req, valid_ing_ids)       # ingredient.id ∈ cache?
    _validate_locked_picks(req, snapshot)      # dish tồn tại + role khớp?
    candidate_dishes = snapshot.dishes         # keep all (kể cả món có gia vị ngoài 62-class)
    filtered_log = _drop_stale_meal_log(...)   # bỏ entry > no_repeat_days
    goal = classify_goal(req.goal.target_kg)   # weight_loss/maintain/weight_gain
    target_cpd = target_cal_per_day(...)       # tdee + targetKg×7700/7

    try:
        result = solve(SolveInput(...))        # ← CP-SAT
    except MealRecommenderError as exc:
        msg = _analyze_infeasibility(...)      # ← message tiếng Việt + gợi ý targetKg
        return MealPlanResponse(status="failed", message=msg, ...)

    plan = [_build_day_plan(d, ...) for d in range(plan_days)]
    compute_missing_per_dish(plan, fridge, ...)  # mutate plan in-place
    shopping = build_shopping_list(plan, ...)
    summary = _build_summary(plan, ...)

    return MealPlanResponse(status="success", plan=plan, summary=summary, shoppingList=shopping)
```

**Validations xảy ra trước solver** — nếu input bẩn, fail fast với message VN cụ thể, không tốn CPU solver.

### Bước 3 — `solve()` — vòng lặp relaxation
**File:** [`cp_sat_solver.py`](cp_sat_solver.py) — hàm `solve()`.

```
                ┌──────────────────────────────────┐
                │  _relax_schedule()               │  6 pass:
                │  yield (delta, window, macro_relax) │  100→200→300, window 2→1→0, ±15% macro
                └────────────┬─────────────────────┘
                             │ pass i
                             ▼
                ┌──────────────────────────────────┐
                │  _build_model(inp, …)            │
                │   ├─ _partition_by_role()        │
                │   ├─ _build_vars()  (BoolVar grid)│
                │   ├─ add_structural(C1)          │
                │   ├─ add_no_repeat_within_plan(C2)│
                │   ├─ add_recent_meal_log(C2 part)│
                │   ├─ add_calorie(C3)             │
                │   ├─ add_macro(C4)               │
                │   ├─ _apply_locked_picks()       │  (nếu có)
                │   └─ build_objective(soft)       │
                └────────────┬─────────────────────┘
                             │
                             ▼
                ┌──────────────────────────────────┐
                │  _run_solver()  (≤5s, 4 workers) │
                └────────────┬─────────────────────┘
                             │ status
        ┌────────────────────┼────────────────────────────────────┐
        ▼                    ▼                                    ▼
   OPTIMAL/FEASIBLE     INFEASIBLE                          UNKNOWN(timeout)
        │                    │                                    │
        ▼                    ▼                                    ▼
  _extract_picks()       pass tiếp                          pass tiếp (đếm timeout)
        │                    │                                    │
        ▼                    └─── hết schedule ──┐                ▼
  SolveResult                                    │       hết schedule + tất cả timeout
   ("success", picks)                            ▼                │
                                          SolverInfeasibleError    ▼
                                                          SolverTimeoutError
```

Status nào trả ra cũng bay về `recommend.py` rồi được map sang message VN qua `_analyze_infeasibility`.

### Bước 4 — Constraints (CP-SAT encoding)

| File | Ràng buộc | Encode kiểu |
|---|---|---|
| [`constraints/structural.py`](constraints/structural.py) | **C1** Số dish trên mỗi (day, meal, role) = `mealStructure[meal][role]` | Equality `Σ x = required` |
| [`constraints/repetition.py`](constraints/repetition.py) | **C2** 1 dish không xuất hiện 2 lần trong cửa sổ `N+1` ngày liên tiếp + bị block bởi `recentMealLog` | `Σ x_in_window ≤ 1` + force `x = 0` cho dish đã ăn gần đây |
| [`constraints/calorie.py`](constraints/calorie.py) | **C3** `target - δ ≤ Σ_meal Σ_role calories(dish) × x ≤ target + δ` cho từng ngày | 2 inequality / day |
| [`constraints/macro.py`](constraints/macro.py) | **C4** Protein g/kg/day, carb%, fat% theo `goal` | Integer scaling × nhân chéo (CP-SAT không chia số) |

Locked picks (replan flow): [`_apply_locked_picks()`](cp_sat_solver.py#L95) ép `x[d, meal, role, idx_of_locked_dish] == 1` — solver vẫn chạy đầy đủ C1-C4 nhưng phải tôn trọng lock.

### Bước 5 — Objective (soft score)
**File:** [`objective.py`](objective.py) — hàm `build_objective()`.

```
maximize  Σ over (d, m, r, i):
    + W_FRIDGE   × |ingredients_of(dish_i) ∩ fridge_ids|       ← S1: dùng tủ lạnh
    + W_EXPIRY   × urgency(ingredient)                          ← S2: ưu tiên sắp hết hạn
                   urgency = max(1, expiry_window - days_to_expire)
    − W_SHOPPING × |ingredients_of(dish_i) − fridge_ids|        ← S4: ít phải đi chợ
```

Trọng số đọc từ env (`WEIGHT_FRIDGE=3, WEIGHT_EXPIRY=5, WEIGHT_SHOPPING_PENALTY=3`). S3 (diversity) không cần — đã cover bởi C2.

### Bước 6 — Hậu xử lý (sau khi solver thành công)

```
SolveResult.picks      = { (day_idx, meal): [Dish, Dish, ...] }
                                │
                                ▼
   _build_day_plan(d, ...)      → tính dish-level entries + day-level nutrition
                                ▼
   plan: list[DayPlan]
                                │
                                ▼
   compute_missing_per_dish(plan, fridge, dishes_map, ingredients_map, derived_n2g)
   ─────────────────────────────
   stock = fridge converted to GAM
   for day in (sorted asc):
       for meal in (breakfast → lunch → dinner):
           for dish in slot:
               for ingredient in dish:
                   need = to_gam(...)
                   have = stock.get(id, 0)
                   if have ≥ need: stock -= need
                   else:
                       deficit = need - have
                       stock = 0
                       missing.append(deficit converted về unit gốc của công thức)
               dish.missing_ingredient = missing      ← MUTATE
                                │
                                ▼
   build_shopping_list(plan, ingredients_map)
   ─────────────────────────────
   gom mọi MissingIngredient từ plan, dedup theo (ingredient_id, unit),
   xử lý case mixed unit (cộng GAM + NUMBER × factor → quy về default_unit).
                                │
                                ▼
   _build_summary(plan, tdee, targetKg, planDays)
   ─────────────────────────────
   avgDailyCalories/Protein/Carb/Fat,
   targetCalories = (tdee + daily_delta) × planDays   (§15 #6)
   deviation = (total_cal - target_total) / target_total
                                │
                                ▼
   MealPlanResponse(status="success", plan, summary, shoppingList)
```

### Bước 7 — Khi solver fail → message + gợi ý targetKg
**File:** [`recommend.py`](recommend.py) — `_analyze_infeasibility()`.

Heuristic chọn message theo thứ tự:
1. `SolverTimeoutError` → "Hệ thống tính toán vượt thời gian..."
2. Pool dish thiếu cho 1 role nào đó (vd `mealStructure.lunch.soup=1` mà DB chỉ có 0 soup) → "chỉ có X canh trong database nhưng cấu trúc cần Y..."
3. Calorie target ngoài `[total_min - 300, total_max + 300]` → "Calo mục tiêu cao/thấp hơn pool" + **gợi ý targetKg cụ thể** từ `_suggest_target_kg`
4. Có `lockedPicks` → "Đã pin N món... tạo xung đột"
5. Fallback (macro/no-repeat) → "Không tìm được kế hoạch..." + gợi ý targetKg

**Gợi ý targetKg** (`_suggest_target_kg`): tính khoảng calo khả thi từ pool, quy đổi ngược về targetKg (kg/tuần), clamp [-0.5, 0.5], round 0.1 theo chiều an toàn (≠ vượt biên). Ví dụ user muốn `-0.5` mà pool chỉ cho phép tối đa deficit `-0.3` → gợi ý `"giảm 0.3 kg/tuần"`.

---

## 3. Workflow phụ — Boot service / load data

**Khi nào chạy?** 1 lần lúc app start (FastAPI lifespan hook ở [`app/main.py`](../main.py)).

```
uvicorn app.main:app
        │
        ▼
   _lifespan()  ─── async startup
        │
        ▼
   load_from_local_files()   ← db_loader.py
        │
        ├─ đọc data/Dish.json, ingredient.json, DishIngredient.json
        ├─ Pydantic TypeAdapter validate (list[Dish], list[Ingredient], list[DishIngredientRow])
        ├─ _validate_cross_refs()   max_ingredient_classes, dishId/ingredientId tồn tại
        ├─ _merge_dish_ingredients()  group rows theo dishId → dish.ingredients[]
        ├─ _compute_nutrition()       dish.protein/carb/fat từ ingredient × gramsEquivalent/100
        ├─ _apply_default_meal_types()  SOUP→[lunch,dinner]; MAIN_DISH/VEGETABLE→[all 3]
        └─ _derive_number_to_gam()    suy NUMBER→GAM từ junction (mỗi dòng có cả số NUMBER + gramsEquivalent)
        │
        ▼
   get_cache().replace(dishes, ingredients, derived_n2g)
        │
        ▼
   service ready, /recommend dùng được
```

Không có endpoint `/update-db` — data bundle trong git, deploy = git push (xem [`docs/08-deploy-render.md`](../../docs/08-deploy-render.md)).

---

## 4. Module tương tác với nhau ra sao

```
   ┌──────────────────────────────────────────────────────┐
   │                    recommend.py                      │
   │            (orchestrator — biết về mọi thứ)         │
   └──┬─────────┬───────────┬──────────────┬──────────────┘
      │         │           │              │
      │         │           │              │
      ▼         ▼           ▼              ▼
 cp_sat_     missing_    shopping_     unit_converter.py
 solver.py   ingredient. list.py       (helper, dùng bởi missing
      │     py│ ▲           ▲             & shopping)
      │       │ │           │
      │       └─┘ depends ──┘
      │
      ▼ uses
 ┌─────────────────┬──────────────┐
 │ constraints/*.py│ objective.py │
 └─────────────────┴──────────────┘
```

- **db_loader** đứng riêng: chỉ chạy lúc boot, sau đó cache là source of truth.
- **unit_converter** không phụ thuộc gì khác — pure utility, an toàn để test isolated.
- **constraints/** không gọi nhau — đều nhận `model`, `x`, dish list rồi `model.add(...)`. Side-effect-only.
- **objective** tương tự — chỉ thêm term vào `model.maximize()`.
- **cp_sat_solver** tổ chức build_model + relax loop, không biết về fridge/missing/shopping (đó là việc của recommend.py).

---

## 5. Khi muốn sửa code, đụng vào đâu?

| Yêu cầu thay đổi | File chính cần đụng |
|---|---|
| Thêm 1 hard constraint mới (vd "không lặp protein source") | Tạo `constraints/protein_source.py`, gọi từ `_build_model` |
| Đổi cách tính calorie target / macro range | [`app/utils/nutrition.py`](../utils/nutrition.py) |
| Đổi trọng số / thêm soft constraint | [`objective.py`](objective.py) + env vars trong [`config.py`](../core/config.py) |
| Đổi nghiệp vụ NUMBER↔GAM, tolerance shortfall | [`unit_converter.py`](unit_converter.py), [`missing_ingredient.py`](missing_ingredient.py) |
| Đổi message lỗi VN / suggestion logic | [`recommend.py`](recommend.py) — `_analyze_infeasibility`, `_suggest_target_kg` |
| Đổi format output (shape MealPlanResponse) | [`app/models/output.py`](../models/output.py) — schema | rồi update `_build_day_plan`, `_build_summary` trong `recommend.py` |
| Thêm endpoint mới | [`app/api/routes.py`](../api/routes.py) — KHÔNG đụng services trừ khi cần logic mới |

---

## 6. Vài invariant quan trọng để khỏi nhớ sai

- **Plan chạy theo thứ tự thời gian** trong `compute_missing_per_dish` — ngày 1 breakfast trừ trước ngày 1 lunch. Nếu sort sai, missing/shoppingList sai số.
- **Solver internal dùng GAM**, **output giữ unit gốc của công thức** (`MissingIngredient.unit` = `dish_ingredient.unit`, không phải GAM). Đừng "đơn giản hóa" về GAM hết.
- **`dish.calories` trust backend** (đã factor yield/retention). Service chỉ tự tính protein/carb/fat từ ingredient × `gramsEquivalent / 100`.
- **Ingredient ngoài 62-class** (gia vị, vd quế hồi) được phép xuất hiện trong `dish_ingredients`. Service skip nó trong nutrition / stock / shopping (xem `_compute_nutrition`, `compute_missing_per_dish`). Fridge thì KHÔNG được phép — fridge ingredient phải ∈ whitelist (asymmetric — chốt 2026-04-25).
- **Locked picks không bypass C1-C4** — chỉ thêm equality `x == 1` cho slot pinned, sau đó solver phải tìm dish khác cho slot còn lại sao cho cả gói vẫn thỏa C1-C4. Nếu lock + macro strict không feasible → relaxation ladder vẫn nới calo/macro nhưng lock luôn giữ.
- **Mọi error của /recommend trả HTTP 200** + `MealPlanResponse(status="failed", message="<VN>", plan=[], summary=null, shoppingList=[])` — chốt với team app 2026-05-08, override §15 #5 cũ.
