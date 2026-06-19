"""
RZA_Param_Extractor — Компонент №0 пайплайна.
Извлекает из сырого ТЗ жёсткие маркеры объекта проектирования.

Вход: текст ТЗ (строка любой длины).
Выход: словарь с карточкой объекта. Все поля, которых нет в ТЗ — null.
Галлюцинации запрещены: LLM получает строгий промпт и обязана
возвращать ТОЛЬКО то, что явно присутствует в тексте ТЗ.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import _call_api

# ============================================================
# СИСТЕМНЫЙ ПРОМПТ ЭКСТРАКТОРА
# ============================================================

EXTRACTOR_SYSTEM_PROMPT = """Ты — инженер-проектировщик РЗА, выполняющий разбор Технического задания (ТЗ).

Твоя задача: извлечь из текста ТЗ только те факты, которые ЯВНО указаны в тексте.
Если параметр не упоминается — ставь null. НИЧЕГО НЕ ВЫДУМЫВАЙ.

Формат ответа — только валидный JSON, без комментариев, без markdown-блоков ```.

Обязательные поля для извлечения:
1. object_name — полное наименование объекта (ПС, подстанция). Если не указано — null.
2. voltage_hv — класс напряжения ВН в кВ (число или строка вида "110 кВ"). Если не указано — null.
3. voltage_lv — класс напряжения НН в кВ (число или строка). Если не указано — null.
4. scheme_hv — шифр первичной схемы ВН: "4Н", "5Н", "5АН", "мостик", "одна СШ", "две СШ с обходной" и т.п. Если не указано — null.
5. scheme_lv — описание схемы НН: "две секции с СВ", "одиночная секционированная" и т.п. Если не указано — null.
6. transformers — массив объектов [{power, qty}]. power — мощность в МВА/МВт. Если не указано — [].
7. transformer_type — тип трансформатора: "двухобмоточный", "трёхобмоточный", "автотрансформатор", "с РПН". Если не указано — null.
8. technology — тип технологии ПС: "цифровая ПС МЭК 61850", "классическая ПС", "цифровая (IEC 61850)" или null.
9. special_nodes — массив строк: особые узлы (БСК, УШР, СТК, ВПТ, КРУЭ и др.). Если нет — [].
10. relay_protection_requirements — текстовый фрагмент с требованиями к РЗА из ТЗ. Если нет отдельного раздела — null.
11. design_stage — стадия проектирования: "ОТР", "П", "РД". Если не указано — null.
12. additional_notes — прочие важные особенности, упомянутые в ТЗ. Если нет — null.

ВАЖНО: Не извлекай значения по контексту или по догадке.
Например, если сказано "трансформаторы 25 МВА" без указания количества — qty ставь null.
Если схема не названа шифром, но описана словами — извлеки описание как есть.
"""

# ============================================================
# ОБЯЗАТЕЛЬНЫЕ ПОЛЯ (для валидации)
# ============================================================

REQUIRED_FIELDS = [
    "object_name",
    "voltage_hv",
    "scheme_hv",
    "transformers",
]

OPTIONAL_FIELDS = [
    "voltage_lv",
    "scheme_lv",
    "transformer_type",
    "technology",
    "special_nodes",
    "relay_protection_requirements",
    "design_stage",
    "additional_notes",
]

# Дефолтный шаблон (пустая карточка)
EMPTY_CARD = {
    "object_name": None,
    "voltage_hv": None,
    "voltage_lv": None,
    "scheme_hv": None,
    "scheme_lv": None,
    "transformers": [],
    "transformer_type": None,
    "technology": None,
    "special_nodes": [],
    "relay_protection_requirements": None,
    "design_stage": None,
    "additional_notes": None,
}


# ============================================================
# ИЗВЛЕЧЕНИЕ JSON ИЗ ОТВЕТА LLM
# ============================================================

def _extract_json_from_response(text: str) -> Optional[dict]:
    """Пытается вытащить JSON из ответа модели (с учётом markdown-блоков)."""
    if not text:
        return None

    # Попытка 1: чистый JSON
    text_stripped = text.strip()
    if text_stripped.startswith("{") and text_stripped.endswith("}"):
        try:
            return json.loads(text_stripped)
        except json.JSONDecodeError:
            pass

    # Попытка 2: JSON внутри ```json ... ``` или ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Попытка 3: найти первую { и последнюю }
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================

def validate_card(card: dict) -> tuple[bool, list[str]]:
    """
    Проверяет карточку объекта на заполненность обязательных полей.
    Возвращает (валидна, список_проблем).
    """
    problems = []

    for field in REQUIRED_FIELDS:
        value = card.get(field)
        if value is None or value == [] or value == "":
            problems.append(f"⚠️ Поле '{field}' не заполнено (null или пустое)")

    # Дополнительные проверки
    if card.get("transformers") and isinstance(card["transformers"], list):
        for i, t in enumerate(card["transformers"]):
            if not isinstance(t, dict):
                problems.append(f"⚠️ transformers[{i}] — не объект")
                continue
            if "power" not in t or t["power"] is None:
                problems.append(f"⚠️ transformers[{i}] — не указана мощность")
            if "qty" not in t or t["qty"] is None:
                problems.append(f"⚠️ transformers[{i}] — не указано количество")

    return len(problems) == 0, problems


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================

def extract_params(
    tz_text: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    """
    Извлекает маркеры объекта из текста ТЗ.

    Аргументы:
        tz_text: полный текст Технического задания.
        model: модель OpenRouter (None = авто).
        temperature: температура (None = 0.1, почти детерминировано).
        max_tokens: макс. токенов ответа (None = 2000).

    Возвращает:
        {
            "card": {...},            # Карточка объекта
            "valid": bool,            # Все ли обязательные поля заполнены
            "problems": [...],        # Список проблем валидации
            "raw_response": "...",    # Сырой ответ LLM (для отладки)
            "tz_length": int,         # Длина исходного ТЗ в символах
        }
    """
    if not tz_text or not tz_text.strip():
        return {
            "card": EMPTY_CARD.copy(),
            "valid": False,
            "problems": ["❌ Текст ТЗ пуст"],
            "raw_response": "",
            "tz_length": 0,
        }

    tz_text = tz_text.strip()

    # Если ТЗ очень длинное — берём первые 15000 символов
    # (модель всё равно не осилит больше в одном промпте)
    tz_snippet = tz_text[:15000]
    truncated = len(tz_text) > 15000

    user_prompt = (
        "Извлеки из следующего Технического задания параметры объекта "
        "в формате JSON согласно инструкции.\n\n"
        "=== ТЕКСТ ТЗ ===\n"
        f"{tz_snippet}"
    )
    if truncated:
        user_prompt += "\n\n(Текст ТЗ обрезан до первых 15000 символов)"

    messages = [
        {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw_response = _call_api(
        messages,
        model=model,
        temperature=temperature if temperature is not None else 0.1,
        max_tokens=max_tokens or 2000,
    )

    if not raw_response:
        return {
            "card": EMPTY_CARD.copy(),
            "valid": False,
            "problems": ["❌ LLM не вернула ответ (ошибка API или таймаут)"],
            "raw_response": raw_response,
            "tz_length": len(tz_text),
        }

    extracted = _extract_json_from_response(raw_response)

    if extracted is None:
        return {
            "card": EMPTY_CARD.copy(),
            "valid": False,
            "problems": ["❌ Не удалось извлечь JSON из ответа LLM. Ответ приложен."],
            "raw_response": raw_response,
            "tz_length": len(tz_text),
        }

    # Мержим с пустой карточкой — чтобы гарантировать все поля
    card = EMPTY_CARD.copy()
    card.update(extracted)

    valid, problems = validate_card(card)

    return {
        "card": card,
        "valid": valid,
        "problems": problems,
        "raw_response": raw_response,
        "tz_length": len(tz_text),
    }


# ============================================================
# ФОРМАТИРОВАНИЕ ДЛЯ ВЫВОДА ИНЖЕНЕРУ (Точка контроля №1)
# ============================================================

def format_card_for_review(result: dict) -> str:
    """
    Форматирует карточку объекта в читаемый вид для показа инженеру
    на точке контроля №1.
    """
    card = result["card"]
    lines = [
        "╔══════════════════════════════════════════╗",
        "║   📋 КАРТОЧКА ОБЪЕКТА (проверьте!)      ║",
        "╠══════════════════════════════════════════╣",
    ]

    def _fmt(val):
        if val is None or val == [] or val == "":
            return "❓ не указано"
        return str(val)

    lines.append(f"║ Объект:       {_fmt(card['object_name'])}")
    lines.append(f"║ Напряжение ВН: {_fmt(card['voltage_hv'])}")
    lines.append(f"║ Напряжение НН: {_fmt(card['voltage_lv'])}")
    lines.append(f"║ Схема ВН:      {_fmt(card['scheme_hv'])}")
    lines.append(f"║ Схема НН:      {_fmt(card['scheme_lv'])}")

    transformers = card.get("transformers", [])
    if transformers:
        for i, t in enumerate(transformers, 1):
            power = t.get("power", "?")
            qty = t.get("qty", "?")
            lines.append(f"║ Трансформатор {i}: {qty}×{power}")
    else:
        lines.append("║ Трансформаторы: ❓ не указаны")

    lines.append(f"║ Тип тр-ра:    {_fmt(card['transformer_type'])}")
    lines.append(f"║ Технология:   {_fmt(card['technology'])}")

    special = card.get("special_nodes", [])
    lines.append(f"║ Особые узлы:  {', '.join(special) if special else '❓ нет'}")

    lines.append(f"║ Стадия:       {_fmt(card['design_stage'])}")
    lines.append(f"║ Требования РЗА: {'✓ указаны' if card.get('relay_protection_requirements') else '❓ нет'}")
    lines.append(f"║ Примечания:   {_fmt(card['additional_notes'])}")

    lines.append("╚══════════════════════════════════════════╝")

    if result["problems"]:
        lines.append("\n⚠️ Обнаружены проблемы:")
        for p in result["problems"]:
            lines.append(f"  {p}")

    if result["tz_length"] > 15000:
        lines.append("\n⚠️ ТЗ было обрезано до 15000 символов.")

    return "\n".join(lines)


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================

if __name__ == "__main__":
    # Тест с коротким примером ТЗ
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
    print("ТЕСТ RZA_Param_Extractor")
    print("=" * 60)

    result = extract_params(test_tz)

    print(format_card_for_review(result))
    print(f"\nВалидна: {result['valid']}")
    print(f"\nСырой ответ LLM:\n{result['raw_response'][:500]}")
