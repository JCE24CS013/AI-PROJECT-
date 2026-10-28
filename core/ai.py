import json
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
_session_local = threading.local()


class AIServiceError(Exception):
    """A user-safe error from the configured chat provider."""


def _http_session():
    session = getattr(_session_local, "session", None)
    if session is None:
        session = requests.Session()
        _session_local.session = session
    return session


def _provider_config():
    preferred = getattr(settings, "AI_PROVIDER", "groq").strip().lower()
    if preferred not in {"groq", "openrouter"}:
        raise AIServiceError("The assistant provider is not configured correctly. Set AI_PROVIDER to groq or openrouter.")

    groq_key = getattr(settings, "GROQ_API_KEY", "")
    openrouter_key = getattr(settings, "OPENROUTER_API_KEY", "")
    providers = {
        "groq": (
            groq_key,
            getattr(settings, "GROQ_MODEL", "openai/gpt-oss-20b"),
            "https://api.groq.com/openai/v1/chat/completions",
        ),
        "openrouter": (
            openrouter_key,
            getattr(settings, "OPENROUTER_MODEL", "openrouter/auto"),
            "https://openrouter.ai/api/v1/chat/completions",
        ),
    }

    key, model, endpoint = providers[preferred]
    provider = preferred
    if not key:
        fallback = "openrouter" if preferred == "groq" else "groq"
        key, model, endpoint = providers[fallback]
        provider = fallback
    if not key:
        raise AIServiceError("The AI assistant is not configured. Add GROQ_API_KEY to the backend .env file.")
    return provider, key, model, endpoint


def _failure_message(error, provider):
    name = "Groq" if provider == "groq" else "OpenRouter"
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    if status_code == 401:
        key_name = "GROQ_API_KEY" if provider == "groq" else "OPENROUTER_API_KEY"
        return f"{name} rejected the API key. Check {key_name} in the backend environment."
    if status_code == 402:
        return f"{name} has no available credits for this request. Check the provider account billing."
    if status_code == 403:
        return f"{name} denied this request. Check account access and model availability."
    if status_code == 404:
        return f"The configured {name} model was not found. Check the model setting."
    if status_code == 429:
        return f"{name} is rate-limiting requests. Wait a moment and try again."
    if status_code and status_code >= 500:
        return f"{name} is temporarily unavailable. Please try again shortly."
    if isinstance(error, requests.RequestException) and getattr(error, "response", None) is None:
        return f"Could not connect to {name}. Check the network and try again."
    return f"{name} returned an invalid response. Check the configured model and try again."


def stream_chat_completion(messages):
    provider, api_key, model, endpoint = _provider_config()
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        ("max_completion_tokens" if provider == "groq" else "max_tokens"): (
            1024 if provider == "openrouter" else 256
        ),
    }
    if provider == "groq" and model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        payload["reasoning_effort"] = "low"
    elif provider == "openrouter":
        payload["reasoning_effort"] = "none"

    started_at = time.perf_counter()
    first_token_ms = None
    received_content = False
    completed = False
    try:
        with _http_session().post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=payload,
            stream=True,
            timeout=(5, 30),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=False):
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    completed = True
                    break
                event = json.loads(data)
                provider_error = event.get("error")
                if provider_error:
                    error_code = provider_error.get("code") if isinstance(provider_error, dict) else None
                    logger.warning(
                        "AI provider stream error (provider=%s, code=%s)",
                        provider,
                        error_code,
                    )
                    raise AIServiceError(
                        f"{provider.title()} could not complete this request. "
                        "Check the configured model and provider availability."
                    )
                choices = event["choices"]
                if not choices:
                    continue
                choice = choices[0]
                content = choice.get("delta", {}).get("content")
                if content is None:
                    continue
                if not isinstance(content, str):
                    raise ValueError("Provider returned non-text content")
                if content:
                    received_content = True
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - started_at) * 1000)
                    yield content
            if not completed:
                raise AIServiceError(
                    f"{provider.title()} ended the response unexpectedly. Please try again."
                )
            if not received_content:
                raise AIServiceError(
                    f"{provider.title()} completed without a text reply. Please try again."
                )
    except requests.RequestException as error:
        logger.warning("AI provider request failed (provider=%s, status=%s)", provider, getattr(getattr(error, "response", None), "status_code", None))
        raise AIServiceError(_failure_message(error, provider)) from None
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as error:
        logger.warning(
            "AI provider returned an invalid stream (provider=%s, error_type=%s, detail=%s)",
            provider,
            type(error).__name__,
            str(error)[:100],
        )
        raise AIServiceError(f"{provider.title()} returned an invalid response. Check the configured model and try again.") from None

    total_ms = round((time.perf_counter() - started_at) * 1000)
    logger.info("AI chat completed provider=%s model=%s ttft_ms=%s total_ms=%s", provider, model, first_token_ms, total_ms)
