"""make_zalo_user_id_non_unique

Revision ID: ee50310fbbc5
Revises: ea3cf25706bf
Create Date: 2026-11-13 01:00:23.958909

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee50310fbbc5'
down_revision: Union[str, Sequence[str], None] = 'ea3cf25706bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Chuyển index ix_users_zalo_user_id thành non-unique để hỗ trợ nhiều tài khoản chia sẻ Zalo ID mẫu."""
    op.drop_index('ix_users_zalo_user_id', table_name='users')
    op.create_index(op.f('ix_users_zalo_user_id'), 'users', ['zalo_user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema: Khôi phục unique index cho ix_users_zalo_user_id."""
    op.drop_index(op.f('ix_users_zalo_user_id'), table_name='users')
    op.create_index('ix_users_zalo_user_id', 'users', ['zalo_user_id'], unique=True)
