from __future__ import annotations

import math

from app.core.exceptions import InvalidIngredientError
from app.models.domain import Ingredient
from app.models.enums import Unit


def _resolve_factor(
    ingredient: Ingredient,
    derived_map: dict[int, float] | None,
) -> float | None:
    """Tìm `gam_per_unit` cho ingredient. Ưu tiên derived_map (suy từ junction),
    fallback `ingredient.number_to_gam` (legacy ingredient_full column).
    """
    if derived_map is not None:
        v = derived_map.get(ingredient.ingredient_id)
        if v and v > 0:
            return v
    if ingredient.number_to_gam and ingredient.number_to_gam > 0:
        return ingredient.number_to_gam
    return None


def to_gam(
    quantity: float,
    unit: Unit,
    ingredient: Ingredient,
    derived_number_to_gam: dict[int, float] | None = None,
) -> float:
    """Convert quantity to GAM for internal comparison (stock tracking, solver).

    Rules:
    - GAM → GAM: passthrough.
    - NUMBER → GAM: nhân `gam_per_unit` lấy từ `derived_number_to_gam` (suy từ
      DishIngredient junction) hoặc fallback `ingredient.number_to_gam`.
    - SPOON: caller phải skip trước khi gọi to_gam (xem missing_ingredient.py).
    - Nếu không có conversion factor → InvalidIngredientError (400).
    """
    if unit is Unit.GAM:
        return quantity
    factor = _resolve_factor(ingredient, derived_number_to_gam)
    if factor is None:
        raise InvalidIngredientError(
            f"Không quy đổi được đơn vị NUMBER sang gam cho nguyên liệu "
            f"'{ingredient.name}' (id={ingredient.ingredient_id}). "
            f"Vui lòng nhập số lượng theo đơn vị GAM hoặc liên hệ hỗ trợ."
        )
    return quantity * factor


def from_gam(
    quantity_gam: float,
    unit: Unit,
    ingredient: Ingredient,
    derived_number_to_gam: dict[int, float] | None = None,
) -> float:
    """Convert GAM back to the target `unit`. NUMBER results are ceil'd to whole items."""
    if unit is Unit.GAM:
        return quantity_gam
    factor = _resolve_factor(ingredient, derived_number_to_gam)
    if factor is None or factor <= 0:
        raise InvalidIngredientError(
            f"Không quy đổi được đơn vị từ gam sang NUMBER cho nguyên liệu "
            f"'{ingredient.name}' (id={ingredient.ingredient_id})."
        )
    return float(math.ceil(quantity_gam / factor))
