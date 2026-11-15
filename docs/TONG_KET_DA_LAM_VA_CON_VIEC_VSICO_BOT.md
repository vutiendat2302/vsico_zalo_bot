# Tổng kết tiến độ VSICO Zalo Bot

Ngày đối chiếu: 15/11/2026. Tài liệu phản ánh code và kiểm thử trong workspace hiện tại; chưa coi đây là xác nhận hệ thống đã chạy ổn định trên các nhóm Zalo thật.

## 1. Đã triển khai

| Phần | Kết quả hiện có | Điểm kiểm chứng |
|---|---|---|
| Tiếp nhận Zalo | Webhook lưu tin gốc, xếp FIFO để worker xử lý; có cơ chế tránh xử lý trùng. | `backend/src/ingestion/`, `backend/src/infrastructure/fifo_queue.py` |
| Bóc tách tin nhà xe (RapidFuzz + Từ điển danh mục + PhoBERT) | Tầng 1 Regex/ISO 6346; Tầng 2 Local NLP kết hợp `RapidFuzz` (`WRatio`, `token_set_ratio`), Từ điển danh mục (`Customer`, `CustomerAlias`, `Warehouse`, `WarehouseAlias`, `Vehicle`, `Driver`, `TransportPlan`) và `PhoBertLocalNlpEngine` (tách từ ghép tiếng Việt, nhận diện thực thể BIO `PER`/`LOC`, phân loại ý định và chuyến kết hợp RO sang LO); giải quyết đồng tham chiếu (`xe trên`, `xe này`, `cont đó`, `chỗ cũ`, `kho cũ`) khi duy nhất 1 thực thể; Tầng 3 AI fallback có che SĐT. | `backend/src/parsing/local_nlp_extractor.py`, `ai-service/app/warehouse/fuzzy.py`, `backend/src/handlers/extraction_handler.py` |
| Đối chiếu kế hoạch 6 nhánh và đa xe | Đã triển khai đầy đủ 6 nhánh (`TH1` đến `TH6`) trong `PlanResolutionEngine`, hỗ trợ `resolve_batch` chống tranh chấp slot khi báo nhiều xe/nhiều chặng và chặn tự động ghép vỏ trả có cảnh báo (`empty_drop`, `other_requested`, `soc`, `over_combined`). | `backend/src/handlers/plan_resolution_engine.py`, `backend/tests/test_nlp_phobert_and_golden_benchmark.py` |
| Cập nhật kế hoạch nội bộ và nguyên tử RO sang LO | Luồng điền/cập nhật thông tin xe, tài xế, cont/seal; hàm `sync_combined_ro_to_lo_plans` cập nhật nguyên tử cả kế hoạch trả (`RO`) và kế hoạch đóng (`LO`) trong cùng giao dịch, giữ nguyên seal cũ của lệnh trả và gán seal mới cho lệnh đóng, tăng `version`, ghi audit. | `backend/src/handlers/plan_sync_service.py`, `backend/src/api/plans.py` |
| Đồng bộ TMS và danh mục | Kéo kế hoạch và danh mục từ TMS; bổ sung luồng ghi ngược TMS có kiểm soát (`sync_plan_to_tms`, `TmsApiClient.push_dispatch_update`) kèm `idempotency_key`, che SĐT tài xế (`0903xxxx59`) trong `tms_sync_logs`, giữ `PENDING` khi tắt cờ ghi TMS và đánh dấu `FAILED` khi API lỗi. | `backend/src/handlers/tms_plan_sync_service.py`, `backend/src/handlers/plan_sync_service.py`, `backend/src/infrastructure/tms_client.py` |
| Trợ lý ba vai trò | Đã dựng `backend/src/assistant/` với scope theo RouteMap/carrier/user ĐHVT, intent local, registry công cụ, truy vấn và trả lời từ DB; câu khó có endpoint AI intent nội bộ. | `backend/src/assistant/`, `ai-service/app/routers/assistant.py` |
| Khách hàng | Tra cứu kế hoạch trong tuyến được cấp, xem xe/cont/lịch/tóm tắt; gửi yêu cầu thay đổi thành ca Web và xem ca của nhóm mình. | `backend/src/assistant/tools_customer.py` |
| Nhà xe | Tra lịch, thông tin còn thiếu, tình trạng báo xe; đổi xe/tài xế qua nháp xác nhận gắn người gửi, nhóm, hạn và phiên bản kế hoạch. | `backend/src/assistant/tools_carrier.py` |
| ĐHVT (kèm thống kê lệnh đóng/trả theo vùng và tỉnh) | Tra cứu tổng số lệnh, số lệnh đóng (`LO`), số lệnh trả (`RO`), phân bổ số lệnh đóng/trả theo từng vùng (`Miền Bắc`, `Miền Trung`, `Miền Nam`) và theo từng tỉnh/thành phố (`province_name`), tổng hợp ca/lỗi/cảnh báo/lịch sử và số liệu Bot trên Zalo; lệnh duyệt/sửa/hủy trên Zalo được chặn và dẫn về Web. | `backend/src/assistant/tools_dhvt.py`, `backend/src/assistant/intent_router.py`, `backend/src/assistant/queries.py` |
| Bảo mật RBAC, khóa phiên bản và giao diện `/reviews` | Các endpoint duyệt/sửa/phát hành trên Web (`reviews.py`, `plans.py`, `outbound.py`) bắt buộc quyền `ADMIN`/`DHVT` và kiểm tra `expected_version` (trả `409 Conflict` khi lệch phiên bản). Màn hình `/reviews` hiển thị bảng `candidate_plans`, cho phép chọn dòng kế hoạch 1 chạm và tự động lưu `WarehouseAlias` khi duyệt. | `backend/src/api/reviews.py`, `backend/src/api/plans.py`, `backend/src/api/outbound.py`, `frontend/src/app/reviews/page.tsx` |
| Đánh giá định lượng (Golden Benchmark) | Bộ kiểm thử 56 tin nhắn Zalo ẩn danh thực tế phủ đủ 7 nhóm nghiệp vụ đạt tỷ lệ nhận diện ý định đúng `100%` (vượt ngưỡng `>= 96%`) và tỷ lệ tự động ghép sai (`False Auto-Match`) bằng `0%` trên 6 kịch bản bẫy đối kháng. | `backend/tests/test_nlp_phobert_and_golden_benchmark.py` |

