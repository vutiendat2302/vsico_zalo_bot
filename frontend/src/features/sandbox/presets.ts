import type { SandboxPreset } from "./types";

/**
 * Danh sách kịch bản đầu vào mẫu (chỉ điền sẵn ô Input để kiểm thử nhanh thuật toán Backend).
 * Mọi kết quả phân tích đều được tính trực tiếp từ API `/api/sandbox/simulate`.
 */
export const PRESETS: SandboxPreset[] = [
  {
    id: "valid_full",
    label: "Đủ 8 trường",
    category: "Điều xe mới",
    description: "Tin báo đủ Khách hàng, Lệnh, Xe, Tài xế, SĐT, Cont ISO 6346, Size, Chì (0 token AI).",
    text: "Khách hàng: Nhựa Á Đông\nLệnh: trả hàng\nXe: 15H-012.34 / Mooc: 15R-045.67\nTài xế: Nguyễn Văn Nam - 0912345678\nCont: VSIU7399796 - Size: 40HC - Số chì: SL998877\nĐiểm trả: Kho Nhựa Á Đông Long An\nDự kiến đến kho: 08:30",
    suggested_follow_up:
      "Đổi xe cont VSIU7399796 sang xe 29H-556.67 tài xế Phạm Minh Tuấn 0987654321 dự kiến 10:00",
  },
  {
    id: "missing_seal",
    label: "Thiếu chì",
    category: "Thiếu trường",
    description: "Cố tình thiếu Số chì để hệ thống sinh tin nhắc Nhà xe và tạo ca chờ bổ sung.",
    text: "Khách hàng: Daikin, Xe 50H-049.15 lái xe Trần Bình 0912345678 trả hàng cont TEMU4455662 40HC tại Kho Daikin Hưng Yên hẹn 09:30",
    suggested_follow_up: "Bổ sung số chì HL778899",
  },
  {
    id: "quote_supplement",
    label: "Quote bù chì",
    category: "Bối cảnh Quote",
    description: "Giả lập nhà xe Quote lại tin nhắc của Bot để bổ sung Số chì còn thiếu.",
    text: "Bổ sung số chì HL778899",
    quote_message:
      "[VSICO BOT] Nhờ nhà xe kiểm tra bổ sung thông tin:\n- Cont TEMU4455662: Thiếu Số chì (seal)",
  },
  {
    id: "update_missing_cont",
    label: "Đổi xe thiếu Cont",
    category: "Hiểu bối cảnh",
    description: "Tin báo đổi xe không nêu Số Container -> Hệ thống nhận diện đúng UPDATE_REQUEST và hỏi lại Số Cont.",
    text: "Đổi sang xe 15C-999.88 tài xế Lê Hùng 0988777666",
  },
  {
    id: "update_with_cont",
    label: "Đổi xe có Cont",
    category: "Hiểu bối cảnh",
    description: "Tin đầu hoặc bối cảnh có CSNU7788996, sau đó đổi xe/tài xế để hệ thống tính diff trường thay đổi.",
    text: "Khách hàng: Samsung Vina\nLệnh: đóng hàng\nXe: 15C-170.66 - Tài xế: Đỗ Văn An 0903456789\nCont: CSNU7788996 40HC - Seal: SS112233\nĐiểm đóng: KCN Yên Phong Bắc Ninh - ETA: 14:00",
    suggested_follow_up:
      "Cập nhật đổi xe cont CSNU7788996 sang xe 15C-999.88 tài xế Lê Hùng 0988777666",
  },
  {
    id: "cancel_request",
    label: "Hủy chuyến",
    category: "Hiểu bối cảnh",
    description: "Phát hiện ý định hủy chuyến, đánh dấu trạng thái hủy trong phiên và cảnh báo ĐHVT.",
    text: "Báo hủy chuyến cont CSNU7788996 xe 15C-999.88 do khách hoãn lịch nhận hàng",
  },
  {
    id: "multi_vehicle",
    label: "Đa xe / đa Cont",
    category: "Phân đoạn đa xe",
    description: "Kiểm tra khả năng tách 2 container và giữ chung ngữ cảnh Khách hàng, Lệnh, Kho.",
    text: "Khách hàng: Canon Việt Nam\nLệnh: trả hàng tại Kho Canon Thăng Long - 08:00\n1. Xe 29H-111.22 - Hoàng Văn Long 0911222333 - Cont MSCU1234566 40HC - Chì CN001122\n2. Xe 29H-333.44 - Ngô Văn Hải 0944555666 - Cont TEMU4455662 40HC - Chì CN003344",
  },
  {
    id: "invalid_iso",
    label: "Sai ISO 6346",
    category: "Kiểm tra hợp lệ",
    description: "Container MSCU1234560 có chữ số kiểm tra sai (đúng phải là 6) -> Cảnh báo lỗi ISO 6346.",
    text: "Khách hàng: LG Display, Xe 15H-888.99 tài xế Vũ Thành 0977888999 trả hàng cont MSCU1234560 40DC seal LG556677 kho VSIP Hải Phòng",
  },
  {
    id: "casual_chat",
    label: "Xã giao",
    category: "Tối ưu Token",
    description: "Kiểm tra Fast Gatekeeper chặn tin nhắn không mang nghiệp vụ ở tầng 1 (< 1ms, 0 token AI).",
    text: "Chào buổi sáng cả nhà, chúc anh em chạy xe an toàn nhé!",
  },
  {
    id: "ambiguous_ai_pii",
    label: "Tự do + SĐT",
    category: "AI & PII Masking",
    description: "Tin nhắn viết tắt thiếu nhãn chuẩn và chứa SĐT 0903123459 để kiểm tra cơ chế che PII (0903xxxx59) & ngưỡng gọi AI.",
    text: "cho xe 29h77889 vao ha dong cty Minh Anh chieu nay nhe, a Tuan lai 0903123459, cont bao sau",
  },
];
