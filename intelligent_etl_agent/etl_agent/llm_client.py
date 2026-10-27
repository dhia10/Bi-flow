
from __future__ import annotations

import json
import os
import re
import requests


class OllamaError(RuntimeError):
    pass


def _extract_json_object(text: str) -> dict:
    """
    Accept:
    - pure JSON
    - ```json ... ``` fenced JSON
    - a small amount of accidental prose around one JSON object
    """
    text = text.strip()

    # Markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try the first balanced-looking JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start:end + 1]
        return json.loads(candidate)

    raise json.JSONDecodeError("No JSON object found", text, 0)


class OllamaClient:
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
        self.base_url = (
            base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")

    def is_alive(self, timeout: int = 5) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
            return r.ok
        except requests.RequestException:
            return False

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_schema: dict | None = None,
        timeout: int = 180,
        retries: int = 3,
    ) -> tuple[dict, list[dict]]:
        """
        Returns (parsed_json, debug_attempts).

        Modern Ollama versions can accept a JSON Schema in `format`.
        If a local Ollama build rejects that, we transparently retry with
        format='json'. This keeps the project compatible with more PCs.
        """
        attempts: list[dict] = []
        last_error: Exception | None = None

        for attempt_no in range(1, retries + 1):
            # First try schema-constrained output; later attempts can fall back
            # to ordinary JSON mode for compatibility.
            output_format = json_schema if (json_schema and attempt_no <= 2) else "json"

            repair_instruction = ""
            if attempt_no > 1:
                repair_instruction = (
                    "\n\nIMPORTANT RETRY: Your previous response could not be accepted. "
                    "Return ONE JSON object only. Use only table/column names supplied in "
                    "the context. Do not use markdown, comments, Python, or SQL."
                )

            payload = {
                "model": self.model,
                "stream": False,
                "format": output_format,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt + repair_instruction,
                    },
                ],
                "options": {
                    "temperature": 0,
                    "num_predict": 1800,
                },
            }

            try:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )

                # Some older Ollama versions may reject JSON Schema formatting.
                if response.status_code >= 400 and isinstance(output_format, dict):
                    attempts.append({
                        "attempt": attempt_no,
                        "mode": "json_schema",
                        "http_status": response.status_code,
                        "error": response.text[:1000],
                    })
                    payload["format"] = "json"
                    response = requests.post(
                        f"{self.base_url}/api/chat",
                        json=payload,
                        timeout=timeout,
                    )

                response.raise_for_status()
                body = response.json()
                content = body.get("message", {}).get("content", "")
                parsed = _extract_json_object(content)

                attempts.append({
                    "attempt": attempt_no,
                    "mode": "json_schema" if isinstance(output_format, dict) else "json",
                    "raw_content": content,
                    "parsed": True,
                })
                return parsed, attempts

            except Exception as exc:
                last_error = exc
                attempts.append({
                    "attempt": attempt_no,
                    "mode": "json_schema" if isinstance(output_format, dict) else "json",
                    "parsed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        raise OllamaError(
            f"Ollama failed after {retries} attempts: "
            f"{type(last_error).__name__ if last_error else 'UnknownError'}: {last_error}"
        )
