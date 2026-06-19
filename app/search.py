"""
ЕДИНЫЙ МОДУЛЬ ПОИСКА (Унифицированный search.py)
Гибридный поиск с автоопределением приоритетной коллекции, усиленным BM25,
пост-ранжированием по ключевым словам и мультиязычным cross-encoder reranking.
FAISS + BM25 + RRF + гарантированная квота + Русский/Многоязычный Cross-Encoder.
"""

import json
import pickle
import re
import sys
import threading
import numpy as np
import faiss
from pathlib import Path
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi

# Добавляем корень проекта в sys.path для корректных импортов
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    COLLECTION_TYPES, INDEXES_DIR,
    EMBEDDING_MODEL, EMBEDDING_PREFIX_QUERY,
    SEMANTIC_TOP_K, BM25_TOP_K, FINAL_TOP_K, RRF_K, MIN_RELEVANCE_SCORE,
    BOOST_FACTOR, BM25_RRF_WEIGHT, RERANK_TOP_K
)
# Импортируем единую токенизацию, которая использовалась при записи индексов
from app.utils import tokenize

_model = None
_reranker = None
_collections = {}
_lock = threading.Lock()  # Защита от race condition в многопоточном рантайме Langflow

COLLECTION_KEYWORDS = {
    "manuals": ["регистратор", "рп4", "бпд", "бэмп", "руководство", "эксплуатации",
                "терминал", "блок", "подключение", "монтаж", "инструкция", "рэ", "рп"],
    "gost": ["гост", "нтп", "приказ", "сто", "уставка", "схема", "защита", "мтз",
             "дфз", "уров", "требования", "норма", "правила"],
    "projects": ["пс", "подстанция", "проект", "стойленская", "мощность", "трансформатор",
                 "ру", "кв", "мва", "автоматика", "аув"],
    "orders": ["приказ", "распоряжение", "утверждение", "обязать", "фс"],
}

def detect_relevant_collections(query: str, top_n: int = 2):
    query_lower = query.lower()
    scores = {}
    for coll, keywords in COLLECTION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[coll] = score
    if not scores:
        return list(COLLECTION_KEYWORDS.keys())
    sorted_cols = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return sorted_cols[:top_n]

def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model

def get_reranker():
    global _reranker
    if _reranker is None:
        with _lock:
            if _reranker is None:
                _reranker = CrossEncoder('BAAI/bge-reranker-base')
    return _reranker

def get_collection_paths(coll):
    """Синхронизировано со структурой сохранения в index_writer.py"""
    base = INDEXES_DIR / coll
    return {
        "faiss": base / "faiss_index.bin",
        "chunks": base / "chunks.json",
        "bm25": base / "bm25.pkl",
    }

def load_collection(coll):
    """Потокобезопасная загрузка коллекции с детальным логированием."""
    if coll in _collections:
        return _collections[coll]
        
    with _lock:
        if coll in _collections:  # Double-check паттерн
            return _collections[coll]
            
        paths = get_collection_paths(coll)
        
        print(f"[DEBUG] Проверяем пути для коллекции '{coll}':")
        print(f"        FAISS: {paths['faiss']} -> {'Найдено' if paths['faiss'].exists() else 'НЕ НАЙДЕНО'}")
        print(f"        Chunks: {paths['chunks']} -> {'Найдено' if paths['chunks'].exists() else 'НЕ НАЙДЕНО'}")
        
        if not paths["faiss"].exists() or not paths["chunks"].exists():
            print(f"[WARNING] Коллекция '{coll}' пропущена: файлы индекса отсутствуют.")
            _collections[coll] = None
            return None
            
        index = faiss.read_index(str(paths["faiss"]))
        with open(paths["chunks"], "r", encoding="utf-8") as f:
            chunks = json.load(f)
            
        bm25_path = paths["bm25"]
        if bm25_path.exists():
            with open(bm25_path, "rb") as f:
                bm25 = pickle.load(f)
        else:
            bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])
            
        print(f"[LOAD SUCCESS] Успешно загружена коллекция '{coll}':")
        print(f"             Размерность FAISS: {index.ntotal} векторов")
        print(f"             Элементов в chunks.json: {len(chunks)}")
        
        _collections[coll] = {"index": index, "chunks": chunks, "bm25": bm25}
        return _collections[coll]

