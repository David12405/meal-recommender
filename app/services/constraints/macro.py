from __future__ import annotations

from ortools.sat.python import cp_model

from app.models.domain import Dish
from app.models.enums import MEAL_TYPES, ROLES, MealType, Role
from app.utils.nutrition import MACRO_TARGETS, GoalType

VarKey = tuple[int, MealType, Role, int]

# Scale protein by 10 to keep integer math (honours 0.1 g granularity).
PROTEIN_SCALE = 10


def _day_sum(
    x: dict[VarKey, cp_model.IntVar],
    day: int,
    dishes_by_role: dict[Role, list[Dish]],
    coeff_fn,
) -> cp_model.LinearExpr:
    terms: list[cp_model.IntVar] = []
    coeffs: list[int] = []
    for meal in MEAL_TYPES:
        for role in ROLES:
            for i, dish in enumerate(dishes_by_role[role]):
                terms.append(x[(day, meal, role, i)])
                coeffs.append(coeff_fn(dish))
    return cp_model.LinearExpr.WeightedSum(terms, coeffs)


def add_macro(
    model: cp_model.CpModel,
    x: dict[VarKey, cp_model.IntVar],
    plan_days: int,
    dishes_by_role: dict[Role, list[Dish]],
    goal: GoalType,
    weight_kg: float,
    relax_pct: float = 0.0,
) -> None:
    """C4: daily macro bounds.

    - Protein: absolute grams per kg body weight.
    - Carb/Fat: percentage of that day's calories (cross-multiplied to stay integer).
      carb kcal = 4 * carb_g, fat kcal = 9 * fat_g.

    `relax_pct` ∈ [0, 1] widens each range symmetrically (used by relaxation pass).
    """
    target = MACRO_TARGETS[goal]

    p_min, p_max = target.protein_g_per_kg
    c_min, c_max = target.carb_pct
    f_min, f_max = target.fat_pct

    if relax_pct > 0:
        span_p = (p_max - p_min) * relax_pct / 2
        p_min -= span_p
        p_max += span_p
        span_c = (c_max - c_min) * relax_pct / 2
        c_min = max(0.0, c_min - span_c)
        c_max = min(1.0, c_max + span_c)
        span_f = (f_max - f_min) * relax_pct / 2
        f_min = max(0.0, f_min - span_f)
        f_max = min(1.0, f_max + span_f)

    protein_min = int(round(p_min * weight_kg * PROTEIN_SCALE))
    protein_max = int(round(p_max * weight_kg * PROTEIN_SCALE))
    c_min_int = int(round(c_min * 100))
    c_max_int = int(round(c_max * 100))
    f_min_int = int(round(f_min * 100))
    f_max_int = int(round(f_max * 100))

    for d in range(plan_days):
        protein_scaled = _day_sum(
            x, d, dishes_by_role,
            lambda dish: int(round(dish.nutrition_per_serving.protein * PROTEIN_SCALE)),
        )
        model.Add(protein_scaled >= protein_min)
        model.Add(protein_scaled <= protein_max)

        cal_d = _day_sum(
            x, d, dishes_by_role,
            lambda dish: int(round(dish.nutrition_per_serving.calories)),
        )
        carb_g = _day_sum(
            x, d, dishes_by_role,
            lambda dish: int(round(dish.nutrition_per_serving.carb)),
        )
        fat_g = _day_sum(
            x, d, dishes_by_role,
            lambda dish: int(round(dish.nutrition_per_serving.fat)),
        )

        # carb_pct_min * cal_d <= (4 * carb_g) <= carb_pct_max * cal_d
        model.Add(4 * 100 * carb_g >= c_min_int * cal_d)
        model.Add(4 * 100 * carb_g <= c_max_int * cal_d)

        # fat: 9 kcal/g
        model.Add(9 * 100 * fat_g >= f_min_int * cal_d)
        model.Add(9 * 100 * fat_g <= f_max_int * cal_d)
