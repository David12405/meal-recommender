# 07 — Replan flow (lockedPicks)

> **Status**: ✅ implemented 2026-04-29. Tests 18/18 pass. Demo end-to-end working (xem [scripts/demo.py](../scripts/demo.py) phần 7-9).

## Use case

User nhận plan từ `/recommend`, sau đó muốn đổi 1 món tại 1 slot cụ thể (ví dụ: lunch ngày 3, MAINDISH từ "Thịt kho tàu" → "Cá thu kho"). App gọi lại `/recommend` với field `lockedPicks` để báo:
- Những slot đã "ăn" → giữ nguyên.
- Slot user vừa đổi → áp dish mới.
- Slot còn lại → solver tự re-solve.

## Tại sao gọi lại `/recommend` chứ không phải endpoint mới?

Quyết định **(b)** — extend endpoint hiện tại với field optional `lockedPicks`. Lý do:
- Backward compat: request không có `lockedPicks` chạy y như cũ.
- App side gọn — 1 endpoint, 1 logic flow.
- Server side gọn — 1 file routes, 1 hàm `recommend()`.

## Schema bổ sung — `lockedPicks`

Đã thêm vào `RecommendRequest` (xem [CLAUDE.md §3.1](../CLAUDE.md)):

```jsonc
"lockedPicks": [
  {
    "day": 3,                    // int [1, planDays]
    "meal": "lunch",             // enum: "breakfast" | "lunch" | "dinner"
    "role": "MAINDISH",          // enum: "MAINDISH" | "SOUP" | "VEGETABLE"
    "dishId": 112                // int — phải có trong cache dishes
  }
]
```

**Validation rules** (đã implement):

| Field | Rule | Tầng | Mã lỗi |
|---|---|---|---|
| `lockedPicks` | optional, default `[]` | Pydantic | — |
| `lockedPicks[].day` | int, [1, 14] | Pydantic field | 422 |
| `lockedPicks[].day ≤ planDays` | cross-field | `@model_validator` | 422 |
| `lockedPicks[].meal` | enum `breakfast \| lunch \| dinner` | Pydantic | 422 |
| `lockedPicks[].role` | enum `MAINDISH \| SOUP \| VEGETABLE` | Pydantic | 422 |
| `lockedPicks[].dishId` | int — tồn tại trong cache | `_validate_locked_picks` (orchestrator) | 400 |
| Role của dish khớp `role` field | dish.role == lp.role | `_validate_locked_picks` | 400 |
| `(day, meal, role)` unique | không lock 2 dish cho cùng slot-role | `@model_validator` | 422 |
| Số lock cho `(meal, role)` ≤ `mealStructure[meal][role]` | capacity | `@model_validator` | 422 |

## Schema response

**Không đổi** — vẫn là `MealPlanResponse` y hệt `/recommend` thường:
- `plan[]` reflect đúng tất cả locked picks (echo back).
- Day chỉ một phần locked + phần solver fill thì plan của day đó là sự kết hợp.
- `summary` tính trên TOÀN plan (cả locked + re-solved).
- `missingIngredient` và `shoppingList` được tính lại trên toàn plan, không chỉ phần re-solved.

## Mẫu request/response

- [`mock_data/sample_replan_request.json`](../mock_data/sample_replan_request.json) — input với 21 locked picks (day 1, 2 toàn bộ + day 3 breakfast + day 3 lunch với swap)
- [`mock_data/sample_replan_response.json`](../mock_data/sample_replan_response.json) — output 5 ngày, day 3 dinner + day 4 + day 5 là phần solver re-solve

## Files đã sửa khi implement

| File | Thay đổi | Lines |
|---|---|---|
| [app/models/input.py](../app/models/input.py) | Thêm `LockedPick` model + field `RecommendRequest.locked_picks` + `@model_validator` cho 3 cross-field rules (day range, uniqueness, capacity) | +60 |
| [app/services/cp_sat_solver.py](../app/services/cp_sat_solver.py) | `SolveInput.locked_picks` field + hàm `_apply_locked_picks` ép `x[d,m,r,idx] == 1` cho mỗi locked pick, gọi từ `_build_model` | +30 |
| [app/services/recommend.py](../app/services/recommend.py) | `_validate_locked_picks` (cache existence + role match), pass `locked_picks` xuống solver | +20 |
| [app/models/domain.py](../app/models/domain.py) | **Bug fix**: `Dish.meal_types` thiếu alias `mealTypes` → backend JSON bị silent ignore khi parse. Thêm `alias="mealTypes"`. Phát hiện khi chạy demo — dish 401-412 (mealTypes=["breakfast"]) bị bỏ qua, solver đặt vào lunch/dinner. | +1 |
| [CLAUDE.md §3.1](../CLAUDE.md) | Bổ sung schema `lockedPicks` + bảng validation | +14 |
| [scripts/demo.py](../scripts/demo.py) | Phần 7-9 mới: simulate user swap → build lockedPicks → call /recommend với lockedPicks → in bảng so sánh trước/sau | +120 |

## Logic implementation

### 1. Pydantic validation ([input.py](../app/models/input.py))

```python
class LockedPick(BaseModel):
    day: int = Field(ge=1, le=14)
    meal: MealType
    role: Role
    dish_id: int = Field(alias="dishId")


class RecommendRequest(BaseModel):
    # ... fields cũ ...
    locked_picks: list[LockedPick] = Field(default_factory=list, alias="lockedPicks")

    @model_validator(mode="after")
    def _check_locked_picks(self):
        # 1. day ≤ planDays
        # 2. (day, meal, role) unique
        # 3. số lock cho slot ≤ mealStructure[meal][role]
        ...
```

### 2. Cache-level validation ([recommend.py](../app/services/recommend.py))

