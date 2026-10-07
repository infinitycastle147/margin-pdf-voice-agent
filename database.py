"""Database model and session setup."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import CheckConstraint, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import Integer, Text


load_dotenv(Path(__file__).with_name(".env"))
DB_PATH = Path(os.getenv("PDF_DATABASE_PATH", Path(__file__).with_name("documents.db")))
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0"),
        CheckConstraint("page_count > 0"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str | None] = mapped_column(Text)
    producer: Mapped[str | None] = mapped_column(Text)
    pdf_format: Mapped[str | None] = mapped_column(Text)
    pdf_created_at: Mapped[str | None] = mapped_column(Text)
    pdf_modified_at: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    pages: Mapped[list["DocumentPage"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (CheckConstraint("page_number > 0"),)

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship(back_populates="pages")