Toàn bộ hệ thống hiện đã qua **99 test backend**, **16 test ai-service** và **build sản xuất frontend (`next build`) thành công 18/18 route**; mỗi bộ pytest chỉ còn một cảnh báo deprecation từ thư viện `TestClient`, không có test thất bại.

## 2. Chưa hoàn thiện hoặc chưa được chứng minh trên môi trường vận hành thật

| Ưu tiên | Việc còn lại | Tiêu chí hoàn thành |
|---|---|---|
| P0 | Kết nối và nghiệm thu đầu cuối API ghi ngược TMS thật trên môi trường staging/production của `be-tms` (`TMS_WRITE_ENABLED=True`). | TMS xác nhận hợp đồng endpoint cập nhật điều vận thực tế, đối soát dữ liệu ghi ngược trên hệ thống TMS thật. |
| P1 | Tải trọng lượng mô hình `vinai/phobert-base-v2` local trên máy chủ vận hành khi bật `PHOBERT_MODEL_ENABLED=True` (mặc định chạy chế độ `phobert_lexicon_hybrid` không cần GPU). | Kiểm tra dung lượng RAM/CPU khi nạp `transformers` + `torch` trên container production. |
| P1 | Kiểm thử pilot trên nhóm Zalo sandbox và cấu hình dữ liệu thật: `RouteMap` khách, `carrier_id` trên lệnh, danh mục xe, user ĐHVT. | Chạy thử có giám sát, đo KPI thực tế và đối chiếu thủ công trước khi mở tự động hoàn toàn. |
| Phase 2 | GPS, POD, sự kiện bãi/cảng realtime; Qdrant Vector DB (768-dim) cho tầng GP2 khi kho vượt quy mô fuzzy. | Chỉ thực hiện khi có nguồn dữ liệu GPS/POD và nhu cầu mở rộng kho. |

## 3. Tài liệu tham chiếu

- [Triển khai trợ lý Phase 1](TRANSPORT_ASSISTANT_IMPLEMENTATION.md)
- [Thiết kế bóc tách và ghép kế hoạch](PLAN_NLP_EXTRACTION_AND_PLAN_MATCHING.md)
- [Kế hoạch trợ lý ba vai trò](PLAN_TRANSPORT_OPERATIONS_AI_ASSISTANT_PHASE1.md)
- [Hướng dẫn kiểm thử hội thoại](../backend/tests/postman/14_tro_ly_van_tai_phase1.md)

Working tree hiện còn nhiều thay đổi chưa commit, gồm cả thay đổi từ các phần việc khác. Cần xem diff theo từng phân hệ trước khi tạo commit hoặc triển khai.
