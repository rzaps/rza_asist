"""
RZA_Orchestrator — Компонент №3 пайплайна.
Связывает Param_Extractor → Plan_Builder → Section_Writer
в единый линейный поток с контрольными точками Human-in-the-Loop.

Предназначен для запуска как из консоли, так и из Streamlit/Langflow.
"""

import json
import sys
from pathlib import Path
from typing import Optional, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.param_extractor import extract_params, format_card_for_review
from pipeline.plan_builder import build_plan, format_plan_for_review
from pipeline.section_writer import write_section, format_section_for_display


# ============================================================
# КОЛЛЕКТОР РЕЗУЛЬТАТОВ
# ============================================================

class PipelineState:
    """
    Хранит состояние пайплайна между этапами.
    Передаётся между функциями, доступен для UI.
    """

    def __init__(self):
        self.tz_text: str = ""
        self.card: Optional[dict] = None
        self.card_valid: bool = False
        self.card_problems: list[str] = []
        self.plan: list[dict] = []
        self.sections: list[dict] = []  # Готовые разделы
        self.current_section_index: int = 0
        self.status: str = "idle"  # idle | extracting | extracted | planning | planned | writing | done | stopped
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "card": self.card,
            "card_valid": self.card_valid,
            "card_problems": self.card_problems,
            "plan": self.plan,
            "sections_count": len(self.sections),
            "total_sections": len(self.plan),
            "current_section_index": self.current_section_index,
            "error": self.error,
        }


# ============================================================
# ФУНКЦИИ КОНТРОЛЬНЫХ ТОЧЕК (HUMAN-IN-THE-LOOP)
# ============================================================

# Тип для callback-функции контрольной точки:
# Callable[[str, dict], bool] — получает этап и данные, возвращает True (продолжить) / False (стоп)
CheckpointCallback = Callable[[str, dict], bool]


def default_console_checkpoint(stage: str, data: dict) -> bool:
    """Консольная реализация контрольной точки: запрос y/n."""
    if stage == "card":
        print(format_card_for_review(data))
        if not data.get("valid"):
            print("\n⚠️ Карточка невалидна. Продолжить всё равно?")
        answer = input("\n🛑 [Точка контроля №1] Утвердить карточку? (y/n/редактировать): ").strip().lower()
        if answer == "n":
            return False
        if answer.startswith("р") or answer.startswith("e"):
            print("🔧 Ручное редактирование карточки...")
            print("Введите исправленный JSON (или пустую строку чтобы оставить как есть):")
            new_json = input("> ").strip()
            if new_json:
                try:
                    data["card"].update(json.loads(new_json))
                except json.JSONDecodeError:
                    print("❌ Невалидный JSON, оставляем как есть.")
        return True

    elif stage == "plan":
        print(format_plan_for_review(data))
        answer = input("\n🛑 [Точка контроля №2] Утвердить план? (y/n): ").strip().lower()
        return answer != "n"

    return True


# ============================================================
# ОСНОВНОЙ ПОТОК
# ============================================================

def run_pipeline(
    tz_text: str,
    checkpoint: CheckpointCallback = None,
    model: Optional[str] = None,
    on_section_done: Optional[Callable[[dict], None]] = None,
    on_status_change: Optional[Callable[[PipelineState], None]] = None,
) -> PipelineState:
    """
    Запускает полный пайплайн генерации ПЗ.

    Аргументы:
        tz_text: текст Технического задания.
        checkpoint: функция контрольной точки (None = консольная).
        model: модель OpenRouter (None = авто).
        on_section_done: callback при завершении каждого раздела.
        on_status_change: callback при смене статуса.

    Возвращает:
        PipelineState с полными результатами.
    """
    state = PipelineState()
    state.tz_text = tz_text

    if checkpoint is None:
        checkpoint = default_console_checkpoint

    def _set_status(status: str):
        state.status = status
        if on_status_change:
            on_status_change(state)

    # ─── ЭТАП 1: ИЗВЛЕЧЕНИЕ МАРКЕРОВ ───
    _set_status("extracting")
    print("\n" + "=" * 60)
    print("ЭТАП 1: Извлечение маркеров объекта")
    print("=" * 60)

    extract_result = extract_params(tz_text, model=model)
    state.card = extract_result["card"]
    state.card_valid = extract_result["valid"]
    state.card_problems = extract_result["problems"]

    _set_status("extracted")

    # Точка контроля №1
    if not checkpoint("card", extract_result):
        _set_status("stopped")
        state.error = "Остановлено на точке контроля №1 (карточка не утверждена)"
        return state

    # ─── ЭТАП 2: ПОСТРОЕНИЕ ПЛАНА ───
    _set_status("planning")
    print("\n" + "=" * 60)
    print("ЭТАП 2: Построение плана ПЗ")
    print("=" * 60)

    plan_result = build_plan(
        state.card,
        tz_text=tz_text,
        model=model,
    )
    state.plan = plan_result["plan"]

    if not state.plan:
        _set_status("stopped")
        state.error = "Не удалось построить план — LLM не вернула результат."
        return state

    _set_status("planned")

    # Точка контроля №2
    if not checkpoint("plan", plan_result):
        _set_status("stopped")
        state.error = "Остановлено на точке контроля №2 (план не утверждён)"
        return state

    # ─── ЭТАП 3: ЦИКЛИЧЕСКАЯ ГЕНЕРАЦИЯ РАЗДЕЛОВ ───
    _set_status("writing")
    print("\n" + "=" * 60)
    print(f"ЭТАП 3: Генерация разделов ({len(state.plan)} шт.)")
    print("=" * 60)

    for i, section_item in enumerate(state.plan):
        state.current_section_index = i

        num = section_item.get("num", str(i + 1))
        title = section_item.get("title", "Без названия")
        print(f"\n▶ [{i + 1}/{len(state.plan)}] Раздел {num}. {title}")

        result = write_section(
            section_item,
            state.card,
            model=model,
            tz_text=tz_text,
        )

        state.sections.append(result)

        if on_section_done:
            on_section_done(result)

        # Короткая пауза между вызовами API
        if i < len(state.plan) - 1:
            import time
            time.sleep(1.0)

    _set_status("done")
    print("\n" + "=" * 60)
    print("✅ ПАЙПЛАЙН ЗАВЕРШЁН")
    print("=" * 60)
    print(f"Сгенерировано разделов: {len(state.sections)}/{len(state.plan)}")
    fallback_count = sum(1 for s in state.sections if s.get("is_fallback"))
    if fallback_count:
        print(f"Из них заглушек: {fallback_count}")

    return state


