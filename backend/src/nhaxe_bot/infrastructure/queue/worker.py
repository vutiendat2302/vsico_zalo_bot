"""Module Công Nhân Xử Lý Hàng Đợi (Queue Worker).

Đóng vai trò Consumer lấy tuần tự các thông điệp InboundMessage từ hàng đợi,
tích hợp bộ lọc tin rác (classify_junk), ranh giới bảo vệ toàn cục (run_safely),
bộ đệm ghép tin nghi ngờ 30 phút (SuspectMessageBuffer) và xuất bản kết quả ra `results.csv`.
"""

from datetime import datetime
from queue import Queue
from typing import List, Dict, Any, Optional, Callable
from ...ingestion.models import InboundMessage
from ...domain.enums import Intent
from ...messaging.classifier.base import IntentClassifier
from ...messaging.classifier.junk_filter import classify_junk, SuspectMessageBuffer
from ...messaging.router import IntentRouter
from ...parsing.fields.container import extract_containers
from ...observability.logging import log_event, request_id_ctx, msg_id_ctx, seq_ctx
from ..error_boundary import run_safely, ErrorAlertThrottler
from ..results_writer import ResultsWriter


class QueueWorker:
    """Tiến trình Worker xử lý tuần tự các tin nhắn từ hàng đợi Message Queue."""

    def __init__(
        self,
        queue: Queue,
        classifier: IntentClassifier,
        router: IntentRouter,
        results_writer: Optional[ResultsWriter] = None,
        throttler: Optional[ErrorAlertThrottler] = None,
        suspect_buffer: Optional[SuspectMessageBuffer] = None,
        admin_alert_fn: Optional[Callable[[str, str, int], None]] = None,
    ):
        """Khởi tạo Queue Worker với các phụ thuộc cần thiết.

        Args:
            queue (Queue): Hàng đợi FIFO chứa các thông điệp InboundMessage.
            classifier (IntentClassifier): Bộ phân loại ý định tin nhắn.
            router (IntentRouter): Bộ định tuyến Use Case Handler.
            results_writer (Optional[ResultsWriter], optional): Bộ ghi nhận kết quả ra CSV.
            throttler (Optional[ErrorAlertThrottler], optional): Bộ điều tiết cảnh báo Admin.
            suspect_buffer (Optional[SuspectMessageBuffer], optional): Bộ đệm tin nghi ngờ 30 phút.
            admin_alert_fn (Optional[Callable], optional): Hàm callback gửi cảnh báo Admin.
        """
        self.queue = queue
        self.classifier = classifier
        self.router = router
        self.results_writer = results_writer
        self.throttler = throttler or ErrorAlertThrottler()
        self.suspect_buffer = suspect_buffer or SuspectMessageBuffer()
        self.admin_alert_fn = admin_alert_fn

    def _handle_inbound_core(self, inbound: InboundMessage) -> List[Dict[str, Any]]:
        """Lõi nghiệp vụ xử lý một thông điệp InboundMessage (được bọc bởi run_safely).

        Quy trình xử lý:
        1. Cập nhật ContextVars (`request_id`, `msg_id`, `seq`).
        2. Nếu tin nhắn bị từ chối từ cửa ngõ Ingestion (nhóm lạ, người lạ, trùng tin, ảnh):
           Ghi nhận lý do và bỏ qua an toàn.
        3. Kiểm tra ghép tin nghi ngờ trong bộ đệm 30 phút (`SuspectMessageBuffer`).
        4. Phân loại độ tin cậy bằng hàm thuần `classify_junk`:
           - JUNK: Bỏ qua (IGNORE_CHAT), không phản hồi nhà xe, không sinh thông báo khách.
           - SUSPECT: Đánh dấu MANUAL_REVIEW, gửi câu xác nhận, báo Admin, lưu vào buffer 30p.
           - CANDIDATE: Đưa vào pipeline Classifier và Router để bóc tách và gửi thông báo.

        Args:
            inbound (InboundMessage): Thông điệp cần xử lý.

        Returns:
            List[Dict[str, Any]]: Danh sách các kết quả chi tiết của từng chuyến xe.
        """
        # Cập nhật ContextVars
        msg_id_ctx.set(inbound.msg_id)
        seq_ctx.set(inbound.seq)
        if inbound.request_id:
            request_id_ctx.set(inbound.request_id)
        current_req = request_id_ctx.get() or ""

        log_event(
            "INGEST",
            f"Bắt đầu xử lý tin seq {inbound.seq} (msg_id={inbound.msg_id})",
            msg_id=inbound.msg_id,
            seq=inbound.seq,
        )

        # 1. Nếu bị từ chối sớm từ cửa ngõ Ingestion
        if not inbound.is_valid:
            log_event(
                "INGEST",
                f"Tin bị từ chối: {inbound.action} ({inbound.drop_reason})",
                msg_id=inbound.msg_id,
                seq=inbound.seq,
            )
            context = {"action": inbound.action}
            results = self.router.dispatch(Intent.IGNORE_CHAT, inbound, context)
            for r in results:
                r["junk_verdict"] = "JUNK"
                r["junk_reason"] = inbound.drop_reason or "Bị từ chối tại cửa ngõ tiếp nhận"
                r["request_id"] = current_req
                r["error_code"] = ""
            return results

        # 2. Kiểm tra bộ đệm ghép tin nghi ngờ trong 30 phút
        active_text = inbound.raw_text
        merged_candidate = False
        if inbound.carrier_id:
            merged = self.suspect_buffer.get_merged_if_recent(inbound.carrier_id, inbound.raw_text)
            if merged:
                m_verdict, m_reason, _ = classify_junk(merged)
                if m_verdict == "CANDIDATE":
                    log_event(
                        "SUSPECT",
                        f"Ghép thành công với tin nghi ngờ trước đó của nhà xe {inbound.carrier_id}",
                        msg_id=inbound.msg_id,
                    )
                    active_text = merged
                    inbound.raw_text = merged
                    merged_candidate = True
                    self.suspect_buffer.clear(inbound.carrier_id)

        # 3. Phân loại tin rác / nghi ngờ qua classify_junk
        if not merged_candidate:
            verdict, reason, signals = classify_junk(active_text)
        else:
            verdict, reason = "CANDIDATE", "Ghép thành công với tin nghi ngờ trước đó trong 30 phút"

        inbound.junk_verdict = verdict
        inbound.junk_reason = reason

        # 4. Xử lý phân nhóm JUNK: Tin rác, xã giao
        if verdict == "JUNK":
            log_event("JUNK", f"Phát hiện tin rác / xã giao: {reason}", msg_id=inbound.msg_id)
            context = {
                "action": Intent.IGNORE_CHAT.value,
                "junk_verdict": "JUNK",
                "junk_reason": reason,
            }
            results = self.router.dispatch(Intent.IGNORE_CHAT, inbound, context)
            for r in results:
                r["junk_verdict"] = "JUNK"
                r["junk_reason"] = reason
                r["action"] = Intent.IGNORE_CHAT.value
                r["send_status"] = "SKIPPED_JUNK"
                r["notification_text"] = None  # Tin rác không sinh thông báo khách
                r["request_id"] = current_req
                r["error_code"] = ""
            return results

        # 5. Xử lý phân nhóm SUSPECT: Thiếu thông tin xe
        elif verdict == "SUSPECT":
            log_event("SUSPECT", f"Tin nghi ngờ thiếu thông tin xe: {reason}", msg_id=inbound.msg_id)
            if inbound.carrier_id:
                self.suspect_buffer.record_suspect(inbound.carrier_id, inbound.raw_text)

            reply_msg = "Anh/chị gửi đủ biển số, tài xế, SĐT, số cont, số chì giúp em"
            suspect_result = {
                "seq": inbound.seq,
                "msg_id": inbound.msg_id,
                "received_at": inbound.timestamp or datetime.now().isoformat(),
                "group_id": inbound.group_id,
                "sender_id": inbound.sender_id,
                "carrier_id": inbound.carrier_id,
                "action": Intent.MANUAL_REVIEW.value,
                "xe_index": 0,
                "status": "need_supplement",
                "admin_alert": True,
                "admin_message": f"Tin nhắn nghi ngờ thiếu thông tin từ nhà xe {inbound.carrier_id or 'lạ'}: {inbound.raw_text}",
                "reason": reason,
                "reply_to_carrier": reply_msg,
                "send_status": "HOLD_SUSPECT_REVIEW",
                "notification_text": None,
                "junk_verdict": "SUSPECT",
                "junk_reason": reason,
                "request_id": current_req,
                "error_code": "",
                "parser_source": "junk_filter",
            }
            return [suspect_result]

        # 6. Phân nhóm CANDIDATE: Tiếp tục phân tích bóc tách chuyên sâu
        conts = extract_containers(inbound.raw_text)
        intent = self.classifier.classify(inbound.raw_text, conts)
        log_event("CLASSIFY", f"Nhận diện Intent: {intent.value}", msg_id=inbound.msg_id)

        context = {
            "intent": intent,
            "conts": conts,
            "junk_verdict": "CANDIDATE",
            "junk_reason": reason,
        }
        results = self.router.dispatch(intent, inbound, context)
        for r in results:
            r["junk_verdict"] = "CANDIDATE"
            r["junk_reason"] = reason
            r["request_id"] = current_req
            if "error_code" not in r:
                r["error_code"] = ""

        log_event(
            "RESULT", f"Hoàn tất xử lý ({len(results)} kết quả)", msg_id=inbound.msg_id
        )
        return results

    def process_message(self, inbound: InboundMessage) -> List[Dict[str, Any]]:
        """Thực thi chu trình xử lý trọn vẹn được bảo vệ bởi ranh giới bắt lỗi toàn cục run_safely.

        Args:
            inbound (InboundMessage): Thông điệp cần xử lý.

        Returns:
            List[Dict[str, Any]]: Danh sách các kết quả chi tiết của từng chuyến xe.
        """
        return run_safely(
            handler_fn=self._handle_inbound_core,
            inbound=inbound,
            alert_fn=self.admin_alert_fn,
            results_writer=self.results_writer,
            throttler=self.throttler,
        )

    def process_all_queued(self) -> List[Dict[str, Any]]:
        """Lấy và xử lý tuần tự toàn bộ các thông điệp đang có trong hàng đợi cho đến khi rỗng.

        Returns:
            List[Dict[str, Any]]: Danh sách tổng hợp kết quả của tất cả các tin nhắn đã xử lý.
        """
        all_results = []
        while not self.queue.empty():
            msg = self.queue.get()
            res = self.process_message(msg)
            all_results.extend(res)
            self.queue.task_done()
        return all_results
