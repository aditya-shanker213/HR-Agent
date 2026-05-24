from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(description="Index uploaded PDFs into the Chroma vector store.")
    parser.add_argument("--rebuild", action="store_true", help="Delete and rebuild the Chroma collection.")
    args = parser.parse_args()

    from app.rag import RAGConfig, RAGPipeline

    config = RAGConfig.from_env()
    pipeline = RAGPipeline(config)
    stats = pipeline.index_pdfs(rebuild=args.rebuild)
    print(stats)


if __name__ == "__main__":
    main()
