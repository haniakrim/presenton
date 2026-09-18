"""add presentation source

Revision ID: bf4928224ca1
Revises: 026c0ba8b35c
Create Date: 2026-09-18 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bf4928224ca1"
down_revision: str | None = "026c0ba8b35c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("presentations")
    }
    if "source" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(sa.Column("source", sa.String(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("presentations")
    }
    if "source" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("source")
