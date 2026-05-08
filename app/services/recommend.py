from __future__ import annotations

import math
from datetime import timedelta

from loguru import logger

from app.core.cache import DBSnapshot
from app.core.config import get_settings
from app.core.exceptions import (
    InvalidIngredientError,
    MealRecommenderError,
    SolverTimeoutError,
)
from app.models.domain import Dish, MealLogEntry
from app.models.enums import MEAL_TYPES, MealType, Role
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
                f"Nguyên liệu trong tủ lạnh (id={item.ingredient_id}) không nằm "
                f"trong danh sách nguyên liệu được hệ thống nhận diện. "
                f"Vui lòng kiểm tra lại tủ lạnh hoặc liên hệ hỗ trợ."
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
                f"Món được pin (dishId={lp.dish_id}) không tồn tại trong "
                f"danh sách món ăn của hệ thống. Vui lòng chọn món khác."
            )
        if dish.role != lp.role:
            raise InvalidIngredientError(
                f"Món được pin (dishId={lp.dish_id}) có vai trò "
                f"'{dish.role.value}', không khớp với vai trò "
                f"'{lp.role.value}' bạn yêu cầu. Vui lòng chọn lại."
            )


_ROLE_ATTR = {Role.MAINDISH: "main_dish", Role.SOUP: "soup", Role.VEGETABLE: "vegetable"}
_ROLE_LABEL_VI = {Role.MAINDISH: "món chính", Role.SOUP: "canh", Role.VEGETABLE: "rau"}


def _needed_per_day(req: RecommendRequest, role: Role) -> int:
    return sum(
        getattr(getattr(req.meal_structure, meal_name), _ROLE_ATTR[role])
        for meal_name in ("breakfast", "lunch", "dinner")
    )


def _suggest_target_kg(
    user_target_kg: float,
    tdee: float,
    total_min: float,
    total_max: float,
    max_delta: int = 300,
) -> float | None:
    """Gợi ý targetKg khả thi gần với input của user nhất.

    Logic:
      - Tính khoảng calo/ngày khả thi: [total_min - max_delta, total_max + max_delta].
      - Quy đổi ngược về targetKg/tuần qua công thức: targetKg = (cal - tdee) × 7 / kcal_per_kg.
      - Clamp vào [-0.5, 0.5] (giới hạn schema).
      - Nếu user_target_kg ngoài khoảng → snap về biên gần nhất.
      - Nếu trong khoảng (lỗi do macro/no-repeat) → kéo 0.2 về phía 0.
      - Round 0.1 theo chiều an toàn (±0.5 → ±0.3 chứ không phải ±0.4).
      - Trả None nếu không có gợi ý hữu ích (≈ user input).
    """
    kcal_per_kg = get_settings().kcal_per_kg
    target_cal_lo = total_min - max_delta
    target_cal_hi = total_max + max_delta

    target_kg_lo_raw = (target_cal_lo - tdee) * 7 / kcal_per_kg
    target_kg_hi_raw = (target_cal_hi - tdee) * 7 / kcal_per_kg

    feasible_lo = max(-0.5, target_kg_lo_raw)
    feasible_hi = min(0.5, target_kg_hi_raw)

    if feasible_lo > feasible_hi:
        return None

    if user_target_kg < feasible_lo:
        suggested_raw = feasible_lo
    elif user_target_kg > feasible_hi:
        suggested_raw = feasible_hi
    else:
        # Calo OK, nghi ngờ macro/no-repeat → kéo 0.2 về phía 0.
        if user_target_kg > 0.05:
            suggested_raw = max(0.0, user_target_kg - 0.2)
        elif user_target_kg < -0.05:
            suggested_raw = min(0.0, user_target_kg + 0.2)
        else:
            return None

    # Round 0.1 theo chiều an toàn:
    # user input cao hơn → floor (0.5 → 0.3 chứ không 0.4 sát biên)
    # user input thấp hơn → ceil (-0.5 → -0.3)
    if user_target_kg > suggested_raw:
        suggested = math.floor(suggested_raw * 10) / 10
    elif user_target_kg < suggested_raw:
        suggested = math.ceil(suggested_raw * 10) / 10
    else:
        suggested = round(suggested_raw, 1)

    suggested = max(-0.5, min(0.5, suggested))

    if abs(suggested - user_target_kg) < 0.05:
        return None

    return round(suggested, 1)


def _format_target_kg_suggestion(target_kg: float) -> str:
    """+0.3 → 'tăng 0.3 kg/tuần'; -0.3 → 'giảm 0.3 kg/tuần'; 0.0 → 'duy trì cân nặng'."""
    if target_kg > 0.05:
        return f"tăng {target_kg:.1f} kg/tuần"
    if target_kg < -0.05:
        return f"giảm {abs(target_kg):.1f} kg/tuần"
    return "duy trì cân nặng (targetKg = 0)"


