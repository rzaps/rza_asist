"""
Вспомогательные функции для RAG-приложения.
Загрузка, очистка, форматирование, работа с файлами.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from config import (
    CHUNKS_PATH,
    METADATA_PATH,
    PAGES_TEXT_PATH,
    TABLES_PATH,
    EXTRACTED_DIR,
)


# ============================================================
# ЗАГРУЗКА ДАННЫХ
# ============================================================

def load_json(path):
    """
    Загружает JSON-файл. Возвращает словарь/список или None при ошибке.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ Ошибка загрузки {path}: {e}")
        return None


def get_db_stats():
    """
    Возвращает статистику базы знаний для отображения в интерфейсе.
    """
    stats = load_json(METADATA_PATH)
    if not stats:
        return {
            "total_chunks": 0,
            "total_sections": 0,
            "total_characters": 0,
            "source_file": "—",
            "embedding_model": "—",
        }

    return {
        "total_chunks": stats.get("total_chunks", 0),
        "total_sections": stats.get("total_sections", 0),
        "total_characters": stats.get("total_characters", 0),
        "avg_chunk_size": stats.get("avg_chunk_size_chars", 0),
        "source_file": stats.get("source_file", "—"),
        "embedding_model": stats.get("embedding_model", "—"),
        "type_distribution": stats.get("type_distribution", {}),
        "created_at": stats.get("created_at", "—"),
    }


def is_db_ready():
    """
    Проверяет, готова ли база знаний к использованию.
    """
    return (
        os.path.exists(CHUNKS_PATH) and
        os.path.exists(METADATA_PATH)
    )


# ============================================================
# ОЧИСТКА ТЕКСТА
# ============================================================

def clean_text(text):
    """
    Очищает текст от артефактов OCR и лишних пробелов.
    """
    # Убираем множественные пробелы
    text = re.sub(r"[ \t]+", " ", text)
    # Убираем множественные переносы строк
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Убираем строки из одних спецсимволов
    text = re.sub(r"^[_\-\=]{3,}$", "", text, flags=re.MULTILINE)
    # Убираем одиночные буквы на строке (мусор OCR)
    text = re.sub(r"^\s*[a-zA-Zа-яА-Я]\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def truncate_text(text, max_chars=500):
    """
    Обрезает текст до max_chars символов, добавляя многоточие.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def highlight_keywords(text, query, tag_start="**", tag_end="**"):
    """
    Подсвечивает слова из запроса в тексте (для отображения результатов).
    """
    if not query:
        return text

    words = set(re.findall(r"\w+", query.lower()))
    result = text

    for word in words:
        if len(word) < 3:
            continue
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        result = pattern.sub(f"{tag_start}{word}{tag_end}", result)

    return result


# ============================================================
# ФОРМАТИРОВАНИЕ
# ============================================================

def format_timestamp(ts=None):
    """
    Возвращает текущую дату/время в читаемом формате.
    """
    if ts is None:
        ts = datetime.now()
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def format_file_size(size_bytes):
    """
    Форматирует размер файла в читаемый вид.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def get_file_info(path):
    """
    Возвращает информацию о файле: размер, дата изменения.
    """
    if not os.path.exists(path):
        return None
    stat = os.stat(path)
    return {
        "size": format_file_size(stat.st_size),
        "modified": format_timestamp(datetime.fromtimestamp(stat.st_mtime)),
        "name": os.path.basename(path),
    }


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================

def validate_api_key():
    """
    Проверяет наличие и формат ключа OpenRouter.
    """
    from config import OPENROUTER_API_KEY

    if not OPENROUTER_API_KEY:
        return False, "Ключ OpenRouter не задан в .env"
    if not OPENROUTER_API_KEY.startswith("sk-or-"):
        return False, "Ключ OpenRouter имеет неверный формат (должен начинаться с sk-or-)"
    return True, "OK"


def validate_query(query):
    """
    Проверяет корректность поискового запроса.
    """
    if not query or not query.strip():
        return False, "Пустой запрос"
    if len(query.strip()) < 3:
        return False, "Запрос слишком короткий (минимум 3 символа)"
    if len(query) > 1000:
        return False, "Запрос слишком длинный (максимум 1000 символов)"
    return True, "OK"


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Utils — проверка функций")
    print("=" * 60)

    # Проверка базы
    ready = is_db_ready()
    print(f"База готова: {ready}")

    if ready:
        stats = get_db_stats()
        print(f"Чанков:     {stats['total_chunks']}")
        print(f"Разделов:   {stats['total_sections']}")
        print(f"Модель:     {stats['embedding_model']}")
        print(f"Типы:       {stats['type_distribution']}")

    # Проверка ключа
    api_ok, api_msg = validate_api_key()
    print(f"\nOpenRouter:  {api_msg}")

    # Тест запроса
    test_query = "напряжение питания"
    ok, msg = validate_query(test_query)
    print(f"Запрос '{test_query}': {msg}")

    # Тест подсветки
    text = "Регистратор обеспечивает измерение напряжения переменного тока от 0.7 В до 1000 В."
    highlighted = highlight_keywords(text, "напряжение переменного тока")
    print(f"\nПодсветка: {highlighted}")