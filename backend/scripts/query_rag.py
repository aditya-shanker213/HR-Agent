from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def print_json_answer(service, query: str) -> None:
    response = service.answer(query)
    if response.done_reason and "connection_error" in response.done_reason:
        print(f"Generation backend unavailable ({response.done_reason}); returning retrieved-document fallback.", file=sys.stderr)
    print(json.dumps(asdict(response), indent=2, ensure_ascii=False))


def print_stream_answer(service, query: str) -> None:
    final_metadata = None
    for event in service.answer_stream_events(query):
        if event.event == "chunk":
            print(event.text, end="", flush=True)
        elif event.event == "metadata":
            final_metadata = event.metadata
    print()
    if final_metadata:
        timing = {
            "latency_seconds": final_metadata.get("latency_seconds"),
            "retrieval_seconds": final_metadata.get("retrieval_seconds"),
            "generation_seconds": final_metadata.get("generation_seconds"),
            "done_reason": final_metadata.get("done_reason"),
        }
        print(json.dumps(timing, indent=2, ensure_ascii=False))


def run_interactive(stream: bool) -> None:
    print("HR AI Agent RAG query console")
    print("Type a question and press Enter. Type 'exit' or 'quit' to stop.")
    service = None
    while True:
        try:
            query = input("\nQuery: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            return
        if service is None:
            from app.rag import RAGService

            service = RAGService()
        if stream:
            print("Answer: ", end="")
            print_stream_answer(service, query)
        else:
            print_json_answer(service, query)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the document-grounded HR RAG service a question.")
    parser.add_argument("query", nargs="?", help="Question to ask. If omitted, starts an interactive query console.")
    parser.add_argument("--stream", action="store_true", help="Stream answer chunks instead of returning JSON.")
    parser.add_argument("--json", action="store_true", help="Return the full response JSON instead of streaming.")
    args = parser.parse_args()

    use_stream = args.stream or not args.json

    if not args.query:
        run_interactive(stream=use_stream)
        return

    from app.rag import RAGService

    service = RAGService()
    if use_stream:
        print_stream_answer(service, args.query)
        return

    print_json_answer(service, args.query)


if __name__ == "__main__":
    main()
