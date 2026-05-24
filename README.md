## Production RAG

The notebook RAG flow has been modularized under:

```text
backend/app/rag
```

Main integration surface:

```python
from app.rag import RAGService

rag = RAGService()
response = rag.answer("What is the leave approval policy?")
print(response.answer)
```

Streaming for STT/TTS:

```python
for text_chunk in rag.answer_stream("What benefits are employees eligible for?"):
    tts.speak_stream(text_chunk)
```

Index PDFs:

```powershell
.\.venv\Scripts\python.exe backend\scripts\index_rag.py
```

Run this once before querying, and rerun it whenever uploaded PDFs change.

Ask a query:

```powershell
.\.venv\Scripts\python.exe backend\scripts\query_rag.py "What is the leave approval policy?"
```

CLI answers stream by default. Use `--json` when you need the full response object with sources and timings:

After a streamed answer, the CLI prints timing metadata:

```json
{
  "latency_seconds": 40.13,
  "retrieval_seconds": 0.08,
  "generation_seconds": 40.05,
  "done_reason": "stream_complete"
}
```

```powershell
.\.venv\Scripts\python.exe backend\scripts\query_rag.py "What is the leave approval policy?" --json
```

Or open the interactive query console:

```powershell
.\.venv\Scripts\python.exe backend\scripts\query_rag.py
```

See [backend/app/rag/README.md](backend/app/rag/README.md) for integration details.
