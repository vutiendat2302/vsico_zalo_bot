"""Module API Quản Lý Danh Mục Nhóm Zalo & Cấu Hình Chế Độ Gửi (Groups Management API).

Phục vụ việc quản lý danh sách các nhóm Zalo (nhóm nhà xe, nhóm khách hàng, nhóm nội bộ)
và cấu hình 2 trạng thái phát hành tin nhắn (`send_mode`):
1. `tu_dong` (Tự động):
   - Các tin nhắn thỏa mãn đầy đủ thông tin sẽ được tự động gửi vào nhóm khách hàng.
   - Các tin nhắn thiếu/sai dữ liệu vẫn được chuyển sang danh sách chờ duyệt.
2. `cho_duyet` (Chờ duyệt):
   - Kể cả tin nhắn có thỏa mãn đầy đủ 100% thì VẪN đưa vào danh sách để Điều độ viên (DVDH) duyệt trước khi phát hành.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.domain.enums import GroupRole, SendMode
from src.infrastructure.database import get_db
from src.infrastructure.models import ZaloGroup

router = APIRouter(prefix="/api/groups", tags=["6. Quản Lý Nhóm Zalo (Groups Management)"])


class GroupCreatePayload(BaseModel):
    """Schema tạo mới hoặc đăng ký nhóm Zalo."""
    zalo_group_id: str = Field(..., description="ID định danh nhóm Zalo (threadId)")
    name: Optional[str] = Field(None, description="Tên hiển thị của nhóm")
    group_role: str = Field(GroupRole.SOURCE.value, description="Vai trò: SOURCE (nhà xe), DESTINATION (khách), DHVT (nội bộ)")
    carrier_id: Optional[str] = Field(None, description="Mã nhà xe nếu là nhóm nhà xe")
    carrier_name: Optional[str] = Field(None, description="Tên nhà xe liên kết")
    send_mode: str = Field(SendMode.AUTO.value, description="Chế độ gửi: AUTO (Tự động) hoặc MANUAL (Chờ duyệt)")
    is_active: bool = Field(True, description="Trạng thái kích hoạt")
    is_test: bool = Field(False, description="Nhóm thử nghiệm nội bộ")


class GroupUpdateSendModePayload(BaseModel):
    """Schema cập nhật trạng thái gửi của nhóm."""
    send_mode: str = Field(
        ...,
        description="Trạng thái gửi mới: 'AUTO' (Tự động) hoặc 'MANUAL' (Chờ duyệt)"
    )


class GroupUpdatePayload(BaseModel):
    """Schema cập nhật thông tin nhóm."""
    name: Optional[str] = None
    group_role: Optional[str] = None
    carrier_id: Optional[str] = None
    carrier_name: Optional[str] = None
    send_mode: Optional[str] = None
    is_active: Optional[bool] = None
    is_test: Optional[bool] = None


class GroupUpdateStatusPayload(BaseModel):
    """Schema cập nhật toàn diện trạng thái nhóm thật."""
    send_mode: Optional[str] = Field(
        None,
        description="Trạng thái phát hành tin: 'tu_dong' (Tự động) hoặc 'cho_duyet' (Chờ duyệt)"
    )
    is_active: Optional[bool] = Field(None, description="Trạng thái kích hoạt nhóm")
    name: Optional[str] = Field(None, description="Tên hiển thị nhóm")
    group_role: Optional[str] = Field(None, description="Vai trò nhóm: source (nhà xe), destination (khách), internal (ĐHVT)")
    carrier_id: Optional[str] = Field(None, description="Mã nhà xe liên kết")
    carrier_name: Optional[str] = Field(None, description="Tên nhà xe liên kết")
    is_test: Optional[bool] = Field(None, description="Đánh dấu nhóm thử nghiệm")


class GroupResponse(BaseModel):
    """Schema hiển thị thông tin nhóm Zalo."""
    id: int
    zalo_group_id: str
    name: Optional[str] = None
    group_role: str
    carrier_id: Optional[str] = None
    carrier_name: Optional[str] = None
    send_mode: str
    send_mode_label: str
    is_active: bool
    is_test: bool
    created_at: Optional[str] = None


@router.get("", response_model=dict[str, Any])
def list_groups(
    role: Optional[str] = Query(None, description="Lọc theo vai trò: source, destination, customer, internal"),
    send_mode: Optional[str] = Query(None, description="Lọc theo chế độ: tu_dong, cho_duyet"),
    is_active: Optional[bool] = Query(None, description="Lọc theo trạng thái kích hoạt"),
    search: Optional[str] = Query(None, description="Tìm kiếm theo tên nhóm hoặc Zalo Group ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy danh sách các nhóm Zalo kèm cấu hình chế độ gửi (`send_mode`)."""
    stmt = select(ZaloGroup)

    if role:
        norm_role = GroupRole(role).value
        stmt = stmt.where(ZaloGroup.group_role.in_([norm_role, role.lower(), role.upper()]))
    if send_mode:
        clean_mode = SendMode(send_mode).value
        stmt = stmt.where(ZaloGroup.send_mode.in_([clean_mode, send_mode.lower(), send_mode.upper()]))
    if is_active is not None:
        stmt = stmt.where(ZaloGroup.is_active == is_active)
    if search:
        s = f"%{search.strip()}%"
        stmt = stmt.where(or_(ZaloGroup.name.ilike(s), ZaloGroup.zalo_group_id.ilike(s)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    groups = list(db.scalars(stmt.order_by(ZaloGroup.id.asc()).offset(offset).limit(limit)).all())

    items = []
    for g in groups:
        mode_val = SendMode(g.send_mode).value if g.send_mode else SendMode.AUTO.value
        mode_label = "Tự động" if mode_val == SendMode.AUTO.value else "Chờ duyệt"
        items.append({
            "id": str(g.id),
            "zalo_group_id": g.zalo_group_id,
            "name": g.name or f"Nhóm {g.zalo_group_id}",
            "group_role": (GroupRole(g.group_role).value if g.group_role else GroupRole.SOURCE.value),
            "carrier_id": g.carrier_id,
            "carrier_name": g.carrier_name,
            "send_mode": mode_val,
            "send_mode_label": mode_label,
            "is_active": g.is_active,
            "is_test": g.is_test,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        })

    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "groups": items,
    }


@router.delete("/test-groups", response_model=dict[str, Any])
def delete_all_test_groups(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Xóa tất cả các nhóm thử nghiệm (test groups) khỏi cơ sở dữ liệu.

    Chỉ giữ lại các nhóm thật đang phục vụ vận hành thực tế (ví dụ nhóm đích thật 6469608867469758994).
    """
    # Điều kiện nhận diện nhóm test: is_test=True hoặc chứa các tiền tố/mẫu test
    test_conditions = or_(
        ZaloGroup.is_test == True,
        ZaloGroup.zalo_group_id.ilike("%test%"),
        ZaloGroup.zalo_group_id.ilike("pytest_%"),
        ZaloGroup.zalo_group_id.ilike("grp_test_%"),
        ZaloGroup.zalo_group_id.ilike("direct_%"),
        ZaloGroup.zalo_group_id.ilike("{{%"),
        ZaloGroup.zalo_group_id == "2001000000000000001",
        ZaloGroup.zalo_group_id == "3051850159021421440",
    )
    test_groups = list(db.scalars(select(ZaloGroup).where(test_conditions)).all())
    deleted_ids = []
    deleted_names = []

    for tg in test_groups:
        deleted_ids.append(tg.id)
        deleted_names.append(f"{tg.name or tg.zalo_group_id} (ID: {tg.id})")
        db.delete(tg)

    db.commit()

    # Lấy danh sách nhóm thật còn lại
    remaining_real_groups = list(db.scalars(select(ZaloGroup).order_by(ZaloGroup.id.asc())).all())
    remaining_out = [
        {
            "id": str(rg.id),
            "zalo_group_id": rg.zalo_group_id,
            "name": rg.name,
            "send_mode": rg.send_mode,
            "is_active": rg.is_active,
            "is_test": rg.is_test,
        }
        for rg in remaining_real_groups
    ]

    return {
        "ok": True,
        "message": f"Đã xóa thành công {len(deleted_ids)} nhóm thử nghiệm khỏi hệ thống.",
        "deleted_count": len(deleted_ids),
        "deleted_groups": deleted_names,
        "remaining_real_groups": remaining_out,
    }


@router.put("/by-zalo-id/{zalo_group_id}/status", response_model=dict[str, Any])
def update_real_group_status_by_zalo_id(
    zalo_group_id: str,
    payload: GroupUpdateStatusPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cập nhật trạng thái nhóm thật thông qua Zalo Group ID (chuỗi số threadId Zalo)."""
    clean_id = str(zalo_group_id).strip()
    g = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == clean_id))
    if not g:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhóm có Zalo ID '{clean_id}'.")

    if payload.send_mode is not None:
        try:
            clean_mode = SendMode(payload.send_mode).value
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Giá trị send_mode không hợp lệ. Chỉ chấp nhận 'AUTO' (Tự động) hoặc 'MANUAL' (Chờ duyệt)."
            )
        g.send_mode = clean_mode

    if payload.is_active is not None:
        g.is_active = payload.is_active

    if payload.name is not None and payload.name.strip():
        g.name = payload.name.strip()

    if payload.group_role is not None:
        try:
            g.group_role = GroupRole(payload.group_role).value
        except Exception:
            g.group_role = payload.group_role.strip().upper()

    if payload.carrier_id is not None:
        g.carrier_id = payload.carrier_id
    if payload.carrier_name is not None:
        g.carrier_name = payload.carrier_name
    if payload.is_test is not None:
        g.is_test = payload.is_test

    db.commit()
    db.refresh(g)

    mode_label = "Tự động" if g.send_mode == SendMode.AUTO.value else "Chờ duyệt"
    return {
        "ok": True,
        "message": f"Đã cập nhật trạng thái nhóm '{g.name or g.zalo_group_id}' thành công.",
        "group": {
            "id": str(g.id),
            "zalo_group_id": g.zalo_group_id,
            "name": g.name,
            "group_role": g.group_role,
            "send_mode": g.send_mode,
            "send_mode_label": mode_label,
            "is_active": g.is_active,
            "is_test": g.is_test,
        }
    }


