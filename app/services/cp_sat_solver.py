from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from loguru import logger
from ortools.sat.python import cp_model

from app.core.config import get_settings
from app.core.exceptions import SolverInfeasibleError, SolverTimeoutError
from app.models.domain import Dish, MealLogEntry
from app.models.enums import MEAL_TYPES, ROLES, MealType, Role
from app.models.input import FridgeItem, LockedPick, MealStructure
from app.services.constraints.calorie import add_calorie
from app.services.constraints.macro import add_macro
from app.services.constraints.repetition import (
    add_no_repeat_within_plan,
    add_recent_meal_log,
)
from app.services.constraints.structural import add_structural, required_count
from app.services.objective import ObjectiveWeights, build_objective
from app.utils.nutrition import GoalType

VarKey = tuple[int, MealType, Role, int]


@dataclass
class SolveInput:
    plan_days: int
    start_date: datetime
    meal_structure: MealStructure
    target_cal_per_day: float
    goal: GoalType
    weight_kg: float
    fridge: list[FridgeItem]
    recent_meal_log: list[MealLogEntry]
    candidate_dishes: list[Dish]
    user_id: int
    locked_picks: list[LockedPick] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.locked_picks is None:
            self.locked_picks = []


@dataclass
class SolveResult:
    status: str  # "SUCCESS" | "FAILED"
    picks: dict[tuple[int, MealType], list[Dish]]  # (day, meal) -> list of dishes in meal order
    relax_notes: list[str]


def _partition_by_role(dishes: list[Dish]) -> dict[Role, list[Dish]]:
    by_role: dict[Role, list[Dish]] = {r: [] for r in ROLES}
    for dish in dishes:
        by_role[dish.role].append(dish)
    return by_role


def _build_vars(
    model: cp_model.CpModel,
    plan_days: int,
    dishes_by_role: dict[Role, list[Dish]],
) -> dict[VarKey, cp_model.IntVar]:
    x: dict[VarKey, cp_model.IntVar] = {}
    for d in range(plan_days):
        for meal in MEAL_TYPES:
            for role in ROLES:
                for i, dish in enumerate(dishes_by_role[role]):
                    var = model.NewBoolVar(f"x_{d}_{meal.value}_{role.value}_{i}")
                    x[(d, meal, role, i)] = var
                    # A dish can only appear in a meal if its mealTypes allow it.
                    if meal not in dish.meal_types:
                        model.Add(var == 0)
    return x


def _expiring_map(fridge: list[FridgeItem]) -> dict[int, datetime]:
    return {f.ingredient_id: f.due_date for f in fridge}


def _make_ids_by_role(dishes_by_role: dict[Role, list[Dish]]) -> dict[Role, list[int]]:
    return {r: [d.dish_id for d in ds] for r, ds in dishes_by_role.items()}


def _total_required(meal_structure: MealStructure) -> int:
    total = 0
    for meal in MEAL_TYPES:
        for role in ROLES:
            total += required_count(meal_structure, meal, role)
    return total


def _apply_locked_picks(
    model: cp_model.CpModel,
    x: dict[VarKey, cp_model.IntVar],
    dishes_by_role: dict[Role, list[Dish]],
    locked_picks: list[LockedPick],
) -> None:
    """Force x[d, meal, role, idx] == 1 cho mỗi (day, meal, role, dishId) trong locked_picks.

    `day` trong LockedPick là 1-indexed (như user thấy), convert sang 0-indexed cho `x`.
    Dish phải tồn tại trong `dishes_by_role[role]` — đã được validate ở recommend.py.
    """
    for lp in locked_picks:
        role_pool = dishes_by_role[lp.role]
        idx = next((i for i, d in enumerate(role_pool) if d.dish_id == lp.dish_id), None)
        if idx is None:
            raise SolverInfeasibleError(
                f"Locked pick dishId={lp.dish_id} không có trong pool {lp.role.value}. "
                f"(Đáng lẽ phải bị reject ở validation tầng trên — bug.)"
            )
        d_idx = lp.day - 1  # 1-indexed → 0-indexed
        model.Add(x[(d_idx, lp.meal, lp.role, idx)] == 1)


def _build_model(
    inp: SolveInput,
    calorie_delta: int,
    no_repeat_window: int,
    macro_relax_pct: float,
    weights: ObjectiveWeights,
) -> tuple[cp_model.CpModel, dict[VarKey, cp_model.IntVar], dict[Role, list[Dish]]]:
    model = cp_model.CpModel()
    dishes_by_role = _partition_by_role(inp.candidate_dishes)
    x = _build_vars(model, inp.plan_days, dishes_by_role)

    add_structural(
        model, x, inp.plan_days, inp.meal_structure, _make_ids_by_role(dishes_by_role)
    )
    add_no_repeat_within_plan(
        model, x, inp.plan_days, _make_ids_by_role(dishes_by_role), no_repeat_window
    )
    add_recent_meal_log(
        model,
        x,
        inp.plan_days,
        inp.start_date,
        inp.recent_meal_log,
        _make_ids_by_role(dishes_by_role),
        no_repeat_window,
    )
    add_calorie(model, x, inp.plan_days, dishes_by_role, inp.target_cal_per_day, calorie_delta)
    add_macro(
        model, x, inp.plan_days, dishes_by_role, inp.goal, inp.weight_kg, macro_relax_pct
    )

    # Locked picks: ép x == 1 cho các slot user đã pin. Áp dụng SAU C1/C2/C3/C4 và
    # objective — không thay đổi chúng, chỉ ràng buộc thêm. Nếu lock + macro strict
    # không feasible, relaxation ladder ở solve() sẽ nới calorie/macro nhưng locked
    # picks vẫn giữ.
    if inp.locked_picks:
        _apply_locked_picks(model, x, dishes_by_role, inp.locked_picks)

    fridge_ids = {f.ingredient_id for f in inp.fridge}
    build_objective(
        model,
        x,
        inp.plan_days,
        dishes_by_role,
        fridge_ids,
        _expiring_map(inp.fridge),
        inp.start_date,
        weights,
    )

    return model, x, dishes_by_role


