from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role, Unit


class MissingIngredient(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ingredient_id: int = Field(alias="ingredientId", serialization_alias="ingredientId")
    unit: Unit
    quantity: float


class MealDishEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dish_id: int = Field(alias="dishId", serialization_alias="dishId")
    role: Role
    missing_ingredient: list[MissingIngredient] = Field(
        default_factory=list,
        alias="missingIngredient",
        serialization_alias="missingIngredient",
    )


class DayMeals(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    breakfast: list[MealDishEntry] = Field(default_factory=list)
    lunch: list[MealDishEntry] = Field(default_factory=list)
    dinner: list[MealDishEntry] = Field(default_factory=list)


class DayNutrition(BaseModel):
    calories: float
    protein: float
    carb: float
    fat: float


class DayPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    day: int
    date: datetime
    meals: DayMeals
    nutrition: DayNutrition


class Summary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    avg_daily_calories: float = Field(
        alias="avgDailyCalories", serialization_alias="avgDailyCalories"
    )
    target_calories: float = Field(
        alias="targetCalories", serialization_alias="targetCalories"
    )
    deviation: float
    avg_daily_protein: float = Field(
        alias="avgDailyProtein", serialization_alias="avgDailyProtein"
    )
    avg_daily_carbs: float = Field(
        alias="avgDailyCarbs", serialization_alias="avgDailyCarbs"
    )
    avg_daily_fat: float = Field(
        alias="avgDailyFat", serialization_alias="avgDailyFat"
    )


class ShoppingItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ingredient_id: int = Field(alias="ingredientId", serialization_alias="ingredientId")
    quantity: float
    unit: Unit


class MealPlanResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    status: str
    plan: list[DayPlan] = Field(default_factory=list)
    summary: Summary | None = None
    shopping_list: list[ShoppingItem] = Field(
        default_factory=list,
        alias="shoppingList",
        serialization_alias="shoppingList",
    )
