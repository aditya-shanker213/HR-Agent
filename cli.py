from dotenv import load_dotenv
load_dotenv()

from RAG import RAGService


def main():
    rag = RAGService()
    print("\nRAG ready. Type a question, 'quit' to exit, or 'stream <q>' to stream.\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            break

        if user_input.lower().startswith("stream "):
            question = user_input[7:]
            print("\nAnswer: ", end="", flush=True)
            for token in rag.stream(question):
                print(token, end="", flush=True)
            print("\n")
            continue

        try:
            result = rag.query(user_input)
        except Exception as e:
            print(f"Error: {e}\n")
            continue

        print(f"\nAnswer:\n{result['answer']}\n")
        print("Sources:")
        for s in result["sources"]:
            print(f"  - {s['source']} (page {s['page']}): {s['snippet']}...")
        print()


if __name__ == "__main__":
    main()