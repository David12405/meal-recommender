from __future__ import annotations

from datetime import datetime

from app.models.enums import Role, Unit
from app.models.output import (
    DayMeals,
    DayNutrition,
    DayPlan,
    MealDishEntry,
    MissingIngredient,
)
from app.services.shopping_list import build_shopping_list


def _day_with_entries(day: int, entries_lunch: list[MealDishEntry]) -> DayPlan:
    return DayPlan(
        day=day,
        date=datetime(2026, 4, 21 + day - 1),
        meals=DayMeals(breakfast=[], lunch=entries_lunch, dinner=[]),
        nutrition=DayNutrition(calories=0, protein=0, carb=0, fat=0),
    )


def test_aggregates_and_sorts(sample_ingredients):
    ing_map = {i.ingredient_id: i for i in sample_ingredients}
    entry_a = MealDishEntry(
        dishId=101,
        role=Role.MAINDISH,
        missingIngredient=[MissingIngredient(ingredientId=1, unit=Unit.GAM, quantity=100)],
    )
    entry_b = MealDishEntry(
        dishId=102,
        role=Role.MAINDISH,
        missingIngredient=[MissingIngredient(ingredientId=1, unit=Unit.GAM, quantity=50)],
    )
    plan = [_day_with_entries(1, [entry_a, entry_b])]
    shopping = build_shopping_list(plan, ing_map)
    assert len(shopping) == 1
    assert shopping[0].ingredient_id == 1
    assert shopping[0].quantity == 150
    assert shopping[0].unit is Unit.GAM


def test_mixed_units_collapse_to_default_number(sample_ingredients):
    ing_map = {i.ingredient_id: i for i in sample_ingredients}
    # ingredient 2 = eggs, defaultUnit=NUMBER, 1 egg = 55g
    entry = MealDishEntry(
        dishId=102,
        role=Role.MAINDISH,
        missingIngredient=[
            MissingIngredient(ingredientId=2, unit=Unit.NUMBER, quantity=2),
            MissingIngredient(ingredientId=2, unit=Unit.GAM, quantity=55),
        ],
    )
    plan = [_day_with_entries(1, [entry])]
    shopping = build_shopping_list(plan, ing_map)
    assert len(shopping) == 1
    assert shopping[0].unit is Unit.NUMBER
    # 2 eggs (110g) + 55g = 165g → ceil(165/55) = 3 eggs
    assert shopping[0].quantity == 3
