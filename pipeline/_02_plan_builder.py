"""
RZA_Plan_Builder — Компонент №1 пайплайна.
Строит оглавление Пояснительной Записки на основе маркеров объекта
и структур аналогичных проектов из базы знаний.

Вход: карточка объекта (из Param_Extractor) + коллекция projects.
Выход: JSON-план разделов ПЗ с источниками.
"""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import _call_api
from app.search import hybrid_search

# ============================================================
# СИСТЕМНЫЙ ПРОМПТ ПОСТРОИТЕЛЯ ПЛАНА
# ============================================================

PLAN_BUILDER_SYSTEM_PROMPT = """Ты — ведущий инженер-проектировщик РЗА. Твоя задача — составить оглавление (план)
Пояснительной Записки (ПЗ) стадии ОТР для заданного объекта подстанции.

Ты получаешь:
1. Карточку объекта (маркеры из ТЗ).
2. Оглавления аналогичных проектов из базы знаний.

Твоя задача — собрать итоговый план разделов ПЗ в формате JSON-массива.

Формат ответа — ТОЛЬКО валидный JSON-массив. Без markdown-блоков ```, без комментариев.

Каждый элемент массива — объект:
{
  "num": "1",                        // Номер раздела (строка: "1", "2.1", "2.2" и т.д.)
  "title": "Общие сведения",         // Название раздела
  "section_type": "general",         // Тип: general|protection|automation|special|appendix
  "sources": ["project_A.docx"],     // Список источников-образцов (имена файлов)
  "forced": false                    // true если раздел добавлен принудительно (нет в шаблонах)
}

ПРАВИЛА ФОРМИРОВАНИЯ ПЛАНА:

1. БАЗОВАЯ СТРУКТУРА. В любом проекте ОТР должны быть:
   - "Общие сведения" или "Введение"
   - Разделы по защитам (защита трансформатора, защита ВН, защита НН и т.д.)
   - Разделы по автоматике (АУВ, АВР, АЧР и т.д.)
   - "Заключение" (опционально)
   - Приложения (опционально)

2. УЧЁТ МАРКЕРОВ. Адаптируй план под конкретный объект:
   - Схема 4Н → разделы "Защита линии 110 кВ", "Защита трансформатора"
   - Схема 5Н → добавить разделы по защите СШ, обходного выключателя
   - Два трансформатора → раздел на каждый, если защиты различаются
   - Цифровая ПС → раздел "Цифровая подстанция. Шина процесса и станционная шина"
   - Классическая ПС → раздел "Вторичные цепи. Кабельный журнал"

3. ОСОБЫЕ УЗЛЫ. Если в карточке есть special_nodes (БСК, УШР и т.д.) —
   ПРИНУДИТЕЛЬНО добавь раздел для каждого узла, ДАЖЕ ЕСЛИ его нет в шаблонах-аналогах.
   В поле forced ставь true.

4. ПОРЯДОК. Разделы должны идти в логическом порядке:
   Общие сведения → Защита ВН → Защита трансформатора → Защита НН → Автоматика → Особые узлы → Заключение

5. ИСТОЧНИКИ. Для каждого раздела укажи в sources имена файлов найденных проектов-аналогов,
   которые содержат похожий раздел. Если источников нет — пустой массив [].

6. НУМЕРАЦИЯ. Используй иерархическую нумерацию: "1", "1.1", "1.2", "2", "2.1" и т.д.

7. НЕ ВЫДУМЫВАЙ. Если сомневаешься в необходимости раздела — НЕ добавляй.
   Лучше пропустить, чем выдумать лишний раздел.
"""

# ============================================================
# ПОСТРОЕНИЕ ПОИСКОВОГО ЗАПРОСА ИЗ КАРТОЧКИ
# ============================================================

def _build_search_query(card: dict) -> str:
    """Собирает поисковый запрос из маркеров для поиска аналогичных проектов."""
    parts = []

    if card.get("voltage_hv"):
        parts.append(f"{card['voltage_hv']}")

    if card.get("scheme_hv"):
        parts.append(f"схема {card['scheme_hv']}")

    if card.get("technology"):
        tech = card["technology"]
        if "цифровая" in tech.lower():
            parts.append("цифровая подстанция")
        elif "классическая" in tech.lower():
            parts.append("классическая подстанция")

    transformers = card.get("transformers", [])
    if transformers:
        powers = [str(t.get("power", "")) for t in transformers if t.get("power")]
        if powers:
            parts.append("трансформатор " + " ".join(powers))

    if card.get("scheme_lv"):
        parts.append(card["scheme_lv"])

    special = card.get("special_nodes", [])
    for node in special:
        parts.append(node)

    query = " ".join(parts)
    # Резервный вариант
    if not query.strip():
        query = "пояснительная записка ОТР подстанция"

    return query


