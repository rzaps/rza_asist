"""
Структурный чанкинг: таблицы, списки, формулы как единые блоки.
ОБЕСПЕЧЕНО : Полная автономность от верстки, защита от шлейфа "Содержания"
             и динамический сброс устаревшего контекста разделов (TTL).
ИСПРАВЛЕНО : Overlap считается ДО flush_text() — раньше обнулялся, чанки стыковались встык.
ДОБАВЛЕНО  : Параметр doc_type прокидывается в метаданные и prefix каждого чанка,
             что даёт RAG-слою возможность фильтровать "только ГОСТ" / "только приказы".
"""

import re
from config import CHUNK_SIZE, CHUNK_OVERLAP, MIN_CHUNK_SIZE
from .utils import detect_heading, classify_chunk_type, is_list_item, is_formula_block, estimate_tokens

# Жесткий фильтр отточий (для вырезания строк оглавления)
TOC_DOTS_PATTERN = re.compile(r'\.{3,}|(?:\.\s){3,}')


def build_chunk(text: str, section: str, title: str, source: str,
                page: int, file_hash: str, ctype: str = None,
                doc_type: str = "general") -> dict:
    """Создаёт чанк с полными метаданными и префиксом для эмбеддинга."""
    ctype = ctype or classify_chunk_type(text)
    # Префикс включает [doc_type] — даёт модели эмбеддинга явный семантический сигнал.
    if title:
        prefix = f"[{doc_type}] {source} | Раздел {section} — {title} | {ctype}"
    else:
        prefix = f"[{doc_type}] {source} | {ctype}"
    return {
        "text": text.strip(),
        "metadata": {
            "section": section,
            "title": title,
            "type": ctype,
            "doc_type": doc_type,  # ← НОВОЕ: для фильтрации при ретриве
            "source": source,
            "file_hash": file_hash,
            "page": page,
            "char_count": len(text),
            "token_estimate": estimate_tokens(text),
            "prefix": prefix
        }
    }


