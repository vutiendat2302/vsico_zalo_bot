# Lịch Sử Phiên Bản (CHANGELOG)

Tất cả thay đổi đáng chú ý của hệ thống **VSICO Zalo Bot & TMS Integration** được ghi nhận theo chuẩn Semantic Versioning (`MAJOR.MINOR.PATCH`), đồng bộ với tệp [`VERSION`](./VERSION) tại thư mục gốc.

---

## [1.5.0] - 2026-11-23

Phiên bản nâng cấp lớn so với bản nền tảng `v1.0.0`, tập trung vào độ chính xác NLP/Regex, luồng duyệt an toàn `MANUAL`, trải nghiệm trợ lý ĐHVT/Nhà xe trên Zalo, khả năng tự giám sát Watchdog và cô lập kiểm thử hoàn toàn trên Proxy.

### Tóm tắt khác biệt chính so với phiên bản `v1.0.0`

| Hạng mục | Phiên bản `v1.0.0` | Phiên bản `v1.5.0` |
| :--- | :--- | :--- |
| Bộ lọc & Regex | Regex cơ bản, chỉ bắt 1 SĐT/tài xế, dễ dính số hàng/trọng tải và thiếu NBSP Zalo | **Precision Regex** (hỗ trợ NBSP, loại đuôi số hàng/cân nặng), bắt **đa SĐT** (`09..1 \| 09..2`) lưu DB và đồng bộ về TMS |
| Mô hình NLP cục bộ | Rule-based + RapidFuzz + từ điển; bật flag PhoBERT nhưng chưa tham gia dự đoán | Kích hoạt trọng số thật **`vinai/phobert-base-v2`** (`phobert_transformers_local`) kèm ngưỡng `UNKNOWN`, benchmark 25.000 mẫu và API `POST /api/sandbox/nlp-analyze` |
| Luồng Lệnh kết hợp & Cont lạ | Xử lý đơn tuyến tính, chưa tách biệt rõ RO+LO và cảnh báo cont lạ hai chiều | Hỗ trợ đầy đủ cặp **`RO + LO`** (AUTO hỏi `combined_lo_confirm`, MANUAL duyệt cả cặp) và cont lạ cảnh báo song song Nhà xe + ĐHVT |
| Chế độ Chờ duyệt (`MANUAL`) | Vẫn cho phép ghi trước `transport_plans` hoặc lọt duyệt khi thiếu `RouteMap` ở lệnh kết hợp | **Cưỡng chế `MANUAL` triệt để** trên mọi luồng: tuyệt đối không ghi trước `transport_plans` hay đẩy TMS cho cả lệnh kết hợp lẫn lệnh trả đủ 4-5 trường trước khi ĐHVT duyệt |
| Gom tin & Cửa sổ đợi 20s | Phản hồi ngay từng tin lẻ, chưa gom tin rời rạc hay bóc danh thiếp Zalo | Nhóm Nhà xe **đợi im lặng 20s từ tin cuối (trần tối đa 60s)** để gom mảnh tin + bóc **Danh thiếp Zalo**; nhóm ĐHVT & Khách **trả lời ngay** |
| Trợ lý ĐHVT & Báo cáo | Chỉ thống kê số đếm chung và xuất bảng thống kê không kèm chi tiết chuyến | Tách riêng **`dhvt_get_province_plans`** (chi tiết lệnh theo tỉnh) khỏi thống kê ngày, thêm **tỷ lệ % đóng/mở** và ảnh PNG chứa **cả bảng thống kê lẫn bảng chi tiết lệnh** |
| Tin nhắn nhóm & Giám sát | Văn phong log kỹ thuật, lộ mã lỗi (`APPROVED`, `empty_drop`, `MISSING_*`), bắn từng tin lẻ | Chuẩn hóa 7 loại tin **`[VSICO] - ...`** thân thiện, tự **gom nhiều ca/quá hạn thành 1 tin**, ĐHVT duyệt trực tiếp trên Zalo chỉ phát **1 tin duy nhất** |
| Đồng bộ TMS & Kiểm thử | Đồng bộ thủ công, test mock phân tán | Bổ sung **`tms_auto_sync`**, danh mục rơ-moóc (`trailers`), làm mới token (`/api/auth/refresh`), **Zalo OA Watchdog** và khóa cứng **`ZALO_PROXY_ONLY`** (0 gửi Zalo OA thật khi test) |

