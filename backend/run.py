#!/usr/bin/env python3
"""Điểm Khởi Chạy Nhanh Dự Án nhaxe-bot (Root Entrypoint Launcher).

Tự động thiết lập đường dẫn tìm kiếm mô-đun Python (sys.path) trỏ vào thư mục `src/`,
giúp người dùng có thể khởi chạy máy chủ trực tiếp bằng lệnh đơn giản:
    python3 run.py --serve --port 8000
hoặc chạy kiểm thử nhanh mà không cần cấu hình biến môi trường PYTHONPATH thủ công.
"""

import os
import sys

# Tự động nạp thư mục src vào sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(CURRENT_DIR, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.main import main

if __name__ == "__main__":
    main()