def semantic_search_in_collection(coll, query, top_k=SEMANTIC_TOP_K):
    data = load_collection(coll)
    if data is None: return []
    model = get_model()
    index = data["index"]
    chunks = data["chunks"]
    q_emb = model.encode([EMBEDDING_PREFIX_QUERY + query])[0].astype(np.float32)
    faiss.normalize_L2(q_emb.reshape(1, -1))
    k = min(top_k, len(chunks))
    if k == 0: return []
    scores, indices = index.search(q_emb.reshape(1, -1), k)
    items = []
    for score, idx in zip(scores[0], indices[0]):
        if 0 <= idx < len(chunks):
            items.append({
                "index": int(idx),
                "score": float(score),
                "method": "semantic",
                "text": chunks[idx]["text"],
                "metadata": chunks[idx]["metadata"],
                "collection": coll,
            })
    return items

def bm25_search_in_collection(coll, query, top_k=BM25_TOP_K):
    data = load_collection(coll)
    if data is None: return []
    chunks = data["chunks"]
    bm25 = data["bm25"]
    scores = bm25.get_scores(tokenize(query))
    k = min(top_k, len(chunks))
    if k == 0: return []
    items = []
    for idx in np.argsort(scores)[::-1][:k]:
        raw_score = float(scores[idx])
        normalized = 1.0 / (1.0 + np.exp(-raw_score / 5.0))
        items.append({
            "index": int(idx),
            "score": normalized,
            "method": "bm25",
            "text": chunks[idx]["text"],
            "metadata": chunks[idx]["metadata"],
            "collection": coll,
        })
    return items

def reciprocal_rank_fusion(sem, bm, k=RRF_K, bm_weight=BM25_RRF_WEIGHT):
    def make_id(item):
        return f"{item['collection']}::{item['index']}"
    scores = {}
    id_to_item = {}
    for rank, item in enumerate(sem, start=1):
        id_ = make_id(item)
        id_to_item[id_] = item
        scores[id_] = scores.get(id_, 0) + 1/(k+rank)
    for rank, item in enumerate(bm, start=1):
        id_ = make_id(item)
        if id_ not in id_to_item:
            id_to_item[id_] = item
        scores[id_] = scores.get(id_, 0) + bm_weight/(k+rank)
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return sorted_ids, scores, id_to_item

def keyword_boost_results(query, results):
    query_terms = set(tokenize(query))
    for r in results:
        text_terms = set(tokenize(r["text"]))
        overlap = len(query_terms & text_terms)
        if overlap > 0:
            r["rrf_score"] = round(r["rrf_score"] * (1 + 0.1 * overlap), 4)
    return sorted(results, key=lambda x: x["rrf_score"], reverse=True)

def rerank_with_cross_encoder(query, candidates, top_k=FINAL_TOP_K):
    if not candidates:
        return candidates
    reranker = get_reranker()
    
    pairs = []
    for c in candidates:
        prefix = c["metadata"].get("prefix", "")
        combined_text = f"{prefix} {c['text']}" if prefix else c["text"]
        pairs.append((query, combined_text))
        
    scores = reranker.predict(pairs)
    
    for c, score in zip(candidates, scores):
        c["ce_score"] = round(float(score), 4)
        
    candidates.sort(key=lambda x: x["ce_score"], reverse=True)
    return candidates[:top_k]

