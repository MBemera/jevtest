"""Minimal OpenRouter client (OpenAI-compatible chat completions with tool calling).

Standard library only. Honours HTTPS_PROXY through urllib's default proxy handling.
"""

import json
import os
import random
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}


class OpenRouterError(Exception):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class OpenRouter:
    def __init__(self, api_key=None, base_url=None, timeout=240, attempts=5):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.attempts = attempts

    def headers(self):
        headers = {"Content-Type": "application/json",
                   "HTTP-Referer": os.environ.get("JEV_APP_URL", "https://github.com/MBemera/jevtest"),
                   "X-Title": os.environ.get("JEV_APP_TITLE", "Jev QA harness")}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def request(self, method, path, payload=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        last_error = None
        for attempt in range(1, self.attempts + 1):
            request = urllib.request.Request(url, data=data, headers=self.headers(), method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                result = json.loads(body) if body.strip() else {}
                if isinstance(result, dict) and result.get("error") and not result.get("choices"):
                    error = result["error"]
                    code = error.get("code") if isinstance(error, dict) else None
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    if isinstance(code, int) and code in RETRY_STATUS and attempt < self.attempts:
                        last_error = OpenRouterError(message, code, body)
                        self.backoff(attempt)
                        continue
                    raise OpenRouterError(f"OpenRouter error {code}: {message}", code, body)
                return result
            except urllib.error.HTTPError as failure:
                body = failure.read().decode("utf-8", "replace")
                message = extract_message(body) or failure.reason
                last_error = OpenRouterError(f"HTTP {failure.code}: {message}", failure.code, body)
                if failure.code in RETRY_STATUS and attempt < self.attempts:
                    self.backoff(attempt, failure.headers.get("Retry-After"))
                    continue
                raise last_error from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as failure:
                last_error = OpenRouterError(f"{type(failure).__name__}: {failure}")
                if attempt < self.attempts:
                    self.backoff(attempt)
                    continue
                raise last_error from None
        raise last_error

    @staticmethod
    def backoff(attempt, retry_after=None):
        try:
            delay = float(retry_after) if retry_after else 0
        except ValueError:
            delay = 0
        time.sleep(min(60.0, max(delay, 2 ** attempt + random.random())))

    def chat(self, payload):
        if not self.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set. Put it in the environment or in a .env file.")
        return self.request("POST", "chat/completions", payload)

    def models(self):
        return self.request("GET", "models").get("data", [])

    def key_info(self):
        return self.request("GET", "key").get("data", {})


def extract_message(body):
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body[:300]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return error.get("message", "")[:500]
    return str(error or body)[:300]


def model_capabilities(models, model_id):
    """Tool and image support as OpenRouter advertises them, or None when unknown."""
    for model in models:
        if model.get("id") == model_id or model.get("canonical_slug") == model_id:
            parameters = set(model.get("supported_parameters") or [])
            modalities = set((model.get("architecture") or {}).get("input_modalities") or [])
            return {"tools": "tools" in parameters, "vision": "image" in modalities,
                    "context": model.get("context_length"), "pricing": model.get("pricing", {}),
                    "name": model.get("name", model_id)}
    return None
