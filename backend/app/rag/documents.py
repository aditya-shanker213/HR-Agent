from __future__ import annotations

import time
from pathlib import Path

from langchain_community.document_loaders import PyMuPDFLoader

from .schemas import TextDocument


class PDFDocumentLoader:
    def __init__(self, pdf_dir: Path):
        self.pdf_dir = Path(pdf_dir)

    def load(self) -> list[TextDocument]:
        pdf_files = sorted(self.pdf_dir.glob("**/*.pdf"))
        documents: list[TextDocument] = []
        started = time.perf_counter()

        for pdf_file in pdf_files:
            loader = PyMuPDFLoader(str(pdf_file))
            for doc in loader.load():
                metadata = dict(doc.metadata)
                metadata["source_file"] = pdf_file.name
                metadata["source_path"] = str(pdf_file)
                metadata["file_type"] = "pdf"
                documents.append(TextDocument(content=doc.page_content, metadata=metadata))

        elapsed = time.perf_counter() - started
        print(f"Loaded {len(documents)} PDF page(s) from {len(pdf_files)} file(s) in {elapsed:.2f}s")
        return documents

