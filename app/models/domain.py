from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, NonNegativeFloat, PositiveInt

from app.models.enums import MealType, Role, Unit


class DishIngredient(BaseModel):
    """Ingredient of a dish as consumed by the solver.

    Merged from the backend junction table; the solver sees `grams_equivalent` (đã
    convert sẵn) và giữ `quantity`+`unit` để output `missingIngredient` đúng đơn vị
    công thức.

    `grams_equivalent` optional vì rows `unit=SPOON` (gia vị) thường không có gram
    equivalent — solver bỏ qua những row đó (xem db_loader._compute_nutrition và
    missing_ingredient.compute_missing_per_dish).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ingredient_id: int = Field(alias="ingredientId")
    quantity: NonNegativeFloat
    unit: Unit
    grams_equivalent: NonNegativeFloat | None = Field(
        default=None,
        validation_alias=AliasChoices("gramsEquivalent", "gramsEqui"),
        serialization_alias="gramsEquivalent",
    )


class NutritionPerServing(BaseModel):
    calories: NonNegativeFloat
    protein: NonNegativeFloat
    carb: NonNegativeFloat
    fat: NonNegativeFloat


class Dish(BaseModel):
    """Post-load Dish. Backend export is flatter; `ingredients`, `nutrition_per_serving`,
    and `meal_types` are filled by `db_loader` (§4.3, §4.4, §4.5)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dish_id: int = Field(alias="id", validation_alias="id")
    name: str
    role: Role = Field(alias="type", validation_alias="type")
    calories: NonNegativeFloat
    servings: PositiveInt = 1

    # Populated by db_loader after merging with junction + ingredients.
    # `meal_types` có thể đến từ backend export (alias `mealTypes`); nếu rỗng,
    # `_apply_default_meal_types()` sẽ áp default rule theo `role`.
    ingredients: list[DishIngredient] = Field(default_factory=list)
    nutrition_per_serving: NutritionPerServing | None = None
    meal_types: list[MealType] = Field(default_factory=list, alias="mealTypes")


class Ingredient(BaseModel):
    """Backend ingredient. Macros (`protein`, `carb`, `fat`) are per 100g.
    `number_to_gam` is null when the ingredient does not convert from NUMBER sensibly.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ingredient_id: int = Field(alias="id", validation_alias="id")
    name: str
    default_unit: Unit = Field(alias="unit", validation_alias="unit")
    number_to_gam: float | None = Field(default=None, alias="numberToGam")
    protein: NonNegativeFloat = 0.0
    carb: NonNegativeFloat = 0.0
    fat: NonNegativeFloat = 0.0


class DishIngredientRow(BaseModel):
    """Raw row from backend junction table (§4.3).

    `grams_equivalent` accept cả 2 alias (`gramsEquivalent` ưu tiên, `gramsEqui`
    fallback cho data legacy). Optional cho rows `unit=SPOON` (gia vị).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dish_id: int = Field(alias="dishId")
    ingredient_id: int = Field(alias="ingredientId")
    amount: NonNegativeFloat
    grams_equivalent: NonNegativeFloat | None = Field(
        default=None,
        validation_alias=AliasChoices("gramsEquivalent", "gramsEqui"),
        serialization_alias="gramsEquivalent",
    )
    unit: Unit


class MealLogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dish_id: int = Field(alias="dishId")
    date: datetime
