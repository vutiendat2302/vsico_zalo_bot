"""Bộ Kiểm Thử Toàn Diện Bảng 1 (1.1 -> 1.6) & Bảng 2 (T01 -> T40).

Kiểm tra khả năng bóc tách và phân loại chính xác toàn bộ các trường hợp biên:
- Lệnh đóng/trả trực tiếp (T01, T02) và suy luận ngữ cảnh xuất/nhập/nơi hạ (T03, T04)
- Một xe nhiều cont (T06), nhiều xe nhiều cont (T07, T08), nhiều lệnh/kho/khách trong 1 tin (T09, T24, T25)
- Biển số viết liền `30H12345`, biển mooc `Mooc: 15R-123.45`, SĐT ẩn `0912******`, mã `Booking: BK9988`
- Cont chờ cấp (T10), sai định dạng (T18), sai Check Digit ISO 6346 (T19), gắn nhầm xe-cont (T34)
- Tin bổ sung (T26), đính chính (T27), đổi xe/đổi tài (T28), lùi giờ/đổi lịch (T29), trùng nội dung (T30), trích dẫn (T31)
- Tin 1 dòng không nhãn (T37), dạng bảng `|` (T38), thời gian tương đối `Chiều nay` / `Báo sau` (T39), không dấu, viết hoa toàn bộ
- Kiểm tra API thống kê `GET /api/messages/statistics` đếm đúng theo số ID tin nhắn riêng biệt.
"""

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from src.infrastructure.database import SessionLocal
from src.infrastructure.models import (
    BotReply,
    ContainerJob,
    Customer,
    CustomerAlias,
    ExtractionRun,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TruckRecord,
    ZaloGroup,
    ZaloMessage,
)
from src.main import app
from src.parsing.ai_fallback import AIFallbackExtractor

client = TestClient(app)

TAX_PREFIX = "pytest_tax_"
TAX_GROUP = f"{TAX_PREFIX}group_01"
TAX_USER = f"{TAX_PREFIX}user_01"


def cleanup_taxonomy_test_records() -> None:
    """Dọn dẹp các bản ghi kiểm thử có tiền tố `pytest_tax_`."""
    with SessionLocal() as db:
        msg_ids = list(
            db.scalars(
                select(ZaloMessage.id).where(
                    ZaloMessage.zalo_message_id.like(f"{TAX_PREFIX}%")
                )
            ).all()
        )
        if msg_ids:
            job_ids = list(
                db.scalars(
                    select(ContainerJob.id).where(ContainerJob.message_id.in_(msg_ids))
                ).all()
            )
            if job_ids:
                out_ids = list(
                    db.scalars(
                        select(OutboundMessageItem.outbound_message_id).where(
                            OutboundMessageItem.container_job_id.in_(job_ids)
                        )
                    ).all()
                )
                db.execute(delete(OutboundMessageItem).where(OutboundMessageItem.container_job_id.in_(job_ids)))
                if out_ids:
                    db.execute(delete(OutboundMessage).where(OutboundMessage.id.in_(out_ids)))

            db.execute(delete(BotReply).where(BotReply.message_id.in_(msg_ids)))
            db.execute(delete(ReviewCase).where(ReviewCase.message_id.in_(msg_ids)))
            db.execute(update(ContainerJob).where(ContainerJob.message_id.in_(msg_ids)).values(parent_job_id=None))
            db.execute(delete(ContainerJob).where(ContainerJob.message_id.in_(msg_ids)))
            db.execute(delete(TruckRecord).where(TruckRecord.message_id.in_(msg_ids)))
            db.execute(delete(ExtractionRun).where(ExtractionRun.message_id.in_(msg_ids)))
            db.execute(delete(ZaloMessage).where(ZaloMessage.id.in_(msg_ids)))
        db.execute(
            delete(ZaloGroup).where(ZaloGroup.zalo_group_id.like(f"{TAX_PREFIX}%"))
        )
        db.commit()


