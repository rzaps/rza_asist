"""01 Param Extractor — извлечение маркеров из ТЗ.

Canvas: Chat Input → [01] → Check1
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class ParamExtractorComponent(Component):
    display_name = "01 Param Extractor"
    description = "ТЗ → карточка объекта (12 полей, строгий JSON)"
    icon = "search"

    inputs = [
        MessageTextInput(
            name="project_root",
            display_name="Путь к проекту rza_asist",
            value="J:\\Documents\\GitHub\\rza_rag",
        ),
        MessageTextInput(
            name="tz_text",
            display_name="← ТЗ (текст)",
            info="Полный текст Технического задания",
        ),
        DataInput(
            name="llm_model",
            display_name="← LLM Model [опц.]",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(name="card_output", display_name="Карточка →", method="run_extract", type=Message),
    ]

    def run_extract(self) -> Message:
        root = Path(self.project_root).resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._01_param_extractor import extract_params

        tz = self.tz_text or ""
        result = extract_params(tz)

        card = result["card"]
        card["_tz_snippet"] = tz[:3000]

        return Message(text=json.dumps({
            "card": card,
            "valid": result["valid"],
            "problems": result["problems"],
        }, ensure_ascii=False))
