from __future__ import annotations

from ortools.sat.python import cp_model

from app.models.domain import Dish
from app.models.enums import MEAL_TYPES, ROLES, MealType, Role

VarKey = tuple[int, MealType, Role, int]


def add_calorie(
    model: cp_model.CpModel,
    x: dict[VarKey, cp_model.IntVar],
    plan_days: int,
    dishes_by_role: dict[Role, list[Dish]],
    target_cal_per_day: float,
    delta: int,
) -> None:
    """C3: per-day calories within [target - delta, target + delta].

    Calories from nutritionPerServing are rounded to int (kcal granularity is fine).
    """
    target_int = int(round(target_cal_per_day))
    for d in range(plan_days):
        terms: list[cp_model.IntVar] = []
        coeffs: list[int] = []
        for meal in MEAL_TYPES:
            for role in ROLES:
                for i, dish in enumerate(dishes_by_role[role]):
                    terms.append(x[(d, meal, role, i)])
                    coeffs.append(int(round(dish.nutrition_per_serving.calories)))
        cal_d = cp_model.LinearExpr.WeightedSum(terms, coeffs)
        model.Add(cal_d >= target_int - delta)
        model.Add(cal_d <= target_int + delta)
