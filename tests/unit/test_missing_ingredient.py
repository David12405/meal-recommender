from __future__ import annotations

from datetime import datetime

from app.models.enums import Role, Unit
from app.models.input import FridgeItem
from app.models.output import DayMeals, DayNutrition, DayPlan, MealDishEntry
from app.services.missing_ingredient import compute_missing_per_dish


def _plan_with_one_lunch_dish(dish_id: int) -> list[DayPlan]:
    return [
        DayPlan(
            day=1,
            date=datetime(2026, 4, 21),
            meals=DayMeals(
                breakfast=[],
                lunch=[MealDishEntry(dishId=dish_id, role=Role.MAINDISH)],
                dinner=[],
            ),
            nutrition=DayNutrition(calories=0, protein=0, carb=0, fat=0),
        )
    ]


def test_empty_fridge_full_missing(sample_dishes, sample_ingredients):
    dishes_map = {d.dish_id: d for d in sample_dishes}
    ings_map = {i.ingredient_id: i for i in sample_ingredients}
    plan = _plan_with_one_lunch_dish(101)
    compute_missing_per_dish(plan, fridge=[], dishes_map=dishes_map, ingredients_map=ings_map)
    missing = plan[0].meals.lunch[0].missing_ingredient
    assert {m.ingredient_id for m in missing} == {1, 3, 7}


def test_fridge_sufficient_no_missing(sample_dishes, sample_ingredients):
    dishes_map = {d.dish_id: d for d in sample_dishes}
    ings_map = {i.ingredient_id: i for i in sample_ingredients}
    plan = _plan_with_one_lunch_dish(102)  # 2 eggs + 5g oil
    fridge = [
        FridgeItem(
            ingredientId=2, quantity=3, unit=Unit.NUMBER, dueDate=datetime(2026, 4, 25)
        ),
        FridgeItem(
            ingredientId=7, quantity=100, unit=Unit.GAM, dueDate=datetime(2026, 4, 25)
        ),
    ]
    compute_missing_per_dish(plan, fridge=fridge, dishes_map=dishes_map, ingredients_map=ings_map)
    assert plan[0].meals.lunch[0].missing_ingredient == []


def test_stock_depletes_across_dishes(sample_dishes, sample_ingredients):
    """Two lunch dishes using the same ingredient — second dish should see less stock."""
    dishes_map = {d.dish_id: d for d in sample_dishes}
    ings_map = {i.ingredient_id: i for i in sample_ingredients}
    plan = [
        DayPlan(
            day=1,
            date=datetime(2026, 4, 21),
            meals=DayMeals(
                breakfast=[],
                lunch=[
                    MealDishEntry(dishId=102, role=Role.MAINDISH),
                    MealDishEntry(dishId=102, role=Role.MAINDISH),
                ],
                dinner=[],
            ),
            nutrition=DayNutrition(calories=0, protein=0, carb=0, fat=0),
        )
    ]
    fridge = [
        FridgeItem(
            ingredientId=2, quantity=3, unit=Unit.NUMBER, dueDate=datetime(2026, 4, 25)
        ),
        FridgeItem(
            ingredientId=7, quantity=10, unit=Unit.GAM, dueDate=datetime(2026, 4, 25)
        ),
    ]
    compute_missing_per_dish(plan, fridge=fridge, dishes_map=dishes_map, ingredients_map=ings_map)
    first = plan[0].meals.lunch[0].missing_ingredient
    second = plan[0].meals.lunch[1].missing_ingredient
    assert first == []
    # After first dish consumes 2 eggs + 5g oil, stock = 1 egg + 5g oil.
    # Second needs 2 eggs + 5g oil → short by 1 egg, oil covered exactly.
    assert len(second) == 1
    assert second[0].ingredient_id == 2
    assert second[0].unit is Unit.NUMBER
    assert second[0].quantity == 1