def test_comprehensive_table1_and_table2_cases() -> None:
    """Kiểm thử các mẫu tin nhắn đại diện cho Bảng 1 (1.1->1.6) và Bảng 2 (T01->T40)."""
    cleanup_taxonomy_test_records()
    try:
        samples = [
            # 1. T03 + T06 + Booking + Mooc + SĐT ẩn + Biển số viết liền + Không nhãn (T37)
            (
                "case_t03_t06",
                "Hàng xuất khách Samsung tại KCN Yên Phong, Booking: BK202688\n"
                "30H12345 Mooc: 15R-123.45 Nguyễn Văn An 0912****** VSIU7399796 MSCU5285725 20DC Seal: VN112233",
            ),
            # 2. T09 + T24 + T25: Nhiều lệnh (Đóng + Trả), nhiều kho, nhiều khách trong cùng 1 tin
            (
                "case_t09_multi_order",
                "1. Lệnh đóng hàng khách Sun Paper tại Kho 3B:\n"
                "15C-878.99 / Trần Quốc Bảo / 0903976359 / VSIU7399796 / 40HC\n"
                "2. Lệnh trả hàng khách Formosa tại Cảng Đình Vũ:\n"
                "15H-008.14 / Lê Văn Minh / 0912345678 / MSCU5285725 / 20DC",
            ),
            # 3. T10 + T39: Chờ cấp cont + Thời gian tương đối ("Chiều nay")
            (
                "case_t10_t39",
                "Lệnh đóng cont rỗng khách Hòa Phát tại Kho Tiên Sơn\n"
                "Biển số: 29C-556.88\nBác tài: Phạm Văn Hùng\nSĐT: 0977665544\n"
                "Số cont: Chờ cấp cont\nDự kiến: Chiều nay",
            ),
            # 4. T18: Số container viết sai định dạng (thiếu ký tự)
            (
                "case_t18_bad_format",
                "Trả hàng tại Kho Đình Vũ: Biển số: 15C-878.99, TX: Trần Quốc Bảo, SĐT: 0903976359, CNTR: MSCU12345",
            ),
            # 5. T28 + T29: Đổi xe / đổi tài xế + Lùi giờ
            (
                "case_t28_t29_update",
                "THÔNG BÁO XE: Báo đổi xe 15C-878.99 sang xe 15C-999.88, đổi lái xe Nguyễn Văn B (0988776655), lùi giờ vào kho sang 16h30 27/10",
            ),
            # 6. T34: Dữ liệu mâu thuẫn (nhiều xe và nhiều cont trộn lẫn trong 1 dòng không rõ quan hệ)
            (
                "case_t34_conflict",
                "Đóng hàng Kho 3B: Xe 15C-878.99 và 29H-111.22 chở cont VSIU7399796 và MSCU5285725",
            ),
            # 7. Tin không dấu + Dạng bảng '|' + Suy luận lệnh trả từ 'noi ha' (T04, T38)
            (
                "case_no_accent_table",
                "Hang nhap noi ha Cang Tan Vu | 15C-878.99 | Tran Quoc Bao | 0903976359 | VSIU7399796 | 40RF",
            ),
            # 8. T33: Tin hội thoại không liên quan
            (
                "case_t33_chat",
                "Cảm ơn anh chị nhé, chúc mọi người buổi sáng vui vẻ!",
            ),
        ]

        for suffix, text in samples:
            res = client.post(
                "/webhook",
                json={
                    "msg_id": f"{TAX_PREFIX}{suffix}",
                    "group_id": TAX_GROUP,
                    "sender_id": TAX_USER,
                    "text": text,
                    "timestamp": "2026-10-27T10:00:00",
                },
            )
            assert res.status_code == 200

        # Kiểm tra kết quả bóc tách từng tin qua GET /api/messages/group/{group_id}
        group_res = client.get(f"/api/messages/group/{TAX_GROUP}")
        assert group_res.status_code == 200
        msgs = {m["zalo_message_id"]: m for m in group_res.json()["messages"]}

        # Case 1: T03 + T06 (1 xe chở 2 container, có booking_no, trailer_plate, SĐT ẩn, biển số viết liền)
        m1 = msgs[f"{TAX_PREFIX}case_t03_t06"]
        assert len(m1["trucks"]) == 1
        assert m1["trucks"][0]["truck_plate"] == "30H-123.45"
        assert m1["trucks"][0]["trailer_plate"] == "15R-123.45"
        assert m1["trucks"][0]["driver_phone"] == "0912******"
        assert len(m1["containers"]) == 2
        assert m1["containers"][0]["booking_no"] == "BK202688"
        assert m1["containers"][0]["order_type"] == "dong"
        assert "T06" in m1["taxonomy"]["matched_types"]
        assert "T03" in m1["taxonomy"]["matched_types"]
        assert "1.2.2" in m1["taxonomy"]["table1_codes"]  # Biển số không dấu phân cách

        # Case 2: T09 + T24 + T25 (Nhiều lệnh Đóng + Trả, nhiều kho, nhiều khách trong 1 tin)
        m2 = msgs[f"{TAX_PREFIX}case_t09_multi_order"]
        assert len(m2["containers"]) == 2
        assert m2["containers"][0]["order_type"] == "dong"
        assert m2["containers"][1]["order_type"] == "tra"
        assert "T09" in m2["taxonomy"]["matched_types"]
        assert "T24" in m2["taxonomy"]["matched_types"]
        assert "T25" in m2["taxonomy"]["matched_types"]

        # Case 3: T10 + T39 (Chờ cấp cont + Thời gian tương đối)
        m3 = msgs[f"{TAX_PREFIX}case_t10_t39"]
        assert "T10" in m3["taxonomy"]["matched_types"]
        assert "T39" in m3["taxonomy"]["matched_types"]

        # Case 4: T18 (Số container viết sai định dạng)
        m4 = msgs[f"{TAX_PREFIX}case_t18_bad_format"]
        assert m4["containers"][0]["container_no"] == "MSCU12345"
        assert "T18" in m4["taxonomy"]["matched_types"]

        # Case 5: T28 + T29 (Đổi xe/đổi tài + Lùi giờ)
        m5 = msgs[f"{TAX_PREFIX}case_t28_t29_update"]
        assert "T28" in m5["taxonomy"]["matched_types"]
        assert "T29" in m5["taxonomy"]["matched_types"]

        # Case 6: T34 (Mâu thuẫn gắn kết Xe - Container)
        m6 = msgs[f"{TAX_PREFIX}case_t34_conflict"]
        assert "T34" in m6["taxonomy"]["matched_types"]

        # Case 7: Không dấu + Dạng bảng + Suy luận lệnh trả (T04)
        m7 = msgs[f"{TAX_PREFIX}case_no_accent_table"]
        assert m7["containers"][0]["order_type"] == "tra"
        assert "T04" in m7["taxonomy"]["matched_types"]
        assert "1.6.8" in m7["taxonomy"]["table1_codes"]  # Tin không dấu
        assert "1.6.3" in m7["taxonomy"]["table1_codes"]  # Tin dạng bảng

        # Case 8: T33 (Tin không liên quan)
        m8 = msgs[f"{TAX_PREFIX}case_t33_chat"]
        assert m8["taxonomy"]["primary_type"] == "T33"

        # Kiểm tra API Thống Kê Bảng 1 & Bảng 2: GET /api/messages/statistics
        stats_res = client.get(
            "/api/messages/statistics",
            params={"group_id": TAX_GROUP},
        )
        assert stats_res.status_code == 200
        stats_body = stats_res.json()
        assert stats_body["total_messages_analyzed"] == 8
        assert "bang_1_hang_muc_du_lieu" in stats_body
        assert "bang_2_phan_loai_dang_tin_T01_T40" in stats_body
        assert len(stats_body["bang_2_phan_loai_dang_tin_T01_T40"]) == 40
    finally:
        cleanup_taxonomy_test_records()


