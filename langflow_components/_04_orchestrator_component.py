"""04 Orchestrator — циклическая генерация всех разделов.

Canvas: Check2 → [04] → 05
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class OrchestratorComponent(Component):
    display_name = "04 Orchestrator"
    description = "Цикл по разделам плана → генерация каждого → массив разделов"
    icon = "repeat"

    inputs = [
        MessageTextInput(
            name="project_root",
            display_name="Путь к проекту rza_asist",
            value="J:\\Documents\\GitHub\\rza_rag",
        ),
        MessageTextInput(
            name="plan_json",
            display_name="← План ПЗ (JSON)",
            info="От Check2.pass",
        ),
        MessageTextInput(
            name="card_json",
            display_name="← Карточка (JSON)",
            info="От Check1.pass",
        ),
        DataInput(
            name="llm_model",
            display_name="← LLM Model [опц.]",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(name="sections_output", display_name="Разделы →", method="run_orchestrator", type=Message),
    ]

    def run_orchestrator(self) -> Message:
        root = Path(self.project_root).resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._03_section_writer import write_section

        try:
            plan_data = json.loads(self.plan_json or "{}")
            plan = plan_data.get("plan", plan_data if isinstance(plan_data, list) else [])
        except Exception:
            plan = []

        try:
            card_data = json.loads(self.card_json or "{}")
            card = card_data.get("card", card_data)
        except Exception:
            card = {}

        sections = []
        for i, section_item in enumerate(plan):
            num = section_item.get("num", str(i + 1))
            title = section_item.get("title", "")
            print(f"> [{i+1}/{len(plan)}] Раздел {num}. {title}", flush=True)

            result = write_section(section_item, card)
            sections.append({
                "section_num": result["section_num"],
                "section_title": result["section_title"],
                "text": result["text"],
                "sources": result["sources"],
                "is_fallback": result["is_fallback"],
            })

        return Message(text=json.dumps({"sections": sections}, ensure_ascii=False))
