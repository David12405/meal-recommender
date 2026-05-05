from __future__ import annotations

from datetime import datetime

from ortools.sat.python import cp_model

from app.models.domain import MealLogEntry
from app.models.enums import MEAL_TYPES, ROLES, MealType, Role
from app.utils.date_utils import days_between

VarKey = tuple[int, MealType, Role, int]


def _vars_for_dish_on_day(
    x: dict[VarKey, cp_model.IntVar],
    day: int,
    dish_id: int,
    dishes_by_idx: dict[Role, list[int]],
) -> list[cp_model.IntVar]:
    out: list[cp_model.IntVar] = []
    for meal in MEAL_TYPES:
        for role in ROLES:
            for i, did in enumerate(dishes_by_idx[role]):
                if did == dish_id:
                    key = (day, meal, role, i)
                    if key in x:
                        out.append(x[key])
    return out


def add_no_repeat_within_plan(
    model: cp_model.CpModel,
    x: dict[VarKey, cp_model.IntVar],
    plan_days: int,
    dishes_by_role: dict[Role, list[int]],
    window: int,
) -> None:
    """C2: a dish appears at most once in any window of (window+1) consecutive days.

    Implemented per dish: for every sliding window, sum of its vars <= 1.
    """
    all_dish_ids: set[int] = set()
    for ids in dishes_by_role.values():
        all_dish_ids.update(ids)

    for dish_id in all_dish_ids:
        per_day_vars: list[list[cp_model.IntVar]] = [
            _vars_for_dish_on_day(x, d, dish_id, dishes_by_role) for d in range(plan_days)
        ]
        # No repeat at all within plan if window >= plan_days
        if window + 1 >= plan_days:
            flat = [v for day_vars in per_day_vars for v in day_vars]
            if len(flat) > 1:
                model.Add(sum(flat) <= 1)
            continue
        for start in range(plan_days - window):
            window_vars = [
                v for d in range(start, start + window + 1) for v in per_day_vars[d]
            ]
            if len(window_vars) > 1:
                model.Add(sum(window_vars) <= 1)


def add_recent_meal_log(
    model: cp_model.CpModel,
    x: dict[VarKey, cp_model.IntVar],
    plan_days: int,
    start_date: datetime,
    recent_log: list[MealLogEntry],
    dishes_by_role: dict[Role, list[int]],
    window: int,
) -> None:
    """Exclude dishes eaten in the window immediately before startDate.

    Per §15 #4 answer (locked 2026-04-22): silently drop entries older than `window`.
    """
    for entry in recent_log:
        age = days_between(start_date, entry.date)
        if age < 0 or age > window:
            continue
        forbidden_days = range(0, max(0, window - age + 1))
        for d in forbidden_days:
            for var in _vars_for_dish_on_day(x, d, entry.dish_id, dishes_by_role):
                model.Add(var == 0)
