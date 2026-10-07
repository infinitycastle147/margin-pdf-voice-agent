"""Page lookup tools shared by the API and voice agent."""

from bisect import bisect_right
import regex

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import Document, DocumentPage


def get_page(session: Session, document_id: str, page_number: int) -> dict:
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise ValueError("Page number must be a positive integer")
    page = session.get(DocumentPage, (document_id, page_number))
    if page is None:
        raise LookupError("Page not found. Older PDFs may need to be uploaded again.")
    return {"document_id": document_id, "page_number": page_number, "content": page.content}


def search_pages(
    session: Session,
    document_id: str,
    pattern: str,
    lines_before: int = 2,
    lines_after: int = 2,
    use_regex: bool = False,
) -> dict:
    if session.get(Document, document_id) is None:
        raise LookupError("Document not found")
    if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
        raise ValueError("Pattern must contain 1 to 200 characters")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 10 for value in (lines_before, lines_after)):
        raise ValueError("Context line counts must be between 0 and 10")
    if not isinstance(use_regex, bool):
        raise ValueError("use_regex must be a boolean")

    expression = regex.compile(pattern if use_regex else regex.escape(pattern), regex.IGNORECASE | regex.MULTILINE)
    if expression.match(""):
        raise ValueError("Pattern must not match empty text")

    matches = []
    count = 0
    pages = session.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    )
    found_page = False
    for page in pages:
        found_page = True
        lines = page.content.splitlines(keepends=True)
        line_starts = [0]
        for line in lines:
            line_starts.append(line_starts[-1] + len(line))
        try:
            for match in expression.finditer(page.content, timeout=0.1):
                count += 1
                if len(matches) >= 50:
                    continue
                line_index = bisect_right(line_starts, match.start()) - 1
                start = max(0, line_index - lines_before)
                stop = min(len(lines), line_index + lines_after + 1)
                matches.append({
                    "page_number": page.page_number,
                    "line_number": line_index + 1,
                    "match": match.group()[:200],
                    "context": "".join(lines[start:stop])[:2000],
                })
        except TimeoutError as error:
            raise ValueError("Pattern search timed out") from error

    if not found_page:
        raise LookupError("Page data is unavailable. Upload this PDF again.")
    return {"document_id": document_id, "occurrences": count, "matches": matches, "truncated": count > len(matches)}
