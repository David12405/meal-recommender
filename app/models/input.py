from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator

from app.models.domain import MealLogEntry
from app.models.enums import MealType, Role, Unit


class Goal(BaseModel):
    """Weight change goal. `targetKg` is kg/week despite the name (§3.1 note)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    target_kg: float = Field(alias="targetKg", ge=-0.5, le=0.5)


class LockedPick(BaseModel):
    """Slot bị pin sẵn — solver không được thay đổi (xem docs/07-replan.md).

    Dùng cho replan flow khi user đổi 1 món hoặc giữ một số slot cố định.
    Validation `day ≤ planDays`, dish exists, role match được làm ở orchestrator
    (cần truy cập cache).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    day: int = Field(ge=1, le=14)
    meal: MealType
    role: Role
    dish_id: int = Field(alias="dishId")


class MealSlotConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    main_dish: int = Field(alias="mainDish", ge=0, le=3)
    soup: int = Field(ge=0, le=3)
    vegetable: int = Field(ge=0, le=3)


class MealStructure(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    breakfast: MealSlotConfig
    lunch: MealSlotConfig
    dinner: MealSlotConfig


class FridgeItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ingredient_id: int = Field(alias="ingredientId")
    quantity: PositiveFloat
    unit: Unit
    due_date: datetime = Field(alias="dueDate")


class RecommendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    user_id: int = Field(alias="userId", ge=1)
    tdee: float = Field(ge=800, le=5000)
    weight: float = Field(ge=30, le=300)
    goal: Goal
    meal_structure: MealStructure = Field(alias="mealStructure")
    plan_days: int = Field(alias="planDays", ge=1, le=14)
    start_date: datetime = Field(alias="startDate")
    recent_meal_log: list[MealLogEntry] = Field(default_factory=list, alias="recentMealLog")
    fridge: list[FridgeItem] = Field(default_factory=list)
    locked_picks: list[LockedPick] = Field(default_factory=list, alias="lockedPicks")

    @model_validator(mode="after")
    def _check_locked_picks(self) -> "RecommendRequest":
        if not self.locked_picks:
            return self

        # 1. day phải nằm trong [1, plan_days]
        for lp in self.locked_picks:
            if lp.day > self.plan_days:
                raise ValueError(
                    f"lockedPicks[].day={lp.day} vượt quá planDays={self.plan_days}"
                )

        # 2. (day, meal, role) unique — không lock 2 dish cho cùng 1 slot+role
        seen: set[tuple[int, MealType, Role]] = set()
        for lp in self.locked_picks:
            key = (lp.day, lp.meal, lp.role)
            if key in seen:
                raise ValueError(f"lockedPicks duplicate (day, meal, role): {key}")
            seen.add(key)

        # 3. Số lock cho (meal, role) trong mỗi day ≤ mealStructure[meal][role]
        # (vd lock 2 SOUP cho lunch khi mealStructure.lunch.soup=1 → invalid)
        from collections import Counter
        per_slot_role: Counter[tuple[int, MealType, Role]] = Counter(
            (lp.day, lp.meal, lp.role) for lp in self.locked_picks
        )
        role_attr = {Role.MAINDISH: "main_dish", Role.SOUP: "soup", Role.VEGETABLE: "vegetable"}
        for (day, meal, role), count in per_slot_role.items():
            slot_cfg = getattr(self.meal_structure, meal.value)
            allowed = getattr(slot_cfg, role_attr[role])
            if count > allowed:
                raise ValueError(
                    f"lockedPicks day={day} meal={meal.value} role={role.value}: "
                    f"locked {count} > mealStructure cho phép {allowed}"
                )

        return self
