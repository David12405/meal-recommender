.PHONY: install run test cov lint type fmt clean

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v

cov:
	pytest --cov=app --cov-report=term-missing --cov-report=html

lint:
	ruff check app/ tests/

fmt:
	ruff format app/ tests/
	ruff check --fix app/ tests/

type:
	mypy app/ --strict

bench:
	pytest tests/benchmarks/ --benchmark-only

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
