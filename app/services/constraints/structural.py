from __future__ import annotations

from ortools.sat.python import cp_model

from app.models.enums import MEAL_TYPES, ROLES, MealType, Role
from app.models.input import MealStructure


def required_count(meal_structure: MealStructure, meal: MealType, role: Role) -> int:
    slot = getattr(meal_structure, meal.value)
    if role is Role.MAINDISH:
        return int(slot.main_dish)
    if role is Role.SOUP:
        return int(slot.soup)
    return int(slot.vegetable)


def add_structural(
    model: cp_model.CpModel,
    x: dict[tuple[int, MealType, Role, int], cp_model.IntVar],
    plan_days: int,
    meal_structure: MealStructure,
    candidates_by_role: dict[Role, list[int]],
) -> None:
    """C1: for each (day, meal, role), exact count of dishes chosen = required."""
    for d in range(plan_days):
        for meal in MEAL_TYPES:
            for role in ROLES:
                need = required_count(meal_structure, meal, role)
                idxs = candidates_by_role[role]
                model.Add(sum(x[(d, meal, role, i)] for i in range(len(idxs))) == need)
