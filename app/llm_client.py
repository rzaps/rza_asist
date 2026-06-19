"""
Клиент для OpenRouter API.
Отправляет контекст и вопрос в LLM, возвращает ответ.
Использует бесплатную модель (по умолчанию Gemini Flash 2.0).
Добавлены кэш запросов и повтор при пустом ответе.
"""

import hashlib
import json
import time
import requests
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    SYSTEM_PROMPT,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT = 90
MAX_RETRIES = 2
RETRY_DELAY = 10

# Простейший кэш в оперативной памяти
_cache = {}

def _call_api(messages, model, temperature, max_tokens):
    """Единый вызов OpenRouter API с обработкой ошибок и повторов."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
        "max_tokens": max_tokens or LLM_MAX_TOKENS,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
                return ""
            elif resp.status_code == 429:
                wait = RETRY_DELAY * attempt
                print(f"  ⚠️ Rate limit, жду {wait} сек...")
                time.sleep(wait)
            else:
                print(f"  ⚠️ HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        except requests.exceptions.Timeout:
            print(f"  ⚠️ Таймаут (попытка {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
        except requests.exceptions.ConnectionError:
            print("  ⚠️ Ошибка соединения с OpenRouter.")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return ""


def ask_llm(question, context_text, model=None, temperature=None, max_tokens=None,
            allow_retry=True):
    if not OPENROUTER_API_KEY:
        return "❌ Ошибка: не задан OPENROUTER_API_KEY в .env"

    # Проверка кэша
    cache_key = hashlib.md5((question + context_text[:500]).encode()).hexdigest()
    if cache_key in _cache:
        return _cache[cache_key]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Контекст из документа:\n---\n{context_text}\n---\n\nВопрос: {question}\n\nОтветь строго по контексту. Если ответа нет — так и скажи. Укажи номера разделов."}
    ]

    answer = _call_api(messages, model, temperature, max_tokens)
    if answer and len(answer) > 20:
        _cache[cache_key] = answer
        return answer

    # Повторная попытка с коротким контекстом
    if allow_retry:
        short_context = "\n\n".join(context_text.split("\n\n")[:5])
        if len(short_context) < len(context_text):
            messages[1]["content"] = f"Контекст из документа:\n---\n{short_context}\n---\n\nВопрос: {question}\n\nОтветь кратко, только факты из контекста. Укажи номера разделов."
            answer = _call_api(messages, model, temperature, max_tokens)
            if answer and len(answer) > 20:
                _cache[cache_key] = answer
                return answer

    fallback = "❌ Не удалось получить ответ от LLM."
    _cache[cache_key] = fallback
    return fallback


if __name__ == "__main__":
    test_ctx = """
[Источник 1] Раздел 4.4.1 — Технические характеристики
Регистратор обеспечивает измерение напряжения переменного тока в диапазоне от 0.7·10⁻⁴ до 1000 В с погрешностью ±0.5%.
"""
    test_q = "Какая погрешность измерения напряжения?"
    print("Тест LLM клиента...")
    print(ask_llm(test_q, test_ctx))