"""
RZA_Section_Writer — Компонент №2 пайплайна.
Генерирует текст одного раздела Пояснительной Записки на основе
маркеров объекта и релевантных чанков из базы знаний.

Вход: пункт плана, карточка объекта, коллекции.
Выход: текст раздела + список источников.

Жёсткие правила:
- Стиль: ГОСТ Р 2.105-2019, академический.
- Только факты из найденных чанков.
- Если по узлу ничего не найдено → стандартная инженерная заглушка.
- Выдумывать запрещено.
"""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import _call_api
from app.search import hybrid_search

# ============================================================
# СИСТЕМНЫЙ ПРОМПТ ГЕНЕРАТОРА РАЗДЕЛОВ
# ============================================================

SECTION_WRITER_SYSTEM_PROMPT = """Ты — ведущий инженер-проектировщик РЗА, пишущий Пояснительную Записку (ПЗ)
стадии ОТР в соответствии с ГОСТ Р 2.105-2019.

Твоя задача — написать ОДИН раздел ПЗ, используя ТОЛЬКО предоставленные фрагменты документов.

ПРАВИЛА НАПИСАНИЯ:

1. СТИЛЬ: сухой академический, без разговорных оборотов. Без "мы", "нами", "следует отметить".
   Писать от третьего лица или в безличной форме: "предусматривается", "выполняется", "принимается".

2. СТРУКТУРА РАЗДЕЛА:
   - Краткое введение (1-2 предложения) — назначение данного раздела.
   - Основная часть — технические решения, требования, параметры.
   - Обоснование — ссылки на нормативные документы (только те, что в чанках!).

3. ИСТОЧНИКИ ФАКТОВ: ТОЛЬКО предоставленные фрагменты (чанки).
   - Каждое утверждение должно опираться на чанк.
   - Если в чанках нет нужной информации — НЕ ДОДУМЫВАЙ.
   - Ссылайся на номера источников в квадратных скобках: [1], [2].

4. ЗАПРЕТ ГАЛЛЮЦИНАЦИЙ:
   - НЕЛЬЗЯ выдумывать номера ГОСТ, СТО, приказов, если их нет в чанках.
   - НЕЛЬЗЯ придумывать типы защит, не упомянутые в чанках.
   - НЕЛЬЗЯ указывать параметры (уставки, токи, выдержки), если их нет в чанках.
   - НЕЛЬЗЯ сочинять логику работы защит, если она не описана в чанках.

5. ЕСЛИ ИНФОРМАЦИИ НЕТ (пустые чанки или "ничего не найдено"):
   Напиши СТРОГО эту фразу:
   «Параметры и состав защит определяются на этапе РД по согласованию с заводом-изготовителем.»
   После этой фразы НИЧЕГО не дописывай.

6. ОБЪЁМ: не более 3000 символов. Пиши плотно, без воды.
   Каждое предложение должно нести технический смысл.

7. СТРУКТУРА ТЕКСТА: используй подзаголовки при необходимости (например,
   "Основные технические решения", "Требования нормативных документов").

Формат ответа — текст раздела. Без markdown-блоков ```, без JSON-обёрток.
В конце текста — список источников.
"""

# ============================================================
# ЗАГЛУШКА (используется когда чанки пусты)
# ============================================================

FALLBACK_TEXT = (
    "Параметры и состав защит определяются на этапе РД "
    "по согласованию с заводом-изготовителем."
)


# ============================================================
# ПОСТРОЕНИЕ ПОИСКОВОГО ЗАПРОСА ДЛЯ РАЗДЕЛА
# ============================================================

def _build_section_query(
    section_item: dict,
    card: dict,
) -> str:
    """
    Собирает узкий поисковый запрос для конкретного раздела.
    Комбинирует маркеры объекта + тему раздела.
    """
    parts = []

    # Маркеры объекта
    if card.get("voltage_hv"):
        parts.append(card["voltage_hv"])

    if card.get("scheme_hv"):
        parts.append(f"схема {card['scheme_hv']}")

    transformers = card.get("transformers", [])
    for t in transformers:
        if t.get("power"):
            parts.append(str(t["power"]))

    # Тема раздела (самое важное)
    title = section_item.get("title", "")
    if title:
        parts.append(title)

    # Ключевые слова из типа раздела
    stype = section_item.get("section_type", "")
    type_keywords = {
        "protection": "защита релейная ток требования",
        "automation": "автоматика АУВ АВР АЧР",
        "special": "защита автоматика требования",
    }
    if stype in type_keywords:
        parts.append(type_keywords[stype])

    # Особые узлы
    special = card.get("special_nodes", [])
    for node in special:
        if node.lower() in title.lower():
            parts.append(node)

    # Технология
    if card.get("technology"):
        tech = card["technology"]
        if "цифровая" in tech.lower():
            parts.append("МЭК 61850 цифровая подстанция")

    query = " ".join(parts)
    if not query.strip():
        query = title

    return query


