"""standardize_enums_to_uppercase_english

Revision ID: 74834fab744f
Revises: 5bc7690b6df4
Create Date: 2026-11-13 02:04:38.609780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74834fab744f'
down_revision: Union[str, Sequence[str], None] = '5bc7690b6df4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Chuẩn hóa toàn bộ dữ liệu trạng thái và vai trò sang tiếng Anh viết hoa toàn bộ (ENGLISH FULL UPPERCASE)."""
    conn = op.get_bind()

    # 1. users: role -> UPPER(role)
    conn.execute(sa.text("UPDATE users SET role = UPPER(role) WHERE role IS NOT NULL"))

    # 2. zalo_groups: send_mode, group_role
    conn.execute(sa.text("UPDATE zalo_groups SET send_mode = 'AUTO' WHERE send_mode IN ('tu_dong', 'auto')"))
    conn.execute(sa.text("UPDATE zalo_groups SET send_mode = 'MANUAL' WHERE send_mode IN ('cho_duyet', 'manual')"))
    conn.execute(sa.text("UPDATE zalo_groups SET group_role = UPPER(group_role) WHERE group_role IS NOT NULL"))

    # 3. zalo_messages: processing_status
    conn.execute(sa.text("UPDATE zalo_messages SET processing_status = 'IGNORED_NON_TEXT' WHERE processing_status = 'bo_qua_anh'"))
    conn.execute(sa.text("UPDATE zalo_messages SET processing_status = UPPER(processing_status) WHERE processing_status IS NOT NULL"))

    # 4. outbound_messages: status
    conn.execute(sa.text("UPDATE outbound_messages SET status = 'PENDING_APPROVAL' WHERE status = 'cho_duyet'"))
    conn.execute(sa.text("UPDATE outbound_messages SET status = 'SENT' WHERE status = 'da_gui'"))
    conn.execute(sa.text("UPDATE outbound_messages SET status = 'FAILED' WHERE status = 'that_bai'"))
    conn.execute(sa.text("UPDATE outbound_messages SET status = 'CANCELLED' WHERE status = 'huy'"))
    conn.execute(sa.text("UPDATE outbound_messages SET status = 'IGNORED_DUPLICATE' WHERE status = 'bo_qua_trung_lap'"))
    conn.execute(sa.text("UPDATE outbound_messages SET status = UPPER(status) WHERE status IS NOT NULL"))

    # 5. container_jobs: validation_status, routing_status, tms_sync_status, order_type
    conn.execute(sa.text("UPDATE container_jobs SET validation_status = UPPER(validation_status) WHERE validation_status IS NOT NULL"))
    conn.execute(sa.text("UPDATE container_jobs SET routing_status = UPPER(routing_status) WHERE routing_status IS NOT NULL"))
    conn.execute(sa.text("UPDATE container_jobs SET tms_sync_status = UPPER(tms_sync_status) WHERE tms_sync_status IS NOT NULL"))
    conn.execute(sa.text("UPDATE container_jobs SET order_type = 'LOAD' WHERE order_type IN ('dong', 'load')"))
    conn.execute(sa.text("UPDATE container_jobs SET order_type = 'RETURN' WHERE order_type IN ('tra', 'return')"))

    # 6. review_cases: status
    conn.execute(sa.text("UPDATE review_cases SET status = UPPER(status) WHERE status IS NOT NULL"))

    # 7. bot_replies: status
    conn.execute(sa.text("UPDATE bot_replies SET status = 'PENDING' WHERE status = 'cho_sua'"))
    conn.execute(sa.text("UPDATE bot_replies SET status = 'SENT' WHERE status = 'da_gui'"))
    conn.execute(sa.text("UPDATE bot_replies SET status = UPPER(status) WHERE status IS NOT NULL"))


def downgrade() -> None:
    """Khôi phục trạng thái."""
    pass
