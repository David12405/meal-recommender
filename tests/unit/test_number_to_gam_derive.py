"""Test logic suy `numberToGam` từ DishIngredient junction (xem docs/09-unit-conversion.md)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.exceptions import InvalidIngredientError
from app.models.domain import DishIngredientRow, Ingredient
from app.models.enums import Unit
from app.models.input import FridgeItem
from app.services.db_loader import _derive_number_to_gam
from app.services.missing_ingredient import _initial_stock_gam


def _row(dish_id, ing_id, amount, grams, unit=Unit.NUMBER):
    return DishIngredientRow(
        dishId=dish_id,
        ingredientId=ing_id,
        amount=amount,
        gramsEquivalent=grams,
        unit=unit,
    )


def test_derive_single_row():
    rows = [_row(1, 2, 1, 70)]   # 1 quả trứng vịt = 70g
    derived = _derive_number_to_gam(rows)
    assert derived == {2: 70.0}


def test_derive_average_multiple_rows():
    rows = [
        _row(1, 12, 1, 55),    # 1 quả trứng gà = 55g
        _row(2, 12, 2, 110),   # 2 quả = 110g → 55g/quả
        _row(3, 12, 1, 65),    # variation: 1 quả = 65g
    ]
    derived = _derive_number_to_gam(rows)
    # Average: (55 + 55 + 65) / 3 = 58.33
    assert derived[12] == pytest.approx(58.33, abs=0.01)


def test_derive_skips_gam_rows():
    rows = [
        _row(1, 1, 100, 100, unit=Unit.GAM),  # GAM row — skip
        _row(2, 1, 200, 200, unit=Unit.GAM),
    ]
    derived = _derive_number_to_gam(rows)
    assert derived == {}


def test_derive_skips_zero_amount_or_grams():
    rows = [
        _row(1, 5, 0, 100),    # amount=0, skip
        _row(2, 5, 1, 0),      # grams=0, skip
        _row(3, 5, 1, 100),    # OK
    ]
    derived = _derive_number_to_gam(rows)
    assert derived == {5: 100.0}


def test_derive_skips_null_grams():
    """SPOON rows thường gramsEquivalent=None — skip."""
    rows = [
        DishIngredientRow(dishId=1, ingredientId=99, amount=1, unit=Unit.NUMBER),
        # gramsEquivalent default None
    ]
    derived = _derive_number_to_gam(rows)
    assert derived == {}


def test_fridge_number_uses_derived_map():
    """Fridge gửi 5 quả trứng → service convert 350g qua derived map."""
    ingredient = Ingredient(
        id=2, name="Trứng vịt", unit=Unit.NUMBER, protein=13, carb=3, fat=12
    )
    fridge = [
        FridgeItem(
            ingredientId=2, quantity=5, unit=Unit.NUMBER, dueDate=datetime(2026, 5, 10)
        )
    ]
    derived = {2: 70.0}   # suy từ junction
    stock = _initial_stock_gam(fridge, {2: ingredient}, derived)
    assert stock[2] == 350.0   # 5 × 70


def test_fridge_number_falls_back_to_ingredient_factor():
    """Nếu derived không cover, fallback ingredient.numberToGam (legacy)."""
    ingredient = Ingredient(
        id=12, name="Trứng gà", unit=Unit.NUMBER,
        numberToGam=55, protein=13, carb=1, fat=10,
    )
    fridge = [
        FridgeItem(
            ingredientId=12, quantity=2, unit=Unit.NUMBER,
            dueDate=datetime(2026, 5, 10),
        )
    ]
    # Derived map rỗng — fallback to ingredient.number_to_gam
    stock = _initial_stock_gam(fridge, {12: ingredient}, derived_number_to_gam={})
    assert stock[12] == 110.0   # 2 × 55


def test_fridge_number_raises_when_no_factor_anywhere():
    """Không có cả derived lẫn ingredient.numberToGam → 400."""
    ingredient = Ingredient(
        id=99, name="X", unit=Unit.NUMBER, protein=0, carb=0, fat=0
    )
    fridge = [
        FridgeItem(
            ingredientId=99, quantity=1, unit=Unit.NUMBER,
            dueDate=datetime(2026, 5, 10),
        )
    ]
    with pytest.raises(InvalidIngredientError, match="NUMBER sang gam"):
        _initial_stock_gam(fridge, {99: ingredient}, derived_number_to_gam={})


def test_fridge_gam_passthrough_unchanged():
    """Fridge gửi GAM không bị ảnh hưởng — derived map không cần thiết."""
    ingredient = Ingredient(id=1, name="Thịt heo", unit=Unit.GAM, protein=20, carb=0, fat=15)
    fridge = [
        FridgeItem(
            ingredientId=1, quantity=400, unit=Unit.GAM,
            dueDate=datetime(2026, 5, 10),
        )
    ]
    stock = _initial_stock_gam(fridge, {1: ingredient}, derived_number_to_gam={})
    assert stock[1] == 400.0
