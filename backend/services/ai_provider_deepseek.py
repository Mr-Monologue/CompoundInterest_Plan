"""v1.0 DeepSeek AI Provider — OpenAI-compatible API."""
import os, json, hashlib, time
from urllib.request import Request, urlopen

API_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEFAULT_MODEL = "deepseek-v4-pro"
TIMEOUT = 30
MAX_RETRIES = 2
_cache = {}

def chat_completion(messages: list, model: str = DEFAULT_MODEL, json_mode: bool = True, temperature: float = 0.0):
    msg_hash = hashlib.md5(json.dumps(messages, sort_keys=True, default=str).encode()).hexdigest()[:16]
    ck = f"{model}:{msg_hash}"
    if ck in _cache: return _cache[ck]
    if not API_KEY: raise ValueError("DEEPSEEK_API_KEY not set")
    body = json.dumps({"model":model,"messages":messages,"temperature":temperature,"response_format":{"type":"json_object"} if json_mode else None}).encode()
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(f"{API_BASE}/chat/completions", data=body, headers={"Authorization":f"Bearer {API_KEY}","Content-Type":"application/json"})
            r = urlopen(req, timeout=TIMEOUT)
            result = json.loads(r.read())
            content = result["choices"][0]["message"]["content"]
            parsed = json.loads(content) if json_mode else content
            _cache[ck] = parsed
            return parsed
        except Exception:
            if attempt == MAX_RETRIES: raise
            time.sleep(1 * (attempt + 1))