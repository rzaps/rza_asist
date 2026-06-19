"""Кастомный компонент Langflow: FAISS Context Provider.

Отдельный узел гибридного поиска для canvas.
Принимает поисковый запрос → возвращает контекст (строку с чанками).
В отличие от local_faiss_search (который Tool для агента),
этот компонент отдаёт Message — можно напрямую подключить к Writer/Planner.
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class FaissContextProvider(Component):
    display_name = "FAISS Context"
    description = "Гибридный поиск FAISS+BM25+Reranker. Принимает запрос → отдаёт контекст для LLM."
    icon = "database"

    inputs = [
        MessageTextInput(
            name="search_query",
            display_name="Поисковый запрос",
            info="Что искать в базе знаний",
        ),
        DataInput(
            name="collections",
            display_name="Коллекции (JSON-список строк)",
            required=False,
        ),
        DataInput(
            name="top_k",
            display_name="Top-K результатов",
            required=False,
        ),
    ]

    outputs = [
        Output(
            name="context_output",
            display_name="Контекст (чанки)",
            method="run_search",
            type=Message,
        ),
    ]

    def run_search(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from app.search import hybrid_search

        query = (self.search_query or "").strip()
        if not query:
            return Message(text=json.dumps({
                "chunks": [],
                "context_text": "",
                "search_query": "",
            }, ensure_ascii=False))

        # Коллекции
        active = ["gost", "manuals", "projects_docx_clean"]
        if self.collections:
            try:
                if isinstance(self.collections, str):
                    active = json.loads(self.collections)
                elif isinstance(self.collections, list):
                    active = self.collections
            except Exception:
                pass

        # Top-K
        top_k = 6
        if self.top_k:
            try:
                top_k = int(self.top_k)
            except Exception:
                pass

        results, _, _ = hybrid_search(query, active_collections=active, top_k=top_k)

        chunks = []
        context_parts = []
        for i, chunk in enumerate(results, 1):
            meta = chunk.get("metadata", {})
            source = meta.get("source", "?")
            section = meta.get("section", "")
            title = meta.get("title", "")
            text = chunk.get("text", "")
            collection = chunk.get("collection", "")

            header = f"[{i}] {collection} | {source}"
            if section:
                header += f" | Раздел {section}"
            if title:
                header += f" — {title}"

            context_parts.append(f"{header}\n{text}")

            chunks.append({
                "num": i,
                "collection": collection,
                "source": source,
                "section": section,
                "title": title,
                "text": text[:500],
                "ce_score": chunk.get("ce_score"),
            })

        payload = json.dumps({
            "chunks": chunks,
            "context_text": "\n\n---\n\n".join(context_parts),
            "chunks_found": len(chunks),
            "search_query": query,
        }, ensure_ascii=False)

        return Message(text=payload)
