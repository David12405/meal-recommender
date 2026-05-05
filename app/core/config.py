from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "meal-recommender"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    solver_timeout_seconds: float = 5.0
    solver_num_workers: int = 4
    calorie_delta: int = 100
    no_repeat_days: int = 2

    weight_fridge: int = 3
    weight_expiry: int = 5
    weight_diversity: int = 2
    weight_shopping_penalty: int = 3

    # Cửa sổ "đang sắp hết hạn" — ingredient có dueDate trong N ngày tính từ
    # ngày tiêu thụ sẽ được boost expiry score. Linear decay:
    #   urgency = (window - days_to_expire + 1)
    # Ví dụ window=7:
    #   - hết hạn hôm nay → urgency=7+1 (max)
    #   - hết hạn 7 ngày sau → urgency=1 (min)
    #   - hết hạn >7 ngày → 0 (ngoài window, không boost)
    expiry_window_days: int = 7

    # Tỷ lệ thiếu ingredient mà service cho phép (không add vào shoppingList).
    # Ví dụ recipe cần 115g, fridge có 100g (thiếu 13%) → vẫn dùng 100g, bỏ qua.
    # Lý do: đời thực user không cân chính xác đến từng gram.
    ingredient_shortfall_tolerance: float = 0.15

    data_dir: Path = Field(default_factory=lambda: Path("./data"))

    # CV model nhận diện 62 classes ingredients trong ảnh tủ lạnh, nhưng dish
    # master pool có thể nhiều hơn (gia vị, condiment ngoài CV). Bump default
    # lên 250 để cover. Fridge tự động bị giới hạn bởi CV (chỉ ingredient nào
    # CV detect được mới vào fridge).
    max_ingredient_classes: int = 250

    # kcal per kg of body fat (physiological constant — ACSM)
    kcal_per_kg: int = 7700


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
