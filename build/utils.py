"""
Общие утилиты: токенизация, определение заголовков, классификация чанков,
извлечение текста и таблиц из PDF, расчет хэшей и детекция баз данных.

ИСПРАВЛЕНО (P1): detect_db возвращает (collection, doc_type) — приказы маршрутизируются
                 в коллекцию gost с doc_type="order" для возможности фильтрации при ретриве.
ИСПРАВЛЕНО (P2): classify_chunk_type — больше не помечает как list любой текст с дефисом.
ИСПРАВЛЕНО (P3): is_list_item — убраны лишние бэкслеши в регэкспе (было [\\)\\.], стало [)\.]).
ДОБАВЛЕНО     : Предупреждение о пустых страницах PDF (потенциальные сканы без OCR).
"""

import re
import hashlib
from pathlib import Path

# Попробуем импортировать библиотеки для работы с PDF, чтобы не падать жестко при их отсутствии
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# =====================================================================
# НАСТРОЙКИ И ПАТТЕРНЫ ДЛЯ ДЕТЕКЦИИ СТРУКТУРЫ (РЗА)
# =====================================================================

# Базовые системные паттерны заголовков
SYSTEM_HEADINGS = [
    re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$"),  # Жесткая нумерация (4.1, 1.2.3 и т.д.)
    re.compile(r"^(Введение|Заключение)$", re.IGNORECASE),
    re.compile(r"^(Содержание|Оглавление)$", re.IGNORECASE),
    re.compile(r"^(Приложение\s+[А-ЯA-Z])$", re.IGNORECASE),
    re.compile(r"^(Список\s+сокращений|Обозначения\s+и\s+сокращения|Список\s+литературы)$", re.IGNORECASE),
]

# Семантические маркеры разделов РЗА (если строка начинается с этого - это заголовок)
RZA_KEYWORDS = [
    "защита", "автоматика", "организация цепей", "оперативный ток",
    "центральная сигнализация", "расчет уставок", "технические требования",
    "регистрация аварийных", "управление выключателем", "шкаф зажимов"
]


def detect_heading(text: str) -> tuple:
    """
    Универсальный детектор заголовков.
    Возвращает (section_num, heading_title) или (None, None).
    """
    stripped = text.strip()

    # Заголовок не может быть пустым или слишком длинным (абзац не заголовок)
    if not stripped or len(stripped) > 150:
        return None, None

    # 1. Проверяем системные паттерны (номера разделов, Содержание, Приложения)
    for pattern in SYSTEM_HEADINGS:
        match = pattern.match(stripped)
        if match:
            if len(match.groups()) == 2:
                return match.group(1), match.group(2).strip()
            else:
                return "", match.group(1).strip()

    # Очищаем строку от лишних знаков препинания в конце для анализа фраз
    clean_text = stripped.rstrip(".:,; ")

    # 2. Проверяем семантику РЗА (независимо от регистра в начале строки)
    clean_lower = clean_text.lower()
    if any(clean_lower.startswith(kw) for kw in RZA_KEYWORDS):
        return "", clean_text

    # 3. Проверяем визуальную структуру (КАПС).
    # Если строка целиком в верхнем регистре, состоит из 2-12 слов и не является числом
    words = clean_text.split()
    if clean_text.isupper() and 2 <= len(words) <= 12 and not clean_text.replace(".", "").isdigit():
        return "", clean_text

    return None, None


# =====================================================================
# ФУНКЦИИ ИЗВЛЕЧЕНИЯ ТЕКСТА И ТАБЛИЦ ИЗ PDF
# =====================================================================

def extract_text_from_pdf(pdf_path: str) -> dict:
    """Извлекает текст из PDF постранично с использованием PyMuPDF.
    Предупреждает о пустых страницах (потенциально сканы без OCR)."""
    if fitz is None:
        print("❌ Ошибка: Библиотека PyMuPDF (pymupdf) не установлена!")
        return {}

    pages_data = {}
    try:
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text("text")
                if not text or not text.strip():
                    print(f"   ⚠️ Страница {page_num}: пустой текст (возможно, скан — нужен OCR).")
                pages_data[str(page_num)] = text
    except Exception as e:
        print(f"❌ Ошибка при чтении текста из PDF {pdf_path}: {e}")

    return pages_data


