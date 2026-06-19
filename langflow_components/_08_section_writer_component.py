"""Кастомный компонент Langflow: RZA_Section_Writer (03)."""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class SectionWriterComponent(Component):
    display_name = "03 Section Writer"
    description = "Генерирует текст одного раздела ПЗ строго по чанкам из базы знаний."
    icon = "pen"

    inputs = [
        MessageTextInput(
            name="section_json",
            display_name="Пункт плана (JSON)",
            info='JSON-объект раздела: {"num","title","section_type","sources","forced"}',
        ),
        MessageTextInput(
            name="card_json",
            display_name="Карточка объекта (JSON)",
        ),
        MessageTextInput(
            name="tz_text",
            display_name="Текст ТЗ (опционально)",
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
        Output(name="section_output", display_name="Текст раздела", method="run_section", type=Message),
    ]

    def run_section(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._03_section_writer import write_section

        try:
            section_item = json.loads(self.section_json or "{}")
        except (json.JSONDecodeError, TypeError):
            section_item = {}

        try:
            card_data = json.loads(self.card_json or "{}")
            card = card_data.get("card", card_data)
        except (json.JSONDecodeError, TypeError):
            card = {}

        tz = self.tz_text or ""

        result = write_section(section_item, card, tz_text=tz if tz else None)

        payload = json.dumps({
            "section_num": result["section_num"],
            "section_title": result["section_title"],
            "text": result["text"],
            "sources": result["sources"],
            "is_fallback": result["is_fallback"],
            "chunks_found": result["chunks_found"],
        }, ensure_ascii=False)

        return Message(text=payload)
