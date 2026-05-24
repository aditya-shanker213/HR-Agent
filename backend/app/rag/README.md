# HR AI Agent RAG Package

This package is the production version of the notebook RAG experiment. It answers from whatever PDFs are placed in the configured document folder.

## Flow

```text
PDFs -> semantic chunks -> bge-small embeddings -> ChromaDB -> reranked MMR retrieval -> LLM answer
```

## Main Integration Point

```python
from app.rag import RAGService

rag = RAGService()
response = rag.answer("What is the leave approval policy?")
print(response.answer)
print(response.sources)
```

For STT/TTS integration:

```python
spoken_text = stt.transcribe(audio)

for chunk in rag.answer_stream(spoken_text):
    tts.speak_stream(chunk)
```

The STT layer only needs to pass text into `answer()` or `answer_stream()`. The TTS layer can consume the final `response.answer` or each streamed text chunk.

## CLI

From the project root:

```powershell
.\.venv\Scripts\python.exe backend\scripts\index_rag.py
.\.venv\Scripts\python.exe backend\scripts\query_rag.py "What is the leave approval policy?"
.\.venv\Scripts\python.exe backend\scripts\query_rag.py "What benefits are employees eligible for?"
.\.venv\Scripts\python.exe backend\scripts\query_rag.py "What benefits are employees eligible for?" --json
.\.venv\Scripts\python.exe backend\scripts\query_rag.py
```

CLI answers stream by default and prints timing metadata after the final token:

```json
{
  "latency_seconds": 40.13,
  "retrieval_seconds": 0.08,
  "generation_seconds": 40.05,
  "done_reason": "stream_complete"
}
```

Use `--json` when you need the full response object with sources and timings. Running `query_rag.py` without a query opens an interactive input console.

Use `--rebuild` when PDFs changed and you want a clean Chroma collection:

```powershell
.\.venv\Scripts\python.exe backend\scripts\index_rag.py --rebuild
```

Run indexing once before the first query. Rerun it whenever documents are added, removed, or edited.

## Environment

Copy `.env.example` to `.env`, then change values as needed. Recommended generator:

```text
OLLAMA_MODEL=llama3.2:3b
```

`qwen3:4b` is not recommended for this answer step because it may emit thinking-style text even when `think=False`.

## LLM Backend

The active generation backend is Ollama:

```text
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
```

Make sure Ollama is running and the model is installed before querying:

```powershell
ollama serve
ollama pull llama3.2:3b
```
