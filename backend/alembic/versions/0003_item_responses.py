"""Store optional item responses for skill diagnostics."""

from alembic import op
import sqlalchemy as sa

revision = "0003_item_responses"
down_revision = "0002_analysis_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("skill", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_item_responses_dataset_id", "item_responses", ["dataset_id"])
    op.create_index("ix_item_responses_dataset_topic_skill", "item_responses", ["dataset_id", "topic", "skill"])


def downgrade() -> None:
    op.drop_index("ix_item_responses_dataset_topic_skill", table_name="item_responses")
    op.drop_index("ix_item_responses_dataset_id", table_name="item_responses")
    op.drop_table("item_responses")