def _run_solver(model: cp_model.CpModel, user_id: int) -> tuple[cp_model.CpSolver, int]:
    settings = get_settings()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.solver_timeout_seconds
    solver.parameters.num_search_workers = settings.solver_num_workers
    solver.parameters.random_seed = hash(user_id) % (2**31)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    return solver, status


def _extract_picks(
    solver: cp_model.CpSolver,
    x: dict[VarKey, cp_model.IntVar],
    plan_days: int,
    dishes_by_role: dict[Role, list[Dish]],
    meal_structure: MealStructure,
) -> dict[tuple[int, MealType], list[Dish]]:
    out: dict[tuple[int, MealType], list[Dish]] = {}
    for d in range(plan_days):
        for meal in MEAL_TYPES:
            picks: list[Dish] = []
            for role in (Role.MAINDISH, Role.SOUP, Role.VEGETABLE):
                need = required_count(meal_structure, meal, role)
                if need == 0:
                    continue
                for i, dish in enumerate(dishes_by_role[role]):
                    if solver.Value(x[(d, meal, role, i)]) == 1:
                        picks.append(dish)
            out[(d, meal)] = picks
    return out


# Relaxation plan from §7.1
# (calorie_delta, no_repeat_window_override, macro_relax_pct, note)
def _relax_schedule(
    base_delta: int, base_window: int
) -> Iterable[tuple[int, int, float, str]]:
    yield (base_delta, base_window, 0.0, "initial")
    yield (200, base_window, 0.0, "calorie_delta=200")
    yield (300, base_window, 0.0, "calorie_delta=300")
    yield (300, 1, 0.0, "no_repeat=1")
    yield (300, 0, 0.0, "no_repeat=0")
    yield (300, 0, 0.15, "macro±15%")


def solve(inp: SolveInput) -> SolveResult:
    if not inp.candidate_dishes:
        raise SolverInfeasibleError("No candidate dishes available")
    if _total_required(inp.meal_structure) == 0:
        raise SolverInfeasibleError("mealStructure requires zero dishes")

    settings = get_settings()
    weights = ObjectiveWeights(
        fridge=settings.weight_fridge,
        expiry=settings.weight_expiry,
        diversity=settings.weight_diversity,
        shopping_penalty=settings.weight_shopping_penalty,
        expiry_window_days=settings.expiry_window_days,
    )

    relax_notes: list[str] = []
    last_status_name = "UNKNOWN"
    timeout_count = 0  # track tổng số pass timeout để phân biệt fail-by-timeout vs fail-by-infeasible

    for calorie_delta, window, macro_relax, note in _relax_schedule(
        settings.calorie_delta, settings.no_repeat_days
    ):
        model, x, dishes_by_role = _build_model(
            inp, calorie_delta, window, macro_relax, weights
        )
        solver, status = _run_solver(model, inp.user_id)
        last_status_name = solver.StatusName(status)
        logger.info(
            "Solver pass: note={note} status={status} wall={wall:.3f}s",
            note=note,
            status=last_status_name,
            wall=solver.WallTime(),
        )

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            picks = _extract_picks(solver, x, inp.plan_days, dishes_by_role, inp.meal_structure)
            relax_notes.append(f"success@{note}")
            return SolveResult(status="SUCCESS", picks=picks, relax_notes=relax_notes)

        if status == cp_model.MODEL_INVALID:
            logger.error("CP-SAT MODEL_INVALID at pass '{note}'", note=note)
            raise SolverInfeasibleError(f"CP-SAT model invalid at pass '{note}'")

        if status == cp_model.UNKNOWN:
            # Timeout — không raise ngay. Pass kế tiếp có ràng buộc lỏng hơn (calorie_delta
            # to hơn, no_repeat nhỏ hơn, macro±15%) thường giải nhanh hơn → tiếp tục thử.
            timeout_count += 1
            logger.warning(
                "CP-SAT UNKNOWN (timeout) at '{note}', falling through to next relaxation pass",
                note=note,
            )

        relax_notes.append(f"{note}:{last_status_name}")

    # Hết schedule mà chưa tìm được. Phân biệt 2 case để analyzer trả message đúng:
    #   - Tất cả pass đều UNKNOWN → SolverTimeoutError (model quá khó, không phải vô nghiệm)
    #   - Có pass INFEASIBLE → SolverInfeasibleError (model thực sự vô nghiệm)
    if timeout_count == sum(1 for _ in _relax_schedule(settings.calorie_delta, settings.no_repeat_days)):
        raise SolverTimeoutError(
            f"All {timeout_count} relaxation passes timed out (last status={last_status_name})"
        )
    raise SolverInfeasibleError(
        f"All relaxation passes failed (last status={last_status_name}, timeouts={timeout_count})"
    )
