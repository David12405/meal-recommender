# 04 — Services: Solver (tim của service)

Đây là phần khó nhất. Đọc [`05-utils.md`](05-utils.md) trước (công thức dinh dưỡng) sẽ dễ hơn.

## Ý tưởng tổng quát

Bài toán: **chọn dish nào cho mỗi (ngày, bữa, role)** sao cho thỏa hard constraint và tối đa soft score.

Mã hóa thành CP-SAT bằng **biến nhị phân**:

```
x[d, meal, role, i] ∈ {0, 1}

 = 1  ↔  chọn dish thứ i (trong ứng viên role r) cho ngày d bữa meal
```

4 hard constraints (C1–C4) + 1 hàm mục tiêu (maximize soft score) → solver ra nghiệm.

## Ứng viên dish

`SolveInput.candidate_dishes` = `snapshot.dishes` nguyên xi. Dish được phép reference
ingredient ngoài 62-class whitelist (vd gia vị: quế, hồi, ngũ vị hương…) — những
ingredient đó sẽ bị skip trong nutrition/stock/shopping logic, coi như user tự túc.

Trong `cp_sat_solver._partition_by_role()` chia thành:
```
dishes_by_role = { MAINDISH: [...], SOUP: [...], VEGETABLE: [...] }
```

Index `i` trong `x[d, meal, role, i]` là index trong list của role đó.

## Biến hóa thành biến nhị phân — `_build_vars()`

```python
for d in range(plan_days):
    for meal in (breakfast, lunch, dinner):
        for role in (MAINDISH, SOUP, VEGETABLE):
            for i, dish in enumerate(dishes_by_role[role]):
                var = model.NewBoolVar(...)
                x[(d, meal, role, i)] = var
                if meal not in dish.meal_types:
                    model.Add(var == 0)        # không hợp lệ cho bữa này → bắt = 0
```

Số biến ≈ `plan_days × 3 × 3 × |candidates|`. Với 500 dish, 7 ngày → ~31,500 biến. CP-SAT
xử lý thoải mái.

## C1 — Structural [`constraints/structural.py`](../app/services/constraints/structural.py)

Mỗi (ngày, bữa, role) phải chọn ĐÚNG `required` dish.

```
∀ d, meal, role:  Σᵢ x[d, meal, role, i] == mealStructure[meal][role]
```

Ví dụ lunch cần 1 main + 1 soup + 1 veg → 3 equality constraint/ngày/bữa.

## C2 — No-repeat [`constraints/repetition.py`](../app/services/constraints/repetition.py)

Một dish không lặp trong cửa sổ `N+1` ngày liên tiếp (default N=2).

```python
for dish_id:
    per_day_vars[d] = [tất cả var cho dish này ngày d]

    nếu window+1 ≥ plan_days:
        # plan ngắn → mỗi dish nhiều nhất 1 lần trong cả plan
        model.Add(sum(flat) <= 1)
    else:
        for start in 0 .. plan_days - window:
            window_vars = per_day_vars[start .. start+window]
            model.Add(sum(window_vars) <= 1)
```

