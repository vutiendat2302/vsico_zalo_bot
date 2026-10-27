# ADR 0001: Chuyển Đổi Sang Kiến Trúc Phân Tầng Hướng Nghiệp Vụ (Clean Layered Architecture)

## Trạng thái: ĐÃ CHẤP NHẬN (ACCEPTED)
Ngày: 16/10/2026

## Bối cảnh
Trước đây, mã nguồn của Task 2 nằm ở cấu trúc phẳng (`parser.py`, `sender.py`, `state.py`, `queue_worker.py` cùng một cấp). Các file gọi chéo lẫn nhau, payload thô của Zalo len lỏi sâu vào các hàm nghiệp vụ, gây khó khăn cho việc viết unit test độc lập và mở rộng thêm các kênh chat khác (Telegram, Web Portal).

## Quyết định
1. Phân tầng rõ rệt: `api` -> `ingestion` -> `messaging` -> `handlers` -> `domain` <- `infrastructure`.
2. Tạo model nội bộ `InboundMessage` để cách ly hoàn toàn cấu trúc Zalo Webhook với nghiệp vụ TMS.
3. Chuyển sang mô hình mỗi Intent một Handler chuyên trách.
4. Sử dụng `dataclass` chuẩn Python cho toàn bộ DTO và Domain Entities.

## Hệ quả
- Dễ dàng kiểm thử từng thành phần (Mocking / Unit testing không cần dựng Webhook).
- Khi Zalo thay đổi format JSON hoặc mở thêm Telegram, chỉ cần viết thêm adapter trong `ingestion/`.
- Lõi thẩm định container ISO 6346 Mod 11 và đối soát Shipping có thể tái sử dụng cho các phân hệ khác của TMS.
