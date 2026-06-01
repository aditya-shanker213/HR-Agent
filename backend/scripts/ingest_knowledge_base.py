# backend/scripts/ingest_knowledge_base.py

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

POLICY_FILE  = os.path.join(os.path.dirname(__file__), '../../knowledge_base/hr_policy.txt')
PINECONE_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME   = os.getenv("PINECONE_INDEX_NAME", "hr-policies")
CLOUD        = os.getenv("PINECONE_CLOUD", "aws")
REGION       = os.getenv("PINECONE_REGION", "us-east-1")
MODEL        = "all-MiniLM-L6-v2"


def parse_sections(text: str) -> list[dict]:
    """
    Split the policy into sections.
    Each SECTION header starts a new chunk.
    This gives focused, high-relevance chunks.
    """
    lines    = text.split('\n')
    sections = []
    current_section = "GENERAL"
    current_lines   = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("SECTION"):
            # Save previous section
            if current_lines:
                sections.append({
                    "section": current_section,
                    "text":    " ".join(current_lines),
                })
            current_section = line
            current_lines   = [line]
        else:
            current_lines.append(line)

    # Don't forget last section
    if current_lines:
        sections.append({
            "section": current_section,
            "text":    " ".join(current_lines),
        })

    return sections


def split_large_sections(sections: list[dict], max_chars: int = 600) -> list[dict]:
    """
    Split sections that are too large into smaller chunks.
    Keeps section label on each chunk for metadata.
    """
    chunks = []
    for sec in sections:
        text = sec["text"]
        if len(text) <= max_chars:
            chunks.append(sec)
        else:
            # Split by sentences
            sentences = text.split('. ')
            current   = []
            curr_len  = 0

            for sent in sentences:
                current.append(sent)
                curr_len += len(sent)
                if curr_len >= max_chars:
                    chunks.append({
                        "section": sec["section"],
                        "text":    '. '.join(current),
                    })
                    current  = []
                    curr_len = 0

            if current:
                chunks.append({
                    "section": sec["section"],
                    "text":    '. '.join(current),
                })

    return chunks


async def ingest():
    print("Starting knowledge base ingestion...")

    # Read policy
    with open(POLICY_FILE, 'r', encoding='utf-8') as f:
        text = f.read()
    print(f"✓ Read policy ({len(text)} chars)")

    # Parse into sections
    sections = parse_sections(text)
    print(f"✓ Parsed {len(sections)} sections")

    # Split large sections
    chunks = split_large_sections(sections)
    print(f"✓ Final chunks: {len(chunks)}")

    for i, c in enumerate(chunks):
        print(f"  [{i:02d}] {c['section'][:50]} ({len(c['text'])} chars)")

    # Load embedding model
    print(f"\nLoading embedding model...")
    model = SentenceTransformer(MODEL)
    print("✓ Model loaded")

    # Embed
    texts   = [c["text"] for c in chunks]
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    print(f"✓ Embedded {len(vectors)} chunks")

    # Connect Pinecone
    pc = Pinecone(api_key=PINECONE_KEY)
    existing = [i.name for i in pc.list_indexes()]

    if INDEX_NAME not in existing:
        pc.create_index(
            name=INDEX_NAME,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud=CLOUD, region=REGION)
        )
        print(f"✓ Created index: {INDEX_NAME}")

    index = pc.Index(INDEX_NAME)

    # Delete old vectors before re-ingesting
    print("Clearing old vectors...")
    try:
        index.delete(delete_all=True)
        print("✓ Old vectors cleared")
    except Exception:
        print("  (index was empty)")

    # Build and upsert
    pinecone_vectors = []
    for i, chunk in enumerate(chunks):
        pinecone_vectors.append({
            "id":     f"chunk_{i:04d}",
            "values": vectors[i].tolist(),
            "metadata": {
                "text":    chunk["text"],
                "section": chunk["section"],
                "doc_id":  "giggs_hr_policy",
            }
        })

    # Upsert in batches
    batch_size = 100
    for i in range(0, len(pinecone_vectors), batch_size):
        batch = pinecone_vectors[i:i+batch_size]
        index.upsert(vectors=batch)

    stats = index.describe_index_stats()
    print(f"\n✅ Ingestion complete!")
    print(f"   Vectors in Pinecone: {stats.total_vector_count}")
    print(f"\nTest queries:")
    print("  'What is the leave policy?'")
    print("  'How many casual leaves do I get?'")
    print("  'What is the work from home policy?'")
    print("  'What is the notice period?'")
    print("  'What are the working hours?'")


if __name__ == "__main__":
    asyncio.run(ingest())