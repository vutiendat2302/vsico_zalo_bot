"""Module Bảo Mật, Mã Hóa Mật Khẩu & Xác Thực JWT (Security & JWT Auth).

Đảm nhiệm:
1. Băm mật khẩu (Bcrypt) và đối soát mật khẩu đăng nhập.
2. Sinh mã xác thực JSON Web Token (JWT) và giải mã định danh người dùng.
3. Cung cấp FastAPI Dependencies để kiểm tra quyền truy cập (RBAC): ĐHVT và Admin.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Header, status
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.infrastructure.database import get_db
from src.infrastructure.models import User

# Khóa bí mật mặc định an toàn nếu chưa khai báo trong biến môi trường
DEFAULT_JWT_SECRET = "vsico_secret_key_production_fallback_minimum_32_bytes_long_123456"


def get_jwt_secret() -> str:
    """Lấy khóa bí mật JWT từ cấu hình hệ thống.

    Returns:
        str: Chuỗi khóa bí mật.
    """
    secret = getattr(settings, "JWT_SECRET_KEY", "")
    if not secret or len(secret) < 16:
        return DEFAULT_JWT_SECRET
    return secret


def hash_password(plain_password: str) -> str:
    """Mã hóa mật khẩu một chiều sử dụng thuật toán Bcrypt.

    Args:
        plain_password (str): Mật khẩu dạng văn bản gốc.

    Returns:
        str: Chuỗi băm Bcrypt an toàn.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Kiểm tra mật khẩu nhập vào có khớp với mật khẩu băm trong cơ sở dữ liệu hay không.

    Args:
        plain_password (str): Mật khẩu văn bản gốc cần kiểm tra.
        hashed_password (str): Chuỗi băm Bcrypt lưu trong CSDL.

    Returns:
        bool: True nếu khớp, False nếu không chính xác.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Sinh chuỗi JWT Access Token chứa thông tin danh tính và vai trò người dùng.

    Args:
        data (dict): Dữ liệu Payload định danh (sub, username, role...).
        expires_delta (Optional[timedelta]): Thời hạn hiệu lực tùy chọn.

    Returns:
        str: Chuỗi JWT đã ký số.
    """
    to_encode = data.copy()
    expire_minutes = getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 1440)
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=expire_minutes)

    to_encode.update({"exp": expire, "iat": now})
    secret = get_jwt_secret()
    algorithm = getattr(settings, "JWT_ALGORITHM", "HS256")
    return jwt.encode(to_encode, secret, algorithm=algorithm)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Giải mã và xác thực chữ ký của JWT Access Token.

    Args:
        token (str): Chuỗi JWT cần giải mã.

    Returns:
        Optional[dict]: Payload nếu token hợp lệ, None nếu hết hạn hoặc sai chữ ký.
    """
    secret = get_jwt_secret()
    algorithm = getattr(settings, "JWT_ALGORITHM", "HS256")
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return payload
    except jwt.PyJWTError:
        return None


def extract_token(
    authorization: Optional[str] = Header(None),
    vsico_token: Optional[str] = Cookie(None),
) -> Optional[str]:
    """Trích xuất mã Token từ Authorization Header (Bearer) hoặc Cookie phiên.

    Args:
        authorization (Optional[str]): Header Authorization dạng 'Bearer <token>'.
        vsico_token (Optional[str]): Cookie lưu token phía trình duyệt.

    Returns:
        Optional[str]: Token hợp lệ hoặc None.
    """
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1].strip()
    if vsico_token:
        return vsico_token.strip()
    return None


def get_current_user(
    token: Optional[str] = Depends(extract_token),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI Dependency: Trích xuất và xác thực người dùng hiện tại từ JWT Token.

    Args:
        token (Optional[str]): Token trích xuất từ Header hoặc Cookie.
        db (Session): Phiên làm việc SQLAlchemy.

    Returns:
        User: Đối tượng người dùng hợp lệ trong cơ sở dữ liệu.

    Raises:
        HTTPException 401: Khi thiếu token, token không hợp lệ hoặc người dùng bị khóa.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Phiên làm việc không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exception

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản này đã bị khóa hoặc ngừng hoạt động.",
        )

    return user


def get_current_active_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI Dependency: Kiểm tra người dùng có quyền Quản trị viên (Admin) hay không.

    Args:
        current_user (User): Người dùng đã xác thực.

    Returns:
        User: Người dùng mang vai trò 'admin'.

    Raises:
        HTTPException 403: Khi người dùng không phải là admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quyền truy cập bị từ chối. Tính năng chỉ dành riêng cho Quản Trị Viên (Admin).",
        )
    return current_user


def get_optional_current_user(
    token: Optional[str] = Depends(extract_token),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """FastAPI Dependency: Trích xuất người dùng nếu có JWT hợp lệ; trả None nếu gọi nội bộ không kèm token."""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        return None
    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError):
        return None
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        return None
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản này đã bị khóa hoặc ngừng hoạt động.",
        )
    return user
