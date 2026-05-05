# 03 — Services: Data layer

Các service "plumbing" — tải dữ liệu, convert đơn vị, tính deficit, gom shopping list.
Không đụng đến CP-SAT.

## [`db_loader.py`](../app/services/db_loader.py) — Download + validate + merge backend JSON

Được gọi bởi `POST /update-db`. Từ 2026-04-24 nhận **3 URL** thay vì 2.

**Flow**:
```
dishes_url, ingredients_url, dish_ingredients_url
        │
        ▼
httpx.AsyncClient.get() × 3  (timeout 30s, raise_for_status)   ← DBLoadError
        │
        ▼
resp.json() × 3                                                  ← DBLoadError
        │
        ▼
TypeAdapter validate:
  list[Dish]              (flat: id, name, type, calories)
  list[Ingredient]        (flat: id, name, unit, numberToGam, protein/carb/fat per 100g)
  list[DishIngredientRow] (junction: dishId, ingredientId, amount, gramsEquivalent, unit)
        │
        ▼
_validate_cross_refs()
  • len(ingredients) ≤ 62 → else DBLoadError
  • dishIngredients.dishId phải ∈ dishes → else DBLoadError
  • dishIngredients.ingredientId phải ∈ ingredients → else DBLoadError
        │
        ▼
_merge_dish_ingredients()  group rows by dishId → dish.ingredients[]
        │
        ▼
_compute_nutrition()       dish.nutrition_per_serving:
                             calories = dish.calories (trust backend)
                             protein  = Σ ing.protein × grams_equivalent / 100
                             carb/fat = tương tự
        │
        ▼
_apply_default_meal_types()  SOUP → lunch+dinner; MAIN_DISH/VEGETABLE → all 3
        │
        ▼
return (dishes, ingredients, rows_count)
```

Route `backup_to_disk()` ghi `data/dishes.json` + `data/ingredients.json` (gitignored)
để debug. Junction bị drop khỏi backup vì đã merge vào dish.

**Vì sao compute nutrition ở service chứ không backend?**
Backend DB chỉ có `calories` per dish, còn `protein/carb/fat` chỉ có ở level ingredient.
Thay vì backend phải JOIN + SUM lúc export, service tự làm (nhanh, làm 1 lần lúc
/update-db, cache cho mọi /recommend sau đó). Chi tiết §4.5 trong CLAUDE.md.

**Vì sao `TypeAdapter` thay vì `BaseModel.model_validate()`?**
Input là `list[Dish]`, không phải một `Dish`. `TypeAdapter` validate được collection.

## [`unit_converter.py`](../app/services/unit_converter.py) — GAM ↔ NUMBER

Quy tắc chốt (§15 #2): **nội bộ luôn so sánh bằng GAM**. Output **giữ đơn vị gốc** của
công thức dish.

```python
to_gam(quantity, unit, ingredient) → float     # GAM hoặc raise
from_gam(quantity_gam, unit, ingredient)       # convert ngược (ceil nếu NUMBER)
```

**Logic `to_gam`**:
| Input | Xử lý |
|---|---|
| `unit=GAM` | passthrough |
| `unit=NUMBER`, có `number_to_gam` | `quantity × factor` |
| `unit=NUMBER`, `number_to_gam=None` | `InvalidIngredientError` |

Ví dụ: 2 quả trứng, `NUMBER_TO_GAM = 55` → 110 GAM.

**Logic `from_gam` (dùng cho missing/shopping)**:
- `GAM` → passthrough.
- `NUMBER` → `ceil(quantity_gam / factor)` (không ai mua được 1.3 quả trứng).

## [`missing_ingredient.py`](../app/services/missing_ingredient.py) — Stock walk

Sau khi solver chọn dish cho từng bữa, cần tính "dish này cần mua gì?" có tính đến:
- Nguyên liệu sẵn trong fridge.
- Các dish **chạy trước** đã dùng bao nhiêu.

Mutate `plan` in-place — set field `missing_ingredient` cho từng `MealDishEntry`.

**Thuật toán**:
```
stock = fridge converted to GAM (tổng theo ingredient_id)

cho từng ngày (asc), từng bữa (breakfast → lunch → dinner), từng dish trong bữa:
    missing = []
    cho từng ingredient của dish:
        need  = to_gam(dish.quantity, dish.unit, ingredient_meta)
        have  = stock.get(ingredient_id, 0)

        nếu have ≥ need:
            stock[id] = have - need              ← trừ dần
        nếu không:
            deficit_gam = need - have
            stock[id] = 0
            # Convert deficit về đơn vị GỐC của công thức (NUMBER giữ NUMBER)
            missing.append(MissingIngredient(ingredientId, unit=RECIPE.unit, quantity))

    dish.missing_ingredient = missing
```

**Tại sao trừ theo thứ tự thời gian?**
Nếu ngày 1 breakfast đã dùng hết 4 quả trứng → ngày 1 lunch phải thấy stock = 0.

**Edge case**:
- Công thức yêu cầu `unit=NUMBER` nhưng ingredient không có `NUMBER_TO_GAM` → không
  compare được GAM → raise `InvalidIngredientError`.

## [`shopping_list.py`](../app/services/shopping_list.py) — Aggregate deficit

Sau khi mọi dish đã có `missing_ingredient`, gom toàn plan thành 1 shopping list:

```
totals: {ingredient_id: {GAM: float, NUMBER: float}}

cho từng DayPlan → từng bữa → từng dish → từng MissingIngredient:
    totals[id][unit] += quantity

cho từng ingredient:
    CASE 1: chỉ GAM      → emit (id, ceil(gam), GAM)
    CASE 2: chỉ NUMBER   → emit (id, int(num), NUMBER)
    CASE 3: cả hai       → quy về default_unit của ingredient:
        • default=NUMBER + có factor: total_gam / factor rồi ceil → NUMBER
        • default=GAM + có factor:    tổng gam (cộng gam thu được từ NUMBER) → GAM
        • không có factor:            emit 2 dòng riêng (GAM + NUMBER)

sort theo ingredient_id
```

**Ví dụ**:
- Dish A thiếu 2 trứng (NUMBER).
- Dish B thiếu 55g trứng (GAM, một công thức nào đó ghi theo khối lượng).
- `ingredient.defaultUnit = NUMBER`, `NUMBER_TO_GAM = 55`.
- → Tổng = 2 × 55 + 55 = 165g → `ceil(165 / 55) = 3 quả`.
- ShoppingItem: `{ingredientId: 2, quantity: 3, unit: NUMBER}`.

## Sơ đồ tương tác

```
   fridge[FridgeItem]
       │
       │  to_gam()
       ▼
   stock: {id → gam}  ─────────┐
                                │ consume dần
   plan[DayPlan]  ──────────────┤
       │                        ▼
       │     compute_missing_per_dish()
       │           mutate plan in-place
       │
       │     build_shopping_list()
       └─────────▶ list[ShoppingItem]  ──→ MealPlanResponse.shoppingList
```
