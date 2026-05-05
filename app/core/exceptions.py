class MealRecommenderError(Exception):
    """Base class for all service-specific errors."""


class CacheNotLoadedError(MealRecommenderError):
    """Raised when /recommend is called before /update-db has populated the cache."""


class InvalidIngredientError(MealRecommenderError):
    """Raised when an ingredient is outside the 62-class whitelist
    or when a unit conversion is requested without NUMBER_TO_GAM defined."""


class SolverInfeasibleError(MealRecommenderError):
    """Raised when CP-SAT returns INFEASIBLE after all relaxation passes."""


class SolverTimeoutError(MealRecommenderError):
    """Raised when CP-SAT times out (UNKNOWN status) after a retry."""


class DBLoadError(MealRecommenderError):
    """Raised when /update-db fails to fetch or validate backend JSON."""
