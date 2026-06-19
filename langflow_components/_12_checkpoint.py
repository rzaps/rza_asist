"""Кастомный компонент Langflow: Checkpoint (Human-in-the-Loop).

Один компонент → два экземпляра на canvas:
  Экземпляр 1: после 01 Param Extractor → проверка карточки
  Экземпляр 2: после 02 Plan Builder → проверка плана

Подключение:
  data_input ← JSON от предыдущего узла
  display_output → Chat Output (инженер читает)
  pass_output → следующий узел (данные едут дальше)
"""

import json
from langflow.custom import Component
from langflow.io import Output, MessageTextInput
from langflow.schema.message import Message


class CheckpointComponent(Component):
    display_name = "🛑 Checkpoint"
    description = "Точка контроля: показать данные инженеру → пропустить дальше."
    icon = "alert-triangle"

    inputs = [
        MessageTextInput(
            name="data_json",
            display_name="← Данные (JSON)",
            info="Что показать инженеру — подключить вывод предыдущего компонента",
        ),
    ]

    outputs = [
        Output(name="display_output", display_name="На экран (Chat Output) →", method="format_display", type=Message),
        Output(name="pass_output", display_name="Данные дальше →", method="run_pass", type=Message),
    ]

    def run_pass(self) -> Message:
        """Пропускает данные дальше как есть."""
        return Message(text=self.data_json or "{}")

    def format_display(self) -> Message:
        """Форматирует данные для вывода инженеру."""
        try:
            data = json.loads(self.data_json or "{}")
        except Exception:
            return Message(text=f"🛑 КОНТРОЛЬНАЯ ТОЧКА\n\n{str(self.data_json)[:1000]}\n\n✅ Если верно — поток продолжается\n❌ Если нет — Stop на canvas")

        lines = ["```", "🛑 КОНТРОЛЬНАЯ ТОЧКА", "=" * 40]

        card = data.get("card", {})
        if card and card.get("object_name"):
            lines.append(f"Объект: {card.get('object_name', '?')}")
            lines.append(f"ВН: {card.get('voltage_hv', '?')}  |  Схема: {card.get('scheme_hv', '?')}")
            tr = card.get("transformers", [])
            if tr:
                for t in tr:
                    lines.append(f"Трансформатор: {t.get('qty','?')}×{t.get('power','?')}")
            if card.get("technology"):
                lines.append(f"Технология: {card['technology']}")
            sn = card.get("special_nodes", [])
            if sn:
                lines.append(f"Особые узлы: {', '.join(sn)}")
            lines.append(f"Валидна: {'✅' if data.get('valid') else '❌ (не все поля)'}")

        plan = data.get("plan", [])
        if plan:
            lines.append("")
            lines.append("План разделов ПЗ:")
            for item in plan:
                num = item.get("num", "?")
                title = item.get("title", "")
                forced = " [ПРИНУД.]" if item.get("forced") else ""
                lines.append(f"  {num}. {title}{forced}")

        lines.append("")
        lines.append("✅ Если верно — идёт дальше автоматически")
        lines.append("❌ Если нет — нажми Stop на canvas'е")
        lines.append("```")

        return Message(text="\n".join(lines))