# ============================================================
# СБОРКА ИТОГОВОГО ТЕКСТА
# ============================================================

def assemble_full_text(state: PipelineState) -> str:
    """
    Склеивает все сгенерированные разделы в итоговый текст ПЗ.
    Добавляет титульную информацию и автосодержание.
    """
    if not state.sections:
        return "❌ Нет сгенерированных разделов."

    lines = []

    # Титульная информация
    card = state.card or {}
    lines.append("=" * 70)
    lines.append("ПОЯСНИТЕЛЬНАЯ ЗАПИСКА (ОТР)")
    if card.get("object_name"):
        lines.append(f"Объект: {card['object_name']}")
    if card.get("voltage_hv") or card.get("voltage_lv"):
        v_hv = card.get("voltage_hv", "")
        v_lv = card.get("voltage_lv", "")
        lines.append(f"Класс напряжения: {v_hv}{' / ' + v_lv if v_lv else ''}")
    if card.get("design_stage"):
        lines.append(f"Стадия: {card['design_stage']}")
    lines.append("=" * 70)
    lines.append("")

    # Автосодержание
    lines.append("СОДЕРЖАНИЕ")
    lines.append("-" * 40)
    for section in state.sections:
        num = section.get("section_num", "?")
        title = section.get("section_title", "")
        fallback = " ⚠️" if section.get("is_fallback") else ""
        lines.append(f"{num}. {title}{fallback}")
    lines.append("")
    lines.append("=" * 70)
    lines.append("")

    # Разделы
    for section in state.sections:
        num = section.get("section_num", "?")
        title = section.get("section_title", "")
        text = section.get("text", "")

        lines.append(f"{num}. {title}")
        lines.append("-" * 40)
        lines.append(text)
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def export_to_json(state: PipelineState, output_path: str) -> str:
    """Экспортирует состояние пайплайна в JSON."""
    data = {
        "object_name": (state.card or {}).get("object_name"),
        "card": state.card,
        "plan": state.plan,
        "sections": [
            {
                "num": s["section_num"],
                "title": s["section_title"],
                "text": s["text"],
                "sources": s.get("sources", []),
                "is_fallback": s.get("is_fallback", False),
            }
            for s in state.sections
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return output_path


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК (БЕЗ API — ТОЛЬКО СТРУКТУРА)
# ============================================================

if __name__ == "__main__":
    test_tz = """
    ТЕХНИЧЕСКОЕ ЗАДАНИЕ
    на проектирование ПС 110/10 кВ "Стойленская"

    1. Объект: Подстанция 110/10 кВ "Стойленская".
    2. Класс напряжения: ВН — 110 кВ, НН — 10 кВ.
    3. Схема ВН: 4Н (мостик с выключателями).
    4. Силовые трансформаторы: 2 × 25 МВА, двухобмоточные с РПН.
    5. Схема НН: две секции 10 кВ с секционным выключателем.
    6. Технология: цифровая ПС на базе МЭК 61850.
    7. Особые узлы: БСК 10 кВ.
    8. Стадия: ОТР.
    9. Требования к РЗА: выполнить в соответствии с ПУЭ, СТО 34.01-21-005-2019.
    """

    print("=" * 60)
    print("ТЕСТ RZA_Orchestrator (полный прогон)")
    print("=" * 60)
    print(f"Длина ТЗ: {len(test_tz)} символов")
    print("Запуск пайплайна...\n")

    state = run_pipeline(test_tz)

    if state.status == "done":
        full_text = assemble_full_text(state)
        print("\n" + full_text[:2000])
        if len(full_text) > 2000:
            print(f"\n... (всего {len(full_text)} символов)")

        # Экспорт
        output_dir = Path(__file__).resolve().parent.parent / "output"
        output_dir.mkdir(exist_ok=True)
        json_path = export_to_json(state, str(output_dir / "pz_output.json"))
        print(f"\n📁 JSON экспортирован: {json_path}")
    else:
        print(f"❌ Пайплайн остановлен: {state.error}")
