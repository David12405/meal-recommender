from __future__ import annotations

import pytest

from app.core.exceptions import InvalidIngredientError
from app.models.domain import Ingredient
from app.models.enums import Unit
from app.services.unit_converter import from_gam, to_gam


def _ingredient(factor: float | None, default: Unit = Unit.GAM) -> Ingredient:
    return Ingredient(
        id=99,
        name="test",
        unit=default,
        numberToGam=factor,
    )


def test_to_gam_passthrough_for_gam():
    ing = _ingredient(None)
    assert to_gam(100, Unit.GAM, ing) == 100


def test_to_gam_multiplies_for_number():
    ing = _ingredient(55, Unit.NUMBER)
    assert to_gam(2, Unit.NUMBER, ing) == 110


def test_to_gam_raises_when_factor_missing():
    ing = _ingredient(None)
    with pytest.raises(InvalidIngredientError):
        to_gam(2, Unit.NUMBER, ing)


def test_from_gam_ceils_number_conversion():
    ing = _ingredient(55, Unit.NUMBER)
    # 56g → needs 2 eggs (even 1g over 55 rounds up)
    assert from_gam(56, Unit.NUMBER, ing) == 2


def test_from_gam_passthrough_for_gam():
    ing = _ingredient(None)
    assert from_gam(150.0, Unit.GAM, ing) == 150.0
