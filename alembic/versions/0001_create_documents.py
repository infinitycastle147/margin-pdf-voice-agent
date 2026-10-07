"""Create the documents table.

Revision ID: 0001
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if inspector.has_table("documents"):
        existing = {column["name"] for column in inspector.get_columns("documents")}
        expected = {
            "id", "filename", "sha256", "size_bytes", "page_count", "title",
            "author", "subject", "keywords", "creator", "producer", "pdf_format",
            "pdf_created_at", "pdf_modified_at", "content", "created_at",
        }
        if existing != expected:
            raise RuntimeError("Existing documents table does not match the expected schema")
        return

    op.create_table(
        "documents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("author", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column("keywords", sa.Text()),
        sa.Column("creator", sa.Text()),
        sa.Column("producer", sa.Text()),
        sa.Column("pdf_format", sa.Text()),
        sa.Column("pdf_created_at", sa.Text()),
        sa.Column("pdf_modified_at", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("size_bytes > 0"),
        sa.CheckConstraint("page_count > 0"),
    )


def downgrade() -> None:
    op.drop_table("documents")
