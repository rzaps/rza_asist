"""05 Docx Assembler — сборка всех разделов в .docx.

Canvas: [04] → [05] → Chat Output
Вход:  sections_json (Message) ← 04.sections_output
       card_json (Message)     ← Check1.pass
Выход: docx_path (Message)      → Chat Output
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput
from langflow.schema.message import Message


class DocxAssemblerComponent(Component):
    display_name = "05 Docx Assembler"
    description = "Разделы + карточка → файл .docx (ГОСТ)"
    icon = "file-text"

    inputs = [
        MessageTextInput(
            name="sections_json",
            display_name="← Разделы (JSON)",
            info="От 04.sections_output",
        ),
        MessageTextInput(
            name="card_json",
            display_name="← Карточка (JSON)",
            info="От Check1.pass",
        ),
    ]

    outputs = [
        Output(name="docx_output", display_name="Путь к .docx →", method="run_assemble", type=Message),
    ]

    def run_assemble(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._05_docx_assembler import assemble_docx
        from pipeline._04_orchestrator import PipelineState

        try:
            sec_data = json.loads(self.sections_json or "{}")
            sections = sec_data.get("sections", [])
        except Exception:
            sections = []

        try:
            card_data = json.loads(self.card_json or "{}")
            card = card_data.get("card", card_data)
        except Exception:
            card = {}

        state = PipelineState()
        state.card = card
        state.sections = sections
        state.status = "done"

        output_path = assemble_docx(state)
        return Message(text=f"✅ Документ сохранён: {output_path}")