# ============================================================
# ФОРМАТИРОВАНИЕ КОНТЕКСТА ДЛЯ LLM
# ============================================================

def _format_chunks_for_writer(results: list) -> tuple[str, list[dict]]:
    """
    Форматирует чанки в контекст для LLM и собирает метаданные источников.
    Возвращает (текст_контекста, список_источников).
    """
    if not results:
        return "", []

    parts = []
    sources = []
    seen_ids = set()

    for i, chunk in enumerate(results, 1):
        meta = chunk.get("metadata", {})
        source = meta.get("source", "Неизвестный источник")
        section = meta.get("section", "—")
        title = meta.get("title", "")
        text = chunk.get("text", "")
        collection = chunk.get("collection", "")

        # Дедупликация по тексту
        text_id = text[:100]
        if text_id in seen_ids:
            continue
        seen_ids.add(text_id)

        header = f"[Источник {i}] Коллекция: {collection}"
        header += f" | Документ: {source}"
        if section:
            header += f" | Раздел: {section}"
        if title:
            header += f" — {title}"

        parts.append(f"{header}\n{text}")

        sources.append({
            "num": i,
            "collection": collection,
            "source": source,
            "section": section,
            "title": title,
            "text_preview": text[:200],
        })

    return "\n\n---\n\n".join(parts), sources


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================