def _analyze_infeasibility(
    req: RecommendRequest,
    candidate_dishes: list[Dish],
    target_cpd: float,
    exc: MealRecommenderError,
) -> str:
    """Heuristic phân tích lý do solver fail để tạo message hữu ích cho user.

    Check theo thứ tự:
      1. Timeout — nói thẳng (không phải vấn đề input)
      2. Pool dish < số slot cần/ngày cho từng role
      3. Calorie target nằm ngoài [min, max] đạt được sau relax tối đa
      4. lockedPicks tạo xung đột (heuristic)
      5. Fallback: nói chung chung
    """
    if isinstance(exc, SolverTimeoutError):
        return (
            "Hệ thống tính toán vượt thời gian cho phép. "
            "Có thể plan quá dài hoặc tủ lạnh có quá nhiều nguyên liệu. "
            "Vui lòng thử lại với planDays nhỏ hơn."
        )

    pool_by_role: dict[Role, list[Dish]] = {
        Role.MAINDISH: [],
        Role.SOUP: [],
        Role.VEGETABLE: [],
    }
    for d in candidate_dishes:
        if d.role in pool_by_role:
            pool_by_role[d.role].append(d)

    pool_issues: list[str] = []
    for role in (Role.MAINDISH, Role.SOUP, Role.VEGETABLE):
        needed = _needed_per_day(req, role)
        if needed == 0:
            continue
        pool_size = len(pool_by_role[role])
        if pool_size < needed:
            pool_issues.append(
                f"chỉ có {pool_size} {_ROLE_LABEL_VI[role]} trong database "
                f"nhưng cấu trúc bữa ăn cần {needed} món/ngày"
            )
    if pool_issues:
        return "Không đủ món để tạo kế hoạch: " + "; ".join(pool_issues) + "."

    total_min = 0.0
    total_max = 0.0
    for meal_name in ("breakfast", "lunch", "dinner"):
        slot = getattr(req.meal_structure, meal_name)
        for role in (Role.MAINDISH, Role.SOUP, Role.VEGETABLE):
            count = getattr(slot, _ROLE_ATTR[role])
            if count == 0 or not pool_by_role[role]:
                continue
            cals = [d.calories for d in pool_by_role[role]]
            total_min += count * min(cals)
            total_max += count * max(cals)

    # Relaxation ladder cho phép calorie_delta lên đến 300 (xem _relax_schedule)
    max_delta = 300
    suggested = _suggest_target_kg(
        req.goal.target_kg, req.tdee, total_min, total_max, max_delta
    )
    suggestion_phrase = (
        f" Gợi ý: {_format_target_kg_suggestion(suggested)}."
        if suggested is not None
        else ""
    )

    if target_cpd > total_max + max_delta:
        return (
            f"Calo mục tiêu ({target_cpd:.0f} kcal/ngày) cao hơn khả năng "
            f"tối đa của các món có sẵn ({total_max:.0f} kcal/ngày)."
            + (suggestion_phrase or " Hãy giảm targetKg hoặc tăng số món/bữa.")
        )
    if target_cpd < total_min - max_delta:
        return (
            f"Calo mục tiêu ({target_cpd:.0f} kcal/ngày) thấp hơn calo "
            f"tối thiểu của các món có sẵn ({total_min:.0f} kcal/ngày)."
            + (suggestion_phrase or " Hãy tăng targetKg hoặc giảm số món/bữa.")
        )

    if req.locked_picks:
        return (
            f"Đã pin {len(req.locked_picks)} món qua lockedPicks nhưng các "
            f"món này tạo xung đột với mục tiêu calo/macro. "
            f"Hãy bỏ bớt món pin hoặc đổi món pin khác."
        )

    return (
        "Không tìm được kế hoạch thoả mãn đồng thời mục tiêu calo, macro và "
        "quy tắc không lặp món."
        + (
            suggestion_phrase + " Hoặc bạn có thể giảm số ngày kế hoạch (planDays)."
            if suggested is not None
            else " Hãy thử nới mục tiêu cân nặng (targetKg) gần 0 hơn, hoặc "
            "giảm số ngày kế hoạch (planDays)."
        )
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
        message = _analyze_infeasibility(req, candidate_dishes, target_cpd, exc)
        return MealPlanResponse(
            status="FAILED",
            message=message,
            plan=[],
            summary=None,
            shoppingList=[],
        )

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

    return MealPlanResponse(status="SUCCESS", plan=plan, summary=summary, shoppingList=shopping)
