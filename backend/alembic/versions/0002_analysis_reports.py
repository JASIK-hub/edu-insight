"""Persist dataset processing state and generated reports."""

from alembic import op
import sqlalchemy as sa

revision = "0002_analysis_reports"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("status", sa.String(length=20), nullable=False, server_default="uploaded"))
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("report_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dataset_id", "request_hash", name="uq_analysis_report_request"),
    )
    op.create_index("ix_analysis_reports_dataset_id", "analysis_reports", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_reports_dataset_id", table_name="analysis_reports")
    op.drop_table("analysis_reports")
    op.drop_column("datasets", "status")
