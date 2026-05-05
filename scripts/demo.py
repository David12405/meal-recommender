"""End-to-end demo chạy qua 2 endpoint thật của service.

Cách chạy (từ thư mục d:/PBL5/meal-recommender):
    python scripts/demo.py

Luồng:
  1. Mock httpx responses để /update-db nhận được 3 URL "giả" và trả JSON mock.
  2. Gọi POST /update-db qua FastAPI TestClient (không cần uvicorn).
  3. Gọi POST /recommend với sample_request.json.
  4. Print đẹp request + response.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Đảm bảo import được app/ khi chạy script từ bất cứ đâu
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Bump solver timeout cho demo dataset lớn (75 dish × 7 ngày × cutting goal).
# Production set qua .env.
os.environ.setdefault("SOLVER_TIMEOUT_SECONDS", "30")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

MOCK_DIR = ROOT / "mock_data"
URLS = {
    "https://mock/dishes.json": MOCK_DIR / "dishes.json",
    "https://mock/ingredients.json": MOCK_DIR / "ingredients.json",
    "https://mock/dish_ingredients.json": MOCK_DIR / "dish_ingredients.json",
}


def _mock_transport_handler(request: httpx.Request) -> httpx.Response:
    """Serve one of the 3 mock JSON files based on URL."""
    url = str(request.url)
    path = URLS.get(url)
    if path is None:
        return httpx.Response(404, json={"error": f"unknown mock url: {url}"})
    return httpx.Response(200, content=path.read_bytes(), headers={"content-type": "application/json"})


def _patch_httpx():
    """Monkey-patch httpx.AsyncClient so db_loader's real httpx calls hit our mock."""
    import httpx as _httpx

    _real_init = _httpx.AsyncClient.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs["transport"] = _httpx.MockTransport(_mock_transport_handler)
        _real_init(self, *args, **kwargs)

    _httpx.AsyncClient.__init__ = _patched_init  # type: ignore[method-assign]


def _banner(text: str) -> None:
    bar = "═" * 78
    print(f"\n{bar}\n  {text}\n{bar}")


def main() -> None:
    _patch_httpx()
    client = TestClient(app)

    _banner("1. POST /health (trước khi load)")
    r = client.get("/health")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))

    _banner("2. POST /update-db")
    update_req = {
        "dishesUrl": "https://mock/dishes.json",
        "ingredientsUrl": "https://mock/ingredients.json",
        "dishIngredientsUrl": "https://mock/dish_ingredients.json",
    }
    print("REQUEST:")
    print(json.dumps(update_req, indent=2, ensure_ascii=False))
    r = client.post("/update-db", json=update_req)
    print(f"\nRESPONSE ({r.status_code}):")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    assert r.status_code == 200, "update-db thất bại"

    _banner("3. POST /health (sau khi load)")
    r = client.get("/health")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))

    _banner("4. POST /recommend")
    req = json.loads((MOCK_DIR / "sample_request.json").read_text(encoding="utf-8"))
    print("REQUEST:")
    print(json.dumps(req, indent=2, ensure_ascii=False))
    r = client.post("/recommend", json=req)
    body = r.json()
    print(f"\nRESPONSE ({r.status_code}) status={body.get('status')}")

    if body.get("status") == "failed":
        print("⚠  Solver không giải được — thử nới mealStructure hoặc targetKg.")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return

    _banner("5. Response chi tiết")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    _banner("6. Tóm tắt dễ đọc")
    summary = body["summary"]
    print(
        f"Target calo/ngày: {summary['targetCalories'] / req['planDays']:.0f} kcal\n"
        f"Avg calo/ngày:    {summary['avgDailyCalories']} kcal\n"
        f"Deviation:        {summary['deviation'] * 100:+.1f}%\n"
        f"Avg protein/ngày: {summary['avgDailyProtein']}g\n"
        f"Avg carb/ngày:    {summary['avgDailyCarbs']}g\n"
        f"Avg fat/ngày:     {summary['avgDailyFat']}g\n"
    )

    # Bảng dish theo ngày
    print(f"{'Ngày':<6} {'Bữa':<10} {'Dish':<30} {'Role':<10}")
    print("-" * 70)
    # Build name lookup from mock
    dish_names = {
        d["id"]: d["name"]
        for d in json.loads((MOCK_DIR / "dishes.json").read_text(encoding="utf-8"))
    }
    for day in body["plan"]:
        for meal in ("breakfast", "lunch", "dinner"):
            for entry in day["meals"][meal]:
                name = dish_names.get(entry["dishId"], "?")
                print(f"{day['day']:<6} {meal:<10} {name:<30} {entry['role']:<10}")
        print(f"  → tổng calo ngày {day['day']}: {day['nutrition']['calories']} kcal")
        print()

    if body["shoppingList"]:
        print("Shopping list (dedup qua cả plan):")
        ing_names = {
            i["id"]: i["name"]
            for i in json.loads((MOCK_DIR / "ingredients.json").read_text(encoding="utf-8"))
        }
        for item in body["shoppingList"]:
            name = ing_names.get(item["ingredientId"], "?")
            print(f"  • {name:<15} {item['quantity']} {item['unit']}")

    # ════════════════════════════════════════════════════════════════════
    #  PART 2: REPLAN FLOW
    #  Giả lập: user nhìn plan, muốn đổi MAINDISH lunch ngày 3 sang dish khác.
    # ════════════════════════════════════════════════════════════════════
    _replan_demo(client, req, body)


