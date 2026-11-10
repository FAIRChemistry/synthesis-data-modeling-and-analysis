#!/usr/bin/env python3
"""Case-agnostic LLM conversion: build a prompt from a preprocessed record and
a schema, call the endpoint, extract and validate the JSON.

Case-specific inputs (how a record is preprocessed, the hints, examples, system
prompt and rules) come from ``cases.Case``; this module only assembles the
prompt and talks to the model.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker
from openai import OpenAI

PLACEHOLDER_KEY = "YOUR_OPENAI_API_KEY_HERE"
DEFAULT_ENDPOINT = "openai"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900.0


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(
    preprocessed: dict[str, Any],
    schema: dict[str, Any],
    hints: str,
    examples: list[dict[str, Any]],
    system: str,
    rules: list[str],
) -> list[dict[str, str]]:
    """Assemble the chat messages for one record.

    ``examples`` are input/output pairs where ``preprocessed_input`` is the same
    representation the model receives for the real input and ``target_json`` is
    the correct output.
    """
    user = {
        "task": "Convert the preprocessed input record to a JSON document satisfying the JSON Schema.",
        "rules": rules,
        "schema": schema,
        "conversion_hints": hints,
        "examples": [
            {
                "description": "Each example is an input-output pair. "
                               "'preprocessed_input' is the same representation you receive for the real input; "
                               "'target_json' is the correct JSON output to produce.",
                "pairs": examples,
            }
        ] if examples else [],
        "preprocessed_input": preprocessed,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def validate_document(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    messages = []
    for error in errors:
        path = "$"
        if error.path:
            path += "." + ".".join(str(part) for part in error.path)
        messages.append(f"{path}: {error.message}")
    return messages


_OPTIONAL_MODEL_PARAMS = ("max_tokens", "top_p", "frequency_penalty", "presence_penalty", "seed")

# GPT-5 and the o-series reasoning models reject a custom sampling temperature
# (only the default of 1 is accepted).
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def is_reasoning_model(model: str) -> bool:
    """True for models that only accept the default temperature (GPT-5 / o-series)."""
    return model.startswith(_REASONING_MODEL_PREFIXES)


def select_endpoint(raw_config: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Pick one endpoint's block from the endpoint-keyed config."""
    if endpoint not in raw_config:
        available = ", ".join(raw_config) or "none"
        raise ValueError(f"Endpoint {endpoint!r} not found in config. Available: {available}.")
    config = dict(raw_config[endpoint])
    config["endpoint"] = endpoint
    config["base_url"] = config.get(f"base_url_{endpoint}") or config.get("base_url")
    return config


def load_config(path: Path, endpoint: str = DEFAULT_ENDPOINT) -> dict[str, Any]:
    """Load the endpoint config and merge in the API key from secrets.json."""
    config = select_endpoint(load_json(path), endpoint)
    secrets_path = path.parent / "secrets.json"
    secrets = load_json(secrets_path) if secrets_path.exists() else {}
    api_key = secrets.get(f"api_key_{endpoint}")
    if not api_key or api_key == PLACEHOLDER_KEY:
        raise ValueError(f"Set api_key_{endpoint} in {secrets_path} before running conversion.")
    config["api_key"] = api_key
    return config


def call_openai(
    messages: list[dict[str, str]],
    config: dict[str, Any],
    temperature: float,
) -> tuple[str, dict[str, int]]:
    base_url = config.get("base_url") or None
    # Large schema-guided extractions can legitimately take several minutes.
    # Endpoint configs may override this without changing the call site.
    timeout = float(config.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS))
    client = OpenAI(api_key=config["api_key"], base_url=base_url, timeout=timeout)
    model = config.get("model", "gpt-4o")
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    # Reasoning models only accept the default temperature (1); others honor it.
    if not is_reasoning_model(model):
        kwargs["temperature"] = temperature
    for param in _OPTIONAL_MODEL_PARAMS:
        val = config.get(param)
        if val is not None:
            kwargs[param] = val
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    else:
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        usage = {
            "prompt_chars": prompt_chars,
            "completion_chars": len(content),
            "total_chars": prompt_chars + len(content),
        }
    return content, usage


def run_conversion(
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    config: dict[str, Any],
    temperature: float,
) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    """Call the model on prebuilt messages, then extract and validate the JSON."""
    raw_response, usage = call_openai(messages, config, temperature)
    document = extract_json_object(raw_response)
    validation_errors = validate_document(document, schema)
    return document, validation_errors, usage


def mock_conversion(
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    config: dict[str, Any],
    temperature: float,
) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    """Offline stand-in for ``run_conversion`` (``--mock``): no API call, no key.

    Returns a deterministic placeholder document that embeds a hash of the
    record, so a changed input yields a changed output and the run/diff
    machinery behaves realistically. The document is still validated against
    the schema (it is a placeholder, so expect validation warnings)."""
    user = json.loads(messages[-1]["content"])
    record = user.get("preprocessed_input", {})
    digest = hashlib.sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    document = {
        "journal_number": record.get("journal_number") or record.get("short_label"),
        "_mock": {"input_sha256": digest, "model": config.get("model", "mock"),
                  "temperature": temperature},
    }
    validation_errors = validate_document(document, schema)
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return document, validation_errors, usage
