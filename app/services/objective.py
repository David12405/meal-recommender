from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ortools.sat.python import cp_model

from app.models.domain import Dish
from app.models.enums import MEAL_TYPES, ROLES, MealType, Role

VarKey = tuple[int, MealType, Role, int]


@dataclass(frozen=True)
class ObjectiveWeights:
    fridge: int
    expiry: int
    diversity: int
    shopping_penalty: int
    expiry_window_days: int = 7


def build_objective(
    model: cp_model.CpModel,
    x: dict[VarKey, cp_model.IntVar],
    plan_days: int,
    dishes_by_role: dict[Role, list[Dish]],
    fridge_ids: set[int],
    expiring: dict[int, datetime],
    start_date: datetime,
    weights: ObjectiveWeights,
) -> None:
    """Maximize weighted soft objectives:

    S1 (fridge): bonus mỗi ingredient của dish có trong fridge.
    S2 (expiry): linear decay theo `expiry_window_days`. Ingredient càng gần hết hạn
        càng được ưu tiên — solver sẽ pick dish dùng ingredient đó trước. Ingredient
        đã quá hạn (`days_to_expire < 0`) hoặc còn rất xa (`> window`) không boost.
    S4 (shopping penalty): trừ điểm mỗi ingredient của dish KHÔNG trong fridge.
    S3 (diversity): cover bởi C2 no-repeat window; skip ở đây.
    """
    terms: list[cp_model.IntVar] = []
    coeffs: list[int] = []
    window = weights.expiry_window_days

    for d in range(plan_days):
        for meal in MEAL_TYPES:
            for role in ROLES:
                for i, dish in enumerate(dishes_by_role[role]):
                    score = 0
                    for ing in dish.ingredients:
                        if ing.ingredient_id in fridge_ids:
                            score += weights.fridge
                            if ing.ingredient_id in expiring:
                                due = expiring[ing.ingredient_id]
                                days_to_expire = (due - start_date).days - d
                                # Linear decay: 0 ngày → urgency=window+1, window ngày → urgency=1.
                                # >window hoặc <0 (đã hết hạn): urgency=0, không boost.
                                if 0 <= days_to_expire <= window:
                                    urgency = window - days_to_expire + 1
                                    score += weights.expiry * urgency
                        else:
                            score -= weights.shopping_penalty
                    if score != 0:
                        terms.append(x[(d, meal, role, i)])
                        coeffs.append(score)

    if terms:
        model.Maximize(cp_model.LinearExpr.WeightedSum(terms, coeffs))
