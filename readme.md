# rza_asist

RAG-ассистент для проектирования релейной защиты и автоматики (РЗА) подстанций.

## Что умеет

- **Гибридный поиск** по нормативной базе и проектам: FAISS (семантика) + BM25 (ключевые слова) + Cross-Encoder reranker
- **Умный чанкинг** документов: таблицы, формулы, списки как цельные блоки, автоопределение разделов
- **Индексация** PDF и DOCX с инкрементальным обновлением и защитой от дубликатов
- **Веб-интерфейс** на Streamlit: вопрос-ответ по документам с источниками

## Коллекции

- `gost` — ГОСТы, СТО, приказы (объединённый индекс)
- `manuals` — руководства по эксплуатации, техдокументация на оборудование
- `projects_docx_clean` — проектная документация (пояснительные записки, ПЗ)

## Быстрый старт

```bash
# Установка
pip install -r requirements.txt

# Индексация
python -m build.index_document --all

# Запуск
streamlit run app/main.py
```

## Переменные окружения (.env)

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=google/gemini-2.0-flash-001
```

## Стек

- Python, FAISS, BM25, Cross-Encoder (BGE-reranker-base)
- Streamlit, OpenRouter API
- `python-docx`, `rank-bm25`, `sentence-transformers`
