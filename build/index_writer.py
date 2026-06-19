"""
Атомарная запись FAISS, BM25 и чанков.
Использует единую токенизацию из utils.py.

ИМЯ ФАЙЛА: faiss_index.bin (синхронизировано с index_document.py — раньше было
           расхождение index.faiss vs faiss_index.bin, из-за которого инкрементальное
           обновление молча сбрасывало индекс коллекции до последнего файла).

ДОБАВЛЕНО : Защита от пустого корпуса (BM25Okapi падает на пустом списке).
"""

import json
import pickle
import os
import faiss
import numpy as np
from pathlib import Path
from rank_bm25 import BM25Okapi
from .utils import tokenize


def safe_write_json(data: list, path: Path):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def safe_write_faiss(index: faiss.Index, path: Path):
    tmp = path.with_suffix('.tmp')
    faiss.write_index(index, str(tmp))
    os.replace(tmp, path)


def safe_write_bm25(bm25: BM25Okapi, path: Path):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'wb') as f:
        pickle.dump(bm25, f)
    os.replace(tmp, path)


def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    if embeddings.shape[0] == 0:
        dim = embeddings.shape[1] if embeddings.ndim == 2 else 0
        return faiss.IndexFlatIP(dim)
    faiss.normalize_L2(embeddings)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def build_bm25_index(chunks: list) -> BM25Okapi:
    """Построение BM25 с правильной токенизацией.
    Защита от пустого корпуса — BM25Okapi падает на [] и [[""], ...]."""
    tokenized = [tokenize(c["text"]) for c in chunks]
    tokenized = [t if t else ["__empty__"] for t in tokenized]  # защита от пустых чанков
    if not tokenized:
        tokenized = [["__empty__"]]
    return BM25Okapi(tokenized)


def save_all(chunks: list, embeddings: np.ndarray, collection_dir: Path):
    faiss_index = build_faiss_index(embeddings)
    bm25 = build_bm25_index(chunks)
    safe_write_json(chunks, collection_dir / "chunks.json")
    safe_write_faiss(faiss_index, collection_dir / "faiss_index.bin")
    safe_write_bm25(bm25, collection_dir / "bm25.pkl")