```python
def _validate_locked_picks(req, snapshot):
    for lp in req.locked_picks:
        dish = snapshot.dishes_by_id.get(lp.dish_id)
        if dish is None:
            raise InvalidIngredientError(f"lockedPicks dishId={lp.dish_id} không có trong cache")
        if dish.role != lp.role:
            raise InvalidIngredientError(f"role mismatch: dish.role={dish.role} != lp.role={lp.role}")
```

### 3. Lock vars trong CP-SAT ([cp_sat_solver.py](../app/services/cp_sat_solver.py))

```python
def _apply_locked_picks(model, x, dishes_by_role, locked_picks):
    for lp in locked_picks:
        idx = next(i for i, d in enumerate(dishes_by_role[lp.role]) if d.dish_id == lp.dish_id)
        d_idx = lp.day - 1   # 1-indexed → 0-indexed
        model.Add(x[(d_idx, lp.meal, lp.role, idx)] == 1)
```

Các dish khác cùng `(d, meal, role)` tự bị ép `== 0` vì C1 (structural) yêu cầu `sum == required`.

### 4. Stock tracking lúc compute missingIngredient

Locked picks đã có trong plan → `compute_missing_per_dish` walk theo thứ tự `(day, meal)` deduct stock như bình thường. **Không cần code thêm.**

### 5. Relaxation ladder

Nếu lock + macro/calorie strict không feasible → relax như `/recommend` thường. Locked picks **vẫn giữ** trong mọi pass (chỉ delta calo + macro range được nới).

### 6. C2 no-repeat

Locked picks `x == 1` được counted vào sum của C2 (no-repeat trong cửa sổ N+1 ngày). Tự động xử lý đúng — không cần augment `recentMealLog`. Ví dụ:
- Lock dish X tại day 1 lunch.
- Window=2 → C2 sliding window [day 1-3]: `x[X day 1] + x[X day 2] + x[X day 3] ≤ 1` ⇒ X bị ép không xuất hiện day 2-3 (đúng yêu cầu).

## Demo flow ([scripts/demo.py](../scripts/demo.py))

```
Phần 1-6: chạy /recommend bình thường, in plan + shopping list (như cũ)
Phần 7  : "user swap" — hardcoded chọn day 3 lunch MAINDISH, pick 1 dish khác chưa có trong plan
Phần 8  : build lockedPicks (slot trước swap + slot có swap đã apply) → POST /recommend
Phần 9  : bảng so sánh trước/sau với status:
            • lock     — nằm trong lockedPicks
            • SWAP     — slot user đổi
            • RESOLVE  — solver chọn dish khác cũ
            • kept     — solver chọn TRÙNG dish cũ (may mắn / objective convergence)
```

Run: `python scripts/demo.py` → step qua từng phần.

## Edge cases đã handle

| Tình huống | Behavior |
|---|---|
| `lockedPicks=[]` hoặc bỏ field | Flow `/recommend` cũ, không thay đổi gì |
| `dishId` không tồn tại trong cache | 400 — `InvalidIngredientError` |
| `role` không khớp với `dish.role` | 400 — `InvalidIngredientError` |
| `day > planDays` | 422 — Pydantic `@model_validator` |
| `(day, meal, role)` duplicate | 422 — Pydantic `@model_validator` |
| Lock 2 SOUP cho lunch khi `mealStructure.lunch.soup=1` | 422 — Pydantic `@model_validator` |
| Lock + strict macro infeasible | Relaxation ladder (delta calo lên 200/300, sau đó macro±15%); locked picks giữ nguyên |
| Lock + macro±15% vẫn infeasible | 200 + `status: "failed"` (như `/recommend` thường) |
| Lock dish ngoài candidate pool sau filter | `SolverInfeasibleError` (đáng lẽ phải bị reject ở `_validate_locked_picks`) |

## Đã chốt với user (2026-04-29)

| Decision | Lựa chọn |
|---|---|
| Endpoint | **(b)** extend `/recommend` với optional `lockedPicks` |
| Format | **(X)** explicit `lockedPicks` list — client tự build |
| Khi infeasible | **(b)** auto-relax (relaxation ladder như /recommend) |
| no-repeat + fridge tracking | Giữ — locked picks tham gia C2 và stock |

## Tổng effort thực tế

~1.5h như spec dự đoán + 15 phút bug fix `mealTypes` alias regression phát hiện qua demo.

## Cách app team sử dụng

```javascript
// Helper: build lockedPicks từ current plan + swap target
function buildLockedPicks(currentPlan, swapTarget) {
  const mealOrder = { breakfast: 0, lunch: 1, dinner: 2 };
  const locked = [];
  for (const day of currentPlan) {
    for (const mealName of ['breakfast', 'lunch', 'dinner']) {
      const afterSwap =
        day.day > swapTarget.day ||
        (day.day === swapTarget.day && mealOrder[mealName] > mealOrder[swapTarget.meal]);
      if (afterSwap) continue;
      for (const entry of day.meals[mealName]) {
        const isSwapped =
          day.day === swapTarget.day &&
          mealName === swapTarget.meal &&
          entry.role === swapTarget.role;
        locked.push({
          day: day.day,
          meal: mealName,
          role: entry.role,
          dishId: isSwapped ? swapTarget.newDishId : entry.dishId,
        });
      }
    }
  }
  return locked;
}

// Khi user tap "Xác nhận" swap:
const lockedPicks = buildLockedPicks(currentPlan, {
  day: 3, meal: 'lunch', role: 'MAINDISH', newDishId: 456
});
const response = await axios.post('/recommend', { ...originalRequest, lockedPicks });
```

Tham khảo Python implementation: [`_build_locked_picks_for_swap` trong scripts/demo.py](../scripts/demo.py).
