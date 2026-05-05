from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.exceptions import CacheNotLoadedError
from app.models.domain import Dish, Ingredient


@dataclass
class DBSnapshot:
    dishes: list[Dish]
    ingredients: list[Ingredient]
    updated_at: datetime
    # Map ingredient_id → grams per 1 NUMBER unit, derive từ DishIngredient junction
    # (xem db_loader._derive_number_to_gam). Dùng để convert fridge NUMBER → GAM
    # mà không cần ingredient_full có cột numberToGam.
    derived_number_to_gam: dict[int, float] = field(default_factory=dict)

    dishes_by_id: dict[int, Dish] = field(init=False)
    ingredients_by_id: dict[int, Ingredient] = field(init=False)

    def __post_init__(self) -> None:
        self.dishes_by_id = {d.dish_id: d for d in self.dishes}
        self.ingredients_by_id = {i.ingredient_id: i for i in self.ingredients}


class DBCache:
    """Thread-safe in-memory singleton holding the latest DB snapshot."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: DBSnapshot | None = None

    def replace(
        self,
        dishes: list[Dish],
        ingredients: list[Ingredient],
        derived_number_to_gam: dict[int, float] | None = None,
    ) -> DBSnapshot:
        snapshot = DBSnapshot(
            dishes=dishes,
            ingredients=ingredients,
            updated_at=datetime.now(timezone.utc),
            derived_number_to_gam=derived_number_to_gam or {},
        )
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def get(self) -> DBSnapshot:
        with self._lock:
            if self._snapshot is None:
                raise CacheNotLoadedError("DB not loaded, call /update-db first")
            return self._snapshot

    def is_loaded(self) -> bool:
        with self._lock:
            return self._snapshot is not None


_cache_singleton = DBCache()


def get_cache() -> DBCache:
    return _cache_singleton
