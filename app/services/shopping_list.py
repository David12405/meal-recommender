from __future__ import annotations

import math
from collections import defaultdict

from app.models.domain import Ingredient
from app.models.enums import MEAL_TYPES, Unit
from app.models.output import DayPlan, ShoppingItem


def build_shopping_list(
    plan: list[DayPlan],
    ingredients_map: dict[int, Ingredient],
) -> list[ShoppingItem]:
    """Aggregate every dish's missingIngredient across the plan (dedup by ingredientId).

    If an ingredient appears in both GAM and NUMBER across different dishes, collapse
    to the ingredient's `defaultUnit`: convert the other via NUMBER_TO_GAM and re-emit.
    """
    totals: dict[int, dict[Unit, float]] = defaultdict(
        lambda: {Unit.GAM: 0.0, Unit.NUMBER: 0.0}
    )

    for day in plan:
        for meal_name in MEAL_TYPES:
            slot = getattr(day.meals, meal_name.value)
            for entry in slot:
                for mi in entry.missing_ingredient:
                    totals[mi.ingredient_id][mi.unit] += mi.quantity

    shopping: list[ShoppingItem] = []
    for ing_id, by_unit in totals.items():
        gam = by_unit[Unit.GAM]
        num = by_unit[Unit.NUMBER]
        meta = ingredients_map.get(ing_id)

        if gam > 0 and num > 0 and meta is not None:
            factor = meta.number_to_gam
            if meta.default_unit is Unit.NUMBER and factor:
                total_gam = gam + num * factor
                qty = math.ceil(total_gam / factor)
                shopping.append(
                    ShoppingItem(ingredientId=ing_id, quantity=float(qty), unit=Unit.NUMBER)
                )
            elif factor:
                total_gam = gam + num * factor
                shopping.append(
                    ShoppingItem(
                        ingredientId=ing_id,
                        quantity=float(math.ceil(total_gam)),
                        unit=Unit.GAM,
                    )
                )
            else:
                # No factor available: emit the two as separate aggregated items
                shopping.append(
                    ShoppingItem(
                        ingredientId=ing_id,
                        quantity=float(math.ceil(gam)),
                        unit=Unit.GAM,
                    )
                )
                shopping.append(
                    ShoppingItem(
                        ingredientId=ing_id,
                        quantity=float(int(num)),
                        unit=Unit.NUMBER,
                    )
                )
        elif gam > 0:
            shopping.append(
                ShoppingItem(
                    ingredientId=ing_id,
                    quantity=float(math.ceil(gam)),
                    unit=Unit.GAM,
                )
            )
        elif num > 0:
            shopping.append(
                ShoppingItem(
                    ingredientId=ing_id,
                    quantity=float(int(num)),
                    unit=Unit.NUMBER,
                )
            )

    return sorted(shopping, key=lambda s: s.ingredient_id)
