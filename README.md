# Meal Recommendation Service

Python microservice that generates N-day meal plans (1–14 days) from a pool of dishes,
solving for meal structure, fridge/expiry usage, calorie target, and macro ratios using
OR-Tools CP-SAT. The I/O contract is locked with the backend team — see `CLAUDE.md`.

## Architecture

```
┌─────────────┐  POST /update-db   ┌──────────────────────┐
│  Backend    │ ──(dishesUrl,      │  Meal Recommender    │
│  (Web/App)  │     ingredientsUrl)│  (FastAPI)           │
└─────────────┘                    └──────────────────────┘
      │                                       │
      │                                       │ httpx download
      │                                       │ → validate (Pydantic v2)
      │                                       │ → cache in-memory (singleton)
      │                                       ▼
      │                              ┌──────────────────┐
      │                              │  dishes.json     │
      │                              │  ingredients.json│
      │                              │  (≤62 classes)   │
      │                              └──────────────────┘
      │                                       │
      │       POST /recommend                 │
      └──────────(input.json)─────────────────┤
                                              ▼
                                   ┌─────────────────────┐
                                   │  CP-SAT Solver      │
                                   │  (OR-Tools)         │
                                   └─────────────────────┘
                                              │
                                              ▼
                                        output.json
```

## Tech stack

- Python 3.11+, FastAPI, Pydantic v2
- OR-Tools CP-SAT for the constraint model
- httpx for backend JSON downloads
- loguru for logging
- pytest + pytest-cov for tests

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # tune weights / delta if desired
make run                      # uvicorn on :8000
```

OpenAPI docs: http://localhost:8000/docs

### Curl examples

```bash
# 1) Populate the cache (dishes + ingredients JSON URLs)
curl -X POST http://localhost:8000/update-db \
  -H 'Content-Type: application/json' \
  -d '{"dishesUrl": "https://example.com/dishes.json",
       "ingredientsUrl": "https://example.com/ingredients.json"}'

# 2) Request a plan
curl -X POST http://localhost:8000/recommend \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/sample_input.json

# 3) Health check
curl http://localhost:8000/health
```

## Environment variables

See [`.env.example`](.env.example). Key settings:

| Variable | Default | Purpose |
|---|---|---|
| `SOLVER_TIMEOUT_SECONDS` | 5.0 | CP-SAT wall-time limit per pass |
| `CALORIE_DELTA` | 100 | Initial ± window around target kcal/day |
| `NO_REPEAT_DAYS` | 2 | Dish cannot repeat within this window (days) |
| `WEIGHT_FRIDGE` / `WEIGHT_EXPIRY` | 3 / 5 | Objective weights (S1, S2) |
| `WEIGHT_SHOPPING_PENALTY` | 3 | Penalty per ingredient not in fridge |
| `MAX_INGREDIENT_CLASSES` | 62 | Hard limit — tied to the CV model |
| `HTTPX_TIMEOUT` | 30.0 | `/update-db` download timeout |

## Locked contract decisions

These answer the CLAUDE.md §15 questions (decided 2026-04-22):

1. **`summary.targetCalories`** = `(TDEE + daily_delta) × planDays`, with
   `daily_delta = (targetKg × 7700) / 7`. (`targetKg` is kg/week despite the name.)
2. **Unit mismatch**: internal comparison always in GAM using
   `unitConversions.NUMBER_TO_GAM`; output `missingIngredient`/`shoppingList`
   preserves the dish recipe's original unit. Missing conversion factor → 400.
3. **Error envelope**: FastAPI default `{"detail": "..."}`.
4. **Stale `recentMealLog`**: entries older than `NO_REPEAT_DAYS` are silently dropped.
5. **Vegetarian/dietary flags**: deferred (no schema field in v1).

## Relaxation ladder (CP-SAT INFEASIBLE → relax)

| Pass | Change |
|---|---|
| 1 | initial (calorie_delta=100, no_repeat=2) |
| 2 | calorie_delta → 200 |
| 3 | calorie_delta → 300 |
| 4 | no_repeat → 1 |
| 5 | no_repeat → 0 |
| 6 | macro bounds widened ±15% |
| — | still INFEASIBLE → `status: "failed"` |

Relaxation notes are logged server-side only (no `warnings[]` field in output per §3.2).

## Testing

```bash
make test           # pytest -v
make cov            # with coverage HTML report
make lint           # ruff
make type           # mypy strict
make bench          # pytest-benchmark
```

## Project layout

```
app/
  api/           FastAPI router + DI
  core/          config, cache, logging, exceptions
  models/        Pydantic I/O & domain models
  services/
    constraints/ structural / repetition / calorie / macro
    cp_sat_solver.py   build + solve + relax
    objective.py       S1/S2/S4 weighted objective
    recommend.py       orchestration
    missing_ingredient.py / shopping_list.py / unit_converter.py
    db_loader.py       backend JSON → cache
  utils/         nutrition targets, date helpers
tests/
  unit/          pure-logic tests
  integration/   FastAPI TestClient + fixtures
  fixtures/      sample dishes / ingredients / input
```

## Troubleshooting

- **503 "DB not loaded"** — call `/update-db` first; the cache is empty on cold start.
- **400 with "ingredient outside ... whitelist"** — a fridge item has an ID not present
  in the last `/update-db` ingredients list; reload or drop the item client-side.
- **`status: "failed"` response** — all relaxation passes infeasible; typically the
  candidate pool is too narrow for the calorie/macro target, or the meal structure
  demands more unique dishes than the pool provides under the no-repeat window.
- **Vietnamese characters garbled in backup JSON** — files are written as UTF-8; your
  editor/terminal must be UTF-8.
- **Solver slow on large DBs** — lower `SOLVER_TIMEOUT_SECONDS` and raise
  `SOLVER_NUM_WORKERS`, or filter the candidate pool by meal type.

## Academic references

- **Jäger et al. (2017)** — ISSN Position Stand on protein intake.
- **ACSM Position Stand (2009)** — macro distribution / weight loss guidance.
- **WHO Guideline (2023)** — Total Fat Intake ≤ 30% of energy.
- **Rossi, Van Beek, Walsh (2006)** — Handbook of Constraint Programming.
- **OR-Tools CP-SAT** — https://developers.google.com/optimization/cp/cp_solver.
- **7700 kcal / kg** — approximation used for weekly calorie deficit/surplus planning
  (ACSM weight-management guidance).
