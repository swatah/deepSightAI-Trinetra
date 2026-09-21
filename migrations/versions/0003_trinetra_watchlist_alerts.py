"""Create per-tenant watchlist_entries and alerts tables (DM-7b)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-21 08:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dsai_bind = op.get_bind()
    dsai_inspector = sa.inspect(dsai_bind)
    dsai_existing_tables = dsai_inspector.get_table_names()

    # 1. Create watchlist_entries table if not exists (DM-7b, WL-27)
    if "watchlist_entries" not in dsai_existing_tables:
        op.create_table(
            'watchlist_entries',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.String(length=255), nullable=False),
            sa.Column('entry_type', sa.String(length=32), nullable=False),
            sa.Column('plate_text_norm', sa.String(length=64), nullable=True),
            sa.Column('reid_reference_pk', sa.String(length=255), nullable=True),
            sa.Column('reid_embedding_json', sa.Text(), nullable=True),
            sa.Column('label', sa.String(length=255), nullable=False),
            sa.Column('priority', sa.String(length=32), nullable=False, server_default='medium'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_by', sa.String(length=255), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
        )

        op.create_index('ix_watchlist_entries_tenant_id', 'watchlist_entries', ['tenant_id'])
        op.create_index('ix_watchlist_entries_plate_text_norm', 'watchlist_entries', ['plate_text_norm'])
        op.create_index('ix_watchlist_entries_active', 'watchlist_entries', ['active'])
        op.create_index('ix_watchlist_entries_tenant_active', 'watchlist_entries', ['tenant_id', 'active'])

    # 2. Handle alerts table (DM-7b, WL-31)
    # Check if existing alerts table has the new schema (integer id, watchlist_entry_id)
    dsai_recreate_alerts = False
    if "alerts" in dsai_existing_tables:
        dsai_columns = [col['name'] for col in dsai_inspector.get_columns('alerts')]
        if 'watchlist_entry_id' not in dsai_columns or 'tenant_id' not in dsai_columns:
            op.drop_table('alerts')
            dsai_recreate_alerts = True
    else:
        dsai_recreate_alerts = True

    if dsai_recreate_alerts:
        op.create_table(
            'alerts',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.String(length=255), nullable=False),
            sa.Column('watchlist_entry_id', sa.Integer(), nullable=False),
            sa.Column('video_object_pk', sa.String(length=255), nullable=False),
            sa.Column('camera_id', sa.String(length=255), nullable=False),
            sa.Column('matched_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('match_score', sa.Float(), nullable=False),
            sa.Column('crop_path', sa.String(length=1024), nullable=True),
            sa.Column('acknowledged', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('acknowledged_by', sa.String(length=255), nullable=True),
            sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

        op.create_index('ix_alerts_tenant_id', 'alerts', ['tenant_id'])
        op.create_index('ix_alerts_watchlist_entry_id', 'alerts', ['watchlist_entry_id'])
        op.create_index('ix_alerts_video_object_pk', 'alerts', ['video_object_pk'])
        op.create_index('ix_alerts_camera_id', 'alerts', ['camera_id'])
        op.create_index('ix_alerts_acknowledged', 'alerts', ['acknowledged'])
        op.create_index('ix_alerts_tenant_ack', 'alerts', ['tenant_id', 'acknowledged'])
        op.create_index('ix_alerts_tenant_id_pk', 'alerts', ['tenant_id', 'id'])


def downgrade() -> None:
    dsai_bind = op.get_bind()
    dsai_inspector = sa.inspect(dsai_bind)
    dsai_existing_tables = dsai_inspector.get_table_names()
    if "alerts" in dsai_existing_tables:
        op.drop_table('alerts')
    if "watchlist_entries" in dsai_existing_tables:
        op.drop_table('watchlist_entries')
