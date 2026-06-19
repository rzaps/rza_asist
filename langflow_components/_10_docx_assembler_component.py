"""Кастомный компонент Langflow: RZA_Docx_Assembler (05).

Собирает все разделы в документ .docx с форматированием по ГОСТ.
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput
from langflow.schema.message import Message


class DocxAssemblerComponent(Component):
    display_name = "05 Docx Assembler"
    description = "Сборка всех разделов в .docx: титул, оглавление, форматирование ГОСТ."
    icon = "file-text"

    inputs = [
        MessageTextInput(
            name="sections_json",
            display_name="Массив разделов (JSON)",
            info='JSON: {"sections": [...]} — от Оркестратора',
        ),
        MessageTextInput(
            name="card_json",
            display_name="Карточка объекта (JSON)",
        ),
    ]

    outputs = [
        Output(
            name="docx_path_output",
            display_name="Путь к .docx",
            method="run_assemble",
            type=Message,
        ),
    ]

    def run_assemble(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._05_docx_assembler import assemble_docx
        from pipeline._04_orchestrator import PipelineState

        try:
            sections_data = json.loads(self.sections_json or "{}")
            sections = sections_data.get("sections", [])
        except (json.JSONDecodeError, TypeError):
            sections = []

        try:
            card_data = json.loads(self.card_json or "{}")
            card = card_data.get("card", card_data)
        except (json.JSONDecodeError, TypeError):
            card = {}

        state = PipelineState()
        state.card = card
        state.sections = sections
        state.status = "done"

        output_path = assemble_docx(state)
        return Message(text=f"Документ сохранён: {output_path}")
