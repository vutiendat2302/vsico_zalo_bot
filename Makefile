.PHONY: help install egg-info run test test-txt ocr-run docker-up docker-down db-up db-down db-status db-check db-migrate db-clean db-clean-all db-clean-tests db-clean-plans db-reset db-shell oa-run oa-tunnel zca-run fe-dev fe-build fe-lint ai-run tms-sync

PYTHON ?= $(shell if [ -f backend/.venv/bin/python ]; then echo backend/.venv/bin/python; else echo python3; fi)
ALEMBIC ?= $(shell if [ -f backend/.venv/bin/alembic ]; then echo backend/.venv/bin/alembic; else echo alembic; fi)
AI_PYTHON ?= $(shell if [ -f ai-service/.venv/bin/python ]; then echo ai-service/.venv/bin/python; else echo python3; fi)

help:
	@echo "=========================================================================="
	@echo " LỆNH KHẢ DỤNG TOÀN DỰ ÁN VSICO ZALO BOT"
	@echo "=========================================================================="
	@echo "  1. Backend & Kiểm thử (Port 8000):"
	@echo "     make install         : Cài đặt editable package backend"
	@echo "     make egg-info        : Cập nhật siêu dữ liệu vsico_zalo_bot.egg-info"
	@echo "     make run             : Khởi chạy Backend FastAPI (Port 8000)"
	@echo "     make ocr-run         : Khởi chạy PaddleOCR cục bộ (Port 8866)"
	@echo "     make test            : Chạy toàn bộ test suite Backend bằng Pytest"
	@echo "     make test-txt        : Chạy toàn bộ test case input TXT fixtures"
	@echo ""
	@echo "  2. Zalo Bridges & Tunnel & Frontend & AI:"
	@echo "     make oa-run          : Khởi chạy OA Bridge (Port 3000)"
	@echo "     make oa-tunnel       : Chạy Cloudflare Tunnel cho oa.vtdat.com -> :3000"
	@echo "     make zca-run         : Khởi chạy ZCA Bridge"
	@echo "     make fe-dev          : Khởi chạy Frontend Next.js dev (Port 3001)"
	@echo "     make fe-build        : Build Frontend Next.js"
	@echo "     make fe-lint         : Kiểm tra ESLint Frontend"
	@echo "     make ai-run          : Khởi chạy AI Service (Port 8001)"
	@echo "     make tms-sync        : Đồng bộ Master Data từ API be-tms về DB cục bộ"
	@echo ""
	@echo "  3. Quản lý Cơ Sở Dữ Liệu MySQL & Hạ tầng (Docker & Alembic):"
	@echo "     make docker-up       : Khởi động toàn bộ Docker services"
	@echo "     make docker-down     : Dừng toàn bộ Docker services"
	@echo "     make db-up           : Khởi động container MySQL 8.4 ngầm"
	@echo "     make db-down         : Dừng container MySQL"
	@echo "     make db-check        : Kiểm tra kết nối DB và phiên bản Alembic"
	@echo "     make db-status       : Thống kê số lượng bản ghi các bảng"
	@echo "     make db-migrate      : Chạy migrations Alembic lên bản mới nhất"
	@echo "     make db-shell        : Mở MySQL Interactive Shell"
	@echo "     make db-clean        : Dọn dữ liệu runtime (giữ catalog & kế hoạch)"
	@echo "     make db-clean-tests  : Dọn dữ liệu kiểm thử tự động"
	@echo "     make db-clean-plans  : Dọn bảng kế hoạch vận chuyển"
	@echo "     make db-clean-all    : Dọn trắng toàn bộ bảng (giữ cấu trúc)"
	@echo "     make db-reset        : Reset toàn bộ DB (Drop & Migrate lại)"
	@echo "=========================================================================="

# --- Backend ---
install:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) -m pip install -e ".[dev]"

egg-info:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) -c "import setuptools; setuptools.setup()" egg_info

run:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) run.py

ocr-run:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/paddle_ocr_server.py --port 8866

test:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) -m pytest tests -v

test-txt:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/run_txt_tests.py --all

# --- Bridges, Tunnel, Frontend, AI ---
oa-run:
	cd oa-bridge && npm start

oa-tunnel:
	cloudflared tunnel --protocol http2 --edge-ip-version 4 run --url http://localhost:3000 vsico-oa

zca-run:
	cd zca-js && npm start

fe-dev:
	cd frontend && npm run dev

fe-build:
	cd frontend && npm run build

fe-lint:
	cd frontend && npm run lint

ai-run:
	cd ai-service && $(shell if [ -f ai-service/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) -m uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload

tms-sync:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/sync_tms_master.py

# --- Docker & Database ---
docker-up:
	docker compose -f docker-compose.yml --env-file .env up -d

docker-down:
	docker compose -f docker-compose.yml --env-file .env down

db-up:
	docker compose -f docker-compose.yml --env-file .env up -d mysql

db-down:
	docker compose -f docker-compose.yml --env-file .env stop mysql

db-check:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py check

db-status:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py status

db-migrate:
	cd backend && $(shell if [ -f backend/.venv/bin/alembic ]; then echo .venv/bin/alembic; else echo alembic; fi) upgrade head

db-shell:
	docker exec -it vsico-zalo-mysql mysql -u $${DB_USER:-vsico_user} -p vsico_zalo_bot

db-clean:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py clean --runtime -y

db-clean-tests:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py clean --tests

db-clean-plans:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py clean --plans -y

db-clean-all:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py clean --all -y

db-reset:
	cd backend && $(shell if [ -f backend/.venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi) scripts/manage_db.py reset -y
