from langchain_ollama import ChatOllama
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from flashrank import Ranker, RerankRequest
from config import settings
from Ingestion import get_embeddings


SYSTEM_PROMPT = """You are an assistant answering questions from a company knowledge base.
Use ONLY the provided context to answer. If the answer is not in the context, say:
"I don't have that information in the knowledge base."
Be concise. When you use a fact, mention the source and page in parentheses."""

USER_PROMPT = """Context:
{context}

Question: {question}

Answer:"""


def format_docs(docs):
    parts = []
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source", "unknown")
        page = d.metadata.get("page", "?")
        parts.append(f"[{i}] (source: {src}, page: {page})\n{d.page_content}")
    return "\n\n".join(parts)


class RAGService:
    def __init__(self):
        self.embeddings = get_embeddings()

        self.vectorstore = Chroma(
            collection_name=settings.CHROMA_COLLECTION,
            embedding_function=self.embeddings,
            persist_directory=settings.CHROMA_PERSIST_DIR,
        )

        search_kwargs = {"k": settings.RETRIEVER_K}
        if settings.RETRIEVER_TYPE == "mmr":
            search_kwargs["fetch_k"] = settings.MMR_FETCH_K
            search_kwargs["lambda_mult"] = settings.MMR_LAMBDA_MULT

        self.retriever = self.vectorstore.as_retriever(
            search_type=settings.RETRIEVER_TYPE,
            search_kwargs=search_kwargs,
        )

        self.reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

        self.llm = ChatOllama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=settings.LLM_TEMPERATURE,
            num_ctx=settings.LLM_NUM_CTX,
        )

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT),
        ])

        self.chain = (
            {
                "context": RunnablePassthrough() | self._retrieve_and_rerank | format_docs,
                "question": RunnablePassthrough(),
            }
            | self.prompt
            | self.llm
            | StrOutputParser()
        ).with_config({"run_name": "rag_chain"})

    def _retrieve_and_rerank(self, question: str):
        candidates = self.retriever.invoke(question)
        if not candidates:
            return []

        passages = [
            {"id": i, "text": d.page_content, "meta": d.metadata}
            for i, d in enumerate(candidates)
        ]
        ranked = self.reranker.rerank(RerankRequest(query=question, passages=passages))
        top_ids = [r["id"] for r in ranked[: settings.RERANK_TOP_N]]
        return [candidates[i] for i in top_ids]

    def query(self, question: str) -> dict:
        if not question or not question.strip():
            raise ValueError("Question cannot be empty.")

        retrieved = self._retrieve_and_rerank(question)
        answer = self.chain.invoke(question)

        sources = [
            {
                "source": d.metadata.get("source"),
                "page": d.metadata.get("page"),
                "snippet": d.page_content[:200].replace("\n", " "),
            }
            for d in retrieved
        ]
        return {"answer": answer, "sources": sources}

    def stream(self, question: str):
        for chunk in self.chain.stream(question):
            yield chunk