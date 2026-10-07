"""Extract a PDF to Markdown with PyMuPDF4LLM."""

import argparse
from pathlib import Path
from typing import Iterator

import pymupdf
import pymupdf4llm


def extract_pdf_pages(
    pdf_path: Path, output_path: Path, batch_size: int = 20
) -> Iterator[tuple[int, str]]:
    """Write Markdown and yield each page with its one-based page number."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    with pymupdf.open(pdf_path) as document, output_path.open("w", encoding="utf-8") as output:
        for start in range(0, len(document), batch_size):
            pages = list(range(start, min(start + batch_size, len(document))))
            chunks = pymupdf4llm.to_markdown(document, pages=pages, page_chunks=True)
            for page_index, chunk in zip(pages, chunks, strict=True):
                content = chunk["text"]
                output.write(content)
                yield page_index + 1, content


def extract_pdf(pdf_path: Path, output_path: Path, batch_size: int = 20) -> Path:
    for _ in extract_pdf_pages(pdf_path, output_path, batch_size):
        pass

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a PDF to Markdown.")
    parser.add_argument("pdf", type=Path, help="Path to the input PDF")
    parser.add_argument("-o", "--output", type=Path, help="Output Markdown path")
    args = parser.parse_args()

    output = args.output or args.pdf.with_suffix(".md")
    print(extract_pdf(args.pdf, output))


if __name__ == "__main__":
    main()