def write_section(
    section_item: dict,
    card: dict,
    model: Optional[str] = None,
    top_k_gost: int = 5,
    top_k_manuals: int = 3,
) -> dict:
    """
    Генерирует текст одного раздела ПЗ.
    Фрагмент ТЗ читается из card["_tz_snippet"] (вложен в Param Extractor).

    Аргументы:
        section_item: пункт плана {"num", "title", "section_type", "sources", "forced"}.
        card: карточка объекта из Param_Extractor.
        model: модель OpenRouter.
        top_k_gost: сколько чанков нормативки искать.
        top_k_manuals: сколько чанков мануалов искать.

    Возвращает:
        {
            "section_num": "...",
            "section_title": "...",
            "text": "...",              # Сгенерированный текст
            "sources": [...],           # Метаданные источников
            "is_fallback": bool,        # True если использована заглушка
            "search_query": "...",      # Поисковый запрос
            "chunks_found": int,        # Сколько чанков найдено
            "raw_response": "...",      # Сырой ответ LLM
        }
    """
    section_num = section_item.get("num", "?")
    section_title = section_item.get("title", "Без названия")
    stype = section_item.get("section_type", "general")
    forced = section_item.get("forced", False)

    # 1. Формируем поисковый запрос
    search_query = _build_section_query(section_item, card)
    print(f"📝 [Section_Writer] Раздел {section_num} «{section_title}»")
    print(f"   🔍 Запрос: '{search_query}'")

    # 2. Поиск в двух коллекциях
    gost_results, _, _ = hybrid_search(
        search_query,
        active_collections=["gost"],
        top_k=top_k_gost,
    )

    manuals_results, _, _ = hybrid_search(
        search_query,
        active_collections=["manuals"],
        top_k=top_k_manuals,
    )

    all_results = (gost_results or []) + (manuals_results or [])

    # Сортируем по ce_score (Cross-Encoder score)
    all_results.sort(key=lambda x: x.get("ce_score", 0), reverse=True)

    # Берём топ-6 для контекста (чтобы не перегружать промпт)
    all_results = all_results[:6]

    context_text, sources = _format_chunks_for_writer(all_results)
    chunks_found = len(all_results)

    # 3. Если чанков нет — сразу заглушка
    if not all_results or not context_text.strip():
        print(f"   ⚠️ Чанков не найдено → заглушка")
        return {
            "section_num": section_num,
            "section_title": section_title,
            "text": FALLBACK_TEXT,
            "sources": [],
            "is_fallback": True,
            "search_query": search_query,
            "chunks_found": 0,
            "raw_response": "",
        }

    # 4. Собираем промпт для LLM
    card_summary = _format_card_summary(card)

    tz_snippet = card.pop("_tz_snippet", "")
    tz_context = ""
    if tz_snippet:
        tz_context = f"\n\n=== ФРАГМЕНТ ТЗ ===\n{tz_snippet[:2000]}\n"

    forced_note = ""
    if forced:
        forced_note = (
            "\n⚠️ Этот раздел добавлен принудительно (особый узел, не имеющий аналогов в базе). "
            "Опиши общие принципы защиты данного узла, если они есть в чанках. "
            "Если нет — используй заглушку."
        )

    user_prompt = (
        f"Напиши раздел «{section_num}. {section_title}» Пояснительной Записки стадии ОТР.\n\n"
        f"=== КАРТОЧКА ОБЪЕКТА ===\n{card_summary}\n"
        f"{tz_context}\n"
        f"=== НОРМАТИВНАЯ БАЗА И ТЕХНИЧЕСКАЯ ДОКУМЕНТАЦИЯ ===\n{context_text}\n"
        f"{forced_note}\n\n"
        f"Напиши текст раздела, строго следуя правилам. "
        f"В конце укажи список источников (только те, что реально есть в контексте)."
    )

    messages = [
        {"role": "system", "content": SECTION_WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw_response = _call_api(
        messages,
        model=model,
        temperature=0.1,
        max_tokens=2500,
    )

    if not raw_response:
        return {
            "section_num": section_num,
            "section_title": section_title,
            "text": FALLBACK_TEXT,
            "sources": sources,
            "is_fallback": True,
            "search_query": search_query,
            "chunks_found": chunks_found,
            "raw_response": "",
        }

    # 5. Проверка: не является ли ответ фактически заглушкой
    is_fallback = FALLBACK_TEXT in raw_response

    return {
        "section_num": section_num,
        "section_title": section_title,
        "text": raw_response.strip(),
        "sources": sources,
        "is_fallback": is_fallback,
        "search_query": search_query,
        "chunks_found": chunks_found,
        "raw_response": raw_response.strip(),
    }


def _format_card_summary(card: dict) -> str:
    """Краткая выжимка карточки для промпта."""
    lines = []
    if card.get("object_name"):
        lines.append(f"Объект: {card['object_name']}")
    if card.get("voltage_hv"):
        lines.append(f"Напряжение ВН: {card['voltage_hv']}")
    if card.get("voltage_lv"):
        lines.append(f"Напряжение НН: {card['voltage_lv']}")
    if card.get("scheme_hv"):
        lines.append(f"Схема ВН: {card['scheme_hv']}")
    if card.get("scheme_lv"):
        lines.append(f"Схема НН: {card['scheme_lv']}")
    transformers = card.get("transformers", [])
    for i, t in enumerate(transformers, 1):
        lines.append(f"Трансформатор {i}: {t.get('qty', '?')}×{t.get('power', '?')}")
    if card.get("transformer_type"):
        lines.append(f"Тип трансформатора: {card['transformer_type']}")
    if card.get("technology"):
        lines.append(f"Технология: {card['technology']}")
    special = card.get("special_nodes", [])
    if special:
        lines.append(f"Особые узлы: {', '.join(special)}")
    if card.get("relay_protection_requirements"):
        lines.append(f"Требования к РЗА: {card['relay_protection_requirements'][:300]}")
    return "\n".join(lines)


# ============================================================
# ФОРМАТИРОВАНИЕ РАЗДЕЛА ДЛЯ ВЫВОДА
# ============================================================

def format_section_for_display(result: dict) -> str:
    """Форматирует результат генерации раздела для отображения в UI."""
    lines = [
        f"{'─' * 60}",
        f"  {result['section_num']}. {result['section_title']}",
        f"{'─' * 60}",
        "",
        result["text"],
        "",
        f"{'─' * 60}",
    ]

    if result["is_fallback"]:
        lines.append("⚠️ ЗАГЛУШКА (данные не найдены в базе знаний)")

    lines.append(f"🔍 Запрос: {result['search_query']}")
    lines.append(f"📊 Найдено чанков: {result['chunks_found']}")

    if result["sources"]:
        lines.append("📁 Источники:")
        for s in result["sources"]:
            lines.append(
                f"   [{s['num']}] {s['source']} | "
                f"Раздел {s['section']} | {s['collection']}"
            )

    return "\n".join(lines)


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================

if __name__ == "__main__":
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
    }

    test_section = {
        "num": "2",
        "title": "Защита силового трансформатора 25 МВА",
        "section_type": "protection",
        "sources": [],
        "forced": False,
    }

    print("=" * 60)
    print("ТЕСТ RZA_Section_Writer")
    print("=" * 60)

    result = write_section(test_section, test_card)
    print(format_section_for_display(result))
