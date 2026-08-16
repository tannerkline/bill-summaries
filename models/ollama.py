"""Small client for generating legislation summaries through a local Ollama server."""

import logging
import os
from typing import Any, Optional

import requests


log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://ollama:11434"
DEFAULT_MODEL = "qwen3.6:35b"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_THINK = False


class OllamaGenerationError(RuntimeError):
    """Raised when Ollama cannot produce a usable response."""


def _configuration() -> tuple[str, str, int, bool]:
    """Read Ollama settings at request time so deployment configuration is respected."""
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    think_setting = os.getenv("OLLAMA_THINK", str(DEFAULT_THINK)).lower()

    try:
        timeout_seconds = int(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
    except ValueError as error:
        raise OllamaGenerationError(
            "OLLAMA_TIMEOUT_SECONDS must be a whole number of seconds"
        ) from error

    if not base_url or not model or timeout_seconds <= 0:
        raise OllamaGenerationError("Ollama configuration contains an invalid value")

    if think_setting not in {"true", "false"}:
        raise OllamaGenerationError("OLLAMA_THINK must be true or false")

    return base_url, model, timeout_seconds, think_setting == "true"


def _response_value_as_int(result: dict[str, Any], name: str) -> Optional[int]:
    """Return an Ollama numeric response field when it is an integer."""
    value = result.get(name)
    return value if isinstance(value, int) else None


def _duration_in_seconds(result: dict[str, Any], name: str) -> Optional[float]:
    """Convert Ollama's nanosecond duration metadata to seconds."""
    duration = _response_value_as_int(result, name)
    return duration / 1_000_000_000 if duration is not None else None


def generate_summary(prompt: str, max_tokens: int = 1_000) -> str:
    """Generate one non-streaming summary using Ollama's local API.

    ``max_tokens`` maps to Ollama's ``num_predict`` option, which limits newly
    generated tokens rather than the size of the input legislation text.
    """
    base_url, model, timeout_seconds, think = _configuration()
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # Qwen is a thinking-capable model. Its reasoning otherwise counts against
        # num_predict and can leave no tokens for the public-facing summary.
        "think": think,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.2,
        },
    }

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise OllamaGenerationError(
            f"Could not generate a summary with Ollama at {base_url}: {error}"
        ) from error

    try:
        result = response.json()
    except ValueError as error:
        raise OllamaGenerationError("Ollama returned an invalid JSON response") from error

    generated_text = result.get("response")
    thinking = result.get("thinking")
    thinking_characters = len(thinking) if isinstance(thinking, str) else 0
    generated_characters = len(generated_text) if isinstance(generated_text, str) else 0
    done_reason = result.get("done_reason")
    load_seconds = _duration_in_seconds(result, "load_duration")
    total_seconds = _duration_in_seconds(result, "total_duration")
    log.info(
        "Ollama response: model=%s, final_chars=%d, thinking_chars=%d, "
        "done=%r, done_reason=%r, load_seconds=%s, total_seconds=%s, "
        "prompt_tokens=%s, generated_tokens=%s",
        model,
        generated_characters,
        thinking_characters,
        result.get("done"),
        done_reason,
        f"{load_seconds:.2f}" if load_seconds is not None else "unknown",
        f"{total_seconds:.2f}" if total_seconds is not None else "unknown",
        _response_value_as_int(result, "prompt_eval_count"),
        _response_value_as_int(result, "eval_count"),
    )
    if not isinstance(generated_text, str) or not generated_text.strip():
        raise OllamaGenerationError(
            "Ollama returned no final summary "
            f"(done_reason={done_reason!r}, generated_tokens="
            f"{_response_value_as_int(result, 'eval_count')!r}, "
            f"thinking_chars={thinking_characters})"
        )

    log.debug("Generated summary using Ollama model %s", model)
    return generated_text.strip()
