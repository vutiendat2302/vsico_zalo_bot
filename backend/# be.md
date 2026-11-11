# be

## Clean data:

- cd backend:
- update môi trường nếu có thay đổi: uv sync
- sau đó: kích hoạt môi trường .venv
- check: file Make file để kích hoạt các lệnh

## migrations:

Thư mục này chứa toàn bộ lịch sử thay đổi cấu trúc cơ sở dữ liệu của hệ thống. Thay vì sửa trực tiếp trên database, chúng ta định nghĩa các thay đổi (thêm bảng, sửa cột, tạo index) thông qua các file script. Điều này giúp:

    - Đồng bộ hóa: Đảm bảo môi trường phát triển (local), staging và production luôn có cấu trúc database giống nhau.
    - Khả năng rollback: Dễ dàng quay lại phiên bản database cũ nếu có lỗi xảy ra.
    - Truy xuất nguồn gốc: Biết được ai đã thay đổi cấu trúc database và tại sao.

    3. Quy trình làm việc với Migrations
Khi bạn cần thay đổi cấu trúc dữ liệu (ví dụ: thêm trường phone_number vào bảng drivers):

Cập nhật Model: Bạn sửa file model trong src/domain/ hoặc src/infrastructure/db/models.py.
Tạo Migration: Chạy lệnh để Alembic tự động so sánh model hiện tại với database và sinh ra file mới trong versions/:
Run
alembic revision --autogenerate -m "add_phone_number_to_drivers"
Kiểm tra: Mở file mới tạo trong versions/ để xem code upgrade/downgrade có đúng không.
Áp dụng: Chạy lệnh để cập nhật database:
Run
alembic upgrade head
Lưu ý quan trọng:

Tuyệt đối không được sửa thủ công các file đã nằm trong versions/ sau khi đã upgrade lên database, vì sẽ làm sai lệch lịch sử migration.
Luôn tuân thủ quy tắc Clean Architecture: Migration chỉ là công cụ kỹ thuật để hiện thực hóa schema, không được chứa logic nghiệp vụ phức tạp bên trong các file này.

## scripts:

Kiểm thử và đánh giá, Đây là nhóm quan trọng nhất để đảm bảo độ chính xác của hệ thống theo quy tắc "Benchmark" đã đề ra:
Quản lý hạ tầng
manage_db.py: Script hỗ trợ các thao tác quản trị database nhanh (ví dụ: reset database, seed dữ liệu mẫu, hoặc kiểm tra kết nối). Nó giúp lập trình viên không phải gõ các lệnh SQL phức tạp.

## Src:

- Update lại các bảng database

### Config

- Setting cấu hình hệ thống backend chú ý cho cấu hình theo .env hết, ko để mk với  api key trong đây,
- Bổ sung thêm min io và snowfalke cho id của hệ thống này

### Webhook.py

- bỏ cái trùng lặp đi vì hệ thống chỉ lấy tin nhắn từ lúc bật hệ thống thôi lên không có chuyện input vào bị lặp được,

```python
    msg, is_duplicate = WebhookIngestor.ingest_webhook_payload(
        db=db,
        payload_dict=payload.model_dump(),
    )
```

sửa lại trucks_summary, containé_sumarry theo theo các bảng mới đã cập nhật, sủa lịa cả cái retunr nữa,

Sửa lại shcenma cho đúng với data mới, cả hệ thống đọc file, ocr cũng phải chuẩn, ko cần mock, phải thật, vì đã hỗ trợ min io lưu file rồi, và hệ thống Ai xử lý hình ảnh rồi,

Hệ thống sẽ không dùng dữ liệu gỉa lập, tất cả đều phải chạy thật từ dữ liệu đầu vào,

```python

        # 2. Tự động đăng ký hoặc cập nhật thông tin Nhóm / Hội thoại trong `zalo_groups`
        zalo_group = db.scalar(
            select(ZaloGroup).where(ZaloGroup.zalo_group_id == group_id)
        )
        is_mock_group = (
            group_id.startswith("test_")
            or group_id.startswith("pytest_")
            or "pytest_" in group_id
            or "test_" in group_id
            or (msg_id and (msg_id.startswith("test_") or msg_id.startswith("pytest_")))
            or (sender_id and (sender_id.startswith("test_") or sender_id.startswith("pytest_")))
        )
        if zalo_group is None:
            zalo_group = ZaloGroup(
                zalo_group_id=group_id,
                name=effective_group_name,
                group_role=group_role,
                send_mode="tu_dong",
                is_active=True,
                is_test=is_mock_group,
            )
            db.add(zalo_group)
            db.flush()
        elif group_name and zalo_group.name != group_name:
            zalo_group.name = group_name
            db.flush()
```

bỏ mock zalo đi, mình sẽ không dùng nhóm test, cứ nhóm chính mà fang, vì nhóm thực tế bây giờ cũng là nhóm test mà m,

```python
 # 3. Lưu ngay lập tức tin nhắn thô (raw message) vào bảng `zalo_messages`
        from src.infrastructure.ocr.paddle_client import PaddleOCRClient

        zalo_sent_at = cls.parse_timestamp(payload_dict.get("timestamp"))
        has_text = bool(text and text.strip())
        has_image = PaddleOCRClient.is_image_payload(payload_dict)

        if has_image:
            msg_type = "image"
        elif has_text:
            msg_type = "text"
        else:
            msg_type = "non_text"

        initial_status = (
            MessageStatus.QUEUED.value
            if (has_text or has_image)
            else MessageStatus.IGNORED_NON_TEXT.value
        )
```

bổ sung thêm định dạng file, với cơ chế lưu sẽ khác đối với image, file sẽ lưu file key
