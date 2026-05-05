from __future__ import annotations

from datetime import timedelta

from loguru import logger

from app.core.cache import DBSnapshot
from app.core.exceptions import InvalidIngredientError, MealRecommenderError
from app.models.domain import Dish, MealLogEntry
from app.models.enums import MEAL_TYPES, MealType
from app.models.input import RecommendRequest
from app.models.output import (
    DayMeals,
    DayNutrition,
    DayPlan,
    MealDishEntry,
    MealPlanResponse,
    Summary,
)
from app.services.cp_sat_solver import SolveInput, solve
from app.services.missing_ingredient import compute_missing_per_dish
from app.services.shopping_list import build_shopping_list
from app.utils.nutrition import classify_goal, target_cal_per_day, target_cal_total


def _validate_fridge(req: RecommendRequest, valid_ingredient_ids: set[int]) -> None:
    for item in req.fridge:
        if item.ingredient_id not in valid_ingredient_ids:
            raise InvalidIngredientError(
                f"Fridge ingredient {item.ingredient_id} is not in the "
                f"current ingredient whitelist"
            )


def _validate_locked_picks(req: RecommendRequest, snapshot: DBSnapshot) -> None:
    """Mỗi locked pick phải reference dish tồn tại trong cache + role khớp với role
    của dish đó. (Validation cấu trúc — day range, uniqueness, capacity — đã làm
    ở Pydantic model_validator.)
    """
    for lp in req.locked_picks:
        dish = snapshot.dishes_by_id.get(lp.dish_id)
        if dish is None:
            raise InvalidIngredientError(
                f"lockedPicks dishId={lp.dish_id} không có trong cache dishes."
            )
        if dish.role != lp.role:
            raise InvalidIngredientError(
                f"lockedPicks dishId={lp.dish_id} có role={dish.role.value}, "
                f"nhưng request yêu cầu role={lp.role.value}"
            )


def _drop_stale_meal_log(
    log: list[MealLogEntry], start_date, no_repeat_days: int
) -> list[MealLogEntry]:
    """Per §15 #4: silently drop entries older than the no-repeat window."""
    kept: list[MealLogEntry] = []
    for entry in log:
        age_days = (start_date - entry.date).days
        if 0 <= age_days <= no_repeat_days:
            kept.append(entry)
    return kept


def _build_day_plan(
    day_index: int,
    start_date,
    picks: dict[tuple[int, MealType], list[Dish]],
) -> DayPlan:
    meals_kwargs: dict[str, list[MealDishEntry]] = {}
    totals = {"calories": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0}
    for meal in MEAL_TYPES:
        entries: list[MealDishEntry] = []
        for dish in picks.get((day_index, meal), []):
            entries.append(
                MealDishEntry(
                    dishId=dish.dish_id,
                    role=dish.role,
                    missingIngredient=[],
                )
            )
            n = dish.nutrition_per_serving
            totals["calories"] += n.calories
            totals["protein"] += n.protein
            totals["carb"] += n.carb
            totals["fat"] += n.fat
        meals_kwargs[meal.value] = entries

    return DayPlan(
        day=day_index + 1,
        date=start_date + timedelta(days=day_index),
        meals=DayMeals(**meals_kwargs),
        nutrition=DayNutrition(
            calories=round(totals["calories"], 2),
            protein=round(totals["protein"], 2),
            carb=round(totals["carb"], 2),
            fat=round(totals["fat"], 2),
        ),
    )


def _build_summary(plan: list[DayPlan], tdee: float, target_kg: float, plan_days: int) -> Summary:
    """Per §15 #6 answer (locked 2026-04-22): targetCalories = (tdee + daily_delta) × planDays."""
    total_cal = sum(d.nutrition.calories for d in plan)
    total_prot = sum(d.nutrition.protein for d in plan)
    total_carb = sum(d.nutrition.carb for d in plan)
    total_fat = sum(d.nutrition.fat for d in plan)

    target_total = target_cal_total(tdee, target_kg, plan_days)
    deviation = (total_cal - target_total) / target_total if target_total else 0.0

    return Summary(
        avgDailyCalories=round(total_cal / plan_days, 2),
        targetCalories=round(target_total, 2),
        deviation=round(deviation, 2),
        avgDailyProtein=round(total_prot / plan_days, 2),
        avgDailyCarbs=round(total_carb / plan_days, 2),
        avgDailyFat=round(total_fat / plan_days, 2),
    )


def recommend(req: RecommendRequest, snapshot: DBSnapshot, no_repeat_days: int) -> MealPlanResponse:
    valid_ing_ids = set(snapshot.ingredients_by_id.keys())

    _validate_fridge(req, valid_ing_ids)
    _validate_locked_picks(req, snapshot)

    # Dish được giữ toàn bộ dù có ingredient ngoài whitelist (gia vị, v.v.) —
    # những ingredient đó sẽ bị skip trong stock/nutrition/shopping logic.
    candidate_dishes = snapshot.dishes
    filtered_log = _drop_stale_meal_log(req.recent_meal_log, req.start_date, no_repeat_days)

    goal = classify_goal(req.goal.target_kg)
    target_cpd = target_cal_per_day(req.tdee, req.goal.target_kg)

    try:
        result = solve(
            SolveInput(
                plan_days=req.plan_days,
                start_date=req.start_date,
                meal_structure=req.meal_structure,
                target_cal_per_day=target_cpd,
                goal=goal,
                weight_kg=req.weight,
                fridge=req.fridge,
                recent_meal_log=filtered_log,
                candidate_dishes=candidate_dishes,
                user_id=req.user_id,
                locked_picks=req.locked_picks,
            )
        )
    except MealRecommenderError as exc:
        logger.warning("Solver failed: {exc}", exc=str(exc))
        return MealPlanResponse(status="failed", plan=[], summary=None, shoppingList=[])

    plan = [_build_day_plan(d, req.start_date, result.picks) for d in range(req.plan_days)]

    compute_missing_per_dish(
        plan,
        req.fridge,
        snapshot.dishes_by_id,
        snapshot.ingredients_by_id,
        derived_number_to_gam=snapshot.derived_number_to_gam,
    )
    shopping = build_shopping_list(plan, snapshot.ingredients_by_id)
    summary = _build_summary(plan, req.tdee, req.goal.target_kg, req.plan_days)

    return MealPlanResponse(status="success", plan=plan, summary=summary, shoppingList=shopping)
