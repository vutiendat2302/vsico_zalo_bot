.PHONY: help run dev test lint format check clean

PYTHON ?= $(shell if [ -f .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
UVICORN ?= $(shell if [ -f .venv/bin/uvicorn ]; then echo .venv/bin/uvicorn; else echo uvicorn; fi)
PYTEST ?= $(shell if [ -f .venv/bin/pytest ]; then echo .venv/bin/pytest; else echo pytest; fi)

help:
	@echo "=========================================================================="
	@echo " LỆNH KHẢ DỤNG CHO DỊCH VỤ AI-SERVICE (FASTAPI - PORT 8001)"
	@echo "=========================================================================="
	@echo "  make run       : Khởi chạy AI Service với reload (0.0.0.0:8001)"
	@echo "  make dev       : Tương đương make run"
	@echo "  make test      : Chạy toàn bộ test suite bằng Pytest"
	@echo "  make check     : Kiểm tra cú pháp và import ứng dụng"
	@echo "  make clean     : Dọn dẹp cache (__pycache__, .pytest_cache, .ruff_cache)"
	@echo "=========================================================================="

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8001 --reload

dev: run

test:
	$(PYTEST) tests -v

check:
	$(PYTHON) -c "import app.main; print('AI Service app imported successfully!')"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
