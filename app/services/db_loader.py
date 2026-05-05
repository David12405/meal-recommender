from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from loguru import logger
from pydantic import TypeAdapter, ValidationError

from app.core.config import get_settings
from app.core.exceptions import DBLoadError
from app.models.domain import (
    Dish,
    DishIngredient,
    DishIngredientRow,
    Ingredient,
    NutritionPerServing,
)
from app.models.enums import MEAL_TYPES, MealType, Role, Unit

# Tên file mặc định trong data/ folder. Tên match với file JSON user xuất từ Crawl_data.
DISHES_FILENAME = "Dish.json"
DISH_INGREDIENTS_FILENAME = "DishIngredient.json"
INGREDIENTS_FILENAME = "ingredient.json"

_DishListAdapter = TypeAdapter(list[Dish])
_IngredientListAdapter = TypeAdapter(list[Ingredient])
_DishIngredientRowListAdapter = TypeAdapter(list[DishIngredientRow])

# §4.4 — default mealTypes rule until backend adds the field.
_DEFAULT_MEAL_TYPES: dict[Role, list[MealType]] = {
    Role.MAINDISH: list(MEAL_TYPES),
    Role.SOUP: [MealType.LUNCH, MealType.DINNER],
    Role.VEGETABLE: list(MEAL_TYPES),
}


