"""Module Router Xác Thực Người Dùng (Authentication Router).

Cung cấp các API:
- `POST /api/auth/login`: Đăng nhập bằng tài khoản và mật khẩu, cấp phát JWT token.
- `GET /api/auth/me`: Lấy thông tin tài khoản đang đăng nhập hiện tại.
- `POST /api/auth/logout`: Đăng xuất và xóa phiên làm việc.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.api.schemas import ApiResponse, LoginData, LoginRequest, LoginResponse, UserOut
from src.infrastructure.database import get_db
from src.infrastructure.models import User
from src.infrastructure.security import (
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["0. Xác Thực & Phân Quyền (Auth)"])


def user_to_out(user: User) -> UserOut:
    """Chuyển đổi thực thể SQLAlchemy User sang Pydantic UserOut.

    Args:
        user (User): Thực thể người dùng trong CSDL.

    Returns:
        UserOut: Đối tượng DTO trả về cho client.
    """
    clean_role = (user.role or "DHVT").strip().upper()
    return UserOut(
        id=str(user.id),
        username=user.username,
        full_name=user.full_name or user.username,
        role=clean_role,
        email=user.email,
        zalo_user_id=user.zalo_user_id,
        zalo_info_id=str(user.zalo_info_id) if user.zalo_info_id is not None else None,
        tms_user_id=str(user.tms_user_id) if user.tms_user_id is not None else None,
        forwarder_id=str(user.forwarder_id) if user.forwarder_id is not None else None,
        is_active=bool(user.is_active),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Đăng nhập tài khoản ĐHVT hoặc Admin",
    description="Xác thực thông tin tài khoản qua username/email và mật khẩu, trả về JWT Access Token.",
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Xử lý đăng nhập, cấp JWT token và lưu vào cookie phiên làm việc."""
    username_or_email = payload.username.strip()
    user = db.scalar(
        select(User).where(
            or_(
                User.username == username_or_email,
                User.email == username_or_email,
            )
        )
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản hoặc mật khẩu không chính xác.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản này đã bị khóa hoặc ngừng hoạt động. Vui lòng liên hệ Admin.",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản hoặc mật khẩu không chính xác.",
        )

    # Cập nhật thời điểm đăng nhập gần nhất
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    # Sinh mã JWT Access Token
    user_out = user_to_out(user)
    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "role": user_out.role,
    }
    access_token = create_access_token(token_data)

    # Thiết lập Cookie an toàn phía client
    response.set_cookie(
        key="vsico_token",
        value=access_token,
        httponly=False,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
    )

    login_data = LoginData(
        access_token=access_token,
        token_type="bearer",
        user=user_out,
    )

    return LoginResponse(
        ok=True,
        status_code=status.HTTP_200_OK,
        message="Đăng nhập thành công",
        access_token=access_token,
        token_type="bearer",
        user=user_out,
        data=login_data,
    )


@router.get(
    "/me",
    response_model=UserOut,
    summary="Lấy thông tin tài khoản hiện tại",
    description="Truy xuất thông tin người dùng đang đăng nhập dựa trên JWT Access Token.",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Trả về hồ sơ cá nhân của người dùng đã xác thực."""
    return user_to_out(current_user)


@router.post(
    "/logout",
    response_model=ApiResponse[None],
    summary="Đăng xuất khỏi hệ thống",
    description="Xóa cookie phiên đăng nhập và kết thúc phiên làm việc.",
)
def logout(response: Response) -> ApiResponse[None]:
    """Xóa cookie token xác thực."""
    response.delete_cookie(key="vsico_token")
    return ApiResponse(
        ok=True,
        status_code=status.HTTP_200_OK,
        message="Đăng xuất thành công",
        data=None,
    )
