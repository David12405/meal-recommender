from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    MAINDISH = "MAINDISH"
    SOUP = "SOUP"
    VEGETABLE = "VEGETABLE"

    @classmethod
    def _missing_(cls, value: object) -> Role | None:
        """Normalize backend variants like "MAIN_DISH" → "MAINDISH" (§4.1)."""
        if isinstance(value, str):
            canonical = value.replace("_", "").upper()
            for member in cls:
                if member.value == canonical:
                    return member
        return None


class Unit(str, Enum):
    GAM = "GAM"
    NUMBER = "NUMBER"
    # SPOON: dùng cho gia vị (tiêu, đường, dầu hào, sa tế...) đo bằng muỗng/thìa.
    # Service không track stock + không tính nutrition cho rows unit=SPOON
    # (lượng đóng góp macro không đáng kể, user tự túc gia vị).
    SPOON = "SPOON"


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"


MEAL_TYPES: tuple[MealType, ...] = (MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER)
ROLES: tuple[Role, ...] = (Role.MAINDISH, Role.SOUP, Role.VEGETABLE)
