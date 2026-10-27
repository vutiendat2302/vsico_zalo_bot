.PHONY: help install run worker test lint format docker-build docker-up docker-down evaluate simulate

PYTHON ?= python3
export PYTHONPATH := src

help:
	@echo "Lệnh khả dụng cho dự án nhaxe-bot:"
	@echo "  make run        : Chạy Webhook & TMS REST API Server"
	@echo "  make worker     : Chạy Queue Worker xử lý tin nhắn"
	@echo "  make test       : Chạy toàn bộ Unit & Integration tests"
	@echo "  make evaluate   : Chạy đo lường độ chính xác trên dataset benchmark"
	@echo "  make simulate   : Chạy công cụ mô phỏng tương tác tin nhắn (CLI Simulator)"
	@echo "  make docker-up  : Khởi động container bằng Docker Compose"
	@echo "  make docker-down: Dừng container"

run:
	PYTHONPATH=src $(PYTHON) -m nhaxe_bot.main --serve --port 8000

worker:
	PYTHONPATH=src $(PYTHON) -m nhaxe_bot.main --worker

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover tests -v

evaluate:
	PYTHONPATH=src $(PYTHON) scripts/evaluate.py

simulate:
	PYTHONPATH=src $(PYTHON) scripts/simulator.py

docker-build:
	docker build -t nhaxe-bot:latest .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down
