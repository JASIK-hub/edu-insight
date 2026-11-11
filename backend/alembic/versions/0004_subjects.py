"""Allow optional subject labels on assessments and item responses."""

from alembic import op
import sqlalchemy as sa

revision = "0004_subjects"
down_revision = "0003_item_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assessments", sa.Column("subject", sa.String(length=255), nullable=True))
    op.add_column("item_responses", sa.Column("subject", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("item_responses", "subject")
    op.drop_column("assessments", "subject")
