.PHONY: help run test test-txt ocr-run docker-up docker-down db-up db-down db-status db-check db-migrate db-clean db-clean-all db-clean-tests db-clean-plans db-reset db-shell

PYTHON ?= $(shell if [ -f .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
ALEMBIC ?= $(shell if [ -f .venv/bin/alembic ]; then echo .venv/bin/alembic; else echo alembic; fi)

help:
	@echo "=========================================================================="
	@echo " LỆNH KHẢ DỤNG CHO DỰ ÁN VSICO ZALO BOT (PM TMS TASK 2)"
	@echo "=========================================================================="
	@echo "  1. Ứng dụng & Kiểm thử:"
	@echo "     make run             : Khởi chạy FastAPI Webhook & TMS REST API (Port 8000)"
	@echo "     make ocr-run         : Khởi chạy máy chủ PaddleOCR tự host cục bộ (Port 8866)"
	@echo "     make test            : Chạy toàn bộ test suite tự động bằng Pytest"
	@echo "     make test-txt        : Chạy toàn bộ 21 test case input TXT fixtures"
	@echo ""
	@echo "  2. Quản lý Cơ Sở Dữ Liệu MySQL (Docker & Alembic):"
	@echo "     make db-up           : Khởi động container MySQL 8.4 ngầm"
	@echo "     make db-down         : Dừng container MySQL"
	@echo "     make db-check        : Kiểm tra kết nối DB và phiên bản Alembic hiện tại"
	@echo "     make db-status       : Thống kê số lượng bản ghi của toàn bộ 17 bảng"
	@echo "     make db-migrate      : Chạy migrations Alembic lên bản mới nhất (HEAD)"
	@echo "     make db-shell        : Mở MySQL Interactive Shell bên trong container"
	@echo ""
	@echo "  3. Dọn dẹp & Reset Cơ Sở Dữ Liệu (Clean DB):"
	@echo "     make db-clean        : Dọn dẹp dữ liệu tin nhắn/xe/cont runtime (GIỮ catalog & kế hoạch)"
	@echo "     make db-clean-tests  : Dọn dẹp chỉ các bản ghi kiểm thử tự động (pytest_*, test_*)"
	@echo "     make db-clean-plans  : Dọn dẹp bảng kế hoạch vận chuyển (transport_plans)"
	@echo "     make db-clean-all    : Dọn dẹp TRẮNG toàn bộ 17 bảng (giữ nguyên cấu trúc)"
	@echo "     make db-reset        : Reset toàn bộ DB (Drop tables & chạy lại migrations)"
	@echo "=========================================================================="

run:
	$(PYTHON) run.py

ocr-run:
	$(PYTHON) scripts/paddle_ocr_server.py --port 8866

test:
	$(PYTHON) -m pytest tests -v

test-txt:
	$(PYTHON) scripts/run_txt_tests.py --all

docker-up:
	docker compose up -d

docker-down:
	docker compose down

db-up:
	docker compose up -d mysql

db-down:
	docker compose stop mysql

db-check:
	$(PYTHON) scripts/manage_db.py check

db-status:
	$(PYTHON) scripts/manage_db.py status

db-migrate:
	$(ALEMBIC) upgrade head

db-shell:
	docker exec -it vsico-zalo-mysql mysql -u root -p123456 vsico_zalo_bot

db-clean:
	$(PYTHON) scripts/manage_db.py clean --runtime -y

db-clean-tests:
	$(PYTHON) scripts/manage_db.py clean --tests

db-clean-plans:
	$(PYTHON) scripts/manage_db.py clean --plans -y

db-clean-all:
	$(PYTHON) scripts/manage_db.py clean --all -y

db-reset:
	$(PYTHON) scripts/manage_db.py reset -y
