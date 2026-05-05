from __future__ import annotations

import pytest

from app.utils.nutrition import (
    classify_goal,
    daily_delta,
    target_cal_per_day,
    target_cal_total,
)


def test_classify_goal_boundaries():
    assert classify_goal(-0.5) == "weight_loss"
    assert classify_goal(-0.1) == "maintain"
    assert classify_goal(0.0) == "maintain"
    assert classify_goal(0.1) == "maintain"
    assert classify_goal(0.5) == "weight_gain"


def test_daily_delta_weight_loss():
    assert daily_delta(-0.5) == pytest.approx(-550.0, rel=1e-6)


def test_target_cal_per_day_cutting():
    assert target_cal_per_day(2150, -0.5) == pytest.approx(1600, rel=1e-6)


def test_target_cal_per_day_maintain():
    assert target_cal_per_day(2150, 0.0) == 2150


def test_target_cal_total_uses_locked_formula():
    # (§15 #6 answer) target = (TDEE + daily_delta) × planDays
    assert target_cal_total(2150, -0.5, 5) == pytest.approx(8000, rel=1e-6)