def extract_tables_from_pdf(pdf_path: str) -> list:
    """Извлекает таблицы из PDF постранично с использованием pdfplumber."""
    if pdfplumber is None:
        return []

    captured_tables = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                for t_idx, table in enumerate(tables):
                    if not table or not any(row for row in table if any(cell for cell in row)):
                        continue

                    table_lines = []
                    for row in table:
                        clean_row = [str(cell).replace('\n', ' ').strip() if cell else "" for cell in row]
                        table_lines.append(" | ".join(clean_row))

                    table_text = "\n".join(table_lines)

                    captured_tables.append({
                        "page": page_idx,
                        "name": f"Таблица {t_idx + 1} (Стр. {page_idx})",
                        "text": table_text,
                        "rows": len(table),
                        "cols": len(table[0]) if table else 0
                    })
    except Exception as e:
        print(f"⚠️ Предупреждение при парсинге таблиц из {pdf_path}: {e}")

    return captured_tables


# =====================================================================
# СИСТЕМНЫЕ ФУНКЦИИ (ХЭШИ, ТОКЕНЫ, КЛАССИФИКАЦИЯ)
# =====================================================================

def file_content_hash(file_path: str) -> str:
    """Генерирует стабильный MD5 хэш содержимого файла для кэширования."""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        buf = f.read(65536)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()


def detect_db(filename: str, text_sample: str = "") -> tuple:
    """
    Автоклассификация документа.
    Возвращает кортеж (collection, doc_type):
      - collection: целевая коллекция индекса (gost, manuals, projects_docx_clean, general)
      - doc_type:   семантический тип документа (gost, order, manual, project, general)

    ВАЖНО: Приказы Минэнерго/Ростехнадзора маршрутизируются В КОЛЛЕКЦИЮ gost,
    но с doc_type="order" — для возможности фильтрации при ретриве.
    Это объединяет нормативную базу в одном индексе, сохраняя гранулярность поиска.
    """
    fn = filename.lower()
    tx = text_sample.lower()

    # По имени файла
    if any(x in fn for x in ['гост', 'gost', 'стандарт']):       return "gost", "gost"
    if any(x in fn for x in ['приказ', 'распоряжени', 'order']): return "gost", "order"   # ← объединяем
    if any(x in fn for x in ['руководств', 'manual', 'инструкц', 'рэ', 'рп']): return "manuals", "manual"
    if any(x in fn for x in ['проект', 'project', 'пз', 'отр', 'пояснительн']): return "projects_docx_clean", "project"

    # Резервный анализ по тексту первой страницы
    if any(x in tx for x in ['настоящий стандарт', 'термины и определения']):           return "gost", "gost"
    if any(x in tx for x in ['приказываю', 'в соответствии с приказом']):               return "gost", "order"
    if any(x in tx for x in ['руководство по эксплуатации', 'паспорт изделия']):        return "manuals", "manual"
    if any(x in tx for x in ['пояснительная записка', 'шифр проекта']):                return "projects_docx_clean", "project"

    return "general", "general"


def estimate_tokens(text: str) -> int:
    """Грубая оценка токенов для кириллицы (~1 токен на 2-3 символа)."""
    return len(text) // 2 + 1


def classify_chunk_type(text: str) -> str:
    """
    Классифицирует тип контента в чанке.

    ИСПРАВЛЕНО: раньше `any(marker in text for marker in ['-', '•', '*', '1.'])` помечал
    как list ЛЮБОЙ текст с дефисом или подстрокой "1." — то есть почти весь технический текст.
    Теперь список определяется по доле строк, реально начинающихся с маркера списка.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return "general"

    # Таблица: много строк с разделителем "|"
    if text.count("|") >= len(lines):
        return "table"

    # Список: ≥50% строк начинаются с маркера списка
    list_markers = ('-', '–', '•', '*', '·')
    list_count = sum(
        1 for l in lines
        if l.startswith(list_markers) or re.match(r'^(\d+|[а-яА-Яa-zA-Z])[)\.]', l)
    )
    if list_count / len(lines) >= 0.5:
        return "list"

    # Формула
    if is_formula_block(text):
        return "formula"

    return "general"


def is_list_item(text: str) -> bool:
    """Определяет, является ли строка элементом списка.

    ИСПРАВЛЕНО: в регэкспе были лишние бэкслеши — `r'^(\d+|...)[\\)\\.]'` в raw-строке
    давало класс символов `[\\).]` (с мусорным `\`). Теперь чистый `r'^(\d+|...)[)\.]'`.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] in ['–', '-', '•', '*', '·']:
        return True
    if re.match(r'^(\d+|[а-яА-Яa-zA-Z])[)\.]', stripped):
        return True
    return False


def is_formula_block(text: str) -> bool:
    """Детекция формульных блоков."""
    return bool(re.search(r'[A-ZА-Яa-zа-я]\w*\s*[=≈<>≤≥±]\s*[-+]?\d+', text))


def tokenize(text: str) -> list:
    """Токенизация текста для алгоритма BM25."""
    return [w for w in re.findall(r'\w+', text.lower()) if len(w) > 1]