"""Кастомный компонент Langflow: гибридный поиск по базе РЗА (FAISS + BM25 + Reranker)."""

import sys
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, BoolInput
from langchain.tools import Tool


class LocalFaissSearch(Component):
    display_name = "Локальный Поиск FAISS РЗА"
    description = "Инструмент точного гибридного поиска (FAISS + BM25 + Реранкер) по базам РЗА."
    icon = "FAISS"

    inputs = [
        MessageTextInput(
            name="project_root",
            display_name="Путь к корню проекта (rza_rag)",
            value="J:\\Documents\\GitHub\\rza_rag",
        ),
        BoolInput(name="search_gost", display_name="Искать в ГОСТ / ПУЭ", value=True),
        BoolInput(name="search_manuals", display_name="Искать в Мануалах (заводы)", value=True),
        BoolInput(name="search_projects", display_name="Искать в старых Проектах", value=True),
    ]

    outputs = [
        Output(name="tool_output", display_name="As Tool", method="build_tool", type=Tool)
    ]

    def run_direct_search(self, query: str) -> str:
        root_path = Path(self.project_root).resolve()
        venv_packages = root_path / "venv" / "Lib" / "site-packages"

        if str(root_path) not in sys.path:
            sys.path.insert(0, str(root_path))
        if venv_packages.exists() and str(venv_packages) not in sys.path:
            sys.path.insert(0, str(venv_packages))

        print(f"\n📢 [LANGFLOW] Входящий запрос к поиску от Агента: '{query}'",
              file=sys.__stdout__, flush=True)

        try:
            from app.search import hybrid_search
            import app.search

            absolute_indexes_dir = root_path / "data" / "processed" / "indexes"
            app.search.INDEXES_DIR = absolute_indexes_dir

            active_collections = []
            if self.search_gost:
                active_collections.append("gost")
            if self.search_manuals:
                active_collections.append("manuals")
            if self.search_projects:
                active_collections.append("projects")

            if not active_collections:
                return "Ошибка: В настройках компонента поиска не выбрана ни одна коллекция."

            search_query = query.strip()

            results, _, _ = hybrid_search(
                search_query, active_collections=active_collections, top_k=4
            )
            print(f"📊 [LANGFLOW] Найдено чанков после реранкинга: {len(results)}",
                  file=sys.__stdout__, flush=True)

            if not results:
                return "В локальной базе знаний ничего не найдено."

            formatted_chunks = []
            for i, chunk in enumerate(results, 1):
                meta = chunk.get("metadata", {})
                file_name = meta.get("source", meta.get("file_name", "Неизвестный файл"))
                page = meta.get("page", "?")
                section = meta.get("section", "Не указан")
                title = meta.get("title", "")

                header_title = f" — {title}" if title else ""
                chunk_text = (
                    f"--- ФРАГМЕНТ №{i} ---\n"
                    f"Коллекция: {chunk['collection']}\n"
                    f"Документ: {file_name} (Страница: {page})\n"
                    f"Раздел: {section}{header_title}\n"
                    f"Текст фрагмента:\n{chunk['text']}\n"
                )
                formatted_chunks.append(chunk_text)

            return "\n".join(formatted_chunks)

        except Exception as e:
            import traceback
            print(
                f"❌ [LANGFLOW COMPONENT ERROR] Сбой внутри LocalFaissSearch:\n"
                f"{traceback.format_exc()}",
                file=sys.__stdout__, flush=True,
            )
            return (
                "[ОШИБКА БАЗЫ ДАННЫХ] Не удалось выполнить локальный поиск РЗА "
                f"из-за внутреннего сбоя. Описание: {str(e)}"
            )

    def build_tool(self) -> Tool:
        return Tool(
            name="search_rza_knowledge_base",
            description=(
                "Используй этот инструмент ОБЯЗАТЕЛЬНО всегда для поиска конкретных "
                "примеров разделов ПЗ, структуры проектов, нормативных требований ГОСТ, "
                "СТО или описаний логики под конкретные схемы подстанций (мостик, 110-4Н и др.)."
            ),
            func=self.run_direct_search,
        )
