"""Кастомный компонент Langflow: RZA_Plan_Builder (02).

Строит JSON-план ПЗ. Может принимать контекст от FAISS Context (опционально).
Если FAISS не подключен — сам делает поиск внутри.
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class PlanBuilderComponent(Component):
    display_name = "02 Plan Builder"
    description = "Строит JSON-план ПЗ. Принимает карточку + FAISS-контекст аналогов."
    icon = "list"

    inputs = [
        MessageTextInput(
            name="card_json",
            display_name="← Карточка объекта (JSON из 01)",
            info="JSON-строка из Param Extractor",
        ),
        MessageTextInput(
            name="faiss_context_json",
            display_name="← FAISS Context (опционально)",
            info="Результат поиска аналогов из FAISS Context. Если не подключен — поиск внутри.",
            required=False,
        ),
        DataInput(
            name="llm_model",
            display_name="← LLM Model",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(name="plan_output", display_name="План ПЗ (JSON) →", method="run_plan", type=Message),
    ]

    def run_plan(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._02_plan_builder import build_plan

        try:
            data = json.loads(self.card_json or "{}")
            card = data.get("card", data)
        except (json.JSONDecodeError, TypeError):
            card = {}

        # Если FAISS-контекст подключен — добавляем в карточку
        if self.faiss_context_json:
            try:
                faiss_data = json.loads(self.faiss_context_json)
                card["_faiss_structures"] = faiss_data.get("chunks", [])
            except (json.JSONDecodeError, TypeError):
                pass

        result = build_plan(card)

        payload = json.dumps({
            "plan": result["plan"],
            "search_query": result["search_query"],
            "sources_found": result["sources_found"],
        }, ensure_ascii=False)

        return Message(text=payload)
