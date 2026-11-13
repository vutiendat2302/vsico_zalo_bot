"""Xác thực bảo mật nội bộ Zero-Trust cho AI Microservice.

Mọi request gọi từ backend vào ai-service bắt buộc phải có header
`X-Internal-Token` khớp với `INTERNAL_SECRET`.
"""

from fastapi import Header, HTTPException, status
from app.core.config import settings


def verify_internal_token(x_internal_token: str = Header(..., alias="X-Internal-Token")) -> str:
    """Xác thực header X-Internal-Token từ backend gửi sang."""
    if not settings.INTERNAL_SECRET or x_internal_token != settings.INTERNAL_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Truy cập bị từ chối: Token nội bộ không hợp lệ hoặc thiếu header X-Internal-Token.",
        )
    return x_internal_token
