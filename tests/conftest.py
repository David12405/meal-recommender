from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.models.domain import Dish, DishIngredientRow, Ingredient
from app.models.input import RecommendRequest
from app.services.db_loader import (
    _apply_default_meal_types,
    _compute_nutrition,
    _merge_dish_ingredients,
)

FIXTURES = Path(__file__).parent / "fixtures"

_DishList = TypeAdapter(list[Dish])
_IngredientList = TypeAdapter(list[Ingredient])
_RowList = TypeAdapter(list[DishIngredientRow])


def _load_all() -> tuple[list[Dish], list[Ingredient]]:
    dishes = _DishList.validate_python(
        json.loads((FIXTURES / "sample_dishes.json").read_text(encoding="utf-8"))
    )
    ingredients = _IngredientList.validate_python(
        json.loads((FIXTURES / "sample_ingredients.json").read_text(encoding="utf-8"))
    )
    rows = _RowList.validate_python(
        json.loads((FIXTURES / "sample_dish_ingredients.json").read_text(encoding="utf-8"))
    )
    _merge_dish_ingredients(dishes, rows)
    _compute_nutrition(dishes, ingredients)
    _apply_default_meal_types(dishes)
    return dishes, ingredients


@pytest.fixture
def sample_ingredients() -> list[Ingredient]:
    _, ingredients = _load_all()
    return ingredients


@pytest.fixture
def sample_dishes() -> list[Dish]:
    dishes, _ = _load_all()
    return dishes


@pytest.fixture
def sample_request() -> RecommendRequest:
    return RecommendRequest.model_validate(
        json.loads((FIXTURES / "sample_input.json").read_text(encoding="utf-8"))
    )
