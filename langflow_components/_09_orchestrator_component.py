"""Кастомный компонент Langflow: RZA_Orchestrator (04).

Центральный диспетчер пайплайна.
Принимает план → циклически вызывает Section Writer для каждого раздела
→ отдаёт массив разделов в Docx Assembler.
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class OrchestratorComponent(Component):
    display_name = "04 Orchestrator"
    description = "Диспетчер пайплайна: цикл по разделам плана → вызов Section Writer для каждого."
    icon = "repeat"

    inputs = [
        MessageTextInput(
            name="plan_json",
            display_name="План ПЗ (JSON-массив)",
            info="JSON-массив разделов из Plan Builder",
        ),
        MessageTextInput(
            name="card_json",
            display_name="Карточка объекта (JSON)",
        ),
        MessageTextInput(
            name="tz_text",
            display_name="Текст ТЗ",
            required=False,
        ),
        DataInput(
            name="llm_model",
            display_name="LLM Model",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(
            name="sections_output",
            display_name="Массив разделов",
            method="run_orchestrator",
            type=Message,
        ),
    ]

    def run_orchestrator(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._03_section_writer import write_section

        try:
            plan = json.loads(self.plan_json or "[]")
        except (json.JSONDecodeError, TypeError):
            plan = []

        try:
            card_data = json.loads(self.card_json or "{}")
            card = card_data.get("card", card_data)
        except (json.JSONDecodeError, TypeError):
            card = {}

        tz = self.tz_text or ""

        sections = []
        for section_item in plan:
            result = write_section(section_item, card, tz_text=tz if tz else None)
            sections.append({
                "section_num": result["section_num"],
                "section_title": result["section_title"],
                "text": result["text"],
                "sources": result["sources"],
                "is_fallback": result["is_fallback"],
            })

        payload = json.dumps({"sections": sections}, ensure_ascii=False)
        return Message(text=payload)
