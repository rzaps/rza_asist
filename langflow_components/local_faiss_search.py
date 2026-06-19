"""Кастомный компонент Langflow: гибридный поиск по базе РЗА (FAISS + BM25 + Reranker).

Два выхода:
- tool_output (Tool) — для Langchain-агентов (rza_agent)
- context_output (Message) — JSON с чанками, для прямого подключения к Writer/Planner
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, BoolInput
from langflow.schema.message import Message
from langchain.tools import Tool


class LocalFaissSearch(Component):
    display_name = "FAISS Search"
    description = "Гибридный поиск FAISS + BM25 + Reranker. Tool для агента + Message для пайплайна."
    icon = "database"

    inputs = [
        MessageTextInput(
            name="project_root",
            display_name="Путь к проекту rza_asist",
            value="J:\\Documents\\GitHub\\rza_rag",
        ),
        MessageTextInput(
            name="search_query",
            display_name="Поисковый запрос",
            info="Что искать",
        ),
        BoolInput(name="search_gost", display_name="ГОСТ / ПУЭ / Приказы", value=True),
        BoolInput(name="search_manuals", display_name="Мануалы (заводы)", value=True),
        BoolInput(name="search_projects", display_name="Проекты (аналоги)", value=True),
    ]

    outputs = [
        Output(name="tool_output", display_name="As Tool (для агента)", method="build_tool", type=Tool),
        Output(name="context_output", display_name="As Context (JSON)", method="run_context_search", type=Message),
    ]

    # ── Внутренний поиск (общий для обоих выходов) ──
    def _do_search(self, query: str, top_k: int = 6):
        root_path = Path(self.project_root).resolve()
        if str(root_path) not in sys.path:
            sys.path.insert(0, str(root_path))

        from app.search import hybrid_search
        import app.search

        absolute_indexes_dir = root_path / "data" / "processed" / "indexes"
        app.search.INDEXES_DIR = absolute_indexes_dir

        active = []
        if self.search_gost: active.append("gost")
        if self.search_manuals: active.append("manuals")
        if self.search_projects: active.append("projects_docx_clean")

        if not active:
            return []

        return hybrid_search(query.strip(), active_collections=active, top_k=top_k)

    # ── Выход 1: Tool (для агента) ──
    def run_direct_search(self, query: str) -> str:
        try:
            results, _, _ = self._do_search(query, top_k=4)
            if not results:
                return "В локальной базе знаний ничего не найдено."

            parts = []
            for i, chunk in enumerate(results, 1):
                meta = chunk.get("metadata", {})
                src = meta.get("source", "?")
                page = meta.get("page", "?")
                section = meta.get("section", "—")
                title = meta.get("title", "")
                header = f" — {title}" if title else ""
                parts.append(
                    f"--- ФРАГМЕНТ №{i} ---\n"
                    f"Коллекция: {chunk['collection']}\n"
                    f"Документ: {src} (стр. {page})\n"
                    f"Раздел: {section}{header}\n"
                    f"Текст:\n{chunk['text']}\n"
                )
            return "\n".join(parts)
        except Exception as e:
            return f"[ОШИБКА БД] {e}"

    def build_tool(self) -> Tool:
        return Tool(
            name="search_rza_knowledge_base",
            description=(
                "Поиск по базе знаний РЗА: примеры разделов ПЗ, структуры проектов, "
                "нормативные требования ГОСТ, СТО, описания логики схем подстанций."
            ),
            func=self.run_direct_search,
        )

    # ── Выход 2: Message (для пайплайна) ──
    def run_context_search(self) -> Message:
        query = (self.search_query or "").strip()
        if not query:
            return Message(text=json.dumps({"chunks": [], "context_text": "", "search_query": ""}))

        try:
            results, _, _ = self._do_search(query, top_k=6)
        except Exception as e:
            return Message(text=json.dumps({"chunks": [], "context_text": "", "error": str(e)}))

        chunks = []
        context_parts = []
        for i, chunk in enumerate(results, 1):
            meta = chunk.get("metadata", {})
            source = meta.get("source", "?")
            section = meta.get("section", "")
            title = meta.get("title", "")
            text = chunk.get("text", "")
            coll = chunk.get("collection", "")

            header = f"[{i}] {coll} | {source}"
            if section: header += f" | Раздел {section}"
            if title: header += f" — {title}"
            context_parts.append(f"{header}\n{text}")

            chunks.append({
                "num": i, "collection": coll, "source": source,
                "section": section, "title": title,
                "text": text[:500], "ce_score": chunk.get("ce_score"),
            })

        return Message(text=json.dumps({
            "chunks": chunks,
            "context_text": "\n\n---\n\n".join(context_parts),
            "chunks_found": len(chunks),
            "search_query": query,
        }, ensure_ascii=False))
