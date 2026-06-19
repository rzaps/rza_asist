"""06 Checkpoint — Human-in-the-Loop.

Два экземпляра: после 01 (карточка) и после 02 (план).
Display → Chat Output, Pass → следующий компонент.
"""

import json
from langflow.custom import Component
from langflow.io import Output, MessageTextInput
from langflow.schema.message import Message


class CheckpointComponent(Component):
    display_name = "Checkpoint"
    description = "Точка контроля: показать данные → пропустить дальше."
    icon = "alert-triangle"

    inputs = [
        MessageTextInput(
            name="data_json",
            display_name="← Данные (JSON)",
            info="От предыдущего компонента",
        ),
    ]

    outputs = [
        Output(name="display_output", display_name="На экран →", method="format_display", type=Message),
        Output(name="pass_output", display_name="Данные дальше →", method="run_pass", type=Message),
    ]

    def run_pass(self) -> Message:
        return Message(text=self.data_json or "{}")

    def format_display(self) -> Message:
        try:
            data = json.loads(self.data_json or "{}")
        except Exception:
            return Message(text=f"🛑 КОНТРОЛЬ\n\n{str(self.data_json)[:800]}\n\n✅ Ок → идёт дальше | ❌ → Stop")

        lines = ["🛑 КОНТРОЛЬНАЯ ТОЧКА", "=" * 36]

        card = data.get("card", {})
        if card.get("object_name"):
            lines.append(f"Объект: {card['object_name']}")
            lines.append(f"ВН: {card.get('voltage_hv','?')} | Схема: {card.get('scheme_hv','?')}")
            tr = card.get("transformers", [])
            for t in tr:
                lines.append(f"Тр-р: {t.get('qty','?')}x{t.get('power','?')}")
            if card.get("technology"):
                lines.append(f"Технология: {card['technology']}")
            sn = card.get("special_nodes", [])
            if sn:
                lines.append(f"Особые узлы: {', '.join(sn)}")
            lines.append(f"Валидна: {'✅' if data.get('valid') else '❌'}")

        plan = data.get("plan", [])
        if plan:
            lines.append("")
            lines.append("План разделов:")
            for item in plan:
                n = item.get("num", "?")
                t = item.get("title", "")
                f = " [ПРИНУД.]" if item.get("forced") else ""
                lines.append(f"  {n}. {t}{f}")

        lines.append("")
        lines.append("✅ Верно → продолжается | ❌ → Stop на canvas")
        return Message(text="\n".join(lines))