def hybrid_search(query, active_collections=None, top_k=FINAL_TOP_K,
                  boost_collections=None, collection_boost=BOOST_FACTOR):
    if active_collections is None:
        active_collections = list(COLLECTION_TYPES.keys())

    if boost_collections is None:
        boost_collections = detect_relevant_collections(query)
        boost_collections = [c for c in boost_collections if c in active_collections]

    print(f"\n[DEBUG] Вызов hybrid_search")
    print(f"[DEBUG] Активные коллекции: {active_collections}")
    print(f"[DEBUG] Приоритетные коллекции (boost): {boost_collections}")

    per_collection = {}
    for coll in active_collections:
        sem = semantic_search_in_collection(coll, query)
        bm = bm25_search_in_collection(coll, query)
        sorted_ids, rrf_scores, id_to_item = reciprocal_rank_fusion(sem, bm)
        per_collection[coll] = (sorted_ids, rrf_scores, id_to_item)
        print(f"   -> Коллекция '{coll}': FAISS нашел={len(sem)}, BM25 нашел={len(bm)}, Уникальных после RRF={len(sorted_ids)}")

    results = []
    if boost_collections:
        for coll in boost_collections:
            if coll not in per_collection:
                continue
            sorted_ids, rrf_scores, id_to_item = per_collection[coll]
            count = 0
            for id_ in sorted_ids:
                if count >= 5:
                    break
                boosted_score = rrf_scores[id_] * collection_boost
                
                # Фильтрация по минимальному скору (если у тебя в config выставлен 0, пройдут все)
                if boosted_score < MIN_RELEVANCE_SCORE:
                    continue
                    
                item = id_to_item[id_]
                results.append({
                    "index": item["index"],
                    "rrf_score": round(boosted_score, 4),
                    "text": item["text"],
                    "metadata": item["metadata"],
                    "collection": coll,
                })
                count += 1
                
        print(f"[DEBUG] Заполнено из приоритетных квот: {len(results)} чанков")

    all_items = []
    for coll, (sorted_ids, rrf_scores, id_to_item) in per_collection.items():
        for id_ in sorted_ids:
            if rrf_scores[id_] < MIN_RELEVANCE_SCORE:
                continue
                
            item = id_to_item[id_]
            all_items.append({
                "index": item["index"],
                "rrf_score": rrf_scores[id_],
                "text": item["text"],
                "metadata": item["metadata"],
                "collection": coll,
            })
    all_items.sort(key=lambda x: x["rrf_score"], reverse=True)

    existing_keys = {(r["collection"], r["index"]) for r in results}
    for item in all_items:
        if len(results) >= RERANK_TOP_K:
            break
        key = (item["collection"], item["index"])
        if key not in existing_keys:
            results.append({
                "index": item["index"],
                "rrf_score": round(item["rrf_score"], 4),
                "text": item["text"],
                "metadata": item["metadata"],
                "collection": item["collection"],
            })
            existing_keys.add(key)

    print(f"[DEBUG] Итоговый пул перед реранкером: {len(results)} чанков")

    if not results:
        return results, [], []

    # 1. Лексическое пост-ранжирование
    results = keyword_boost_results(query, results)

    # 2. Финальный Cross-Encoder reranking
    results = rerank_with_cross_encoder(query, results, top_k=top_k)
    print(f"[DEBUG] Возвращаем топ-{len(results)} результатов после реранкинга.")

    return results, [], []

def format_context(results):
    parts = []
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        section = meta.get("section", "")
        title = meta.get("title", "")
        ctype = meta.get("type", "")
        coll = r.get("collection", "")
        header = f"[Источник {i}]"
        if coll:
            coll_label = COLLECTION_TYPES.get(coll, coll)
            header += f" ({coll_label})"
        if section:
            header += f" Раздел {section}"
        if title:
            header += f" — {title}"
        if ctype == "warning":
            header += " ⚠️ ПРЕДУПРЕЖДЕНИЕ"
        parts.append(f"{header}\n{r['text']}")
    return "\n\n---\n\n".join(parts)