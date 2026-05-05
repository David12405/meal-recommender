from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings

GoalType = Literal["weight_loss", "maintain", "weight_gain"]


@dataclass(frozen=True)
class MacroTarget:
    protein_g_per_kg: tuple[float, float]
    carb_pct: tuple[float, float]
    fat_pct: tuple[float, float]


MACRO_TARGETS: dict[GoalType, MacroTarget] = {
    "weight_loss": MacroTarget(
        protein_g_per_kg=(1.6, 2.2),
        carb_pct=(0.45, 0.55),
        fat_pct=(0.20, 0.30),
    ),
    "maintain": MacroTarget(
        protein_g_per_kg=(1.2, 1.6),
        carb_pct=(0.45, 0.60),
        fat_pct=(0.25, 0.35),
    ),
    "weight_gain": MacroTarget(
        protein_g_per_kg=(1.4, 2.0),
        carb_pct=(0.50, 0.60),
        fat_pct=(0.20, 0.30),
    ),
}


def classify_goal(target_kg_per_week: float) -> GoalType:
    if target_kg_per_week < -0.1:
        return "weight_loss"
    if target_kg_per_week > 0.1:
        return "weight_gain"
    return "maintain"


def daily_delta(target_kg_per_week: float) -> float:
    """Calorie delta per day derived from kg/week goal. 1 kg fat ≈ 7700 kcal."""
    return (target_kg_per_week * get_settings().kcal_per_kg) / 7


def target_cal_per_day(tdee: float, target_kg_per_week: float) -> float:
    return tdee + daily_delta(target_kg_per_week)


def target_cal_total(tdee: float, target_kg_per_week: float, plan_days: int) -> float:
    """Locked formula (§15 #6 answer from user 2026-04-22): (tdee + daily_delta) × planDays."""
    return target_cal_per_day(tdee, target_kg_per_week) * plan_days
