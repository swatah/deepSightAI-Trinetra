"""Create per-tenant plate_reads table and pg_trgm GIN index (DM-7)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21 02:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dsai_bind = op.get_bind()
    dsai_is_postgres = dsai_bind.dialect.name == "postgresql"

    # Enable pg_trgm extension if PostgreSQL (DM-7)
    if dsai_is_postgres:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        op.execute(sa.text('CREATE SCHEMA IF NOT EXISTS "trinetra_plates";'))

    # Check if plate_reads table already exists in the active tenant schema
    dsai_inspector = sa.inspect(dsai_bind)
    dsai_existing_tables = dsai_inspector.get_table_names()

    if "plate_reads" not in dsai_existing_tables:
        op.create_table(
            'plate_reads',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.String(length=255), nullable=False),
            sa.Column('video_object_pk', sa.String(length=255), nullable=False, unique=True),
            sa.Column('video_id', sa.String(length=255), nullable=False),
            sa.Column('camera_id', sa.String(length=255), nullable=False),
            sa.Column('frame_timestamp', sa.Float(), nullable=False),
            sa.Column('plate_text_raw', sa.String(length=64), nullable=False),
            sa.Column('plate_text_norm', sa.String(length=64), nullable=False),
            sa.Column('ocr_confidence', sa.Float(), nullable=False),
            sa.Column('ocr_engine', sa.String(length=64), nullable=False, server_default='pp-ocrv3'),
            sa.Column('crop_path', sa.String(length=1024), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

        op.create_index('ix_plate_reads_tenant_id', 'plate_reads', ['tenant_id'])
        op.create_index('ix_plate_reads_video_object_pk', 'plate_reads', ['video_object_pk'], unique=True)
        op.create_index('ix_plate_reads_camera_id', 'plate_reads', ['camera_id'])
        op.create_index('ix_plate_reads_frame_timestamp', 'plate_reads', ['frame_timestamp'])
        op.create_index('ix_plate_reads_plate_text_norm', 'plate_reads', ['plate_text_norm'])
        op.create_index('ix_plate_reads_tenant_plate', 'plate_reads', ['tenant_id', 'plate_text_norm'])

        # Create pg_trgm GIN index for high-speed fuzzy trigram search (DM-7)
        if dsai_is_postgres:
            op.execute(sa.text(
                'CREATE INDEX IF NOT EXISTS ix_plate_reads_trgm '
                'ON plate_reads USING gin (plate_text_norm gin_trgm_ops);'
            ))


def downgrade() -> None:
    dsai_bind = op.get_bind()
    dsai_inspector = sa.inspect(dsai_bind)
    dsai_existing_tables = dsai_inspector.get_table_names()
    if "plate_reads" in dsai_existing_tables:
        op.drop_table('plate_reads')
