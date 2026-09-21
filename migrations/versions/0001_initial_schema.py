"""Initial schema for cameras, plates, watchlists, alerts (DM-5, DM-10)

Revision ID: 0001
Revises: 
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cameras registry table (DM-5)
    op.create_table(
        'cameras',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('rtsp_url', sa.String(length=1024), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_cameras_id', 'cameras', ['id'])

    # Plate reads table
    op.create_table(
        'plate_reads',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('plate_number', sa.String(length=64), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('camera_id', sa.String(length=255), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('frame_path', sa.String(length=1024), nullable=True),
        sa.Column('crop_path', sa.String(length=1024), nullable=True),
    )
    op.create_index('ix_plate_reads_plate_number', 'plate_reads', ['plate_number'])
    op.create_index('ix_plate_reads_camera_id', 'plate_reads', ['camera_id'])

    # Watchlists table
    op.create_table(
        'watchlists',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    # Alerts table
    op.create_table(
        'alerts',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('watchlist_id', sa.String(length=255), nullable=False),
        sa.Column('camera_id', sa.String(length=255), nullable=False),
        sa.Column('matched_entity', sa.String(length=255), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('frame_path', sa.String(length=1024), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='NEW'),
    )


def downgrade() -> None:
    op.drop_table('alerts')
    op.drop_table('watchlists')
    op.drop_table('plate_reads')
    op.drop_table('cameras')
