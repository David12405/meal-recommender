from __future__ import annotations

import math

from app.core.config import get_settings
from app.core.exceptions import InvalidIngredientError
from app.models.domain import Dish, Ingredient
from app.models.enums import MEAL_TYPES, Unit
from app.models.input import FridgeItem
from app.models.output import DayPlan, MissingIngredient
from app.services.unit_converter import to_gam


def _initial_stock_gam(
    fridge: list[FridgeItem],
    ingredients_map: dict[int, Ingredient],
    derived_number_to_gam: dict[int, float] | None = None,
) -> dict[int, float]:
    stock: dict[int, float] = {}
    for f in fridge:
        meta = ingredients_map.get(f.ingredient_id)
        if meta is None:
            raise InvalidIngredientError(
                f"Tủ lạnh chứa nguyên liệu không xác định "
                f"(id={f.ingredient_id}). Vui lòng kiểm tra lại."
            )
        stock[f.ingredient_id] = stock.get(f.ingredient_id, 0.0) + to_gam(
            f.quantity, f.unit, meta, derived_number_to_gam
        )
    return stock


def compute_missing_per_dish(
    plan: list[DayPlan],
    fridge: list[FridgeItem],
    dishes_map: dict[int, Dish],
    ingredients_map: dict[int, Ingredient],
    derived_number_to_gam: dict[int, float] | None = None,
) -> None:
    """Mutate `plan` in-place: populate `missingIngredient` on every MealDishEntry.

    Walks meals in (day asc, breakfast→lunch→dinner) order, deducting from a shared
    stock (in GAM). Per §15 #2: output quantity is expressed in the *dish recipe's*
    original unit, not GAM.

    Áp dụng `ingredient_shortfall_tolerance` (default 15%): thiếu trong ngưỡng này
    không vào shopping (real-world hao hụt — user không cân chính xác đến gram).

    `derived_number_to_gam`: map suy từ junction để convert NUMBER ↔ GAM mà không
    cần ingredient.numberToGam (xem db_loader._derive_number_to_gam).
    """
    stock = _initial_stock_gam(fridge, ingredients_map, derived_number_to_gam)
    tolerance = get_settings().ingredient_shortfall_tolerance

    for day in sorted(plan, key=lambda p: p.day):
        meals = day.meals
        for meal_name in MEAL_TYPES:
            slot = getattr(meals, meal_name.value)
            for dish_entry in slot:
                dish = dishes_map.get(dish_entry.dish_id)
                if dish is None:
                    raise InvalidIngredientError(
                        f"Kế hoạch tham chiếu món ăn không tồn tại "
                        f"(dishId={dish_entry.dish_id}). Lỗi nội bộ, "
                        f"vui lòng thử lại."
                    )
                missing: list[MissingIngredient] = []
                for ing in dish.ingredients:
                    # SPOON rows = gia vị ước lượng (tiêu, dầu hào, sa tế...).
                    # User tự túc — không track stock + không thêm vào shopping list.
                    if ing.unit is Unit.SPOON:
                        continue
                    meta = ingredients_map.get(ing.ingredient_id)
                    if meta is None:
                        # Ingredient ngoài 62-class whitelist (gia vị / user-supplied) —
                        # bỏ qua: không track stock, không đẩy vào shopping list.
                        continue
                    if ing.grams_equivalent is None:
                        # gramsEqui null nhưng unit không phải SPOON — data lạ, skip an toàn.
                        continue
                    need_gam = to_gam(ing.quantity, ing.unit, meta, derived_number_to_gam)
                    have_gam = stock.get(ing.ingredient_id, 0.0)

                    if have_gam >= need_gam:
                        stock[ing.ingredient_id] = have_gam - need_gam
                        continue

                    deficit_gam = need_gam - have_gam
                    stock[ing.ingredient_id] = 0.0

                    # Tolerance check: nếu thiếu ≤ 15% need thì coi như user
                    # dùng phần đang có, không cần đi chợ thêm.
                    if need_gam > 0 and deficit_gam / need_gam <= tolerance:
                        continue

                    # Convert deficit back to the *recipe's* unit.
                    if ing.unit is Unit.GAM:
                        qty_out: float = round(deficit_gam, 2)
                    else:
                        # Tra factor từ derived map trước, fallback ingredient.numberToGam.
                        factor: float | None = None
                        if derived_number_to_gam is not None:
                            factor = derived_number_to_gam.get(ing.ingredient_id)
                        if not factor or factor <= 0:
                            factor = meta.number_to_gam
                        if not factor or factor <= 0:
                            raise InvalidIngredientError(
                                f"Không quy đổi được đơn vị cho nguyên liệu "
                                f"id={ing.ingredient_id} (công thức yêu cầu đơn vị "
                                f"NUMBER nhưng thiếu hệ số quy đổi sang gam)."
                            )
                        qty_out = float(math.ceil(deficit_gam / factor))

                    missing.append(
                        MissingIngredient(
                            ingredientId=ing.ingredient_id,
                            unit=ing.unit,
                            quantity=qty_out,
                        )
                    )
                dish_entry.missing_ingredient = missing
