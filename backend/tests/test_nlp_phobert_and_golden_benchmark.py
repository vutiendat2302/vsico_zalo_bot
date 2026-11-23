"""Kiểm thử toàn diện: RapidFuzz + Từ điển danh mục + PhoBERT, Trợ lý ĐHVT theo vùng,
Đối chiếu 6 nhánh (TH1–TH6), Đồng bộ nguyên tử RO->LO, RBAC/Version Lock, TMS Write-back
và Bộ dữ liệu chuẩn 56 tin nhắn ẩn danh (Golden Evaluation Benchmark).
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.assistant.intent_router import route_local
from src.config.settings import settings
from src.domain.models import ExtractedContainerLine
from src.domain.rules import compute_iso6346_check_digit
from src.handlers.plan_resolution_engine import PlanResolutionEngine
from src.handlers.plan_sync_service import (
    mask_pii_payload,
    sync_combined_ro_to_lo_plans,
    sync_plan_to_tms,
)
from src.infrastructure.models import (
    ActivityLog,
    Carrier,
    ContainerJob,
    Customer,
    CustomerAlias,
    Driver,
    OutboundMessage,
    ReviewCase,
    TmsSyncLog,
    TransportPlan,
    TruckRecord,
    User,
    Vehicle,
    Warehouse,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.security import create_access_token
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiError
from src.parsing.local_nlp_extractor import PhoBertLocalNlpEngine, enrich_local
from src.parsing.trip_parser import TripParser
from src.validation.validators import ContainerValidator


def _make_valid_cont(prefix: str, six_digits: str) -> str:
    """Sinh số container 11 ký tự đạt chuẩn ISO 6346 Modulo 11."""
    base10 = f"{prefix.upper()}{six_digits}0"
    cd = compute_iso6346_check_digit(base10)
    return f"{prefix.upper()}{six_digits}{cd}"


def _mock_plan(**kwargs):
    """Tạo đối tượng kế hoạch giả lập phục vụ kiểm thử đơn vị bộ đối chiếu."""
    defaults = {
        "id": 101,
        "plan_date": date(2026, 11, 9),
        "carrier_id": 10,
        "order_type": "dong",
        "order_code": "LO101",
        "container_no": None,
        "container_size": "40HC",
        "planned_truck_plate": None,
        "customer_id": 1,
        "warehouse_id": 11,
        "customer_name": "Công ty TNHH Samsung Bắc Ninh",
        "warehouse_name": "Kho Yên Phong Bắc Ninh",
        "delivery_address": "KCN Yên Phong, Bắc Ninh",
        "ward_name": "Xã Yên Trung",
        "province_name": "Tỉnh Bắc Ninh",
        "required_time": "08:00",
        "booking_no": "BK26110901",
        "container_warning": None,
        "container_ownership": 1,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ==============================================================================
# 1. KIỂM THỬ PHOBERT + RAPIDFUZZ + TỪ ĐIỂN DANH MỤC + ĐỒNG THAM CHIẾU (P1.1)
# ==============================================================================


def test_phobert_local_nlp_segmentation_and_ner():
    """PhoBERT Local NLP tách từ ghép tiếng Việt, nhận diện luồng kết hợp và thực thể BIO."""
    engine = PhoBertLocalNlpEngine.get_instance()
    seg = engine.segment_vietnamese_compounds(
        "Xe đầu kéo trả vỏ xong đóng hàng luôn tại khu công nghiệp Yên Phong"
    )
    assert "dau_keo" in seg
    assert "tra_vo" in seg
    assert "dong_hang" in seg
    assert "khu_cong_nghiep" in seg

    analysis = engine.analyze(
        "Xe 15C-123.45 tài xế Nguyễn Văn Hùng trả xong đóng luôn kho Yên Phong lúc 8h"
    )
    assert analysis.is_combined_trip is True
    assert analysis.order_type_hint == "LOAD"
    labels = {s.label for s in analysis.spans}
    assert "LOC" in labels
    assert "PER" in labels


def test_enrich_local_rapidfuzz_catalog_and_coreference(db_session):
    """Làm giàu từ danh mục bằng RapidFuzz và giải quyết đồng tham chiếu duy nhất."""
    token = uuid4().hex[:6]
    carrier = Carrier(
        id=snowflake.generate(),
        name=f"Nhà xe {token}",
        normalized_name=f"nha xe {token}",
        is_active=True,
    )
    customer = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"CUST_{token}",
        name=f"Công ty Điện tử Canon {token}",
        normalized_name=f"cong ty dien tu canon {token}",
    )
    warehouse = Warehouse(
        id=snowflake.generate(),
        tms_warehouse_id=f"WH_{token}",
        customer_id=customer.id,
        name=f"Kho Quế Võ Bắc Ninh {token}",
        normalized_name=f"kho que vo bac ninh {token}",
        address=f"KCN Quế Võ, Bắc Ninh {token}",
    )
    db_session.add_all([carrier, customer, warehouse])
    db_session.flush()

    db_session.add(
        WarehouseAlias(
            id=snowflake.generate(),
            warehouse_id=warehouse.id,
            alias=f"que vo {token}",
            normalized_alias=f"que vo {token}",
        )
    )
    db_session.add(
        Driver(
            id=snowflake.generate(),
            tms_driver_id=snowflake.generate(),
            carrier_id=carrier.id,
            full_name="Phạm Văn Huynh",
            normalized_name="pham van huynh",
            phone="0986713346",
            is_active=True,
        )
    )
    db_session.add(
        Vehicle(
            id=snowflake.generate(),
            tms_vehicle_id=snowflake.generate(),
            carrier_id=carrier.id,
            plate_no="15C-170.66",
            vehicle_type=1,
            is_active=True,
        )
    )
    db_session.flush()

    # 1. RapidFuzz + Catalog + PhoBERT trên câu viết tắt biển số 4 số cuối + tên tài xế + alias kho
    raw = f"Xe 7066 tài Huynh đóng hàng kho que vo {token} lúc 08:00 chưa có cont"
    line = ExtractedContainerLine(line_text=raw)
    enriched = enrich_local(
        db_session,
        [line],
        carrier.id,
        raw,
        datetime(2026, 11, 9, 7, 30, tzinfo=UTC),
    )[0]
    assert enriched.truck_plate == "15C-170.66"
    assert enriched.driver_name == "Phạm Văn Huynh"
    assert enriched.driver_phone == "0986713346"
    assert enriched.warehouse_code_or_id == warehouse.id
    assert enriched.order_type == "LOAD"
    assert enriched.container_status == "DEFERRED"
    assert enriched.field_evidences["nlp_engine"] in ("rule_char_ngram_fuzzy_nlp", "phobert_transformers_local")
    assert enriched.confidence >= 0.75  # Đủ tin cậy sau Tier 2, không gọi sang Tier 3 LLM

    # 1b. Kiểm tra ngưỡng tin cậy intent: câu không liên quan có điểm thấp phải trả UNKNOWN (không đoán bừa)
    from src.parsing.local_nlp_extractor import PhoBertLocalNlpEngine

    low_res = PhoBertLocalNlpEngine.get_instance().analyze("thời tiết hôm nay trời nắng đẹp")
    assert low_res.intent_label == "UNKNOWN"
    assert low_res.intent_confidence < PhoBertLocalNlpEngine.INTENT_MIN_CONFIDENCE

    # 2. Giải quyết đồng tham chiếu 'xe trên' khi quote có đúng 1 xe duy nhất
    coref_raw = "Xe trên bổ sung chì SL9988 nhé"
    coref_line = ExtractedContainerLine(line_text=coref_raw, seal_no="SL9988")
    resolved_line = enrich_local(
        db_session,
        [coref_line],
        carrier.id,
        coref_raw,
        datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
        quoted_text="Xe 15C-170.66 đóng hàng kho Quế Võ",
    )[0]
    assert resolved_line.truck_plate == "15C-170.66"
    assert "context_reference" not in resolved_line.unresolved_fields

    # 3. Khi quote có 2 xe khác nhau -> KHÔNG đoán mò, giữ context_reference để hỏi lại
    amb_coref = ExtractedContainerLine(line_text=coref_raw, seal_no="SL9988")
    unresolved_line = enrich_local(
        db_session,
        [amb_coref],
        carrier.id,
        coref_raw,
        datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
        quoted_text="Xe 15C-170.66 và xe 29C-445.41 đóng hàng",
    )[0]
    assert unresolved_line.truck_plate is None
    assert "context_reference" in unresolved_line.unresolved_fields


# ==============================================================================
# 2. KIỂM THỬ BỘ ĐỐI CHIẾU 6 NHÁNH (TH1–TH6) & ĐỒNG BỘ NGUYÊN TỬ RO -> LO (P0.1)
# ==============================================================================


def test_six_branches_plan_resolution_engine():
    """Kiểm chứng đầy đủ 6 nhánh TH1–TH6 và chống tự ghép sai trong PlanResolutionEngine."""
    cont_shared = _make_valid_cont("MSCU", "123456")
    cont_ro_only = _make_valid_cont("GAOU", "654321")
    cont_lo_only = _make_valid_cont("TCLU", "112233")
    cont_new_depot = _make_valid_cont("OOCL", "778899")

    ro_shared = _mock_plan(
        id=1,
        order_type="tra",
        order_code="RO001",
        container_no=cont_shared,
        warehouse_name="Kho Trả Tiên Sơn",
    )
    lo_shared = _mock_plan(
        id=2,
        order_type="dong",
        order_code="LO002",
        container_no=cont_shared,
        warehouse_name="Kho Đóng Yên Phong",
    )

    # TH1a: Container nằm ở cả RO và LO, tin nhắn báo kết hợp -> chọn cả 2 kế hoạch
    line_th1_comb = ExtractedContainerLine(
        container_no=cont_shared,
        order_type="LOAD",
        is_combined_from_return=True,
    )
    res_th1_comb = PlanResolutionEngine.resolve(
        line_th1_comb, [ro_shared, lo_shared], 10, ["2026-11-09"], shadow=False
    )
    assert res_th1_comb.branch == "TH1_COMBINED_RO_LO"
    assert res_th1_comb.selected_plan_id == "2"
    assert res_th1_comb.secondary_plan_id == "1"

    # TH1b: Container nằm ở cả RO và LO nhưng không rõ chặng -> ASK_CARRIER
    line_th1_amb = ExtractedContainerLine(container_no=cont_shared)
    res_th1_amb = PlanResolutionEngine.resolve(
        line_th1_amb, [ro_shared, lo_shared], 10, ["2026-11-09"]
    )
    assert res_th1_amb.branch == "TH1_AMBIGUOUS_RO_LO"
    assert res_th1_amb.action == "ASK_CARRIER"

    # TH2: Container chỉ nằm ở RO, báo xe trả hàng -> AUTO_COMMIT
    ro_only = _mock_plan(id=3, order_type="tra", order_code="RO003", container_no=cont_ro_only)
    line_th2 = ExtractedContainerLine(container_no=cont_ro_only, order_type="RETURN")
    res_th2 = PlanResolutionEngine.resolve(line_th2, [ro_only], 10, ["2026-11-09"])
    assert res_th2.branch == "TH2_RO_EXACT"
    assert res_th2.action == "AUTO_COMMIT"
    assert res_th2.selected_plan_id == "3"

    # TH3a: Container nằm ở RO nhưng có cảnh báo hạ rỗng (empty_drop) -> chặn tự ghép sang LO
    ro_warn = _mock_plan(
        id=4,
        order_type="tra",
        order_code="RO004",
        container_no=cont_ro_only,
        container_warning="empty_drop",
    )
    lo_open = _mock_plan(
        id=5,
        order_type="dong",
        order_code="LO005",
        container_no=None,
        warehouse_name="Kho Yên Phong Bắc Ninh",
    )
    line_th3_blocked = ExtractedContainerLine(
        container_no=cont_ro_only,
        order_type="LOAD",
        is_combined_from_return=True,
        warehouse_hint="Kho Yên Phong Bắc Ninh",
    )
    res_th3_blocked = PlanResolutionEngine.resolve(
        line_th3_blocked, [ro_warn, lo_open], 10, ["2026-11-09"]
    )
    assert res_th3_blocked.branch == "TH3_BLOCKED_CONTAINER_WARNING"
    assert res_th3_blocked.action == "ESCALATE_DHVT_WEB"
    assert "CONTAINER_REUSE_BLOCKED" in res_th3_blocked.candidates[0].exclusions

    # TH3b: Container nằm ở RO hợp lệ, ghép sang LO trống cont khớp kho -> chọn LO + lưu secondary RO
    res_th3_ok = PlanResolutionEngine.resolve(
        line_th3_blocked, [ro_only, lo_open], 10, ["2026-11-09"], shadow=False
    )
    assert res_th3_ok.branch == "TH3_COMBINED_RO_TO_LO"
    assert res_th3_ok.action == "AUTO_COMMIT"
    assert res_th3_ok.selected_plan_id == "5"
    assert res_th3_ok.secondary_plan_id == "3"

    # TH4: Container chỉ nằm ở LO đã có sẵn cont -> AUTO_COMMIT
    lo_exact = _mock_plan(id=6, order_type="dong", order_code="LO006", container_no=cont_lo_only)
    line_th4 = ExtractedContainerLine(container_no=cont_lo_only, order_type="LOAD")
    res_th4 = PlanResolutionEngine.resolve(line_th4, [lo_exact], 10, ["2026-11-09"])
    assert res_th4.branch == "TH4_LO_EXACT"
    assert res_th4.action == "AUTO_COMMIT"
    assert res_th4.selected_plan_id == "6"

    # TH5a: Container lệch 1 ký tự so với kế hoạch -> ASK_CARRIER cảnh báo gõ nhầm
    typo_cont = cont_ro_only[:-2] + ("9" if cont_ro_only[-2] != "9" else "8") + cont_ro_only[-1]
    line_th5_near = ExtractedContainerLine(container_no=typo_cont, order_type="RETURN")
    res_th5_near = PlanResolutionEngine.resolve(line_th5_near, [ro_only], 10, ["2026-11-09"])
    assert res_th5_near.branch == "TH5_NEAR_MISS_CONTAINER"
    assert res_th5_near.action == "ASK_CARRIER"

    # TH5b: Container mới lấy từ bãi cho lệnh đóng đang trống cont
    line_th5_new = ExtractedContainerLine(
        container_no=cont_new_depot,
        check_digit_valid=True,
        order_type="LOAD",
        booking_no="BK26110901",
        warehouse_hint="Kho Yên Phong Bắc Ninh",
    )
    res_th5_new = PlanResolutionEngine.resolve(
        line_th5_new, [lo_open], 10, ["2026-11-09"], shadow=False
    )
    assert res_th5_new.branch == "TH5_NEW_CONTAINER_LO"
    assert res_th5_new.action == "AUTO_COMMIT"
    assert res_th5_new.selected_plan_id == "5"

    # Đa xe trong cùng tin nhắn không tranh cùng 1 slot LO
    lo_open_2 = _mock_plan(
        id=7,
        order_type="dong",
        order_code="LO007",
        container_no=None,
        warehouse_name="Kho Quế Võ Bắc Ninh",
        booking_no="BK26110902",
    )
    batch_res = PlanResolutionEngine.resolve_batch(
        [
            ExtractedContainerLine(
                order_type="LOAD",
                booking_no="BK26110901",
                warehouse_hint="Kho Yên Phong Bắc Ninh",
            ),
            ExtractedContainerLine(
                order_type="LOAD",
                booking_no="BK26110902",
                warehouse_hint="Kho Quế Võ Bắc Ninh",
            ),
        ],
        [lo_open, lo_open_2],
        10,
        ["2026-11-09"],
        shadow=False,
    )
    assert batch_res[0].selected_plan_id == "5"
    assert batch_res[1].selected_plan_id == "7"


def test_atomic_combined_ro_to_lo_sync_and_warning_guard(db_session):
    """Đồng bộ nguyên tử cả hai kế hoạch RO và LO trong cùng giao dịch, chặn vỏ cảnh báo."""
    cont = _make_valid_cont("MSCU", "445566")
    carrier = Carrier(
        id=snowflake.generate(),
        name="Nhà xe Kết Hợp",
        normalized_name="nha xe ket hop",
        is_active=True,
    )
    db_session.add(carrier)
    db_session.flush()

    ro_plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 9),
        carrier_id=carrier.id,
        order_type="tra",
        order_code="RO701",
        container_no=cont,
        container_size="40HC",
        seal_no="SEAL_OLD_RO",
        container_warning="empty_drop",
        version=1,
    )
    lo_plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 9),
        carrier_id=carrier.id,
        order_type="dong",
        order_code="LO702",
        container_no=None,
        container_size="40HC",
        version=1,
    )
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=uuid4().hex,
        group_id="test_grp_comb",
        sender_id="sender_1",
        message_text=f"Xe 15C-888.99 tài Nam 0912345678 trả xong đóng luôn cont {cont} chì SEAL_NEW_LO",
        raw_payload={"is_test": True},
    )
    db_session.add_all([ro_plan, lo_plan, msg])
    db_session.flush()

    tr = TruckRecord(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_plate="15C-888.99",
        driver_name="Nguyễn Văn Nam",
        driver_phone="0912345678",
    )
    db_session.add(tr)
    db_session.flush()
    job = ContainerJob(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_record_id=tr.id,
        container_no=cont,
        container_size="40",
        seal_no="SEAL_NEW_LO",
        order_type="dong",
    )
    db_session.add(job)
    db_session.flush()
    job.truck_record = tr

    # 1. Khi RO có cảnh báo empty_drop và chưa được ĐHVT override -> CONFLICT cả 2
    ro_out_1, lo_out_1 = sync_combined_ro_to_lo_plans(
        db_session, job, ro_plan, lo_plan, allow_plan_override=False
    )
    assert ro_out_1.mode == "CONFLICT" and lo_out_1.mode == "CONFLICT"
    assert lo_plan.container_no is None and ro_plan.version == 1 and lo_plan.version == 1

    # 2. Khi vỏ hợp lệ (hoặc ĐHVT duyệt override) -> Cập nhật nguyên tử cả RO và LO
    ro_plan.container_warning = None
    db_session.flush()
    ro_out_2, lo_out_2 = sync_combined_ro_to_lo_plans(
        db_session, job, ro_plan, lo_plan, actor_id="dhvt_1", allow_plan_override=False
    )
    assert ro_out_2.mode in ("FILLED", "UPDATED")
    assert lo_out_2.mode in ("FILLED", "UPDATED")
    assert ro_plan.planned_truck_plate == "15C-888.99"
    assert ro_plan.seal_no == "SEAL_OLD_RO"  # Không ghi đè seal cũ của RO bằng seal mới của LO
    assert lo_plan.container_no == cont
    assert lo_plan.seal_no == "SEAL_NEW_LO"
    assert lo_plan.planned_truck_plate == "15C-888.99"
    assert ro_plan.version == 2 and lo_plan.version == 2
    assert ro_plan.tms_sync_status == "PENDING" and lo_plan.tms_sync_status == "PENDING"


# ==============================================================================
# 3. KIỂM THỬ TRỢ LÝ ĐHVT TRA CỨU SỐ LỆNH ĐÓNG/TRẢ/TỔNG & THEO TỪNG VÙNG/TỈNH
# ==============================================================================


def test_dhvt_assistant_order_stats_by_type_region_and_province(db_session, monkeypatch):
    """ĐHVT tra cứu được số lệnh đóng, số lệnh trả, tổng số lệnh và thống kê theo từng vùng/tỉnh."""
    from src.assistant.service import handle_assistant

    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", False)
    dhvt_group = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"dhvt_reg_{uuid4().hex[:6]}",
        name="Nhóm ĐHVT Vùng",
        group_role="DHVT",
        is_active=True,
        is_test=True,
    )
    db_session.add(dhvt_group)
    db_session.flush()
    user = User(
        id=snowflake.generate(),
        username=f"dhvt_u_{uuid4().hex[:6]}",
        password_hash="hash",
        full_name="ĐHVT Test",
        role="DHVT",
        is_active=True,
        zalo_user_id="dhvt_sender_reg",
        zalo_info_id=dhvt_group.id,
    )
    db_session.add(user)

    test_day = date(2099, 11, 20)
    ref_dt = datetime(2099, 11, 20, 3, 0, tzinfo=UTC)
    sample_plans = [
        TransportPlan(
            id=snowflake.generate(),
            plan_date=test_day,
            order_type="dong",
            order_code="LO901",
            container_size="40HC",
            region=1,
            province_name="Tỉnh Bắc Ninh",
            planned_truck_plate="29C-111.22",
        ),
        TransportPlan(
            id=snowflake.generate(),
            plan_date=test_day,
            order_type="dong",
            order_code="LO902",
            container_size="20DC",
            region=1,
            province_name="Tỉnh Bắc Ninh",
        ),
        TransportPlan(
            id=snowflake.generate(),
            plan_date=test_day,
            order_type="tra",
            order_code="RO903",
            container_size="40HC",
            region=1,
            province_name="Thành phố Hải Phòng",
        ),
        TransportPlan(
            id=snowflake.generate(),
            plan_date=test_day,
            order_type="tra",
            order_code="RO904",
            container_size="20DC",
            region=2,
            province_name="Thành phố Đà Nẵng",
        ),
    ]
    db_session.add_all(sample_plans)
    db_session.flush()

    def ask_dhvt(question_text: str) -> str:
        msg = ZaloMessage(
            id=snowflake.generate(),
            zalo_message_id=uuid4().hex,
            group_id=dhvt_group.zalo_group_id,
            sender_id="dhvt_sender_reg",
            message_text=question_text,
            raw_payload={"is_test": True},
            created_at=ref_dt,
            zalo_sent_at=ref_dt,
        )
        db_session.add(msg)
        db_session.flush()
        assert handle_assistant(db_session, msg, dhvt_group) is True
        out = db_session.scalar(
            select(OutboundMessage)
            .where(OutboundMessage.target_group_id == dhvt_group.id)
            .order_by(OutboundMessage.id.desc())
        )
        return out.content if out else ""

    # 1. Hỏi tổng số lệnh và số lệnh đóng, trả theo từng vùng
    ans_all = ask_dhvt("Hôm nay tổng số lệnh, số lệnh đóng, trả theo từng vùng thế nào?")
    assert "[VSICO] - 📊 KẾ HOẠCH VẬN CHUYỂN" in ans_all
    assert "4 lệnh vận chuyển" in ans_all
    assert "Lệnh đóng: 2 (50,0%)" in ans_all
    assert "Lệnh trả: 2 (50,0%)" in ans_all
    assert "Miền Bắc: 3 (đóng: 2 · trả: 1)" in ans_all
    assert "Miền Trung: 1 (đóng: 0 · trả: 1)" in ans_all
    assert "Bắc Ninh: 2 (đóng: 2 · trả: 0)" in ans_all
    assert "Hải Phòng: 1 (đóng: 0 · trả: 1)" in ans_all

    # 2. Hỏi riêng số lệnh đóng
    ans_dong = ask_dhvt("Hôm nay có bao nhiêu lệnh đóng?")
    assert "2 lệnh vận chuyển" in ans_dong
    assert "Lệnh đóng: 2 (100,0%)" in ans_dong
    assert "Lệnh trả: 0 (0,0%)" in ans_dong

    # 3. Hỏi riêng số lệnh trả
    ans_tra = ask_dhvt("Hôm nay có bao nhiêu lệnh trả?")
    assert "2 lệnh vận chuyển" in ans_tra
    assert "Lệnh đóng: 0 (0,0%)" in ans_tra
    assert "Lệnh trả: 2 (100,0%)" in ans_tra

    # 4. Hỏi theo tỉnh Bắc Ninh (không cần gõ chữ 'Tỉnh') -> tách riêng sang form Chi tiết tỉnh + danh sách lệnh
    ans_bn = ask_dhvt("Bắc Ninh hôm nay có bao nhiêu lệnh?")
    assert "[VSICO] - 📍 CHI TIẾT KẾ HOẠCH BẮC NINH" in ans_bn
    assert "2 lệnh tại Bắc Ninh" in ans_bn
    assert "Lệnh đóng: 2 (100,0%)" in ans_bn
    assert "Danh sách lệnh trong ngày:" in ans_bn


# ==============================================================================
# 4. KIỂM THỬ RBAC, OPTIMISTIC VERSION LOCK (P0.2), CHỌN ỨNG VIÊN WEB (P1.3) & TMS WRITE-BACK (P0.3)
# ==============================================================================


def test_web_rbac_version_lock_candidate_selection_and_tms_writeback(
    api_client, db_session, monkeypatch
):
    """Kiểm chứng RBAC (chặn role!=ADMIN/DHVT), khóa phiên bản 409, chọn plan lưu alias kho và TMS write-back."""
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", False)
    token_str = uuid4().hex[:6]

    cust_user = User(
        id=snowflake.generate(),
        username=f"cust_{token_str}",
        password_hash="h",
        full_name="Customer User",
        role="CUSTOMER",
        is_active=True,
    )
    dhvt_user = User(
        id=snowflake.generate(),
        username=f"dhvt_{token_str}",
        password_hash="h",
        full_name="DHVT User",
        role="DHVT",
        is_active=True,
    )
    customer = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"C_{token_str}",
        name=f"Khách {token_str}",
        normalized_name=f"khach {token_str}",
    )
    warehouse = Warehouse(
        id=snowflake.generate(),
        tms_warehouse_id=f"WH_{token_str}",
        name=f"Kho Tiên Sơn {token_str}",
        normalized_name=f"kho tien son {token_str}",
    )
    dest_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"dest_{token_str}",
        name="Nhóm Đích",
        group_role="DESTINATION",
        is_active=True,
        is_test=True,
    )
    db_session.add_all([cust_user, dhvt_user, customer, warehouse, dest_grp])
    db_session.flush()

    cust_jwt = create_access_token(
        {"sub": str(cust_user.id), "username": cust_user.username, "role": "CUSTOMER"}
    )
    dhvt_jwt = create_access_token(
        {"sub": str(dhvt_user.id), "username": dhvt_user.username, "role": "DHVT"}
    )
    cust_headers = {"Authorization": f"Bearer {cust_jwt}"}
    dhvt_headers = {"Authorization": f"Bearer {dhvt_jwt}"}

    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 9),
        order_type="dong",
        order_code=f"LO_{token_str}",
        customer_id=customer.id,
        customer_name=customer.name,
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        group_id=dest_grp.zalo_group_id,
        version=1,
    )
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=uuid4().hex,
        group_id=f"test_src_{token_str}",
        sender_id="s1",
        message_text="Xe 15C-333.44 đóng hàng kho TS",
        raw_payload={"is_test": True},
    )
    db_session.add_all([plan, msg])
    db_session.flush()

    rc = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        case_type="PLAN_RESOLUTION",
        reason="Đề xuất chọn kế hoạch",
        status="PENDING",
        details={
            "selected_plan_id": str(plan.id),
            "warehouse_hint": f"kho ts alias {token_str}",
            "truck_plate": "15C-333.44",
            "driver_name": "Lê Văn B",
            "driver_phone": "0903123459",
            "candidate_plans": [
                {
                    "plan_id": str(plan.id),
                    "order_code": plan.order_code,
                    "customer_name": plan.customer_name,
                    "warehouse_name": plan.warehouse_name,
                    "score": 88,
                    "evidences": ["warehouse_match"],
                    "exclusions": [],
                }
            ],
        },
    )
    db_session.add(rc)
    db_session.flush()

    # 1. Tài khoản sai role (CUSTOMER) bị chặn 403 trên cả /reviews và /plans
    assert (
        api_client.post(f"/api/reviews/{rc.id}/approve", headers=cust_headers).status_code == 403
    )
    assert (
        api_client.put(
            f"/api/plans/{plan.id}",
            json={"notes": "hack"},
            headers=cust_headers,
        ).status_code
        == 403
    )

    # 2. Stale expected_version bị chặn 409 Conflict
    assert (
        api_client.post(
            f"/api/reviews/{rc.id}/approve",
            json={"selected_plan_id": plan.id, "expected_version": 99},
            headers=dhvt_headers,
        ).status_code
        == 409
    )

    # 3. ĐHVT duyệt với đúng expected_version=1 -> cập nhật plan + tự động lưu WarehouseAlias
    ok_resp = api_client.post(
        f"/api/reviews/{rc.id}/approve",
        json={"selected_plan_id": plan.id, "expected_version": 1, "save_warehouse_habit": True},
        headers=dhvt_headers,
    )
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["warehouse_habit_saved"] is True
    db_session.refresh(plan)
    assert plan.planned_truck_plate == "15C-333.44"
    assert plan.version == 2
    saved_alias = db_session.scalar(
        select(WarehouseAlias).where(WarehouseAlias.warehouse_id == warehouse.id)
    )
    assert saved_alias is not None

    # 4. Duyệt lặp lại cùng ca đã APPROVED bị chặn 409 Conflict
    assert (
        api_client.post(f"/api/reviews/{rc.id}/approve", headers=dhvt_headers).status_code == 409
    )

    # 5. Kiểm thử TMS Write-back Sync (PENDING khi tắt -> SYNCED có che PII -> FAILED khi lỗi)
    job = db_session.get(ContainerJob, rc.container_job_id)
    monkeypatch.setattr(settings, "TMS_SYNC_ENABLED", False)
    monkeypatch.setattr(settings, "TMS_WRITE_ENABLED", False)
    assert sync_plan_to_tms(db_session, plan, job) == "PENDING"
    assert plan.tms_sync_status == "PENDING"

    monkeypatch.setattr(settings, "TMS_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "TMS_WRITE_ENABLED", True)

    class _FakeTmsOk:
        def push_dispatch_update(self, payload, idempotency_key=None):
            return 200, {"status": "ok", "driver_phone": payload.get("driver_phone")}

    assert sync_plan_to_tms(db_session, plan, job, client=_FakeTmsOk()) == "SYNCED"
    db_session.flush()
    assert plan.tms_sync_status == "SYNCED"
    sync_log = db_session.scalar(
        select(TmsSyncLog).where(TmsSyncLog.container_job_id == job.id)
    )
    assert sync_log is not None and sync_log.status == "SUCCESS"
    # SĐT tài xế trong tms_sync_logs bắt buộc đã được che PII (0903xxxx59)
    assert "0903123459" not in str(sync_log.request_data)
    assert "0903xxxx59" in str(sync_log.request_data)

    # Khi tăng version và TMS lỗi -> chuyển FAILED
    plan.version = 3

    class _FakeTmsFail:
        def push_dispatch_update(self, payload, idempotency_key=None):
            raise TmsApiError("TMS HTTP 503 Unavailable", status_code=503)

    assert sync_plan_to_tms(db_session, plan, job, client=_FakeTmsFail()) == "FAILED"
    assert plan.tms_sync_status == "FAILED"


# ==============================================================================
# 5. GOLDEN EVALUATION BENCHMARK (56 TIN NHẮN ZALO ẨN DANH THỰC TẾ — P1.2)
# ==============================================================================


GOLDEN_MESSAGES = [
    # --- Nhóm A: Báo xe lệnh trả (RO) chuẩn & tự do (10 mẫu) ---
    ("CARRIER", "Xe 15C-170.66 tài Phạm Văn Huynh 0986713346 trả hàng cont MSCU1234566 chì SL001", "REPORT_DISPATCH"),
    ("CARRIER", "15H-067.22 Đào Đức Thoại 0364461978 giao cont GAOU6543216 seal 233338", "REPORT_DISPATCH"),
    ("CARRIER", "Em báo xe 29C-445.41 lx Hùng 0903123459 trả vỏ cont TCLU1122337", "REPORT_DISPATCH"),
    ("CARRIER", "Đầu kéo 15C-088.12 rơ moóc 15R-055.11 tài Tuấn 0912345678 trả hàng cont OOCL7788990", "REPORT_DISPATCH"),
    ("CARRIER", "Xe 34C-221.09 tài Long 0977888999 hạ rỗng contSITG1234560", "REPORT_DISPATCH"),
    ("CARRIER", "Báo xe 15C-991.02 tài Minh 0988111222 giao kho Tiên Sơn cont CMAU2233445", "REPORT_DISPATCH"),
    ("CARRIER", "15C17066 - Huynh 0986713346 - MSCU1234566 - SL8899 - 08h00", "REPORT_DISPATCH"),
    ("CARRIER", "Xe: 29H-112.33\nLái xe: Trần Văn Bình - 0934567890\nCont: EGHU3344556\nChì: A112233", "REPORT_DISPATCH"),
    ("CARRIER", "Gửi đhvt xe 15C-441.20 tài Kiên 0965432109 trả hàng nhập cont TGBU8877665 lúc 9h", "REPORT_DISPATCH"),
    ("CARRIER", "Xe 15H-019.88 lx Tùng 0919888777 giao hàng contBMOU4455667 hẹn 10h30", "REPORT_DISPATCH"),
    # --- Nhóm B: Báo xe lệnh đóng (LO) chưa có cont / lấy rỗng (8 mẫu) ---
    ("CARRIER", "Xe 15C-170.66 tài Huynh 0986713346 vào đóng hàng kho Yên Phong lúc 8h chưa có cont", "REPORT_DISPATCH"),
    ("CARRIER", "29C-445.41 tài Đạt 0931142873 đi lấy rỗng đóng hàng kho Quế Võ hẹn 14h, cont báo sau", "REPORT_DISPATCH"),
    ("CARRIER", "Báo xe 15H-090.11 lx Tám 0905123456 đóng cont 40HC kho Tiên Sơn booking BK26110901", "REPORT_DISPATCH"),
    ("CARRIER", "Xe 15C-332.11 tài Hòa 0971223344 đóng hàng xuất KCN Quang Châu lúc 13:30 đợi cấp cont", "REPORT_DISPATCH"),
    ("CARRIER", "Em gửi xe 29H-881.22 tài Sơn 0944556677 vào đóng kho Samsung Bắc Ninh 07:30 chì báo sau", "REPORT_DISPATCH"),
    ("CARRIER", "Xe 15C-665.43 lx Thắng 0982334455 nhận lệnh đóng 20DC kho Vsip Bắc Ninh 9h00", "REPORT_DISPATCH"),
    ("CARRIER", "15H-554.32 tài Dũng 0918223344 đóng hàng kho Đại Đồng Hoàn Sơn lúc 15h chưa có số cont", "REPORT_DISPATCH"),
    ("CARRIER", "Báo xe 34C-109.88 tài Hải 0966778899 đóng kho Tân Quang Hưng Yên hẹn 11h", "REPORT_DISPATCH"),
    # --- Nhóm C: Chuyến kết hợp RO -> LO & nhiều xe (6 mẫu) ---
    ("CARRIER", "Xe 15C-170.66 tài Huynh 0986713346 trả xong cont MSCU1234566 đóng luôn kho Yên Phong lúc 13h", "REPORT_DISPATCH"),
    ("CARRIER", "29C-445.41 hạ vỏ GAOU6543216 xong bốc hàng luôn kho Quế Võ chì SL9900", "REPORT_DISPATCH"),
    ("CARRIER", "Xe 15H-067.22 kết hợp trả cont TCLU1122337 rồi qua đóng kho Tiên Sơn hẹn 14h", "REPORT_DISPATCH"),
    ("CARRIER", "15C-888.99 tài Nam 0912345678 giao hàng xong quay đầu đóng tiếp cont MSCU1234566", "REPORT_DISPATCH"),
    ("CARRIER", "Xe 1: 15C-170.66 tài Huynh 0986713346 đóng kho Yên Phong\nXe 2: 29C-445.41 tài Đạt 0931142873 đóng kho Quế Võ", "REPORT_DISPATCH"),
    ("CARRIER", "Báo 2 xe đóng Bắc Ninh: 15C-111.22 tài An 0901112233 và 15C-333.44 tài Bình 0902223344", "REPORT_DISPATCH"),
    # --- Nhóm D: Bổ sung, Đổi xe, Sửa gõ nhầm, Hủy chuyến (8 mẫu) ---
    ("CARRIER", "LO2447 bổ sung chì SL998877", "carrier_supplement_trip"),
    ("CARRIER", "Bổ sung số cont MSCU1234566 và chì 223344 cho xe 15C-170.66", "carrier_supplement_trip"),
    ("CARRIER", "LO2447 đổi sang xe 29C-447.22 tài Nam 0912345678", "carrier_request_vehicle_update"),
    ("CARRIER", "Cho anh thay đầu kéo chuyến RO2846 sang 15H-099.88", "carrier_request_vehicle_update"),
    ("CARRIER", "Gõ nhầm biển số lúc nãy, sửa lại là 15C-170.66 nhé", "carrier_fix_recent_submission"),
    ("CARRIER", "Xin hủy chuyến RO2846 do xe hỏng dọc đường", "carrier_report_issue_or_cancel"),
    ("CARRIER", "Báo sự cố xe 15C-170.66 nổ lốp xin trả lệnh LO2447", "carrier_report_issue_or_cancel"),
    ("CARRIER", "xác nhận #12345", "CONFIRM"),
    # --- Nhóm E: Câu hỏi Trợ lý Nhà xe (6 mẫu) ---
    ("CARRIER", "Hôm nay bên anh có mấy chuyến?", "carrier_list_plans_by_date"),
    ("CARRIER", "Còn lệnh nào thiếu cont hoặc thiếu chì không em?", "carrier_list_incomplete_plans"),
    ("CARRIER", "Lệnh LO2447 mấy giờ đóng ở đâu?", "carrier_get_order_detail"),
    ("CARRIER", "Xe 447.22 hôm nay chạy những chuyến nào?", "carrier_get_vehicle_schedule"),
    ("CARRIER", "Tin báo xe lúc nãy bot ghi nhận chưa?", "carrier_check_submission_status"),
    ("CARRIER", "Tổng hợp kế hoạch hôm nay của nhà xe", "carrier_get_summary"),
    # --- Nhóm F: Câu hỏi Trợ lý Khách hàng (8 mẫu) ---
    ("CUSTOMER", "Hôm nay có những chuyến nào về kho chị?", "customer_list_trips_by_date"),
    ("CUSTOMER", "Cont MSCU1234566 xe nào chở vậy em?", "customer_get_trip_detail"),
    ("CUSTOMER", "Cho xin số điện thoại tài xế xe 29C-445.41", "customer_get_vehicle_driver"),
    ("CUSTOMER", "Booking BK26110901 hôm nay có mấy xe?", "customer_query_schedule"),
    ("CUSTOMER", "Tổng hợp lịch giao nhận hôm nay", "customer_get_summary"),
    ("CUSTOMER", "Hôm nay có chuyến nào đổi xe không?", "customer_get_trip_changes"),
    ("CUSTOMER", "Cho chị hủy chuyến LO2447 nhé", "customer_create_change_request"),
    ("CUSTOMER", "Ca #987 duyệt xong chưa em?", "customer_get_request_status"),
    # --- Nhóm G: Câu hỏi Trợ lý ĐHVT gồm thống kê vùng/tỉnh & chặn duyệt Zalo (10 mẫu) ---
    ("DHVT", "Hôm nay tổng số lệnh, số lệnh đóng, trả theo từng vùng thế nào?", "dhvt_get_daily_overview"),
    ("DHVT", "Miền Bắc hôm nay có bao nhiêu lệnh đóng?", "dhvt_get_daily_overview"),
    ("DHVT", "Số lệnh trả hôm nay là bao nhiêu?", "dhvt_get_daily_overview"),
    ("DHVT", "Thống kê lệnh đóng trả theo tỉnh hôm nay?", "dhvt_get_daily_overview"),
    ("DHVT", "Có xe nào trùng chuyến không?", "dhvt_detect_duplicate_vehicles"),
    ("DHVT", "Có vỏ nào cảnh báo hạ rỗng hoặc SOC không?", "dhvt_get_container_warnings"),
    ("DHVT", "Hôm nay có ca chờ nào cần xử lý gấp?", "dhvt_get_priority_digest"),
    ("DHVT", "Tại sao ca #123 cần duyệt?", "dhvt_explain_review_case"),
    ("DHVT", "Hôm nay tỷ lệ bot tự xử lý và dùng LLM thế nào?", "dhvt_get_bot_performance"),
    ("DHVT", "Duyệt ca #123 cho gửi khách luôn", "dhvt_direct_review_action"),
]


def test_golden_56_messages_benchmark_and_zero_false_auto_match():
    """Đánh giá định lượng trên bộ 56 tin nhắn ẩn danh: Intent Accuracy >= 95% và False Auto-Match = 0%."""
    ref = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    assert len(GOLDEN_MESSAGES) >= 56

    correct_intents = 0
    for role, text, expected_intent in GOLDEN_MESSAGES:
        pred = route_local(text, role, ref)  # type: ignore[arg-type]
        if pred.intent == expected_intent:
            correct_intents += 1

    intent_accuracy = correct_intents / len(GOLDEN_MESSAGES)
    assert intent_accuracy >= 0.96, f"Intent accuracy đạt {intent_accuracy:.2%}, thấp hơn 96%"

    # Kiểm chứng 0% False Auto-Match trên bộ kịch bản bẫy (sai nhà xe, trùng điểm kho, thiếu bằng chứng, vỏ cấm ghép)
    adversarial_cases = [
        # 1. Sai nhà xe dù trùng booking
        (
            ExtractedContainerLine(order_type="LOAD", booking_no="BK26110901"),
            [_mock_plan(id=1, carrier_id=99, booking_no="BK26110901")],
        ),
        # 2. Hai lệnh đóng cùng kho, cùng giờ hẹn (trùng điểm)
        (
            ExtractedContainerLine(order_type="LOAD", warehouse_hint="Kho Yên Phong Bắc Ninh", eta_time="08:00"),
            [
                _mock_plan(id=1, warehouse_name="Kho Yên Phong Bắc Ninh", required_time="08:00"),
                _mock_plan(id=2, warehouse_name="Kho Yên Phong Bắc Ninh", required_time="08:00"),
            ],
        ),
        # 3. Chỉ có 1 slot trống nhưng tin nhắn không nêu kho/khách/booking
        (
            ExtractedContainerLine(order_type="LOAD"),
            [_mock_plan(id=1)],
        ),
        # 4. Vỏ trả có cảnh báo hạ rỗng (empty_drop) nhưng nhà xe báo đóng kết hợp
        (
            ExtractedContainerLine(
                container_no=_make_valid_cont("MSCU", "123456"),
                order_type="LOAD",
                is_combined_from_return=True,
                warehouse_hint="Kho Yên Phong Bắc Ninh",
            ),
            [
                _mock_plan(
                    id=1,
                    order_type="tra",
                    container_no=_make_valid_cont("MSCU", "123456"),
                    container_warning="empty_drop",
                ),
                _mock_plan(id=2, order_type="dong", container_no=None),
            ],
        ),
        # 5. Container gõ lệch 1 ký tự so với kế hoạch
        (
            ExtractedContainerLine(container_no="MSCU1234576", order_type="RETURN"),
            [_mock_plan(id=1, order_type="tra", container_no=_make_valid_cont("MSCU", "123456"))],
        ),
        # 6. Tham chiếu ngữ cảnh mơ hồ ('xe trên') chưa giải quyết được
        (
            ExtractedContainerLine(order_type="LOAD", unresolved_fields=["context_reference"]),
            [_mock_plan(id=1)],
        ),
    ]

    false_auto_matches = 0
    for adv_line, adv_plans in adversarial_cases:
        res = PlanResolutionEngine.resolve(
            adv_line, adv_plans, 10, ["2026-11-09"], shadow=False
        )
        if res.action == "AUTO_COMMIT":
            false_auto_matches += 1

    assert false_auto_matches == 0, f"Phát hiện {false_auto_matches} ca tự ghép sai!"
