"""
Создание эмбеддингов с префиксом из метаданных.

Без изменений по функциональности — prefix уже формируется в chunking.build_chunk
и включает [doc_type], что даёт модели явный семантический сигнал о типе документа.
"""

import numpy as np
from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL, EMBEDDING_PREFIX_DOC

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model

def encode_chunks(chunks: list, batch_size: int = 1024) -> np.ndarray:
    """Преобразует чанки в эмбеддинги, добавляя префикс метаданных."""
    model = get_model()
    texts = []
    for c in chunks:
        prefix = c["metadata"].get("prefix", "")
        combined = prefix + " " + c["text"]
        texts.append(EMBEDDING_PREFIX_DOC + combined)
    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_embs = model.encode(batch_texts, show_progress_bar=True)
        all_embs.append(batch_embs)
    return np.vstack(all_embs)