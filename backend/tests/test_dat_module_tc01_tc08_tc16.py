"""Bộ Kiểm Thử Chuyên Biệt Cho Module Đọc Hiểu & Định Tuyến (TC-01 -> TC-08 và TC-16).

Kiểm tra toàn diện các yêu cầu của module Đạt phụ trách:
1. Bộ đọc F1 (`TC-01`, `TC-02`, `TC-03`): tách biển số, tài xế, SĐT, cont, chì.
2. Bộ đọc F2 (`TC-04`) và F3 (`TC-05`) theo nhãn, xử lý các điểm khó ở mục 2.
3. Chuẩn hóa và kiểm tra từng trường theo Bảng 6.2 (`TC-06` sai ISO 6346, `TC-07` SĐT 9 số / 9 ký tự ẩn,
   `TC-08` biển rơ-moóc `15R01234` ở vị trí đầu kéo), trả về danh sách lỗi (`warnings` + `reply_to_carrier`).
4. Đầu ra là Bản ghi chuẩn (`canonical_record`) mỗi container một bản ghi.
5. Tin xã giao (`TC-16`) bị chặn ở bộ lọc 2 tầng; tin tự do không theo F1/F2/F3 được đánh dấu chuyển AI (`ZCB-10`).
6. Xác nhận `TC-01` -> `TC-08` và `TC-16` chạy đúng 100% mà KHÔNG cần gọi AI (`used_ai == False`).
"""

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_dat_module_suite_tc01_to_tc08_and_tc16() -> None:
    """Chạy API `/api/messages/test-suite/dat-module` và kiểm tra 9/9 ca PASS, 0 lần gọi AI."""
    res = client.post("/api/messages/test-suite/dat-module")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["total_cases"] == 9
    assert body["passed_cases"] == 9
    assert body["failed_cases"] == 0
    assert body["ai_calls_count"] == 0

    by_id = {item["tc_id"]: item for item in body["results"]}
    for tc_id in ("TC-01", "TC-02", "TC-03", "TC-04", "TC-05", "TC-06", "TC-07", "TC-08", "TC-16"):
        assert by_id[tc_id]["passed"] is True
        assert by_id[tc_id]["used_ai"] is False


def test_tc07_masked_9_chars_and_zcb10_ai_routing_flag() -> None:
    """Kiểm tra TC-07 với SĐT ẩn 9 ký tự (`098******`) và cờ định tuyến AI (`route_to_ai_zcb10`)."""
    # 1. TC-07 với SĐT ẩn chỉ có 9 ký tự (trong file TC-07_input.txt)
    res_tc07_masked = client.post(
        "/api/messages/test-parse",
        json={
            "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 098****** / VSIU2621051 chì 23333878",
            "timestamp": "2026-10-09T07:30:00",
            "allow_ai_fallback": False,
        },
    )
    assert res_tc07_masked.status_code == 200
    data_07 = res_tc07_masked.json()
    assert data_07["used_ai"] is False
    assert data_07["canonical_records"][0]["driver_name"] == "Phạm Văn Huynh"
    assert data_07["canonical_records"][0]["driver_phone"] == "098******"
    assert "INVALID_DRIVER_PHONE" in data_07["warnings"]
    assert data_07["reply_to_carrier"] is not None

    # 2. Tin nhắn văn xuôi tự do không theo F1/F2/F3 và không có cấu trúc biển số/cont chuẩn -> route_to_ai_zcb10 = True
    res_zcb10 = client.post(
        "/api/messages/test-parse",
        json={
            "text": "Anh ơi chiều nay bên em cho tài xế Phong số 0931142873 vào kho đóng hàng khách Nhựa Á Đông nhé",
            "timestamp": "2026-10-09T07:30:00",
            "allow_ai_fallback": False,
        },
    )
    assert res_zcb10.status_code == 200
    data_zcb10 = res_zcb10.json()
    assert data_zcb10["source_format"] == "tu_do"
    assert data_zcb10["route_to_ai_zcb10"] is True