**`recentMealLog`**: dish đã ăn trong `[startDate - window, startDate)` bị ép = 0 cho
các ngày đầu của plan. Entry cũ hơn `window` ngày thì bỏ qua (§15 #4).

## C3 — Calorie [`constraints/calorie.py`](../app/services/constraints/calorie.py)

**Per-day constraint** — mỗi ngày trong plan đều phải nằm trong khoảng `target ± δ`,
không phải tổng cả plan. Phân phối calo đều qua các ngày để tránh trường hợp ngày đói
ngày bội thực.

```python
target_int = round(tdee + daily_delta)        # 1 con số áp dụng cho mọi ngày

for d in range(plan_days):                    # ← ràng buộc lặp cho TỪNG ngày
    cal_d = Σ_{m,r,i} x[d, m, r, i] × dish.calories
    model.Add(cal_d >= target_int - DELTA)
    model.Add(cal_d <= target_int + DELTA)
```

- `target_cal_per_day = tdee + daily_delta` với `daily_delta = targetKg × 7700 / 7` (§15 #6 chốt).
- `DELTA` mặc định 100 kcal, sẽ được nới dần ở relaxation ladder (200 → 300).
- `summary.targetCalories` ở response = `target_cal_per_day × planDays` (cộng dồn cho user xem dễ), KHÔNG phải là ràng buộc tổng plan.

## C4 — Macro [`constraints/macro.py`](../app/services/constraints/macro.py) — trick integer scaling

Vấn đề: CP-SAT chỉ làm việc với integer. Mà ràng buộc là:
```
carb_pct_min ≤ (4 × carb_g) / cal_d ≤ carb_pct_max       (carb 4 kcal/g)
fat_pct_min  ≤ (9 × fat_g)  / cal_d ≤ fat_pct_max        (fat 9 kcal/g)
```

Có **chia**. Giải quyết bằng **nhân chéo**:
```
carb_pct_min × 100 × cal_d ≤ 4 × 100 × carb_g ≤ carb_pct_max × 100 × cal_d
```

Protein dùng grams/kg trực tiếp (không cần pct), scale ×10 để giữ 0.1 g resolution:
```
1.2 g/kg × 68 kg × 10 = 816   ≤  Σ protein × 10  ≤  1.6 × 68 × 10 = 1088
```

**`relax_pct`**: khi pass 6 của relaxation, range được nới ±15% để tăng khả năng giải được.

**Goal ảnh hưởng range**:
```python
classify_goal(targetKg):
    < -0.1  → weight_loss   (protein 1.6-2.2, carb 45-55%, fat 20-30%)
    ≥  0.1  → weight_gain   (protein 1.4-2.0, carb 50-60%, fat 20-30%)
    else    → maintain      (protein 1.2-1.6, carb 45-60%, fat 25-35%)
```

## Objective [`objective.py`](../app/services/objective.py) — soft score

Maximize tổng:
```
S1 (fridge):  + W_FRIDGE mỗi ingredient của dish có trong fridge
S2 (expiry):  + W_EXPIRY × urgency nếu ingredient đó sắp hết hạn (≤ 2 ngày)
                 urgency = max(1, 3 - days_to_expire)
S4 (penalty): - W_SHOPPING mỗi ingredient của dish KHÔNG có trong fridge
```

→ Solver sẽ ưu tiên dish dùng nhiều ingredient sẵn có + sắp hết hạn.

S3 (diversity) bỏ qua — đã cover bởi C2 no-repeat window.

## Build + Solve + Relax — [`cp_sat_solver.py`](../app/services/cp_sat_solver.py)

Hàm `solve(SolveInput)`:

```
for (calorie_delta, window, macro_relax, note) in _relax_schedule():
    model, x, dishes_by_role = _build_model(inp, calorie_delta, window, macro_relax, weights)
    status = solver.Solve(model)

    match status:
        OPTIMAL | FEASIBLE → extract picks → return SolveResult("success")
        MODEL_INVALID     → SolverInfeasibleError (bug)
        UNKNOWN (timeout) → retry 1 lần; nếu vẫn UNKNOWN → SolverTimeoutError
        INFEASIBLE        → tiếp pass sau

raise SolverInfeasibleError
```

### Relaxation ladder (§7.1)

| Pass | Thay đổi | Ý nghĩa |
|---|---|---|
| 1 | mặc định (delta=100, window=2) | strict |
| 2 | delta=200 | nới calo |
| 3 | delta=300 | |
| 4 | window=1 | cho phép lặp gần hơn |
| 5 | window=0 | không no-repeat |
| 6 | macro±15% | nới protein/carb/fat |
| — | fail → `status: "failed"` | |

Relax **không** được expose ra response (schema không có `warnings[]`), chỉ log.

### Solver config

```python
solver.parameters.max_time_in_seconds = 5.0
solver.parameters.num_search_workers = 4
solver.parameters.random_seed = hash(user_id) % 2³¹   # cùng user → kế hoạch ổn định
```

## Extract picks

```python
for (d, meal, role, i) nếu solver.Value(x[key]) == 1:
    picks[(d, meal)].append(dishes_by_role[role][i])
```

Trả về `SolveResult(picks, status, relax_notes)`.

## [`recommend.py`](../app/services/recommend.py) — Orchestrator

Ghép mọi thứ lại, là entry point của route `/recommend`.

```
recommend(req, snapshot, no_repeat_days):

    1. _validate_fridge()              → 400 nếu ingredient lạ
    2. candidate_dishes = snapshot.dishes (keep all, kể cả món chứa gia vị ngoài 62-class)
    3. _drop_stale_meal_log()          → §15 #4
    4. classify_goal() + target_cal_per_day()
    5. solve(SolveInput(...))          → SolveResult hoặc raise
    6. _build_day_plan() × plan_days   → tính nutrition/ngày
    7. compute_missing_per_dish()      → điền missingIngredient
    8. build_shopping_list()
    9. _build_summary()                → avgDaily*, targetCalories, deviation

    nếu solver raise MealRecommenderError → return MealPlanResponse(status="failed")
```

## Sơ đồ 1 pass solve

```
SolveInput ──► _build_model:
                  ├── _build_vars (31k BoolVar)
                  ├── add_structural   C1
                  ├── add_no_repeat    C2 (+ recent meal log exclusion)
                  ├── add_calorie      C3
                  ├── add_macro        C4
                  └── build_objective  S1+S2+S4  (Maximize)
                       │
                       ▼
                  model
                       │
                       ▼
              _run_solver (timeout 5s, 4 workers)
                       │
      ┌────────────────┼──────────────────────┐
      ▼                ▼                      ▼
  OPTIMAL/FEASIBLE  INFEASIBLE            UNKNOWN
      │               │                      │
      ▼               ▼                      ▼
 _extract_picks  pass tiếp             retry 1 lần
      │
      ▼
  SolveResult("success", picks={(day, meal): [Dish]})
```
