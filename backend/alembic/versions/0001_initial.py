"""Initial dataset and assessment tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("textbook", sa.String(length=255), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("assessment_date", sa.Date(), nullable=True),
        sa.Column("class_id", sa.String(length=255), nullable=True),
        sa.Column("grade", sa.Integer(), nullable=True),
    )
    op.create_index("ix_assessments_dataset_id", "assessments", ["dataset_id"])
    op.create_index("ix_assessments_dataset_topic", "assessments", ["dataset_id", "topic"])
    op.create_index("ix_assessments_dataset_textbook", "assessments", ["dataset_id", "textbook"])


def downgrade() -> None:
    op.drop_table("assessments")
    op.drop_table("datasets")