# ============================================================
# ИЗВЛЕЧЕНИЕ СТРУКТУР ИЗ РЕЗУЛЬТАТОВ ПОИСКА
# ============================================================

def _extract_structures_from_chunks(search_results: list) -> list[dict]:
    """
    Из найденных чанков извлекает структурированную информацию:
    имя файла, номер раздела, заголовок.
    Возвращает список уникальных структур.
    """
    structures = []
    seen = set()

    for chunk in search_results:
        meta = chunk.get("metadata", {})
        source = meta.get("source", "")
        section = meta.get("section", "")
        title = meta.get("title", "")

        if not section and not title:
            continue

        key = f"{source}::{section}::{title}"
        if key in seen:
            continue
        seen.add(key)

        structures.append({
            "source": source,
            "section": section,
            "title": title,
            "snippet": chunk.get("text", "")[:300],
        })

    return structures


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================

def build_plan(
    card: dict,
    model: Optional[str] = None,
    top_k_sources: int = 8,
) -> dict:
    """
    Строит оглавление ПЗ на основе карточки объекта и поиска аналогов.
    Фрагмент ТЗ читается из card["_tz_snippet"] (вложен в Param Extractor).

    Аргументы:
        card: карточка объекта из Param_Extractor.
        model: модель OpenRouter.
        top_k_sources: сколько чанков проектов искать в базе.

    Возвращает:
        {
            "plan": [...],               # JSON-массив разделов
            "search_query": "...",        # Поисковый запрос
            "sources_found": int,         # Сколько структур-аналогов найдено
            "raw_response": "...",        # Сырой ответ LLM
        }
    """
    # 1. Поиск аналогичных проектов
    search_query = _build_search_query(card)

    print(f"🔍 [Plan_Builder] Ищем аналоги: '{search_query}'")

    search_results, _, _ = hybrid_search(
        search_query,
        active_collections=["projects_docx_clean"],
        top_k=top_k_sources,
    )

    structures = _extract_structures_from_chunks(search_results)

    if not search_results:
        print("⚠️ [Plan_Builder] Аналоги не найдены. План будет построен без образцов.")
        structures_text = "(аналогичные проекты не найдены в базе)"
    else:
        structures_text = "Найденные структуры аналогичных проектов:\n\n"
        for i, s in enumerate(structures, 1):
            structures_text += (
                f"[{i}] {s['source']} | Раздел {s['section']} — {s['title']}\n"
                f"    Фрагмент: {s['snippet'][:200]}\n\n"
            )

    # 2. Формируем промпт для LLM
    card_json = json.dumps(card, ensure_ascii=False, indent=2)

    tz_snippet = card.pop("_tz_snippet", "")
    tz_context = ""
    if tz_snippet:
        tz_context = f"\n\n=== ФРАГМЕНТ ТЗ (для контекста) ===\n{tz_snippet[:3000]}\n"

    user_prompt = (
        "Построй план (оглавление) Пояснительной Записки стадии ОТР для следующего объекта.\n\n"
        f"=== КАРТОЧКА ОБЪЕКТА ===\n{card_json}\n"
        f"{tz_context}\n"
        f"=== СТРУКТУРЫ АНАЛОГОВ ===\n{structures_text}\n\n"
        "На основе карточки объекта и структур аналогов составь JSON-массив разделов ПЗ.\n"
        "Ответ — ТОЛЬКО JSON-массив, без пояснений."
    )

    messages = [
        {"role": "system", "content": PLAN_BUILDER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw_response = _call_api(
        messages,
        model=model,
        temperature=0.1,
        max_tokens=3000,
    )

    # 3. Парсим JSON
    plan = _parse_plan_json(raw_response)

    # 4. Принудительно проверяем special_nodes
    special_nodes = card.get("special_nodes", [])
    if special_nodes:
        plan = _enforce_special_nodes(plan, special_nodes)

    return {
        "plan": plan,
        "search_query": search_query,
        "sources_found": len(structures),
        "raw_response": raw_response or "",
    }


def _parse_plan_json(text: str) -> list[dict]:
    """Парсит JSON-план из ответа LLM."""
    import re

    if not text:
        return []

    text = text.strip()

    # Попытка 1: чистый JSON-массив
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Попытка 2: внутри ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Попытка 3: найти первый [ и последний ]
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


def _enforce_special_nodes(plan: list[dict], special_nodes: list[str]) -> list[dict]:
    """
    Гарантирует, что для каждого special_node есть раздел в плане.
    Если раздела нет — добавляет принудительно с forced=true.
    """
    if not special_nodes:
        return plan

    plan_titles_lower = {item.get("title", "").lower() for item in plan}

    for node in special_nodes:
        node_lower = node.lower()
        # Проверяем, есть ли уже раздел с упоминанием этого узла
        already_covered = any(node_lower in title for title in plan_titles_lower)

        if not already_covered:
            # Находим максимальный номер раздела для вставки
            max_section_num = 0
            for item in plan:
                num = item.get("num", "0")
                try:
                    max_section_num = max(max_section_num, int(num.split(".")[0]))
                except ValueError:
                    pass

            new_num = str(max_section_num + 1) if max_section_num > 0 else str(len(plan) + 1)
            plan.append({
                "num": new_num,
                "title": f"Защита и автоматика {node}",
                "section_type": "special",
                "sources": [],
                "forced": True,
            })

    return plan


# ============================================================
# ФОРМАТИРОВАНИЕ ДЛЯ ВЫВОДА ИНЖЕНЕРУ (Точка контроля №2)
# ============================================================

def format_plan_for_review(result: dict) -> str:
    """
    Форматирует план ПЗ в читаемый вид для показа инженеру
    на точке контроля №2. Под каждым пунктом — источники.
    """
    plan = result.get("plan", [])

    if not plan:
        return "❌ План не построен — LLM не вернула результат."

    lines = [
        "╔════════════════════════════════════════════════╗",
        "║   📑 ПЛАН ПОЯСНИТЕЛЬНОЙ ЗАПИСКИ (ОТР)         ║",
        "╠════════════════════════════════════════════════╣",
    ]

    for item in plan:
        num = item.get("num", "?")
        title = item.get("title", "Без названия")
        stype = item.get("section_type", "general")
        forced = item.get("forced", False)
        sources = item.get("sources", [])

        type_icon = {
            "general": "📄",
            "protection": "🛡️",
            "automation": "⚙️",
            "special": "⚠️",
            "appendix": "📎",
        }.get(stype, "📄")

        forced_mark = " [ПРИНУДИТЕЛЬНО]" if forced else ""

        lines.append(f"║ {type_icon} {num}. {title}{forced_mark}")

        if sources:
            for src in sources[:3]:
                lines.append(f"║    📁 {src}")
        else:
            lines.append(f"║    ⚠️ источники-аналоги не найдены")

    lines.append("╚════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"🔍 Поисковый запрос: '{result.get('search_query', '')}'")
    lines.append(f"📊 Найдено структур-аналогов: {result.get('sources_found', 0)}")

    return "\n".join(lines)


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================

if __name__ == "__main__":
    # Тест с типовой карточкой
    test_card = {
        "object_name": 'ПС 110/10 кВ "Стойленская"',
        "voltage_hv": "110 кВ",
        "voltage_lv": "10 кВ",
        "scheme_hv": "4Н",
        "scheme_lv": "две секции с СВ",
        "transformers": [{"power": "25 МВА", "qty": 2}],
        "transformer_type": "двухобмоточный с РПН",
        "technology": "цифровая ПС МЭК 61850",
        "special_nodes": ["БСК"],
        "relay_protection_requirements": "ПУЭ, СТО 34.01-21-005-2019",
        "design_stage": "ОТР",
        "additional_notes": None,
    }

    print("=" * 60)
    print("ТЕСТ RZA_Plan_Builder")
    print("=" * 60)

    result = build_plan(test_card)
    print(format_plan_for_review(result))

    if result["plan"]:
        print("\nJSON плана:")
        print(json.dumps(result["plan"], ensure_ascii=False, indent=2))
