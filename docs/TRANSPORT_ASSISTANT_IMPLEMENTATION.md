# Trợ lý vận tải Phase 1: triển khai và vận hành

## 1. Điểm vào và phân lớp

`route_conversation` chuyển hội thoại vào `backend/src/assistant/service.py`. Bộ trợ lý dùng chung cho CUSTOMER/DESTINATION, CARRIER/SOURCE và DHVT. Registry khai báo các nhóm C01–C10, N01–N12, O01–O14; `get_role_help` dùng chung, `CONFIRM` là bước nội bộ của N07.

- `schemas.py`: hợp đồng Pydantic, từ chối tham số ngoài schema; ID ca trong JSON là chuỗi.
- `scope_resolver.py`, `queries.py`: danh tính, RouteMap và truy vấn giới hạn phạm vi.
- `intent_router.py`: luật local, ngày gửi, mã lệnh, cont, biển số, booking/BL.
- `queries.enrich_catalog`: tên trong kế hoạch, alias khách/kho và đuôi biển số trong danh mục nhà xe; khớp nhiều kết quả thì hỏi lại.
- `tool_registry.py`, `tools_customer.py`, `tools_carrier.py`, `tools_dhvt.py`: kiểm quyền lần cuối và thực thi.
- `mutation_outbound.py`, `reviews.py`: kiểm tra trước phát hành, outbox, ca Web đúng phạm vi.

Tin báo xe mới tiếp tục dùng pipeline bóc tách hiện hữu. Tin bổ sung bằng quote được chuyển về luồng cũ chỉ khi quote thuộc chính người gửi/nhóm và không ghi đè trường đã có. Tin báo lại thay đổi xe/tài xế không được bỏ qua xác nhận chỉ vì thiếu từ “đổi”.

## 2. Quyền truy cập

| Vai trò | Điều kiện |
|---|---|
| Khách | RouteMap đang hoạt động, đúng khách, kho và loại lệnh. Không sử dụng `transport_plans.group_id` mặc định để mở quyền. |
| Nhà xe | Nhóm gắn nhà xe đang hoạt động; truy vấn chỉ `carrier_id` tương ứng. Lệnh chưa gán nhà xe không xuất hiện trong danh sách. |
| ĐHVT | Nhóm đang hoạt động; duy nhất một user active, role admin/dhvt, đúng `zalo_user_id` và `zalo_info_id`. |

Registry kiểm quyền kể cả khi bỏ qua router. LLM chỉ được đề xuất công cụ đọc trong tập đóng; không có SQL hoặc tham số cấp quyền. Ngoài phạm vi và không tồn tại dùng chung thông báo không tìm thấy. Ca của khách/nhà xe được tra theo nhóm của tin gốc; hai nhóm cùng số cont không bị gộp ca.

ĐHVT trên Zalo chỉ tra cứu. Lệnh duyệt/sửa/hủy/cho gửi và “ok” đều hướng dẫn Web. Phân tích giả định “nếu hủy LO...” chỉ đọc dữ liệu. Đề xuất trợ lý khi được duyệt trên Web bắt buộc có tài khoản DHVT/Admin và phiên bản kế hoạch còn khớp.

## 3. Cập nhật kế hoạch và xác nhận

1. Nhà xe báo mã lệnh/cont hoặc dùng ngữ cảnh duy nhất của chính mình trong 30 phút.
2. Bổ sung chỉ vào trường trống có thể áp dụng ngay sau hậu kiểm. Ghi đè tạo `message_drafts` với `entities.kind = assistant_vehicle_change`, `plan_id`, `version`, `changes`, `prompt_outbound_id`.
3. Nháp `WAITING_REPLY`, hạn 15 phút. Xác nhận bằng `xác nhận #mã`, quote câu hỏi bot, hoặc “đúng” khi chỉ có một đề xuất còn hạn của người gửi trong nhóm.
4. Khóa nháp và kế hoạch, kiểm lại nhà xe/phiên bản. Hết hạn hoặc thay đổi phiên bản không được ghi đè. Nháp đã dùng chuyển `FLUSHED`.
5. Xe ngoài danh mục, xe có lệnh khác cùng ngày, đổi cont đã có trên lệnh khác, lệch cont/chì gốc RO hoặc có thông báo khách đang chờ/đã gửi đều chuyển Web. Không kết luận xe trùng lịch chỉ vì chạy nhiều chuyến.
6. Cập nhật hợp lệ tăng version một lần, lưu diff/audit, tạo snapshot job mới, đặt plan/job TMS `PENDING`. Không sửa lịch sử truck/job đã phát hành.
7. Chưa đủ thông tin: lưu BotReply chờ bổ sung. Đủ thông tin và đúng một tuyến khách active: tạo outbox; tuyến MANUAL chờ duyệt. Phản hồi trợ lý được lưu cùng transaction, gửi sau commit.

