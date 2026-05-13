from dotenv import load_dotenv
load_dotenv()
import os
from pathlib import Path
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from config import settings


os.environ['LANGCHAIN_PROJECT_NAME'] = 'HR_AGENT'

PDF_PATH = "HR_Policy.pdf"


def get_embeddings():
    """Build the embedding model. Shared between ingestion and serving."""
    return OllamaEmbeddings(
        model=settings.EMBEDDING_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
    )


def ingest():
    path = Path(PDF_PATH)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

    # Load PDF
    loader = PyMuPDFLoader(str(path))
    docs = loader.load()

    # Add custom metadata to each page
    for d in docs:
        d.metadata["source"] = path.stem
        d.metadata["document_type"] = "hr_policy"

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"{path.name}: {len(docs)} pages -> {len(chunks)} chunks")

    # Embed and persist to Chroma
    print(f"Embedding with {settings.EMBEDDING_MODEL}...")
    embeddings = get_embeddings()

    Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=settings.CHROMA_COLLECTION,
        persist_directory=settings.CHROMA_PERSIST_DIR,
    )
    print(f"Indexed {len(chunks)} chunks -> {settings.CHROMA_PERSIST_DIR}")


if __name__ == "__main__":
    ingest()