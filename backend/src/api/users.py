"""Module Router Quản Lý Tài Khoản Người Dùng (Users Management CRUD Router).

Cung cấp đầy đủ các thao tác:
- `GET /api/users`: Truy vấn danh sách tài khoản phân trang, lọc theo vai trò và trạng thái.
- `POST /api/users`: Thêm mới tài khoản với giá trị mặc định tối giản (username, password=123456,
  zalo_user_id=6691387223255581446, zalo_info_id=3073804738540831090).
- `GET /api/users/{user_id}`: Lấy chi tiết thông tin một tài khoản.
- `PUT /api/users/{user_id}`: Cập nhật thông tin hoặc đổi mật khẩu tài khoản.
- `DELETE /api/users/{user_id}`: Xóa tài khoản khỏi hệ thống.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.auth import user_to_out
from src.api.schemas import (
    ApiResponse,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from src.domain.enums import GroupRole, SendMode, UserRole
from src.infrastructure.database import get_db
from src.infrastructure.models import User, ZaloGroup
from src.infrastructure.security import hash_password
from src.infrastructure.snowflake import snowflake

router = APIRouter(prefix="/api/users", tags=["0. Quản Lý Tài Khoản (Users)"])


def ensure_zalo_group_exists(db: Session, group_id_int: int) -> None:
    """Đảm bảo nhóm Zalo liên kết tồn tại trong bảng `zalo_groups` để tránh lỗi khóa ngoại (FK).

    Args:
        db (Session): Phiên làm việc CSDL.
        group_id_int (int): Khóa chính nhóm Zalo cần kiểm tra.
    """
    existing_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.id == group_id_int))
    if not existing_grp:
        new_grp = ZaloGroup(
            id=group_id_int,
            zalo_group_id=str(group_id_int),
            name="Nhóm ĐHVT Nội Bộ VSICO",
            group_role=GroupRole.DHVT.value,
            send_mode=SendMode.AUTO.value,
            is_test=False,
            is_active=True,
        )
        db.add(new_grp)
        db.commit()


@router.get(
    "",
    response_model=UserListResponse,
    summary="Danh sách tài khoản người dùng",
    description="Truy xuất danh sách người dùng có hỗ trợ phân trang và tìm kiếm theo tên hoặc username.",
)
def list_users(
    page: int = Query(1, ge=1, description="Số trang hiển thị"),
    page_size: int = Query(20, ge=1, le=100, description="Số bản ghi mỗi trang"),
    role: Optional[str] = Query(None, description="Lọc theo vai trò: ADMIN | DHVT"),
    is_active: Optional[bool] = Query(None, description="Lọc theo trạng thái kích hoạt"),
    search: Optional[str] = Query(None, description="Tìm kiếm theo username, họ tên hoặc email"),
    db: Session = Depends(get_db),
) -> UserListResponse:
    """Lấy danh sách người dùng phân trang."""
    query = select(User)

    if role:
        clean_role = role.strip().upper()
        query = query.where(User.role == clean_role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            or_(
                User.username.ilike(s),
                User.full_name.ilike(s),
                User.email.ilike(s),
            )
        )

    # Đếm tổng số bản ghi
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    # Phân trang và sắp xếp mới nhất lên đầu
    offset = (page - 1) * page_size
    users = db.scalars(
        query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    ).all()

    user_outs = [user_to_out(u) for u in users]
    return UserListResponse(
        ok=True,
        status_code=status.HTTP_200_OK,
        message="Lấy danh sách người dùng thành công.",
        data=user_outs,
        total=total,
        page=page,
        page_size=page_size,
        items=user_outs,
        meta={"total": total, "page": page, "page_size": page_size},
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo mới tài khoản người dùng",
    description=(
        "Tạo tài khoản mới. Các trường password, zalo_user_id, zalo_info_id "
        "được cấu hình sẵn giá trị mặc định nếu không truyền."
    ),
)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Tạo mới tài khoản nhân viên ĐHVT hoặc Admin."""
    username_clean = payload.username.strip()

    # 1. Kiểm tra username đã tồn tại chưa
    existing_user = db.scalar(select(User).where(User.username == username_clean))
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tên đăng nhập '{username_clean}' đã tồn tại trong hệ thống.",
        )

    # 2. Kiểm tra email nếu có
    if payload.email:
        email_clean = payload.email.strip()
        existing_email = db.scalar(select(User).where(User.email == email_clean))
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{email_clean}' đã được sử dụng.",
            )

    # 3. Đảm bảo nhóm Zalo liên kết tồn tại nếu có zalo_info_id
    zalo_info_id = payload.zalo_info_id or 3073804738540831090
    if zalo_info_id:
        ensure_zalo_group_exists(db, zalo_info_id)

    # 4. Thiết lập các trường mặc định
    password_raw = payload.password or "123456"
    full_name = payload.full_name.strip() if payload.full_name else username_clean
    zalo_user_id = payload.zalo_user_id or "6691387223255581446"
    role_input = (payload.role or "DHVT").strip().upper()
    role = UserRole.ADMIN.value if role_input in ("ADMIN", "admin") else UserRole.DHVT.value

    # 5. Sinh Snowflake ID và băm mật khẩu
    user_id = snowflake.generate()
    pwd_hash = hash_password(password_raw)

    new_user = User(
        id=user_id,
        username=username_clean,
        email=payload.email.strip() if payload.email else None,
        password_hash=pwd_hash,
        full_name=full_name,
        role=role,
        zalo_user_id=zalo_user_id,
        zalo_info_id=zalo_info_id,
        tms_user_id=payload.tms_user_id,
        forwarder_id=payload.forwarder_id,
        is_active=payload.is_active if payload.is_active is not None else True,
        created_at=datetime.now(timezone.utc),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return UserResponse(
        ok=True,
        status_code=status.HTTP_201_CREATED,
        message="Tạo mới tài khoản thành công.",
        data=user_to_out(new_user),
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Lấy chi tiết tài khoản theo ID",
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Lấy thông tin chi tiết một tài khoản."""
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tài khoản có ID {user_id}.",
        )
    return UserResponse(
        ok=True,
        status_code=status.HTTP_200_OK,
        message="Lấy thông tin tài khoản thành công.",
        data=user_to_out(user),
    )


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    summary="Cập nhật thông tin tài khoản",
)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Cập nhật thông tin hoặc đặt lại mật khẩu cho tài khoản."""
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tài khoản có ID {user_id}.",
        )

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.role is not None:
        clean_role = payload.role.strip().upper()
        if clean_role in ("ADMIN", "DHVT"):
            user.role = clean_role
    if payload.email is not None:
        user.email = payload.email.strip() if payload.email else None
    if payload.zalo_user_id is not None:
        user.zalo_user_id = payload.zalo_user_id.strip() if payload.zalo_user_id else None
    if payload.zalo_info_id is not None:
        ensure_zalo_group_exists(db, payload.zalo_info_id)
        user.zalo_info_id = payload.zalo_info_id
    if payload.tms_user_id is not None:
        user.tms_user_id = payload.tms_user_id
    if payload.forwarder_id is not None:
        user.forwarder_id = payload.forwarder_id
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None and len(payload.password) >= 6:
        user.password_hash = hash_password(payload.password)

    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    return UserResponse(
        ok=True,
        status_code=status.HTTP_200_OK,
        message="Cập nhật tài khoản thành công.",
        data=user_to_out(user),
    )


@router.delete(
    "/{user_id}",
    response_model=ApiResponse[None],
    summary="Xóa tài khoản khỏi hệ thống",
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """Xóa một tài khoản theo ID."""
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tài khoản có ID {user_id}.",
        )

    db.delete(user)
    db.commit()

    return ApiResponse(
        ok=True,
        status_code=status.HTTP_200_OK,
        message=f"Đã xóa tài khoản '{user.username}' (ID: {user_id}) thành công.",
        data=None,
    )
