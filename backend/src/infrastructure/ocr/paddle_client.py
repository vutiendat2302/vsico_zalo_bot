"""Client Kết Nối & Tương Tác Dịch Vụ PaddleOCR Tự Host (Self-Hosted Local PaddleOCR).

Chịu trách nhiệm:
1. Tiếp nhận dữ liệu ảnh từ tin nhắn Zalo (URL, Base64, đường dẫn file cục bộ hoặc raw bytes).
2. Chuẩn hóa và gửi tới mô hình PaddleOCR tự host cục bộ (PaddleHub Serving hoặc Microservice FastAPI).
3. Sắp xếp các hộp nhận diện (Bounding Boxes) theo thứ tự đọc tự nhiên từ trên xuống dưới, trái qua phải.
4. Trả về văn bản đã ghép dòng, điểm tin cậy trung bình và danh sách chi tiết các từ/dòng.
5. Chống chịu lỗi (Fault Tolerance & Graceful Degradation): Nếu dịch vụ OCR ngoại tuyến,
   không làm sập luồng xử lý tin nhắn mà ghi nhận cảnh báo và xử lý mềm dẻo.
"""

import base64
import json
import logging
import os
import re
from typing import Any, Optional
import urllib.parse
import urllib.request

from src.config.settings import settings

logger = logging.getLogger("nhaxe_bot.ocr.paddle")