Không có thay đổi bảng/cột trong đợt này. Dùng schema và JSON hiện có, không cần migration mới. Không thêm rơ-moóc hay sự kiện GPS/POD.

## 4. Phạm vi báo cáo và giới hạn dữ liệu

- Danh sách theo ngày, lệnh/cont/xe/booking/BL; lịch sử thay đổi khách chỉ lấy thông báo update đã SENT vào chính nhóm khách.
- Tổng hợp SQL đếm toàn bộ lệnh theo loại/cỡ và có xe/chưa có xe. Số đã phát hành chỉ tính thông báo có liên kết job-plan thật.
- Cân đối vỏ ĐHVT loại các cảnh báo hạ rỗng, bên khác đã xin, SOC, quá số lượng kết hợp. Đây là cân đối số lượng, chưa chứng minh khả thi ghép tuyến/giờ.
- Nghi trùng xe được đánh dấu khi trùng giờ hẹn hoặc thiếu giờ; không tự suy thời gian vận chuyển.
- Ca ưu tiên là hàng chờ hiện tại; các báo cáo theo ngày dùng ngày được hỏi. Liệt kê tối đa 20 dòng, yêu cầu lọc thêm khi cần.
- Hiệu quả Bot thống kê số lượt rule/local/LLM từ extraction_runs, lỗi và thời gian đã ghi nhận; nhãn chưa biết giữ riêng. Không suy độ chính xác hoặc tỷ lệ ghép sai từ số lượt xử lý.
- Thông tin tiến độ chỉ là kế hoạch và trạng thái xử lý/phát hành. Chưa có GPS, POD, sự kiện cổng cảng. Không triển khai `trip_events` của Phase 1.5.

Thời gian tương đối tính theo thời điểm tin gốc, múi giờ Asia/Ho_Chi_Minh. ORM hiện lưu datetime không timezone theo giờ máy chủ Việt Nam; giá trị aware được đổi sang giờ Việt Nam. Không đổi toàn bộ quy ước thời gian của dữ liệu cũ trong đợt này.

## 5. AI fallback và cấu hình

`POST /api/v1/assistant-intent` chỉ nội bộ, bắt buộc `X-Internal-Token`. Request gồm `message_text` đã che SĐT, `allowed_tools`, `reference_date` của tin gốc. Response gồm `call`, `model_name`, `prompt_version`, `latency_ms`.

Local xử lý trước. Chỉ intent chưa rõ mới gọi client chung khi `AI_ENABLED`; hết hạn/mất kết nối/schema sai/quyền không hợp lệ thì hỏi rõ lại. Câu chứa cả hỏi và sửa cần tách yêu cầu; không tự ghi theo LLM. Chưa có cam kết tỷ lệ 75% local hoặc chính xác 100% nếu chưa đo bằng bộ tin vận hành được gán nhãn.

Trước khi thử ở nhóm vận hành: kiểm tra RouteMap khách, carrier_id nhóm/lệnh, danh mục xe và user ĐHVT gắn đúng nhóm. Lệnh chưa phân nhà xe cần ĐHVT gán trên Web/TMS trước. Trạng thái PENDING không đồng nghĩa ghi ngược TMS thành công.

## 6. Kiểm thử

Chạy từ `backend` bằng `.venv/bin/pytest tests -q`; chạy AI từ `ai-service` bằng `.venv/bin/pytest -q`. Bộ `test_assistant_phase1.py` kiểm tra router và hội thoại thật qua DB trong SAVEPOINT: chống dò chéo, loại lệnh RouteMap, quyền ĐHVT, xác nhận khác người/hết hạn/phiên bản cũ/lặp/quote outbox, cập nhật trường trống, chuyển review sau SENT, không gộp ca xuyên nhóm và chống LLM vượt quyền. Các tình huống mới dùng mock ở biên mạng, không gửi tin Zalo thật.
