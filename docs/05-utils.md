# 05 — Utils (Pure helpers)

Thư mục: [`app/utils/`](../app/utils/)

Hàm thuần toán — không có I/O, không có side-effect. Dễ test.

## [`nutrition.py`](../app/utils/nutrition.py) — công thức dinh dưỡng

### Hằng số macro targets

Theo ISSN / ACSM / WHO. Range chứ không phải điểm.

```python
MACRO_TARGETS = {
    "weight_loss": MacroTarget(
        protein_g_per_kg=(1.6, 2.2),    # ISSN cutting
        carb_pct=(0.45, 0.55),
        fat_pct=(0.20, 0.30),
    ),
    "maintain": MacroTarget(
        protein_g_per_kg=(1.2, 1.6),
        carb_pct=(0.45, 0.60),
        fat_pct=(0.25, 0.35),
    ),
    "weight_gain": MacroTarget(
        protein_g_per_kg=(1.4, 2.0),    # ISSN muscle gain
        carb_pct=(0.50, 0.60),
        fat_pct=(0.20, 0.30),
    ),
}
```

### Phân loại goal

```python
classify_goal(target_kg_per_week) → "weight_loss" | "maintain" | "weight_gain"

   < -0.1  →  weight_loss
   ≥  0.1  →  weight_gain
   else    →  maintain        (gồm cả ±0.1 biên an toàn)
```

### Công thức chốt (§15 #6)

```python
daily_delta(target_kg) = (target_kg × 7700) / 7     # kcal/ngày

target_cal_per_day(tdee, target_kg) = tdee + daily_delta(target_kg)

target_cal_total(tdee, target_kg, plan_days)
    = target_cal_per_day(tdee, target_kg) × plan_days         # dùng trong Summary
```

**Hằng số `7700`**: 1 kg mỡ ≈ 7700 kcal (ACSM). Sống trong [`Settings.kcal_per_kg`](../app/core/config.py)
để dễ override.

**Ví dụ**:
| tdee | targetKg (kg/tuần) | daily_delta | target_cal/ngày |
|---|---|---|---|
| 2150 | -0.5 | -550 | 1600 (cutting aggressive) |
| 2150 |  0.0 |    0 | 2150 (maintain) |
| 2150 | +0.5 | +550 | 2700 (surplus) |

### Ai gọi?

- `services/recommend.py`:
  - `classify_goal()` để chọn `MACRO_TARGETS` row
  - `target_cal_per_day()` → truyền vào solver constraint C3
  - `target_cal_total()` → tính `summary.targetCalories`
- `services/constraints/macro.py`: đọc `MACRO_TARGETS[goal]` để tạo bound.

## [`date_utils.py`](../app/utils/date_utils.py)

2 helper nhỏ:
```python
add_days(dt, days)       # dt + timedelta(days)
days_between(later, earlier)   # (later - earlier).days, signed
```

Chưa dùng nhiều — dự phòng cho logic ngày tháng phức tạp về sau. Trong code hiện tại
`services/recommend.py` và `constraints/repetition.py` đang dùng `timedelta` trực tiếp;
có thể refactor qua helper để test đơn vị ngày dễ hơn.

## Test — [`tests/unit/test_nutrition.py`](../tests/unit/test_nutrition.py)

5 test xác nhận:
1. Biên phân loại goal (±0.1).
2. `daily_delta(-0.5) ≈ -550`.
3. Cutting: `target_cal_per_day(2150, -0.5) == 1600`.
4. Maintain: `target_cal_per_day(2150, 0) == 2150`.
5. Tổng: `target_cal_total(2150, -0.5, 5) == 8000`.

Công thức chốt (§15 #6) **phải** được test — nếu ai đó đổi từ (b) về (a) thì test này phải fail.
