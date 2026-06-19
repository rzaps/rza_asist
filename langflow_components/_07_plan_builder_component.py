"""02 Plan Builder — построение оглавления ПЗ.

Canvas: Check1 → [02] → Check2
Вход:  card_json (Message)         ← Check1.pass
       faiss_context (Message)     ← FAISS.context_output [опционально]
       llm_model (BaseLanguageModel) ← OpenRouter [опционально]
Выход: plan_json (Message)          → Check2
"""

import sys
import json
from pathlib import Path
from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message


class PlanBuilderComponent(Component):
    display_name = "02 Plan Builder"
    description = "Карточка + аналоги → JSON-план разделов ПЗ"
    icon = "list"

    inputs = [
        MessageTextInput(
            name="card_json",
            display_name="← Карточка (JSON)",
            info="От Check1.pass",
        ),
        MessageTextInput(
            name="faiss_context_json",
            display_name="← FAISS Context [опц.]",
            info="От FAISS.context_output — структуры аналогов",
            required=False,
        ),
        DataInput(
            name="llm_model",
            display_name="← LLM Model [опц.]",
            input_types=["BaseLanguageModel"],
            required=False,
        ),
    ]

    outputs = [
        Output(name="plan_output", display_name="План ПЗ →", method="run_plan", type=Message),
    ]

    def run_plan(self) -> Message:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from pipeline._02_plan_builder import build_plan

        try:
            data = json.loads(self.card_json or "{}")
            card = data.get("card", data)
        except Exception:
            card = {}

        # FAISS-контекст от отдельного узла (если подключен)
        if self.faiss_context_json:
            try:
                faiss_data = json.loads(self.faiss_context_json)
                card["_faiss_structures"] = faiss_data.get("chunks", [])
            except Exception:
                pass

        result = build_plan(card)

        return Message(text=json.dumps({
            "plan": result["plan"],
            "search_query": result["search_query"],
            "sources_found": result["sources_found"],
        }, ensure_ascii=False))