def chunk_text(text: str, source: str, page_num: int, file_hash: str,
               prev_section: str = "", prev_title: str = "",
               doc_type: str = "general") -> tuple:
    """
    Разбивает текст страницы на чанки с защитой от протаскивания ложного контекста.

    ИСПРАВЛЕНО: overlap вычисляется ДО flush_text() — иначе current_chunk уже пустой
    и overlap получается "", чанки стыкуются встык без перекрытия.
    """
    paragraphs = _split_into_paragraphs(text)
    chunks = []
    current_chunk = ""

    # ПРЕДОХРАНИТЕЛЬ: Защита от шлейфа Содержания/Введения между страницами
    if prev_title and prev_title.upper() in ["СОДЕРЖАНИЕ", "ОГЛАВЛЕНИЕ", "ВВЕДЕНИЕ"]:
        current_section = ""
        current_title = ""
    else:
        current_section = prev_section
        current_title = prev_title

    list_buffer = []
    formula_buffer = []
    in_table = False

    # Счётчик параграфов для автосброса устаревшего контекста (TTL)
    paragraphs_since_heading = 0

    def flush_list():
        nonlocal list_buffer
        if list_buffer:
            combined = "\n".join(list_buffer)
            if len(combined) >= MIN_CHUNK_SIZE:
                chunks.append(build_chunk(combined, current_section, current_title,
                                          source, page_num, file_hash, "list", doc_type))
            list_buffer = []

    def flush_formula():
        nonlocal formula_buffer
        if formula_buffer:
            combined = "\n".join(formula_buffer)
            if len(combined) >= MIN_CHUNK_SIZE:
                chunks.append(build_chunk(combined, current_section, current_title,
                                          source, page_num, file_hash, "formula", doc_type))
            formula_buffer = []

    def flush_text():
        nonlocal current_chunk
        if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
            chunks.append(build_chunk(current_chunk, current_section, current_title,
                                      source, page_num, file_hash, None, doc_type))
        current_chunk = ""

    for para in paragraphs:
        # 1. Снайперский отстрел оглавлений с точечками
        if TOC_DOTS_PATTERN.search(para):
            continue

        paragraphs_since_heading += 1

        # Авторазрыв шлейфа заголовка по истечении TTL (защита от сквозного зависания)
        if paragraphs_since_heading > 15:
            current_section = ""
            current_title = ""

        section_num, section_title = detect_heading(para)

        # 2. Если встретили блок Содержания внутри текущей страницы
        if section_num is not None and section_title.upper() in ["СОДЕРЖАНИЕ", "ОГЛАВЛЕНИЕ"]:
            flush_list()
            flush_formula()
            flush_text()
            current_section = ""
            current_title = ""
            continue

        # 3. Заголовок таблицы
        if section_num is not None and section_title.startswith("Таблица"):
            flush_list()
            flush_formula()
            flush_text()
            current_section = section_num if section_num else current_section
            current_title = section_title
            current_chunk = para
            in_table = True
            paragraphs_since_heading = 0
            continue

        # 4. Легитимный заголовок раздела/подраздела
        if section_num is not None:
            flush_list()
            flush_formula()
            flush_text()
            current_section = section_num
            current_title = section_title
            current_chunk = ""
            in_table = False
            paragraphs_since_heading = 0

            if len(para) >= 8:
                chunks.append(build_chunk(para, current_section, current_title,
                                          source, page_num, file_hash, "heading", doc_type))
            continue

        # 5. Элементы списков
        if is_list_item(para) and not in_table:
            flush_formula()
            if list_buffer and estimate_tokens("\n".join(list_buffer) + "\n" + para) > CHUNK_SIZE:
                flush_list()
            list_buffer.append(para)
            continue

        # 6. Формулы
        if is_formula_block(para):
            flush_list()
            if formula_buffer and estimate_tokens("\n".join(formula_buffer) + "\n" + para) > CHUNK_SIZE:
                flush_formula()
            formula_buffer.append(para)
            continue

        if formula_buffer and not is_formula_block(para):
            formula_buffer.append(para)
            if len(formula_buffer) >= 3 or estimate_tokens("\n".join(formula_buffer)) > CHUNK_SIZE:
                flush_formula()
            continue

        # 7. Обычный текст
        flush_list()
        if formula_buffer:
            flush_formula()

        candidate = (current_chunk + "\n\n" + para).strip()
        if estimate_tokens(candidate) > CHUNK_SIZE and current_chunk:
            # ИСПРАВЛЕНО: сначала считаем overlap из ЕЩЁ ЖИВОГО current_chunk,
            # потом уже вызываем flush_text() (которая обнуляет current_chunk).
            sentences = re.split(r'(?<=[.!?])\s+', current_chunk)
            overlap = ""
            for s in reversed(sentences):
                if estimate_tokens(s + " " + overlap) > CHUNK_OVERLAP:
                    break
                overlap = s + " " + overlap
            flush_text()
            current_chunk = (overlap.strip() + "\n\n" + para).strip() if overlap else para
            in_table = False
        else:
            current_chunk = candidate

    flush_list()
    flush_formula()
    flush_text()

    return chunks, current_section, current_title


def chunk_tables(tables: list, source: str, section_context: str = "",
                 file_hash: str = "", doc_type: str = "general") -> list:
    """Каждая таблица становится одним чанком."""
    chunks = []
    for table in tables:
        text = table.get("text", "")
        if len(text) < MIN_CHUNK_SIZE:
            continue
        if section_context:
            prefix = f"[{doc_type}] {source} | Раздел {section_context} — {table.get('name', 'Таблица')} | table"
        else:
            prefix = f"[{doc_type}] {source} | {table.get('name', 'Таблица')} | table"
        chunks.append({
            "text": text.strip(),
            "metadata": {
                "section": section_context,
                "title": table.get("name", "Таблица"),
                "type": "table",
                "doc_type": doc_type,
                "source": source,
                "file_hash": file_hash,
                "page": table.get("page", 0),
                "rows": table.get("rows", 0),
                "cols": table.get("cols", 0),
                "char_count": len(text),
                "token_estimate": estimate_tokens(text),
                "prefix": prefix
            }
        })
    return chunks


def _split_into_paragraphs(text: str) -> list:
    """Внутренняя функция разбивки текста на параграфы."""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) >= 5 or len(text) <= 500:
        return parts
    lines = text.split("\n")
    paragraphs = []
    current = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        section_num, _ = detect_heading(stripped)
        if section_num is not None:
            if current:
                paragraphs.append(current)
                current = ""
            paragraphs.append(stripped)
            continue
        if current:
            current += " " + stripped
        else:
            current = stripped
    if current:
        paragraphs.append(current)
    return paragraphs