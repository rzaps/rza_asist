"""Кастомный компонент Langflow: RZA_Param_Extractor (01)."""

import sys
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class ParamExtractorComponent(Component):
    display_name = "01 Param Extractor"
    description = "Извлекает 12 маркеров объекта из сырого ТЗ. Строгий JSON, без галлюцинаций."
    icon = "search"

    inputs = [
        MessageTextInput(
            name="tz_text",
            display_name="Текст ТЗ",
            info="Полный текст Технического задания",
        ),
        DataInput(
            name="llm_model",
            display_name="LLM Model (из Роутера)",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(name="card_output", display_name="Карточка объекта", method="run_extract", type=Message),
    ]

    def run_extract(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._01_param_extractor import extract_params

        tz = self.tz_text or ""
        result = extract_params(tz)

        # Вкладываем фрагмент ТЗ в карточку — дальше по пайплайну tz_text не передаётся отдельно
        import json
        card = result["card"]
        card["_tz_snippet"] = tz[:3000] if tz else ""

        payload = json.dumps({
            "card": card,
            "valid": result["valid"],
            "problems": result["problems"],
        }, ensure_ascii=False)

        return Message(text=payload)