def _read_json(path: Path) -> object:
    if not path.exists():
        raise DBLoadError(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DBLoadError(f"{path.name} is not valid JSON: {exc}") from exc


def _validate_cross_refs(
    dishes: list[Dish],
    ingredients: list[Ingredient],
    rows: list[DishIngredientRow],
) -> None:
    settings = get_settings()
    if len(ingredients) > settings.max_ingredient_classes:
        raise DBLoadError(
            f"Too many ingredient classes: {len(ingredients)} > "
            f"{settings.max_ingredient_classes}"
        )

    dish_ids = {d.dish_id for d in dishes}
    ing_ids = {i.ingredient_id for i in ingredients}

    unknown_dish = {r.dish_id for r in rows if r.dish_id not in dish_ids}
    if unknown_dish:
        raise DBLoadError(
            f"dish_ingredients references {len(unknown_dish)} unknown dishId(s); "
            f"first few: {sorted(unknown_dish)[:5]}"
        )
    unknown_ing = {r.ingredient_id for r in rows if r.ingredient_id not in ing_ids}
    if unknown_ing:
        # Không raise: dish được phép reference gia vị / nguyên liệu ngoài 62-class
        # whitelist (ví dụ quế, hồi). Những ingredient đó:
        #   - Không đóng góp nutrition (bị skip trong _compute_nutrition).
        #   - Không vào stock/shopping (bị skip trong missing_ingredient).
        # Coi như "user tự túc gia vị" — hợp lý vì CV model chỉ nhận diện 62 class.
        logger.info(
            "dish_ingredients references {n} ingredient(s) outside the 62-class whitelist "
            "(treated as 'user-supplied', e.g. spices): {ids}",
            n=len(unknown_ing),
            ids=sorted(unknown_ing)[:10],
        )


def _merge_dish_ingredients(
    dishes: list[Dish], rows: list[DishIngredientRow]
) -> None:
    """Group junction rows by dishId and attach to the corresponding Dish."""
    by_dish: dict[int, list[DishIngredient]] = defaultdict(list)
    for row in rows:
        by_dish[row.dish_id].append(
            DishIngredient(
                ingredientId=row.ingredient_id,
                quantity=row.amount,
                unit=row.unit,
                gramsEquivalent=row.grams_equivalent,
            )
        )
    for dish in dishes:
        dish.ingredients = by_dish.get(dish.dish_id, [])


def _compute_nutrition(
    dishes: list[Dish], ingredients: list[Ingredient]
) -> None:
    """Fill dish.nutrition_per_serving from ingredient per-100g stats.

    Calories: trust backend's dish.calories (already factors yield/retention).
    Protein/carb/fat: compute locally — backend doesn't store them per-dish (§4.5).
    """
    ing_map = {i.ingredient_id: i for i in ingredients}
    dropped: list[int] = []

    for dish in dishes:
        protein = carb = fat = 0.0
        for di in dish.ingredients:
            meta = ing_map.get(di.ingredient_id)
            if meta is None:
                # Cross-ref đã validate, nhưng có rows ingredient ngoài 62-class
                # whitelist (gia vị không CV-detect) — ignore khỏi nutrition.
                continue
            # SPOON rows = gia vị ước lượng. gramsEqui thường None.
            # Lượng đóng góp macro không đáng kể → skip.
            if di.unit is Unit.SPOON or di.grams_equivalent is None or di.grams_equivalent == 0:
                continue
            factor = di.grams_equivalent / 100.0
            protein += meta.protein * factor
            carb += meta.carb * factor
            fat += meta.fat * factor

        dish.nutrition_per_serving = NutritionPerServing(
            calories=dish.calories,
            protein=round(protein, 1),
            carb=round(carb, 1),
            fat=round(fat, 1),
        )

        if not dish.ingredients:
            dropped.append(dish.dish_id)

    if dropped:
        logger.warning(
            "Computed nutrition for {total} dishes; {n} had no ingredient rows "
            "(protein/carb/fat=0 — solver will likely reject via macro constraint): {ids}",
            total=len(dishes),
            n=len(dropped),
            ids=dropped[:10],
        )


def _apply_default_meal_types(dishes: list[Dish]) -> None:
    for dish in dishes:
        if not dish.meal_types:
            dish.meal_types = list(
                _DEFAULT_MEAL_TYPES.get(dish.role, [MealType.LUNCH, MealType.DINNER])
            )


def _derive_number_to_gam(rows: list[DishIngredientRow]) -> dict[int, float]:
    """Suy ra `gam_per_unit` cho mỗi ingredient từ các row có `unit=NUMBER` trong junction.

    Lý do: `ingredient_full` không có cột `numberToGam`. Khi fridge gửi NUMBER (vd
    "5 quả trứng"), service cần biết 1 quả nặng bao nhiêu gram. Junction table đã
    chứa thông tin này gián tiếp qua các row recipe (vd "1 quả trứng = 70g").

    Logic:
      - Lọc các row `unit=NUMBER` có `gramsEqui` và `amount > 0`.
      - Tính ratio `gramsEqui / amount` = grams per 1 unit cho row đó.
      - Average các sample của cùng `ingredient_id` (handle nhiều dish với ratio
        hơi khác nhau, vd 1 quả trứng = 60g vs 70g).

    Trả về `{ingredient_id: gam_per_unit}`. Ingredient không có row NUMBER nào sẽ
    không xuất hiện trong map → fridge gửi NUMBER cho id đó sẽ raise lỗi 400.
    """
    samples: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        if (
            row.unit is Unit.NUMBER
            and row.amount > 0
            and row.grams_equivalent
            and row.grams_equivalent > 0
        ):
            samples[row.ingredient_id].append(row.grams_equivalent / row.amount)

    derived = {iid: sum(s) / len(s) for iid, s in samples.items()}
    if derived:
        logger.info(
            "Derived numberToGam cho {n} ingredient từ junction: {sample}",
            n=len(derived),
            sample=dict(list(derived.items())[:5]),
        )
    return derived


def load_from_local_files(
    data_dir: Path | None = None,
) -> tuple[list[Dish], list[Ingredient], dict[int, float], int]:
    """Đọc 3 file JSON từ folder `data/` (commit cùng code), validate + merge.

    Files mặc định:
      - data/Dish.json
      - data/DishIngredient.json
      - data/ingredient.json

    Returns:
      (dishes, ingredients, derived_number_to_gam, dish_ingredients_count)
    """
    settings = get_settings()
    folder = data_dir or settings.data_dir

    raw_dishes = _read_json(folder / DISHES_FILENAME)
    raw_ingredients = _read_json(folder / INGREDIENTS_FILENAME)
    raw_rows = _read_json(folder / DISH_INGREDIENTS_FILENAME)

    try:
        dishes = _DishListAdapter.validate_python(raw_dishes)
        ingredients = _IngredientListAdapter.validate_python(raw_ingredients)
        rows = _DishIngredientRowListAdapter.validate_python(raw_rows)
    except ValidationError as exc:
        raise DBLoadError(f"Schema validation failed: {exc}") from exc

    _validate_cross_refs(dishes, ingredients, rows)
    _merge_dish_ingredients(dishes, rows)
    _compute_nutrition(dishes, ingredients)
    _apply_default_meal_types(dishes)
    derived_number_to_gam = _derive_number_to_gam(rows)

    logger.info(
        "Loaded local data: dishes={d}, ingredients={i}, junction_rows={r}",
        d=len(dishes),
        i=len(ingredients),
        r=len(rows),
    )
    return dishes, ingredients, derived_number_to_gam, len(rows)
