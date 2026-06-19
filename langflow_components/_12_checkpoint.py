"""Кастомный компонент Langflow: Checkpoint (Human-in-the-Loop).

Выводит данные инженеру на экран и пропускает их дальше.
В реальном Langflow canvas: инженер видит вывод, может нажать Stop на canvas'е.
Для полной интерактивности нужен внешний UI (Streamlit).
"""

import json
from langflow.custom import Component
from langflow.io import Output, MessageTextInput
from langflow.schema.message import Message


class CheckpointComponent(Component):
    display_name = "🛑 Checkpoint"
    description = "Точка контроля: выводит данные инженеру, пропускает дальше."
    icon = "alert-triangle"

    inputs = [
        MessageTextInput(
            name="data_json",
            display_name="Данные для проверки (JSON)",
            info="Что показать инженеру",
        ),
        MessageTextInput(
            name="checkpoint_label",
            display_name="Метка (название чека)",
            value="Проверка",
        ),
    ]

    outputs = [
        Output(
            name="approved_output",
            display_name="Данные (утверждено)",
            method="run_checkpoint",
            type=Message,
        ),
        Output(
            name="display_output",
            display_name="На экран",
            method="format_display",
            type=Message,
        ),
    ]

    def run_checkpoint(self) -> Message:
        """Пропускает данные дальше как есть — инженер видит их в display_output."""
        return Message(text=self.data_json or "{}")

    def format_display(self) -> Message:
        """Форматирует данные для вывода инженеру."""
        try:
            data = json.loads(self.data_json or "{}")
        except (json.JSONDecodeError, TypeError):
            data = {"raw": str(self.data_json)[:500]}

        lines = [
            "╔══════════════════════════════════════╗",
            f"║  🛑 КОНТРОЛЬНАЯ ТОЧКА               ║",
            f"║  {self.checkpoint_label or 'Проверка'}",
            "╠══════════════════════════════════════╣",
        ]

        # Карточка
        card = data.get("card", {})
        if card and card.get("object_name"):
            lines.append(f"║ Объект: {card.get('object_name', '?')}")
            lines.append(f"║ ВН: {card.get('voltage_hv', '?')}")
            lines.append(f"║ Схема: {card.get('scheme_hv', '?')}")
            lines.append(f"║ Трансформаторы: {json.dumps(card.get('transformers', []), ensure_ascii=False)}")
            if card.get("special_nodes"):
                lines.append(f"║ Особые узлы: {', '.join(card['special_nodes'])}")
            lines.append(f"║ Валидна: {'✅' if data.get('valid') else '❌'}")

        # План
        plan = data.get("plan", [])
        if plan:
            lines.append("║ План разделов:")
            for item in plan[:10]:
                num = item.get("num", "?")
                title = item.get("title", "")
                forced = " [ПРИНУД.]" if item.get("forced") else ""
                lines.append(f"║  {num}. {title}{forced}")

        lines.append("║")
        lines.append("║ ✅ Если всё верно — поток продолжается")
        lines.append("║ ❌ Если нет — нажми Stop на canvas")
        lines.append("╚══════════════════════════════════════╝")

        return Message(text="\n".join(lines))
