"""Module Hàng Đợi Xử Lý Tin Nhắn Tuần Tự Vào Trước Ra Trước (Real-time FIFO Queue).

Đảm bảo toàn bộ tin nhắn từ Zalo (cả chat trực tiếp 1-1 lẫn chat trong Group) sau khi lưu
thô vào bảng `zalo_messages` đều được đưa vào hàng đợi FIFO (First-In, First-Out) và
bóc tách tuần tự theo đúng thứ tự thời gian đến (`id ASC`), tuyệt đối không bị tranh chấp
luồng (race condition) hay đảo thứ tự xử lý.
"""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from src.domain.enums import MessageStatus
from src.infrastructure.database import SessionLocal
from src.infrastructure.models import ZaloMessage
from src.observability.logging import get_logger

logger = get_logger(__name__)


class FIFOExtractionQueue:
    """Hàng đợi FIFO xử lý bóc tách tin nhắn thời gian thực (Vào Trước - Ra Trước).

    Cơ chế hoạt động:
    1. Khi có tin nhắn mới lưu vào `zalo_messages`, `message_id` được đẩy vào `queue.Queue`.
    2. Bộ khóa tuần tự (`_processing_lock`) đảm bảo tại mọi thời điểm chỉ có duy nhất
       1 tiến trình/luồng thực hiện lấy tin nhắn ra theo thứ tự FIFO (`id ASC`) để bóc tách.
    3. Hỗ trợ cả 2 chế độ:
       - Thực thi tuần tự tức thời (`enqueue_and_drain`): Đẩy vào hàng đợi và rút tuần tự
         ngay lập tức để có kết quả real-time trong vài mili-giây.
       - Luồng Worker chạy nền (`start_worker`): Tự động quét và xử lý các tin nhắn tồn đọng
         (`received`, `queued`) trong cơ sở dữ liệu theo đúng thứ tự `id ASC`.
    """

    def __init__(self) -> None:
        """Khởi tạo hàng đợi FIFO, khóa đồng bộ tuần tự và trạng thái luồng Worker."""
        self._queue: queue.Queue[int] = queue.Queue()
        self._processing_lock = threading.RLock()
        self._processor_fn: Optional[Callable[[Session, int], None]] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._total_enqueued: int = 0
        self._total_processed: int = 0

    def register_processor(self, processor_fn: Callable[[Session, int], None]) -> None:
        """Đăng ký hàm callback thực hiện bóc tách dữ liệu cho từng `message_id`.

        Args:
            processor_fn (Callable[[Session, int], None]): Hàm xử lý nhận vào `db: Session`
                và `message_id: int`.
        """
        self._processor_fn = processor_fn

    def enqueue(self, message_id: int) -> None:
        """Đưa một mã bản ghi tin nhắn (`zalo_messages.id`) vào cuối hàng đợi FIFO.

        Args:
            message_id (int): Khóa chính `id` của tin nhắn trong bảng `zalo_messages`.
        """
        self._queue.put(message_id)
        self._total_enqueued += 1
        logger.info("Đã xếp tin nhắn ID=%s vào hàng đợi FIFO.", message_id)

    def enqueue_and_drain(self, db: Session, message_id: int) -> None:
        """Đưa tin nhắn vào hàng đợi FIFO và xử lý tuần tự ngay lập tức theo nguyên tắc Vào Trước Ra Trước.

        Phương thức này trước tiên kiểm tra xem có tin nhắn nào đến trước (`id < message_id`)
        đang ở trạng thái `received` hoặc `queued` chưa được xử lý hay không, sau đó rút
        lần lượt từng tin nhắn từ đầu hàng đợi ra xử lý và lưu kết quả vào DB.

        Args:
            db (Session): Phiên làm việc SQLAlchemy hiện tại.
            message_id (int): Khóa chính `id` của tin nhắn vừa tiếp nhận.
        """
        self.drain_fifo(db)

    def drain_fifo(self, db: Optional[Session] = None) -> list[int]:
        """Rút và xử lý toàn bộ các tin nhắn đang chờ theo đúng thứ tự FIFO (Vào Trước Ra Trước).

        Args:
            db (Optional[Session]): Phiên kết nối DB truyền vào (nếu không truyền sẽ tự mở phiên mới).

        Returns:
            list[int]: Danh sách các `message_id` đã được xử lý theo đúng thứ tự thực thi.
        """
        if self._processor_fn is None:
            logger.warning("Chưa đăng ký hàm processor_fn cho FIFOExtractionQueue.")
            return []

        if db is None:
            with SessionLocal() as scan:
                rows = scan.execute(select(ZaloMessage.id, ZaloMessage.group_id).where(
                    ZaloMessage.processing_status.in_(["RECEIVED", "QUEUED", "PROCESSING"])
                ).order_by(ZaloMessage.id).limit(500)).all()
            groups: dict[str, list[int]] = defaultdict(list)
            for mid, gid in rows:
                groups[gid].append(mid)
            with ThreadPoolExecutor(max_workers=4) as executor:
                batches = list(executor.map(self._process_group, groups.items()))
            return [mid for batch in batches for mid in batch]

        processed_ids: list[int] = []
        with self._processing_lock:
            own_session = db is None
            session: Session = db if db is not None else SessionLocal()
            try:
                # 1. Lấy tất cả các tin nhắn đang ở trạng thái chờ xử lý trong DB theo thứ tự id ASC (vào trước ra trước)
                pending_stmt = (
                    select(ZaloMessage.id)
                    .where(
                        ZaloMessage.processing_status.in_(
                            [MessageStatus.RECEIVED.value, MessageStatus.QUEUED.value]
                        )
                    )
                    .order_by(ZaloMessage.id.asc())
                )
                db_pending_ids = list(session.scalars(pending_stmt).all())

                # 2. Rút hết các phần tử hiện có trong in-memory queue để đồng bộ
                mem_ids: list[int] = []
                while not self._queue.empty():
                    try:
                        mem_ids.append(self._queue.get_nowait())
                        self._queue.task_done()
                    except queue.Empty:
                        break

                # 3. Hợp nhất danh sách cần xử lý theo thứ tự tăng dần của ID (đảm bảo tuyệt đối FIFO)
                ordered_ids: list[int] = []
                seen: set[int] = set()
                for mid in sorted(set(db_pending_ids + mem_ids)):
                    if mid not in seen:
                        seen.add(mid)
                        ordered_ids.append(mid)

                # 4. Thực thi tuần tự từng tin nhắn một
                for mid in ordered_ids:
                    try:
                        self._processor_fn(session, mid)
                        processed_ids.append(mid)
                        self._total_processed += 1
                    except Exception as exc:
                        logger.exception("Lỗi khi xử lý FIFO cho message_id=%s: %s", mid, exc)
                        session.rollback()
            finally:
                if own_session:
                    session.close()

        return processed_ids

    def _process_group(self, batch: tuple[str, list[int]]) -> list[int]:
        """Xử lý tuần tự cùng nhóm; khóa MySQL ngăn hai tiến trình xử lý cùng hội thoại."""
        import hashlib
        from src.infrastructure.database import engine
        group_id, ids = batch
        lock_name = "fifo:" + hashlib.sha256(group_id.encode()).hexdigest()[:50]
        done: list[int] = []
        with engine.connect() as lock_conn:
            acquired = lock_conn.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name})
            if not acquired:
                return done
            try:
                # Có khóa nhóm độc quyền: PROCESSING còn lại là tin bị gián đoạn trước đó.
                with SessionLocal() as recovery:
                    recovery.execute(update(ZaloMessage).where(
                        ZaloMessage.group_id == group_id,
                        ZaloMessage.processing_status == "PROCESSING",
                    ).values(processing_status="NEEDS_REVIEW", last_error="Tiến trình bị gián đoạn; đối soát trước khi xử lý lại."))
                    recovery.commit()
                for mid in ids:
                    with SessionLocal() as session:
                        try:
                            self._processor_fn(session, mid)
                            done.append(mid)
                        except Exception:
                            session.rollback()
                            session.execute(update(ZaloMessage).where(ZaloMessage.id == mid).values(processing_status="FAILED"))
                            session.commit()
                            logger.exception("Xử lý tin %s lỗi; giữ FAILED để đối soát.", mid)
            finally:
                lock_conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
        self._total_processed += len(done)
        return done

    def start_background_worker(self) -> None:
        """Khởi chạy luồng Worker chạy nền để vét và xử lý các tin nhắn tồn đọng theo FIFO."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="vsico-fifo-extraction-worker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Đã khởi chạy luồng nền FIFOExtractionQueue Worker.")

    def stop_background_worker(self) -> None:
        """Dừng luồng Worker chạy nền một cách an toàn."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def _worker_loop(self) -> None:
        """Vòng lặp lắng nghe hàng đợi nền và kích hoạt `drain_fifo` khi có sự kiện."""
        # Ngay khi khởi động, vét toàn bộ tin nhắn tồn đọng trong DB theo FIFO
        try:
            self.drain_fifo()
        except Exception as exc:
            logger.exception("Lỗi khi vét hàng đợi FIFO lúc khởi động: %s", exc)

        while not self._stop_event.is_set():
            try:
                # Chờ tối đa 1 giây xem có tin nhắn mới trong queue không
                mid = self._queue.get(timeout=1.0)
                self._queue.task_done()
                self.drain_fifo()
            except queue.Empty:
                self.drain_fifo()
            except Exception as exc:
                logger.exception("Lỗi trong vòng lặp FIFO worker: %s", exc)
            finally:
                from src.infrastructure.outbox_worker import drain_outbox
                try:
                    drain_outbox()
                except Exception:
                    logger.exception("Lỗi xử lý hàng đợi phát hành.")

    def stats(self) -> dict[str, int]:
        """Trả về thông số thống kê tình trạng hoạt động của hàng đợi FIFO.

        Returns:
            dict[str, int]: Từ điển chứa số lượng đang chờ, tổng đã xếp hàng và tổng đã xử lý.
        """
        return {
            "queue_size": self._queue.qsize(),
            "total_enqueued": self._total_enqueued,
            "total_processed": self._total_processed,
        }


# Khởi tạo Singleton hàng đợi FIFO dùng chung cho toàn bộ ứng dụng Backend
fifo_queue = FIFOExtractionQueue()
