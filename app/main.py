"""
Веб-интерфейс RAG-системы на Streamlit.
Поддерживает несколько коллекций документов.
"""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    FINAL_TOP_K,
    OPENROUTER_MODEL,
    SYSTEM_PROMPT,
    COLLECTION_TYPES,
    INDEXES_DIR,
)
from search import hybrid_search, load_collection, format_context
from llm_client import ask_llm
from utils import (
    validate_api_key,
    validate_query,
    truncate_text,
    highlight_keywords,
)


def get_collection_paths(collection_name: str):
    """Возвращает пути к faiss_index.bin и chunks.json для коллекции."""
    base = INDEXES_DIR / collection_name
    return {
        "faiss": base / "faiss_index.bin",
        "chunks": base / "chunks.json",
    }


# ============================================================
# КОНФИГУРАЦИЯ СТРАНИЦЫ
# ============================================================

st.set_page_config(
    page_title="RAG — База знаний",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ
# ============================================================

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "total_queries" not in st.session_state:
    st.session_state.total_queries = 0

if "active_collections" not in st.session_state:
    st.session_state.active_collections = []


# ============================================================
# САЙДБАР
# ============================================================

def render_sidebar():
    """Боковая панель с информацией о коллекциях."""
    st.sidebar.title("📚 База знаний")

    # Проверяем наличие коллекций
    available_collections = []
    for coll_key in COLLECTION_TYPES:
        paths = get_collection_paths(coll_key)
        if paths["chunks"].exists():
            available_collections.append(coll_key)

    if not available_collections:
        st.sidebar.warning("⚠️ База не готова. Запустите индексацию:")
        st.sidebar.code("python build/index_document.py --all", language="bash")
        st.session_state.active_collections = []
        return False

    st.sidebar.success(f"✅ Готово ({len(available_collections)} коллекций)")

    # Выбор коллекций
    st.sidebar.markdown("### 🗂️ Коллекции")
    active_collections = []
    for coll_key, coll_label in COLLECTION_TYPES.items():
        available = coll_key in available_collections
        if st.sidebar.checkbox(
            coll_label,
            value=available,
            key=f"coll_{coll_key}",
            disabled=not available,
        ):
            if available:
                active_collections.append(coll_key)

    st.session_state.active_collections = active_collections

    # Суммарная статистика по выбранным коллекциям
    total_chunks = 0
    total_sections = set()
    total_chars = 0
    type_dist = {}

    for coll in active_collections:
        data = load_collection(coll)
        if data:
            chunks = data["chunks"]
            total_chunks += len(chunks)
            for c in chunks:
                sec = c["metadata"].get("section", "")
                if sec:
                    total_sections.add(sec)
                ctype = c["metadata"].get("type", "general")
                type_dist[ctype] = type_dist.get(ctype, 0) + 1
                total_chars += len(c["text"])

    st.sidebar.markdown("### 📊 Статистика")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("Чанков", total_chunks)
    with col2:
        st.metric("Разделов", len(total_sections))

    st.sidebar.markdown(f"**Символов:** {total_chars:,}".replace(",", " "))

    if type_dist:
        st.sidebar.markdown("### Типы чанков")
        for ctype, count in sorted(type_dist.items()):
            st.sidebar.text(f"  {ctype}: {count}")

    return True


# ============================================================
# ОСНОВНАЯ ОБЛАСТЬ
# ============================================================

def render_chat():
    """Область чата с историей."""
    st.title("💬 Вопросы по документам")

    api_ok, api_msg = validate_api_key()
    if api_ok:
        st.caption(f"🤖 Модель: `{OPENROUTER_MODEL}` | 🟢 API готов")
    else:
        st.caption(f"🔴 {api_msg}")

    st.divider()

    # История чата
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "sources" in msg and msg["sources"]:
                with st.expander("📎 Источники"):
                    for src in msg["sources"]:
                        coll_label = COLLECTION_TYPES.get(src.get("collection", ""), "")
                        section = src.get("section", "—")
                        title = src.get("title", "—")
                        st.markdown(f"**{coll_label} | Раздел {section}** — {title}")
                        st.caption(truncate_text(src.get("text", ""), 300))

    # Поле ввода
    if prompt := st.chat_input("Задайте вопрос по документам..."):
        ok, msg = validate_query(prompt)
        if not ok:
            st.error(msg)
            return

        st.session_state.chat_history.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🔍 Ищу в базе знаний..."):
                results, sem_items, bm25_items = hybrid_search(
                    prompt,
                    active_collections=st.session_state.get("active_collections"),
                )

            if not results:
                response = "❌ В базе знаний не найдено релевантной информации. Попробуйте переформулировать."
                st.markdown(response)
                sources = []
            else:
                st.caption(
                    f"Найдено чанков: {len(results)} "
                    f"(семантика: {len(sem_items)}, BM25: {len(bm25_items)})"
                )

                context = format_context(results)
                with st.spinner("🤖 Генерирую ответ..."):
                    response = ask_llm(prompt, context)

                st.markdown(response)

                sources = [
                    {
                        "section": r["metadata"].get("section", "—"),
                        "title": r["metadata"].get("title", "—"),
                        "text": r.get("text", ""),
                        "collection": r.get("collection", ""),
                    }
                    for r in results
                ]

                with st.expander("📎 Источники (чанки)"):
                    for i, src in enumerate(sources, 1):
                        coll_label = COLLECTION_TYPES.get(src.get("collection", ""), "")
                        section = src.get("section", "—")
                        title = src.get("title", "—")
                        st.markdown(f"**#{i} | {coll_label} | Раздел {section}** — {title}")
                        highlighted = highlight_keywords(
                            src.get("text", "")[:500], prompt, tag_start="**", tag_end="**"
                        )
                        st.markdown(highlighted)
                        st.divider()

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": response,
                "sources": sources,
            })
            st.session_state.total_queries += 1


def render_debug_tab():
    """Вкладка отладки."""
    st.header("🛠️ Отладка")

    st.markdown("### Системный промпт")
    st.code(SYSTEM_PROMPT, language="text")

    st.markdown("### Статистика сессии")
    st.metric("Всего запросов", st.session_state.total_queries)
    st.metric("Сообщений в истории", len(st.session_state.chat_history))

    if st.button("🗑️ Очистить историю чата"):
        st.session_state.chat_history = []
        st.session_state.total_queries = 0
        st.rerun()


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

def main():
    """Главная функция."""
    db_ready = render_sidebar()

    if not db_ready:
        st.title("📚 RAG — База знаний")
        st.info("👈 Запустите индексацию коллекций, как указано в боковой панели.")
        return

    tab1, tab2 = st.tabs(["💬 Чат", "🛠️ Отладка"])

    with tab1:
        render_chat()

    with tab2:
        render_debug_tab()


if __name__ == "__main__":
    main()