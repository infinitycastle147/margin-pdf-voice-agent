"""Store extracted content by page.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_pages",
        sa.Column("document_id", sa.Text(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("page_number", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("page_number > 0"),
    )
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO document_pages (document_id, page_number, content)
        SELECT id, 1, content FROM documents WHERE page_count = 1
    """))


def downgrade() -> None:
    op.drop_table("document_pages")