class PaddleOCRClient:
    """Bộ giao tiếp với mô hình PaddleOCR chạy local để nhận diện văn bản từ ảnh."""

    @classmethod
    def is_image_payload(cls, payload_dict: dict[str, Any]) -> bool:
        """Kiểm tra xem một payload tin nhắn Zalo có chứa dữ liệu ảnh hay không.

        Hỗ trợ các trường:
        - `image_url`, `image_base64`, `image_path` ở cấp root
        - `message.image_url`, `message.url`, `message.href`, `message.src`
        - `attachments` danh sách tệp đính kèm có loại 'image' hoặc đuôi ảnh (.png, .jpg, .jpeg)
        - `event_name` là 'user_send_image'
        """
        if not isinstance(payload_dict, dict):
            return False

        if payload_dict.get("event_name") == "user_send_image":
            return True

        if payload_dict.get("image_url") or payload_dict.get("image_base64") or payload_dict.get("image_path"):
            return True

        if payload_dict.get("mock_ocr_text") is not None:
            return True

        nested_msg = payload_dict.get("message")
        if isinstance(nested_msg, dict):
            if nested_msg.get("image_url") or nested_msg.get("image_base64") or nested_msg.get("image_path"):
                return True
            url_candidate = nested_msg.get("url") or nested_msg.get("href") or nested_msg.get("src")
            if url_candidate and cls._is_image_url(str(url_candidate)):
                return True

        attachments = payload_dict.get("attachments")
        if isinstance(attachments, list) and len(attachments) > 0:
            for att in attachments:
                if isinstance(att, dict):
                    att_type = str(att.get("type", "")).lower()
                    att_url = str(att.get("url") or att.get("href") or "")
                    if att_type in ("image", "photo") or cls._is_image_url(att_url):
                        return True

        return False

    @classmethod
    def extract_text_from_payload(
        cls, payload_dict: dict[str, Any]
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Trích xuất văn bản từ một payload tin nhắn Zalo chứa ảnh.

        Args:
            payload_dict (dict[str, Any]): Dữ liệu raw của webhook tin nhắn.

        Returns:
            tuple[str, float, list[dict[str, Any]]]:
                - Văn bản thô đã ghép dòng từ kết quả OCR (`\n` giữa các dòng).
                - Điểm tin cậy trung bình (0.0 - 1.0).
                - Danh sách các hộp chi tiết `[{"text": ..., "confidence": ..., "box": ...}]`.
        """
        if not settings.OCR_ENABLED:
            logger.info("Chức năng OCR đang bị tắt (OCR_ENABLED=False).")
            return "", 0.0, []

        # 1. Hỗ trợ dữ liệu giả lập kiểm thử nhanh (Mock test)
        mock_text = payload_dict.get("mock_ocr_text")
        if mock_text is not None:
            text_str = str(mock_text).strip()
            return text_str, 0.99, [{"text": text_str, "confidence": 0.99, "box": []}] if text_str else ("", 0.0, [])

        # 2. Thu thập nguồn ảnh (URL, Base64, Đường dẫn tệp)
        image_input = cls._find_image_input(payload_dict)
        if not image_input:
            logger.debug("Không tìm thấy thông tin hình ảnh hợp lệ trong payload.")
            return "", 0.0, []

        return cls.extract_text(image_input)

    @classmethod
    def extract_text(
        cls, image_input: str | bytes
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Thực thi nhận diện ký tự quang học qua dịch vụ PaddleOCR tự host.

        Args:
            image_input (str | bytes): Đường dẫn file, URL http/https, chuỗi base64 hoặc bytes.

        Returns:
            tuple[str, float, list[dict[str, Any]]]:
                `(văn bản đã bóc tách, độ tin cậy trung bình, chi tiết từng dòng)`.
        """
        # 1. Chuẩn hóa hình ảnh thành chuỗi Base64
        base64_str = cls._to_base64(image_input)
        if not base64_str:
            logger.warning("Không thể đọc hoặc chuẩn hóa dữ liệu ảnh đầu vào sang Base64.")
            return "", 0.0, []

        # 2. Gọi HTTP Service PaddleOCR tự host (PaddleHub Serving / Microservice)
        result = cls._call_remote_paddleocr(base64_str)
        if result is not None:
            return result

        # 3. Fallback: Nếu không kết nối được dịch vụ HTTP, kiểm tra xem có thư viện paddleocr cục bộ trong Python không
        local_result = cls._call_inprocess_paddleocr(image_input)
        if local_result is not None:
            return local_result

        logger.warning(
            "Dịch vụ PaddleOCR tại '%s' hiện không phản hồi. Trả về kết quả rỗng.",
            settings.PADDLE_OCR_URL,
        )
        return "", 0.0, []

    # =========================================================================
    # CÁC HÀM XỬ LÝ NỘI BỘ (HELPER METHODS)
    # =========================================================================

    @classmethod
    def _find_image_input(cls, payload_dict: dict[str, Any]) -> Optional[str]:
        """Tìm đường dẫn, base64 hoặc URL ảnh từ các vị trí có thể có trong payload."""
        for key in ("image_base64", "image_url", "image_path"):
            val = payload_dict.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

        nested_msg = payload_dict.get("message")
        if isinstance(nested_msg, dict):
            for key in ("image_base64", "image_url", "image_path", "url", "href", "src"):
                val = nested_msg.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()

        attachments = payload_dict.get("attachments")
        if isinstance(attachments, list):
            for att in attachments:
                if isinstance(att, dict):
                    att_url = att.get("url") or att.get("href") or att.get("path")
                    if att_url and isinstance(att_url, str) and att_url.strip():
                        return att_url.strip()

        return None

    @classmethod
    def _is_image_url(cls, url: str) -> bool:
        """Kiểm tra chuỗi có định dạng URL ảnh phổ biến hay không."""
        clean = url.lower().split("?")[0]
        return any(clean.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".jfif"))

    @classmethod
    def _to_base64(cls, image_input: str | bytes) -> Optional[str]:
        """Chuyển đổi các dạng ảnh khác nhau về chuỗi Base64 chuẩn."""
        if isinstance(image_input, bytes):
            return base64.b64encode(image_input).decode("utf-8")

        clean_str = image_input.strip()

        # Dạng Data URI: data:image/png;base64,iVBOR...
        if clean_str.startswith("data:image/") and ";base64," in clean_str:
            return clean_str.split(";base64,", 1)[1].strip()

        # Dạng Base64 thuần
        if len(clean_str) > 100 and not clean_str.startswith(("http://", "https://", "/")) and "\n" not in clean_str:
            # Kiểm tra cơ bản ký tự base64
            if re.match(r"^[A-Za-z0-9+/=]+$", clean_str[:100]):
                return clean_str

        # Dạng đường dẫn tệp cục bộ
        if os.path.isfile(clean_str):
            try:
                with open(clean_str, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception as e:
                logger.error("Lỗi đọc file ảnh cục bộ '%s': %s", clean_str, e)
                return None

        # Dạng URL mạng (HTTP / HTTPS)
        if clean_str.startswith(("http://", "https://")):
            try:
                req = urllib.request.Request(
                    clean_str,
                    headers={"User-Agent": "VSICO-Zalo-Bot-OCR/2.0"},
                )
                with urllib.request.urlopen(req, timeout=settings.OCR_TIMEOUT_SECONDS) as resp:
                    data = resp.read()
                    return base64.b64encode(data).decode("utf-8")
            except Exception as e:
                logger.warning("Không thể tải ảnh từ URL '%s': %s", clean_str, e)
                return None

        return None

    @classmethod
    def _call_remote_paddleocr(
        cls, base64_image: str
    ) -> Optional[tuple[str, float, list[dict[str, Any]]]]:
        """Gửi yêu cầu nhận diện sang máy chủ PaddleOCR (PaddleHub Serving / REST API)."""
        url = settings.PADDLE_OCR_URL.strip()
        if not url:
            return None

        # Hỗ trợ cả 2 chuẩn giao tiếp phổ biến của Paddle:
        # Chuẩn 1: PaddleHub Serving {"images": [base64_str]}
        # Chuẩn 2: Generic Microservice {"image": base64_str}
        req_body = json.dumps({
            "images": [base64_image],
            "image": base64_image,
            "lang": settings.OCR_LANG,
        }).encode("utf-8")

        req = urllib.request.Request(
            url=url,
            data=req_body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "VSICO-Zalo-Bot-OCR/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=settings.OCR_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    logger.warning("PaddleOCR server trả về HTTP status %s", response.status)
                    return None

                raw_bytes = response.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                return cls._parse_paddle_response(data)
        except urllib.error.URLError as e:
            logger.debug("Không thể kết nối máy chủ PaddleOCR tại %s: %s", url, e)
            return None
        except Exception as e:
            logger.warning("Lỗi xử lý phản hồi từ PaddleOCR: %s", e)
            return None

    @classmethod
    def _parse_paddle_response(
        cls, data: dict[str, Any]
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Phân tích cú pháp dữ liệu JSON từ các biến thể của PaddleOCR."""
        items: list[dict[str, Any]] = []

        # Định dạng 1: PaddleHub Serving (status: "000", results: [[{"text": ..., "confidence": ..., "text_region": ...}]])
        if "results" in data and isinstance(data["results"], list):
            res_list = data["results"]
            if len(res_list) > 0 and isinstance(res_list[0], list):
                for box_item in res_list[0]:
                    if isinstance(box_item, dict):
                        t = str(box_item.get("text", "")).strip()
                        c = float(box_item.get("confidence", 0.0))
                        reg = box_item.get("text_region") or []
                        if t:
                            items.append({"text": t, "confidence": c, "box": reg})

        # Định dạng 2: Direct REST Microservice {"text": "...", "lines": [...]}
        elif "lines" in data and isinstance(data["lines"], list):
            for line_item in data["lines"]:
                if isinstance(line_item, dict):
                    t = str(line_item.get("text", "")).strip()
                    c = float(line_item.get("confidence", 0.9))
                    reg = line_item.get("box", [])
                    if t:
                        items.append({"text": t, "confidence": c, "box": reg})
                elif isinstance(line_item, str) and line_item.strip():
                    items.append({"text": line_item.strip(), "confidence": 0.9, "box": []})

        # Định dạng 3: Python PaddleOCR direct dump: `[[box, [text, conf]], ...]`
        elif "data" in data and isinstance(data["data"], list):
            for entry in data["data"]:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    reg = entry[0]
                    text_info = entry[1]
                    if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                        t = str(text_info[0]).strip()
                        c = float(text_info[1])
                        if t:
                            items.append({"text": t, "confidence": c, "box": reg})

        if not items:
            # Nếu phản hồi có trường 'text' trực tiếp
            direct_text = data.get("text") or data.get("raw_text")
            if direct_text and isinstance(direct_text, str) and direct_text.strip():
                return direct_text.strip(), 0.9, [{"text": direct_text.strip(), "confidence": 0.9, "box": []}]
            return "", 0.0, []

        # Sắp xếp các đoạn văn theo chiều dọc (trên xuống dưới) để đảm bảo đúng thứ tự dòng
        sorted_items = cls._sort_boxes_by_reading_order(items)
        lines = [it["text"] for it in sorted_items if it["text"]]
        combined_text = "\n".join(lines).strip()
        avg_confidence = round(sum(it["confidence"] for it in sorted_items) / len(sorted_items), 3)

        return combined_text, avg_confidence, sorted_items

    @classmethod
    def _sort_boxes_by_reading_order(
        cls, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Sắp xếp các khối văn bản theo trật tự đọc tự nhiên (tọa độ Y từ trên xuống, X từ trái qua)."""
        def get_top_y(item: dict[str, Any]) -> float:
            box = item.get("box")
            if isinstance(box, (list, tuple)) and len(box) >= 1:
                p = box[0]
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    return float(p[1])
            return 0.0

        def get_left_x(item: dict[str, Any]) -> float:
            box = item.get("box")
            if isinstance(box, (list, tuple)) and len(box) >= 1:
                p = box[0]
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    return float(p[0])
            return 0.0

        # Nếu các item có box tọa độ, sắp xếp theo Y x 1000 + X để phân dòng hợp lý
        has_coords = any(bool(it.get("box")) for it in items)
        if has_coords:
            return sorted(items, key=lambda it: (round(get_top_y(it) / 15) * 1000 + get_left_x(it)))
        return items

    @classmethod
    def _call_inprocess_paddleocr(
        cls, image_input: str | bytes
    ) -> Optional[tuple[str, float, list[dict[str, Any]]]]:
        """Fallback: Nếu cài sẵn thư viện `paddleocr` trong Python, chạy trực tiếp in-process."""
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError:
            return None

        try:
            ocr = PaddleOCR(use_angle_cls=True, lang=settings.OCR_LANG, show_log=False)
            res = ocr.ocr(image_input, cls=True)
            if not res or len(res) == 0 or res[0] is None:
                return "", 0.0, []

            items = []
            for line_res in res[0]:
                box = line_res[0]
                text_tuple = line_res[1]
                t = str(text_tuple[0]).strip()
                c = float(text_tuple[1])
                if t:
                    items.append({"text": t, "confidence": c, "box": box})

            if not items:
                return "", 0.0, []

            sorted_items = cls._sort_boxes_by_reading_order(items)
            lines = [it["text"] for it in sorted_items if it["text"]]
            combined = "\n".join(lines).strip()
            avg_conf = round(sum(it["confidence"] for it in sorted_items) / len(sorted_items), 3)
            return combined, avg_conf, sorted_items
        except Exception as e:
            logger.warning("Lỗi chạy in-process PaddleOCR: %s", e)
            return None