# ════════════════════════════════════════════════════════════════════════
#  REPLAN HELPERS
# ════════════════════════════════════════════════════════════════════════

MEAL_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2}


def _build_locked_picks_for_swap(plan, swap_day, swap_meal, swap_role, new_dish_id):
    """Build lockedPicks list cho 1 swap.

    Lock: tất cả slot TRƯỚC (swap_day, swap_meal) + cùng slot với swap (đổi role bị swap).
    Để trống: slot SAU swap → solver tự re-solve.
    """
    locked = []
    swap_meal_idx = MEAL_ORDER[swap_meal]

    for day in plan:
        for meal_name in ("breakfast", "lunch", "dinner"):
            after = (
                day["day"] > swap_day
                or (day["day"] == swap_day and MEAL_ORDER[meal_name] > swap_meal_idx)
            )
            if after:
                continue  # solver re-solve
            for entry in day["meals"][meal_name]:
                is_swapped = (
                    day["day"] == swap_day
                    and meal_name == swap_meal
                    and entry["role"] == swap_role
                )
                locked.append(
                    {
                        "day": day["day"],
                        "meal": meal_name,
                        "role": entry["role"],
                        "dishId": new_dish_id if is_swapped else entry["dishId"],
                    }
                )
    return locked


def _pick_alternative_main_dish(dishes, current_dish_id, used_dish_ids, target_meal):
    """Tìm 1 dish MAIN_DISH thay thế, ưu tiên:
    1. Chưa có trong plan (tránh xung đột no-repeat).
    2. Hợp lệ với target_meal (mealTypes contains target_meal, hoặc không có field này).
    3. Calo gần giống current (để fit constraint dễ hơn).
    """
    current = next((d for d in dishes if d["id"] == current_dish_id), None)
    target_cal = current["calories"] if current else 500

    def is_meal_compatible(d):
        mts = d.get("mealTypes")
        return (mts is None) or (target_meal in mts)

    candidates = [
        d for d in dishes
        if d["type"] == "MAIN_DISH"
        and d["id"] != current_dish_id
        and d["id"] not in used_dish_ids
        and is_meal_compatible(d)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: abs(d["calories"] - target_cal))
    return candidates[0]