@router.put("/{group_id}/status", response_model=dict[str, Any])
def update_real_group_status(
    group_id: int,
    payload: GroupUpdateStatusPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cập nhật trạng thái và thông tin nhóm thật theo Database ID nguyên bản."""
    g = db.get(ZaloGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhóm Zalo ID={group_id}.")

    if payload.send_mode is not None:
        try:
            clean_mode = SendMode(payload.send_mode).value
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Giá trị send_mode không hợp lệ. Chỉ chấp nhận 'AUTO' (Tự động) hoặc 'MANUAL' (Chờ duyệt)."
            )
        g.send_mode = clean_mode

    if payload.is_active is not None:
        g.is_active = payload.is_active

    if payload.name is not None and payload.name.strip():
        g.name = payload.name.strip()

    if payload.group_role is not None:
        try:
            g.group_role = GroupRole(payload.group_role).value
        except Exception:
            g.group_role = payload.group_role.strip().upper()

    if payload.carrier_id is not None:
        g.carrier_id = payload.carrier_id
    if payload.carrier_name is not None:
        g.carrier_name = payload.carrier_name
    if payload.is_test is not None:
        g.is_test = payload.is_test

    db.commit()
    db.refresh(g)

    mode_label = "Tự động" if g.send_mode == SendMode.AUTO.value else "Chờ duyệt"
    return {
        "ok": True,
        "message": f"Đã cập nhật trạng thái nhóm '{g.name or g.zalo_group_id}' thành công.",
        "group": {
            "id": str(g.id),
            "zalo_group_id": g.zalo_group_id,
            "name": g.name,
            "group_role": g.group_role,
            "send_mode": g.send_mode,
            "send_mode_label": mode_label,
            "is_active": g.is_active,
            "is_test": g.is_test,
        }
    }


@router.delete("/{group_id}", response_model=dict[str, Any])
def delete_group(group_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Xóa một nhóm Zalo khỏi cơ sở dữ liệu."""
    g = db.get(ZaloGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhóm Zalo ID={group_id}.")

    # Kiểm tra xem nhóm có tin nhắn outbound hay không
    from src.infrastructure.models import OutboundMessage
    outbound_count = db.scalar(
        select(func.count()).select_from(OutboundMessage).where(OutboundMessage.target_group_id == group_id)
    ) or 0

    if outbound_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Không thể xóa nhóm ID={group_id} vì đang có {outbound_count} tin nhắn gửi đi (outbound_messages) liên kết."
        )

    name_holder = g.name or g.zalo_group_id
    db.delete(g)
    db.commit()

    return {
        "ok": True,
        "message": f"Đã xóa nhóm '{name_holder}' thành công.",
        "deleted_id": str(group_id),
    }


@router.get("/{group_id}", response_model=dict[str, Any])
def get_group_detail(group_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Xem chi tiết một nhóm Zalo theo ID kèm thông tin thành viên thật từ Zalo nếu có."""
    import json
    import urllib.request

    g = db.get(ZaloGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhóm Zalo ID={group_id}.")

    mode_val = SendMode(g.send_mode).value if g.send_mode else SendMode.AUTO.value
    mode_label = "Tự động" if mode_val == SendMode.AUTO.value else "Chờ duyệt"

    zalo_live_info: Optional[dict[str, Any]] = None
    try:
        url = f"http://localhost:3000/api/bot/groups/{g.zalo_group_id}/info"
        req = urllib.request.Request(url, headers={"User-Agent": "Backend-VSICO"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            live_data = json.loads(resp.read().decode())
            if live_data.get("ok"):
                zalo_live_info = {
                    "total_members": live_data.get("total_members", 0),
                    "creator_id": live_data.get("data", {}).get("creatorId"),
                    "members": [
                        {
                            "id": uid,
                            "display_name": prof.get("displayName") or prof.get("zaloName") or uid,
                            "avatar": prof.get("avatar"),
                        }
                        for uid, prof in live_data.get("members_profiles", {}).items()
                    ],
                }
    except Exception:
        zalo_live_info = None

    return {
        "ok": True,
        "group": {
            "id": str(g.id),
            "zalo_group_id": g.zalo_group_id,
            "name": g.name or f"Nhóm {g.zalo_group_id}",
            "group_role": g.group_role,
            "carrier_id": g.carrier_id,
            "carrier_name": g.carrier_name,
            "send_mode": mode_val,
            "send_mode_label": mode_label,
            "is_active": g.is_active,
            "is_test": g.is_test,
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "zalo_live_info": zalo_live_info,
        },
    }


@router.put("/{group_id}/send-mode", response_model=dict[str, Any])
def update_group_send_mode(
    group_id: int,
    payload: GroupUpdateSendModePayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cập nhật trạng thái phát hành tin nhắn của nhóm giữa `tu_dong` (Tự động) và `cho_duyet` (Chờ duyệt).

    - `AUTO`: Tin nhắn thỏa mãn đầy đủ 8 trường chính sẽ được gửi tự động vào nhóm. Tin sai/thiếu vẫn chờ duyệt.
    - `MANUAL`: Mọi tin nhắn (kể cả thỏa mãn 100%) đều được giữ lại trong danh sách chờ duyệt để DVDH duyệt trước.
    """
    g = db.get(ZaloGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhóm Zalo ID={group_id}.")

    try:
        clean_mode = SendMode(payload.send_mode).value
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Giá trị send_mode không hợp lệ. Chỉ chấp nhận 'AUTO' (Tự động) hoặc 'MANUAL' (Chờ duyệt)."
        )

    g.send_mode = clean_mode
    db.commit()
    db.refresh(g)

    mode_label = "Tự động" if g.send_mode == SendMode.AUTO.value else "Chờ duyệt"
    return {
        "ok": True,
        "message": f"Đã chuyển trạng thái nhóm '{g.name or g.zalo_group_id}' sang '{mode_label}'.",
        "group_id": str(g.id),
        "zalo_group_id": g.zalo_group_id,
        "send_mode": g.send_mode,
        "send_mode_label": mode_label,
    }


@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreatePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Tạo hoặc đăng ký nhóm Zalo mới vào hệ thống."""
    existing = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == payload.zalo_group_id))
    if existing:
        raise HTTPException(status_code=400, detail=f"Nhóm có Zalo ID '{payload.zalo_group_id}' đã tồn tại.")

    clean_mode = SendMode(payload.send_mode).value if payload.send_mode else SendMode.AUTO.value
    clean_role = GroupRole(payload.group_role).value if payload.group_role else GroupRole.SOURCE.value
    grp = ZaloGroup(
        zalo_group_id=payload.zalo_group_id.strip(),
        name=payload.name,
        group_role=clean_role,
        carrier_id=payload.carrier_id,
        carrier_name=payload.carrier_name,
        send_mode=clean_mode,
        is_active=payload.is_active,
        is_test=payload.is_test,
    )
    db.add(grp)
    db.commit()
    db.refresh(grp)

    mode_label = "Tự động" if grp.send_mode == SendMode.AUTO.value else "Chờ duyệt"
    return {
        "ok": True,
        "message": f"Đã tạo nhóm Zalo '{grp.name or grp.zalo_group_id}' thành công.",
        "group": {
            "id": str(grp.id),
            "zalo_group_id": grp.zalo_group_id,
            "name": grp.name,
            "send_mode": grp.send_mode,
            "send_mode_label": mode_label,
        }
    }
