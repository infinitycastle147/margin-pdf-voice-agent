"""PDF upload and extraction API."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Iterator
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
import pymupdf
from sqlalchemy.orm import Session
import regex

from database import Document, DocumentPage, SessionLocal
from extract_pdf import extract_pdf_pages
from page_tools import get_page, search_pages


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


app = FastAPI(title="PDF Extraction API")


@app.post("/documents", status_code=201)
def upload_document(
    file: Annotated[UploadFile, File(description="PDF to extract")],
    session: Annotated[Session, Depends(get_session)],
):
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(400, "Upload a PDF file")

    with TemporaryDirectory() as directory:
        pdf_path = Path(directory) / "upload.pdf"
        digest = sha256()
        size = 0
        with pdf_path.open("wb") as destination:
            while chunk := file.file.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
                size += len(chunk)

        if not size:
            raise HTTPException(400, "PDF is empty")

        try:
            with pymupdf.open(pdf_path) as pdf:
                if not pdf.is_pdf or pdf.is_encrypted or pdf.page_count == 0:
                    raise HTTPException(400, "PDF is invalid, encrypted, or empty")
                metadata = pdf.metadata or {}
                page_count = pdf.page_count

            markdown_path = Path(directory) / "content.md"
            pages = list(extract_pdf_pages(pdf_path, markdown_path))
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError) as error:
            raise HTTPException(400, f"Could not extract PDF: {error}") from error

        document_id = str(uuid4())
        document = Document(
            id=document_id,
            filename=Path(file.filename).name,
            sha256=digest.hexdigest(),
            size_bytes=size,
            page_count=page_count,
            title=metadata.get("title"),
            author=metadata.get("author"),
            subject=metadata.get("subject"),
            keywords=metadata.get("keywords"),
            creator=metadata.get("creator"),
            producer=metadata.get("producer"),
            pdf_format=metadata.get("format"),
            pdf_created_at=metadata.get("creationDate"),
            pdf_modified_at=metadata.get("modDate"),
            content=markdown_path.read_text(encoding="utf-8"),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        document.pages = [
            DocumentPage(page_number=number, content=content)
            for number, content in pages
        ]
        session.add(document)
        session.commit()

    return {"id": document_id, "page_count": page_count}


@app.get("/documents/{document_id}")
def get_document(document_id: str, session: Annotated[Session, Depends(get_session)]):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return {column.name: getattr(document, column.name) for column in Document.__table__.columns}


@app.get("/documents/{document_id}/pages/{page_number}")
def read_page(document_id: str, page_number: int, session: Annotated[Session, Depends(get_session)]):
    try:
        return get_page(session, document_id, page_number)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/documents/{document_id}/search")
def search_document(
    document_id: str,
    pattern: str,
    session: Annotated[Session, Depends(get_session)],
    lines_before: int = 2,
    lines_after: int = 2,
    use_regex: bool = False,
):
    try:
        return search_pages(session, document_id, pattern, lines_before, lines_after, use_regex)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, regex.error) as error:
        raise HTTPException(400, str(error)) from error