### Chi tiết các thay đổi từ `v1.0.0` lên `v1.5.0`
- **Bóc tách Precision Regex & Đa SĐT**: Chuẩn hóa regex container ISO 6346, biển số xe/rơ-moóc (hỗ trợ NBSP từ Zalo, loại trừ đuôi số hàng hóa/trọng tải) và bóc tách nhiều SĐT trên một tài xế (`09..1 | 09..2`), bổ sung migration mở rộng cột `driver_phone`.
- **NLP thật `vinai/phobert-base-v2`**: Đưa PhoBERT thật (`phobert_transformers_local`) vào tầng phân loại ý định/thực thể có ngưỡng tin cậy `UNKNOWN`, hoàn thiện bộ benchmark 25.000 mẫu qua Proxy và endpoint `POST /api/sandbox/nlp-analyze`.
- **Cưỡng chế Chờ duyệt (`MANUAL`) & Duyệt đồng bộ 1 cửa**: Áp dụng thống nhất `is_manual_approval_required` trên `extraction_handler`, `carrier_flow_service`, `tools_carrier` và đồng bộ `TransportPlan` + TMS khi duyệt từ cả `/reviews`, `/results` lẫn Zalo ĐHVT.
- **Tối ưu giao tiếp Zalo (`[VSICO] - ...`) & Gom thông báo lô**: Chuyển ngữ toàn bộ mã cảnh báo kỹ thuật sang tiếng Việt tự nhiên; gom nhiều ca cần duyệt hoặc quá hạn phát sinh cùng lúc thành 1 thông báo tổng hợp; gộp phản hồi duyệt/từ chối trực tiếp trên Zalo ĐHVT thành duy nhất 1 tin đầy đủ tên người duyệt.
- **Mở rộng Trợ lý ĐHVT & Kết xuất ảnh PNG**: Tách riêng tra cứu chi tiết lệnh theo tỉnh (`dhvt_get_province_plans`), thêm tỷ lệ `%` đóng/mở và nâng cấp `HtmlReportImageGenerator` vẽ kèm bảng danh sách chi tiết các lệnh trong ảnh báo cáo.
- **Đồng bộ TMS tự động & Hạ tầng an toàn**: Tích hợp `tms_auto_sync`, module quản lý `trailers`, Watchdog sức khỏe Zalo OA (`/api/health/zalo-oa`, SSE), ngắn liên kết Web (`/[code]`), **cửa sổ đợi nhóm Nhà xe im lặng 20 giây (`GROUP_PROCESS_DELAY_SECONDS=20`, trần tối đa `GROUP_PROCESS_MAX_WAIT_SECONDS=60`) trong khi nhóm ĐHVT xử lý ngay**, tắt quét quá hạn nền mặc định (`ZALO_OVERDUE_ESCALATION_ENABLED=False`) và khóa cứng Proxy (`ZALO_PROXY_ONLY`) cho toàn bộ 169 bài kiểm thử Pytest.

---

## [1.0.0] - 2026-11-16

### Phát hành lần đầu
- Hoàn thiện kiến trúc đa phân hệ (`backend`, `frontend`, `ai-service`, `oa-bridge`, `zca-js`, `database` 23 bảng MySQL 8.4 + Snowflake ID 64-bit).
- Triển khai cổng Webhook `< 50ms`, hàng đợi FIFO, bộ đối chiếu kế hoạch 6 nhánh `PlanResolutionEngine`, Trợ lý AI 3 vai trò và giao diện điều hành Web cho ĐHVT/Admin.
