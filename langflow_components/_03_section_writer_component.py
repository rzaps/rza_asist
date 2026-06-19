"""03 Section Writer — генерация одного раздела ПЗ (вызывается из 04)."""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class SectionWriterComponent(Component):
    display_name = "03 Section Writer"
    description = "1 раздел ПЗ из FAISS-чанков (вызывается из 04, не на canvas)"
    icon = "pen"

    inputs = [
        MessageTextInput(
            name="project_root",
            display_name="Путь к проекту rza_asist",
            value="J:\\Documents\\GitHub\\rza_rag",
        ),
        MessageTextInput(
            name="section_json",
            display_name="← Пункт плана (JSON)",
        ),
        MessageTextInput(
            name="card_json",
            display_name="← Карточка объекта (JSON)",
        ),
        MessageTextInput(
            name="faiss_context_json",
            display_name="← FAISS Context (JSON)",
        ),
        DataInput(
            name="llm_model",
            display_name="← LLM Model [опц.]",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(name="section_output", display_name="Текст раздела →", method="run_section", type=Message),
    ]

    def run_section(self) -> Message:
        root = Path(self.project_root).resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._03_section_writer import write_section

        try:
            section_item = json.loads(self.section_json or "{}")
        except Exception:
            section_item = {}

        try:
            card_data = json.loads(self.card_json or "{}")
            card = card_data.get("card", card_data)
        except Exception:
            card = {}

        if self.faiss_context_json:
            try:
                faiss_data = json.loads(self.faiss_context_json)
                card["_faiss_context"] = faiss_data
            except Exception:
                pass

        result = write_section(section_item, card)

        return Message(text=json.dumps({
            "section_num": result["section_num"],
            "section_title": result["section_title"],
            "text": result["text"],
            "sources": result["sources"],
            "is_fallback": result["is_fallback"],
            "chunks_found": result["chunks_found"],
        }, ensure_ascii=False))