def _replan_demo(client, original_req, original_response):
    _banner("7. REPLAN — user đổi 1 món")

    # Chọn slot swap: ngày 3 lunch MAINDISH (nếu plan đủ 3 ngày + có lunch)
    if original_req["planDays"] < 3:
        print("⏭  Plan < 3 ngày, skip replan demo.")
        return

    plan = original_response["plan"]
    target_day = 3
    target_meal = "lunch"
    target_role = "MAINDISH"

    day3 = next((d for d in plan if d["day"] == target_day), None)
    if day3 is None:
        print(f"⏭  Không tìm thấy ngày {target_day}, skip.")
        return

    current_main = next(
        (e for e in day3["meals"][target_meal] if e["role"] == target_role), None
    )
    if current_main is None:
        print(f"⏭  Ngày {target_day} {target_meal} không có {target_role}, skip.")
        return

    dishes = json.loads((MOCK_DIR / "dishes.json").read_text(encoding="utf-8"))
    dish_names = {d["id"]: d["name"] for d in dishes}

    # Tập hợp dish IDs đang có trong plan để tránh chọn trùng (C2 no-repeat)
    used_ids = {
        e["dishId"]
        for d in plan
        for m in ("breakfast", "lunch", "dinner")
        for e in d["meals"][m]
    }

    alt = _pick_alternative_main_dish(
        dishes, current_main["dishId"], used_ids, target_meal
    )
    if alt is None:
        print("⏭  Không có dish MAIN_DISH thay thế.")
        return

    print(
        f"User swap:\n"
        f"  Ngày {target_day} {target_meal} {target_role}:\n"
        f"    [cũ] {dish_names.get(current_main['dishId'], '?')} (id={current_main['dishId']})\n"
        f"    [mới] {alt['name']} (id={alt['id']})"
    )

    # Build lockedPicks: lock day 1, 2, day 3 breakfast + lunch (với MAINDISH thay)
    locked_picks = _build_locked_picks_for_swap(
        plan,
        swap_day=target_day,
        swap_meal=target_meal,
        swap_role=target_role,
        new_dish_id=alt["id"],
    )
    print(f"\n→ Build {len(locked_picks)} lockedPicks "
          f"(slot trước swap + slot có swap đã apply)")

    _banner("8. POST /recommend với lockedPicks")
    replan_req = {**original_req, "lockedPicks": locked_picks}
    r = client.post("/recommend", json=replan_req)
    body2 = r.json()
    print(f"RESPONSE ({r.status_code}) status={body2.get('status')}")

    if body2.get("status") != "success":
        print("⚠  Replan thất bại:")
        print(json.dumps(body2, indent=2, ensure_ascii=False))
        return

    _banner("9. So sánh — bảng plan trước & sau replan")
    print(f"{'Ngày':<6} {'Bữa':<10} {'Role':<10} {'Trước':<28} {'Sau':<28} {'Status':<8}")
    print("-" * 96)
    plan_old = {(d["day"], m): d["meals"][m] for d in plan for m in ("breakfast", "lunch", "dinner")}
    plan_new = {
        (d["day"], m): d["meals"][m]
        for d in body2["plan"]
        for m in ("breakfast", "lunch", "dinner")
    }
    swap_meal_idx = MEAL_ORDER[target_meal]
    for day_n in range(1, original_req["planDays"] + 1):
        for meal_name in ("breakfast", "lunch", "dinner"):
            old_entries = plan_old.get((day_n, meal_name), [])
            new_entries = plan_new.get((day_n, meal_name), [])
            # Match theo role
            for role in ("MAINDISH", "SOUP", "VEGETABLE"):
                old = next((e for e in old_entries if e["role"] == role), None)
                new = next((e for e in new_entries if e["role"] == role), None)
                if old is None and new is None:
                    continue
                old_id = old["dishId"] if old else None
                new_id = new["dishId"] if new else None
                old_name = dish_names.get(old_id, "—")[:26]
                new_name = dish_names.get(new_id, "—")[:26]
                # Status
                is_after = day_n > target_day or (
                    day_n == target_day and MEAL_ORDER[meal_name] > swap_meal_idx
                )
                if is_after:
                    status = "RESOLVE" if old_id != new_id else "kept"
                elif day_n == target_day and meal_name == target_meal and role == target_role:
                    status = "SWAP"
                else:
                    status = "lock"
                print(f"{day_n:<6} {meal_name:<10} {role:<10} {old_name:<28} {new_name:<28} {status:<8}")
        print()

    # So sánh summary
    s1, s2 = original_response["summary"], body2["summary"]
    print(f"{'Metric':<22} {'Trước':>10} {'Sau':>10} {'Δ':>10}")
    print("-" * 56)
    for k in ("avgDailyCalories", "avgDailyProtein", "avgDailyCarbs", "avgDailyFat", "deviation"):
        print(f"{k:<22} {s1[k]:>10.2f} {s2[k]:>10.2f} {s2[k] - s1[k]:>+10.2f}")


if __name__ == "__main__":
    main()