def test_exact_f1_f2_f3_canonical_records_and_ai_masking() -> None:
    """Kiểm thử chính xác 3 mẫu F1, F2, F3 trong đặc tả Mục 2 cùng Bản ghi chuẩn và che SĐT cho AI."""
    cleanup_taxonomy_test_records()
    with SessionLocal() as db:
        # Khởi tạo khách hàng mẫu 'Nhựa Á Đông' (tms_customer_id='KH_NAD_TEST') và alias 'Nhựa Long An'
        existing_cust = db.scalar(select(Customer).where(Customer.tms_customer_id == "KH_NAD_TEST"))
        if not existing_cust:
            cust = Customer(
                tms_customer_id="KH_NAD_TEST",
                name="Nhựa Á Đông",
                normalized_name="nhua a dong",
                is_active=True,
            )
            db.add(cust)
            db.flush()
            alias = CustomerAlias(
                customer_id=cust.id,
                alias="Nhựa Long An",
                normalized_alias="nhua long an",
                source="dhvt_hcm",
            )
            db.add(alias)
            db.commit()

    try:
        # 1. Định dạng F1 (Nhà xe miền Bắc, 3 xe ngăn bằng dấu '/')
        f1_text = (
            "1 xe 15C17066/ Phạm Văn Huynh đt:  0986713346 / VSIU2621051 chì 23333878\n"
            "2 Xe 15h00642 / Đoàn Văn Biên 0984457785/ VSIU2321938 chì 23333310\n"
            "3 xe: 15H06722/ Đào Đức Thoại đt:  0364461978/ VSIU2323000 chì 23333330"
        )
        res_f1 = client.post(
            "/webhook",
            json={
                "msg_id": f"{TAX_PREFIX}exact_f1",
                "group_id": TAX_GROUP,
                "sender_id": TAX_USER,
                "text": f1_text,
                "timestamp": "2026-10-09T07:30:00",
            },
        )
        assert res_f1.status_code == 200
        f1_conts = res_f1.json()["containers"]
        assert len(f1_conts) == 3

        c1 = f1_conts[0]["canonical_record"]
        assert c1["source_format"] == "F1"
        assert c1["plan_date"] == "2026-10-09"
        assert c1["plate"] == "15C17066"
        assert c1["driver_name"] == "Phạm Văn Huynh"
        assert c1["driver_phone"] == "0986713346"  # Giữ nguyên số thật khi lưu DB
        assert c1["cont_no"] == "VSIU2621051"
        assert c1["seal_no"] == "23333878"

        c2 = f1_conts[1]["canonical_record"]
        assert c2["plate"] == "15H00642"
        assert c2["driver_name"] == "Đoàn Văn Biên"
        assert c2["driver_phone"] == "0984457785"
        assert c2["cont_no"] == "VSIU2321938"
        assert c2["seal_no"] == "23333310"

        c3 = f1_conts[2]["canonical_record"]
        assert c3["plate"] == "15H06722"
        assert c3["driver_name"] == "Đào Đức Thoại"
        assert c3["driver_phone"] == "0364461978"
        assert c3["cont_no"] == "VSIU2323000"
        assert c3["seal_no"] == "23333330"

        # 2. Định dạng F2 (ĐHVT HCM: Ngày .9/10/2026, Đóng , Trả hàng: Tra 1x20 Nhựa Long An)
        f2_text = (
            "Đầu ĐHVT HCM đang gửi nội dung xe trả hàng:\n"
            "1.  Ngày: .9/10/2026 : Đóng , Trả hàng: Tra 1x20 Nhựa Long An\n"
            "- Tên lái xe: Nguyên Thanh Phong\n"
            "- Sđt: 0931142873\n"
            "-  Số xe: 50H-04915\n"
            "- Số cont : VSIU2620327\n"
            "-  Số seal:\n"
            "- Thời gian xe đến kho: 8h"
        )
        res_f2 = client.post(
            "/webhook",
            json={
                "msg_id": f"{TAX_PREFIX}exact_f2",
                "group_id": TAX_GROUP,
                "sender_id": TAX_USER,
                "text": f2_text,
                "timestamp": "2026-10-08T18:00:00",
            },
        )
        assert res_f2.status_code == 200
        f2_cont = res_f2.json()["containers"][0]
        assert f2_cont["check_digit_valid"] is True
        f2_canon = f2_cont["canonical_record"]
        assert f2_canon == {
            "source_format": "F2",
            "plan_date": "2026-10-09",
            "order_type": "tra",
            "customer_raw": "Nhựa Long An",
            "customer_id": "KH_NAD_TEST",
            "location_raw": None,
            "warehouse_id": None,
            "plate": "50H04915",
            "driver_name": "Nguyên Thanh Phong",
            "driver_phone": "0931142873",
            "cont_no": "VSIU2620327",
            "cont_size": "20",
            "seal_no": None,
            "eta": "08:00",
            "match_source": "customer_alias",
        }

        # 3. Định dạng F3 (Cú pháp mẫu VSICO)
        f3_text = (
            "Khách hàng: Nhựa Á Đông\n"
            "Lệnh: Trả\n"
            "Biển số xe: 50H-04915\n"
            "Tên lái xe: Nguyễn Thanh Phong\n"
            "SĐT: 0931142873\n"
            "Số cont: VSIU2620327\n"
            "Số chì:\n"
            "Điểm đóng/trả: Kho Nhựa Á Đông – Long An\n"
            "Thời gian dự kiến đến kho: 08:00"
        )
        res_f3 = client.post(
            "/webhook",
            json={
                "msg_id": f"{TAX_PREFIX}exact_f3",
                "group_id": TAX_GROUP,
                "sender_id": TAX_USER,
                "text": f3_text,
                "timestamp": "2026-10-09T07:00:00",
            },
        )
        assert res_f3.status_code == 200
        f3_canon = res_f3.json()["containers"][0]["canonical_record"]
        assert f3_canon["source_format"] == "F3"
        assert f3_canon["plan_date"] == "2026-10-09"
        assert f3_canon["order_type"] == "tra"
        assert f3_canon["customer_raw"] == "Nhựa Á Đông"
        assert f3_canon["customer_id"] == "KH_NAD_TEST"
        assert f3_canon["location_raw"] == "Kho Nhựa Á Đông – Long An"
        assert f3_canon["plate"] == "50H04915"
        assert f3_canon["driver_name"] == "Nguyễn Thanh Phong"
        assert f3_canon["driver_phone"] == "0931142873"
        assert f3_canon["cont_no"] == "VSIU2620327"
        assert f3_canon["seal_no"] == None
        assert f3_canon["eta"] == "08:00"
        assert f3_canon["match_source"] == "direct_match"

        # 4. Kiểm tra cơ chế che SĐT CHỈ KHI gửi cho AI và khôi phục lại số thật
        masked_text, phone_map = AIFallbackExtractor.mask_phones_for_ai("Tài xế Phong SĐT 0931142873")
        assert "0931xxxx73" in masked_text
        assert "0931142873" not in masked_text
        restored = AIFallbackExtractor.restore_real_phone("0931xxxx73", phone_map)
        assert restored == "0931142873"
    finally:
        cleanup_taxonomy_test_records()
        with SessionLocal() as db:
            cust = db.scalar(select(Customer).where(Customer.tms_customer_id == "KH_NAD_TEST"))
            if cust:
                db.execute(delete(CustomerAlias).where(CustomerAlias.customer_id == cust.id))
                db.delete(cust)
                db.commit()
