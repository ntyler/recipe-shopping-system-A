import json
import os
import re
import time

import requests


OLLAMA_BASE_URL_ENV_VAR = "OLLAMA_BASE_URL"
OLLAMA_FULL_RECIPE_MODEL_ENV_VAR = "OLLAMA_FULL_RECIPE_MODEL"
OLLAMA_FULL_RECIPE_TIMEOUT_ENV_VAR = "OLLAMA_FULL_RECIPE_TIMEOUT_SECONDS"
OLLAMA_FULL_RECIPE_BATCH_SIZE_ENV_VAR = "OLLAMA_FULL_RECIPE_BATCH_SIZE"
OLLAMA_FULL_RECIPE_WORKERS_ENV_VAR = "OLLAMA_FULL_RECIPE_WORKERS"
OLLAMA_FULL_RECIPE_PROVIDER_ENV_VAR = "OLLAMA_FULL_RECIPE_PROVIDER"
OLLAMA_FULL_RECIPE_MODEL_DEFAULT = "qwen2.5:7b"
OLLAMA_FULL_RECIPE_BATCH_SIZE_DEFAULT = 1
OLLAMA_FULL_RECIPE_WORKERS_DEFAULT = 2
OLLAMA_BASE_URL_DEFAULT = "http://localhost:11434"
OLLAMA_PROVIDER_ONLY = "ollama_only"
OLLAMA_PROVIDER_AUTO = "auto_ollama_openai"
OLLAMA_PROVIDER_DEFAULT = OLLAMA_PROVIDER_ONLY
OLLAMA_PROVIDER_LABELS = {
    OLLAMA_PROVIDER_ONLY: "Ollama only",
    OLLAMA_PROVIDER_AUTO: "Auto Ollama/OpenAI",
}
OLLAMA_PROVIDER_LABEL = OLLAMA_PROVIDER_LABELS[OLLAMA_PROVIDER_AUTO]
OLLAMA_ACTION_NAME = "generate-full-recipes-ollama-support"
OLLAMA_FALLBACK_ERROR_CODES = {
    "OLLAMA_CONNECTION_FAILED",
    "OLLAMA_JSON_INVALID",
    "OLLAMA_REQUIRED_FIELDS_MISSING",
}

REQUIRED_FULL_RECIPE_FIELDS = (
    "recipe_name",
    "servings",
    "ingredients",
    "equipment",
    "instructions",
    "prep_time",
    "cook_time",
    "total_time",
    "difficulty",
    "estimated_cost",
)

TOKEN_STOPWORDS = {
    "and",
    "with",
    "the",
    "for",
    "menu",
    "item",
    "dish",
    "house",
    "special",
    "style",
    "fresh",
    "served",
    "side",
    "sauce",
    "spicy",
    "sweet",
    "fried",
    "grilled",
    "roasted",
    "steamed",
}


class OllamaRecipeError(RuntimeError):
    pass


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bool_text(value):
    return "true" if bool(value) else "false"


def _env_int(name, default, minimum=1, maximum=32):
    try:
        value = int(os.getenv(str(name or "")) or int(default or 0))
    except (TypeError, ValueError):
        value = int(default or 0)
    return max(int(minimum), min(int(maximum), value))


def _env_is_set(name):
    value = os.getenv(str(name or ""))
    return value is not None and _clean_text(value) != ""


def ollama_full_recipe_model():
    return _clean_text(os.getenv(OLLAMA_FULL_RECIPE_MODEL_ENV_VAR)) or OLLAMA_FULL_RECIPE_MODEL_DEFAULT


def normalize_ollama_provider(value):
    provider = _clean_text(value).lower()
    return provider if provider in {OLLAMA_PROVIDER_ONLY, OLLAMA_PROVIDER_AUTO} else OLLAMA_PROVIDER_DEFAULT


def ollama_full_recipe_provider(value=None):
    if value is not None and _clean_text(value):
        return normalize_ollama_provider(value)
    return normalize_ollama_provider(os.getenv(OLLAMA_FULL_RECIPE_PROVIDER_ENV_VAR))


def ollama_provider_label(provider=None):
    return OLLAMA_PROVIDER_LABELS.get(normalize_ollama_provider(provider), OLLAMA_PROVIDER_LABELS[OLLAMA_PROVIDER_DEFAULT])


def ollama_full_recipe_batch_size():
    return _env_int(
        OLLAMA_FULL_RECIPE_BATCH_SIZE_ENV_VAR,
        OLLAMA_FULL_RECIPE_BATCH_SIZE_DEFAULT,
        minimum=1,
        maximum=8,
    )


def ollama_full_recipe_default_workers(model=None):
    model_name = _clean_text(model or ollama_full_recipe_model()).lower()
    if "qwen2.5:14b" in model_name or "qwen2.5:32b" in model_name:
        return 1
    if "qwen2.5:7b" in model_name:
        return 2
    return OLLAMA_FULL_RECIPE_WORKERS_DEFAULT


def ollama_full_recipe_workers(batch_total=None, model=None):
    default_workers = ollama_full_recipe_default_workers(model)
    workers = _env_int(
        OLLAMA_FULL_RECIPE_WORKERS_ENV_VAR,
        default_workers,
        minimum=1,
        maximum=8,
    ) if _env_is_set(OLLAMA_FULL_RECIPE_WORKERS_ENV_VAR) else default_workers
    if batch_total:
        return max(1, min(workers, int(batch_total)))
    return workers


def ollama_base_url():
    return (_clean_text(os.getenv(OLLAMA_BASE_URL_ENV_VAR)) or OLLAMA_BASE_URL_DEFAULT).rstrip("/")


def ollama_timeout_seconds():
    try:
        value = float(os.getenv(OLLAMA_FULL_RECIPE_TIMEOUT_ENV_VAR) or "120")
    except (TypeError, ValueError):
        value = 120.0
    return max(1.0, min(600.0, value))


def clean_ollama_json_response(text):
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = text.replace("\r\n", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


def parse_ollama_json_response(text):
    return json.loads(clean_ollama_json_response(text))


def _as_list(value):
    if isinstance(value, list):
        return value
    if value is None:
        return []
    text = _clean_text(value)
    return [text] if text else []


def _normalize_ingredients(value):
    rows = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = _clean_text(
                item.get("ingredient")
                or item.get("name")
                or item.get("text")
                or item.get("original_text")
            )
            original_text = _clean_text(item.get("original_text") or item.get("text") or name)
            if not name and not original_text:
                continue
            rows.append({
                **item,
                "quantity": _clean_text(item.get("quantity")),
                "unit": _clean_text(item.get("unit")),
                "ingredient": name or original_text,
                "preparation": _clean_text(item.get("preparation")),
                "original_text": original_text or name,
            })
        else:
            text = _clean_text(item)
            if text:
                rows.append({
                    "quantity": "",
                    "unit": "",
                    "ingredient": text,
                    "preparation": "",
                    "original_text": text,
                })
    return rows


def _normalize_equipment(value):
    rows = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = _clean_text(item.get("name") or item.get("equipment") or item.get("text") or item.get("item"))
            if name:
                rows.append({"name": name})
        else:
            name = _clean_text(item)
            if name:
                rows.append({"name": name})
    return rows


def _normalize_instructions(value):
    rows = []
    for index, item in enumerate(_as_list(value), start=1):
        if isinstance(item, dict):
            text = _clean_text(
                item.get("instruction")
                or item.get("text")
                or item.get("step_text")
                or item.get("description")
            )
            step = item.get("step") or item.get("step_number") or index
        else:
            text = _clean_text(item)
            step = index
        if text:
            rows.append({"step": step, "instruction": text})
    return rows


def normalize_ollama_full_recipe_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    difficulty = _clean_text(payload.get("difficulty") or payload.get("difficulty_level"))
    return {
        "recipe_name": _clean_text(payload.get("recipe_name") or payload.get("recipe_title") or payload.get("name")),
        "servings": _clean_text(payload.get("servings")),
        "predicted_ingredients": _normalize_ingredients(payload.get("ingredients") or payload.get("predicted_ingredients")),
        "predicted_equipment": _normalize_equipment(payload.get("equipment") or payload.get("predicted_equipment")),
        "predicted_instructions": _normalize_instructions(payload.get("instructions") or payload.get("predicted_instructions")),
        "prep_time": _clean_text(payload.get("prep_time")),
        "cook_time": _clean_text(payload.get("cook_time")),
        "total_time": _clean_text(payload.get("total_time")),
        "difficulty": difficulty,
        "difficulty_level": difficulty,
        "estimated_cost": _clean_text(payload.get("estimated_cost") or payload.get("cost_estimate")),
        "confidence": payload.get("confidence", 0.8),
        "notes": _as_list(payload.get("notes")),
    }


def _menu_item_from_entry(entry):
    entry = entry if isinstance(entry, dict) else {}
    return entry.get("menu_item") if isinstance(entry.get("menu_item"), dict) else {}


def menu_item_id_from_entry(entry):
    item = _menu_item_from_entry(entry)
    return _clean_text(item.get("menu_item_id") or (entry or {}).get("menu_item_id"))


def menu_item_name_from_entry(entry):
    item = _menu_item_from_entry(entry)
    stub = (entry or {}).get("stub") if isinstance((entry or {}).get("stub"), dict) else {}
    return _clean_text(
        item.get("item_name")
        or stub.get("menu_item_name")
        or stub.get("recipe_title")
        or (entry or {}).get("recipe_url")
    )


def _menu_item_prompt_context(entry):
    item = _menu_item_from_entry(entry)
    stub = (entry or {}).get("stub") if isinstance((entry or {}).get("stub"), dict) else {}
    return {
        "menu_item_id": menu_item_id_from_entry(entry),
        "name": menu_item_name_from_entry(entry),
        "section": _clean_text(item.get("menu_section") or stub.get("menu_section") or stub.get("section_name")),
        "description": _clean_text(item.get("description") or stub.get("menu_description") or stub.get("description")),
        "price": _clean_text(item.get("price") or stub.get("menu_price") or stub.get("price")),
        "source_menu_url": _clean_text(item.get("source_menu_url") or stub.get("source_menu_url") or stub.get("menu_source_url")),
        "restaurant_name": _clean_text(item.get("restaurant_name") or stub.get("restaurant_name")),
        "cuisine_hint": _clean_text(item.get("broad_category") or stub.get("cuisine") or stub.get("restaurant_cuisine_tags")),
    }


def build_ollama_full_recipe_prompt(entry, repair_response="", repair_error=""):
    schema = {
        "recipe_name": "string",
        "servings": "string or number",
        "ingredients": [
            {
                "quantity": "string",
                "unit": "string",
                "ingredient": "string",
                "preparation": "string",
                "original_text": "string",
            }
        ],
        "equipment": ["string"],
        "instructions": ["string"],
        "prep_time": "string",
        "cook_time": "string",
        "total_time": "string",
        "difficulty": "easy, medium, or hard",
        "estimated_cost": "short string",
    }
    context = _menu_item_prompt_context(entry)
    if repair_response:
        return f"""
Repair this invalid recipe JSON response.

Return ONLY valid JSON. Do not include markdown fences or commentary.
The repaired JSON must match this schema:
{json.dumps(schema, ensure_ascii=False)}

Menu item context:
{json.dumps(context, ensure_ascii=False)}

Previous parser error:
{_clean_text(repair_error)}

Invalid response:
{str(repair_response or "").strip()}
"""

    return f"""
Infer a practical home-cooking recipe from this restaurant menu item.

Return ONLY valid JSON. Do not include markdown fences or commentary.
This is not the restaurant's exact recipe. Make a plausible AI-inferred home recipe.
The recipe must clearly relate to the menu item name and description.

Expected JSON schema:
{json.dumps(schema, ensure_ascii=False)}

Rules:
- Include at least 4 instruction steps.
- Include practical equipment.
- Use the menu item name, section, description, price, restaurant, and cuisine hints as context.
- Use concise but complete prep_time, cook_time, total_time, difficulty, and estimated_cost values.

Menu item context:
{json.dumps(context, ensure_ascii=False)}
"""


def call_ollama_generate(prompt_text, model="", base_url="", timeout_seconds=None):
    model = _clean_text(model) or ollama_full_recipe_model()
    base_url = (_clean_text(base_url) or ollama_base_url()).rstrip("/")
    url = f"{base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": str(prompt_text or ""),
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
        },
    }
    response = requests.post(url, json=payload, timeout=timeout_seconds or ollama_timeout_seconds())
    response.raise_for_status()
    data = response.json()
    text = data.get("response")
    if text is None and isinstance(data.get("message"), dict):
        text = data["message"].get("content")
    if text is None:
        raise OllamaRecipeError("Ollama response did not include generated text.")
    return str(text)


def _token_set(value):
    tokens = set()
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9']+", str(value or "").lower()):
        token = token.strip("'")
        if len(token) < 3 or token in TOKEN_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _recipe_looks_unrelated(normalized, entry):
    context = _menu_item_prompt_context(entry)
    source_tokens = _token_set(" ".join([
        context.get("name", ""),
        context.get("description", ""),
        context.get("section", ""),
    ]))
    if not source_tokens:
        return False

    generated_parts = [
        normalized.get("recipe_name", ""),
        " ".join(item.get("ingredient", "") for item in normalized.get("predicted_ingredients") or []),
        " ".join(step.get("instruction", "") for step in normalized.get("predicted_instructions") or []),
    ]
    generated_tokens = _token_set(" ".join(generated_parts))
    return not bool(source_tokens & generated_tokens)


def validate_ollama_full_recipe_payload(payload, entry):
    normalized = normalize_ollama_full_recipe_payload(payload)
    missing = []
    if not normalized["recipe_name"]:
        missing.append("recipe_name")
    if not normalized["servings"]:
        missing.append("servings")
    if not normalized["predicted_ingredients"]:
        missing.append("ingredients")
    if not normalized["predicted_equipment"]:
        missing.append("equipment")
    if not normalized["predicted_instructions"]:
        missing.append("instructions")
    if not normalized["prep_time"]:
        missing.append("prep_time")
    if not normalized["cook_time"]:
        missing.append("cook_time")
    if not normalized["total_time"]:
        missing.append("total_time")
    if not normalized["difficulty"]:
        missing.append("difficulty")
    if not normalized["estimated_cost"]:
        missing.append("estimated_cost")

    low_confidence_reasons = []
    if not normalized["predicted_ingredients"]:
        low_confidence_reasons.append("ingredients_empty")
    if len(normalized["predicted_instructions"]) < 4:
        low_confidence_reasons.append("instructions_fewer_than_4_steps")
    if not normalized["predicted_equipment"]:
        low_confidence_reasons.append("equipment_empty")
    if missing:
        low_confidence_reasons.append("required_fields_blank")
    if _recipe_looks_unrelated(normalized, entry):
        low_confidence_reasons.append("recipe_unrelated_to_menu_item")

    return {
        "ok": not missing,
        "normalized": normalized,
        "missing_fields": missing,
        "low_confidence": bool(low_confidence_reasons),
        "low_confidence_reasons": low_confidence_reasons,
    }


def generate_ollama_full_recipe_for_entry(entry, model="", base_url="", timeout_seconds=None, cancellation_check=None):
    if cancellation_check:
        cancellation_check()
    model = _clean_text(model) or ollama_full_recipe_model()
    base_url = (_clean_text(base_url) or ollama_base_url()).rstrip("/")
    started = time.perf_counter()
    raw_response = ""
    repair_attempted = False
    try:
        raw_response = call_ollama_generate(
            build_ollama_full_recipe_prompt(entry),
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        if cancellation_check:
            cancellation_check()
        try:
            payload = parse_ollama_json_response(raw_response)
            json_valid = True
            parse_error = ""
        except Exception as exc:
            json_valid = False
            parse_error = str(exc)
            repair_attempted = True
            try:
                repair_response = call_ollama_generate(
                    build_ollama_full_recipe_prompt(
                        entry,
                        repair_response=raw_response,
                        repair_error=parse_error,
                    ),
                    model=model,
                    base_url=base_url,
                    timeout_seconds=timeout_seconds,
                )
                if cancellation_check:
                    cancellation_check()
                payload = parse_ollama_json_response(repair_response)
                raw_response = repair_response
                json_valid = True
            except Exception as repair_exc:
                return {
                    "ok": False,
                    "inference": {},
                    "json_valid": False,
                    "low_confidence": False,
                    "low_confidence_reasons": [],
                    "missing_fields": [],
                    "repair_attempted": True,
                    "duration_seconds": time.perf_counter() - started,
                    "raw_response": raw_response,
                    "error": str(repair_exc) or parse_error or "Ollama recipe JSON could not be parsed.",
                    "error_code": "OLLAMA_JSON_INVALID",
                    "exception_type": type(repair_exc).__name__,
                }

        validation = validate_ollama_full_recipe_payload(payload, entry)
        inference = {
            **validation["normalized"],
            "ai_provider": "ollama",
            "provider": "ollama",
            "ollama_model": model,
            "ollama_base_url": base_url,
            "json_valid": json_valid,
            "low_confidence": bool(validation["low_confidence"]),
            "low_confidence_reasons": validation["low_confidence_reasons"],
            "repair_attempted": repair_attempted,
        }
        return {
            "ok": bool(validation["ok"]),
            "inference": inference,
            "json_valid": json_valid,
            "low_confidence": bool(validation["low_confidence"]),
            "low_confidence_reasons": validation["low_confidence_reasons"],
            "missing_fields": validation["missing_fields"],
            "repair_attempted": repair_attempted,
            "duration_seconds": time.perf_counter() - started,
            "raw_response": raw_response,
            "error": "" if validation["ok"] else "Ollama recipe JSON is missing required fields.",
            "error_code": "" if validation["ok"] else "OLLAMA_REQUIRED_FIELDS_MISSING",
        }
    except Exception as exc:
        error_code = (
            "OLLAMA_CONNECTION_FAILED"
            if isinstance(exc, (requests.ConnectionError, requests.Timeout))
            else "OLLAMA_REQUEST_FAILED"
        )
        return {
            "ok": False,
            "inference": {},
            "json_valid": False,
            "low_confidence": False,
            "low_confidence_reasons": [],
            "missing_fields": [],
            "repair_attempted": repair_attempted,
            "duration_seconds": time.perf_counter() - started,
            "raw_response": raw_response,
            "error": str(exc) or "Ollama recipe generation failed.",
            "error_code": error_code,
            "exception_type": type(exc).__name__,
        }


def _call_openai_fallback(openai_infer_batch, entries, cancellation_check=None):
    if not openai_infer_batch:
        return {
            "ok": False,
            "items": {},
            "failures": {},
            "error_message": "OpenAI fallback is not configured.",
        }
    try:
        return openai_infer_batch(entries, cancellation_check=cancellation_check)
    except TypeError as exc:
        if "cancellation_check" not in str(exc):
            raise
        return openai_infer_batch(entries)


def _fallback_item_result(fallback_result, item_id):
    fallback_result = fallback_result if isinstance(fallback_result, dict) else {}
    items = fallback_result.get("items") if isinstance(fallback_result.get("items"), dict) else {}
    if item_id and isinstance(items.get(item_id), dict):
        return items[item_id]
    if len(items) == 1:
        value = next(iter(items.values()))
        return value if isinstance(value, dict) else {}
    return {}


def _fallback_failure(fallback_result, item_id):
    fallback_result = fallback_result if isinstance(fallback_result, dict) else {}
    failures = fallback_result.get("failures") if isinstance(fallback_result.get("failures"), dict) else {}
    failure = failures.get(item_id) if item_id and isinstance(failures.get(item_id), dict) else {}
    return failure if isinstance(failure, dict) else {}


def _log_ollama_event(action, entry, started=None, model="", provider="", json_valid=False, low_confidence=False, fallback_used=False, success=False, error="", **fields):
    duration = ""
    if started is not None:
        duration = f" duration={time.perf_counter() - started:.3f}s"
    extra = " ".join(
        f"{key}={json.dumps(value, ensure_ascii=True) if isinstance(value, (dict, list)) else value}"
        for key, value in fields.items()
        if value not in (None, "")
    )
    print(
        "[MenuRecipeGeneration] "
        f"action={action} "
        f"provider={provider} "
        f"ollama_model={model} "
        f"menu_item_name={json.dumps(menu_item_name_from_entry(entry), ensure_ascii=True)} "
        f"{duration} "
        f"json_valid={_bool_text(json_valid)} "
        f"low_confidence={_bool_text(low_confidence)} "
        f"fallback_used={_bool_text(fallback_used)} "
        f"success={_bool_text(success)} "
        f"error={json.dumps(str(error or ''), ensure_ascii=True)}"
        f"{(' ' + extra) if extra else ''}"
    )


def infer_menu_item_recipe_batch_with_ollama_support(
    entries,
    user_id=None,
    model_resolution=None,
    openai_infer_batch=None,
    provider=None,
    cancellation_check=None,
):
    del user_id
    entries = [entry for entry in entries or [] if isinstance(entry, dict)]
    model = ollama_full_recipe_model()
    base_url = ollama_base_url()
    provider = normalize_ollama_provider(provider)
    items = {}
    failures = {}
    ollama_success_count = 0
    openai_fallback_count = 0
    openai_fallback_success_count = 0
    ollama_failed_count = 0
    ollama_low_confidence_count = 0
    ollama_json_invalid_count = 0

    for entry in entries:
        if cancellation_check:
            cancellation_check()
        item_id = menu_item_id_from_entry(entry)
        item_started = time.perf_counter()
        _log_ollama_event(
            "ollama_item_start",
            entry,
            started=item_started,
            model=model,
            provider=provider,
            success=False,
        )
        ollama_result = generate_ollama_full_recipe_for_entry(
            entry,
            model=model,
            base_url=base_url,
            cancellation_check=cancellation_check,
        )
        if ollama_result.get("ok"):
            inference = ollama_result.get("inference") if isinstance(ollama_result.get("inference"), dict) else {}
            inference = {
                **inference,
                "provider": inference.get("provider") or "ollama",
                "ai_provider": provider,
                "ollama_support": True,
                "fallback_used": False,
                "ollama_model": inference.get("ollama_model") or model,
            }
            items[item_id] = inference
            ollama_success_count += 1
            _log_ollama_event(
                "ollama_item_complete",
                entry,
                started=item_started,
                model=model,
                provider=provider,
                json_valid=ollama_result.get("json_valid"),
                low_confidence=ollama_result.get("low_confidence"),
                fallback_used=False,
                success=True,
            )
            continue

        ollama_failed_count += 1
        if not ollama_result.get("json_valid"):
            ollama_json_invalid_count += 1
        if ollama_result.get("low_confidence"):
            ollama_low_confidence_count += 1

        fallback_allowed = (
            provider == OLLAMA_PROVIDER_AUTO
            and str(ollama_result.get("error_code") or "") in OLLAMA_FALLBACK_ERROR_CODES
        )
        _log_ollama_event(
            "ollama_item_failed",
            entry,
            started=item_started,
            model=model,
            provider=provider,
            json_valid=ollama_result.get("json_valid"),
            low_confidence=ollama_result.get("low_confidence"),
            fallback_used=fallback_allowed,
            success=False,
            error=ollama_result.get("error", ""),
            error_code=ollama_result.get("error_code", ""),
        )
        if not fallback_allowed:
            error = (
                ollama_result.get("error")
                or "Ollama recipe generation failed without OpenAI fallback."
            )
            failures[item_id or str(len(failures) + 1)] = {
                "error": error,
                "provider": provider,
                "ollama_model": model,
                "ollama_error": error,
                "ollama_error_code": ollama_result.get("error_code", ""),
            }
            _log_ollama_event(
                "ollama_item_complete",
                entry,
                started=item_started,
                model=model,
                provider=provider,
                json_valid=ollama_result.get("json_valid"),
                low_confidence=ollama_result.get("low_confidence"),
                fallback_used=False,
                success=False,
                error=error,
                error_code=ollama_result.get("error_code", ""),
            )
            continue

        fallback_started = time.perf_counter()
        openai_fallback_count += 1
        _log_ollama_event(
            "openai_fallback_start",
            entry,
            started=fallback_started,
            model=model,
            provider=provider,
            json_valid=ollama_result.get("json_valid"),
            low_confidence=ollama_result.get("low_confidence"),
            fallback_used=True,
            success=False,
            error=ollama_result.get("error", ""),
            error_code=ollama_result.get("error_code", ""),
        )
        fallback_result = _call_openai_fallback(openai_infer_batch, [entry], cancellation_check=cancellation_check)
        fallback_result = fallback_result if isinstance(fallback_result, dict) else {}
        fallback_item = _fallback_item_result(fallback_result, item_id)
        if fallback_item:
            fallback_item = {
                **fallback_item,
                "ai_provider": "openai",
                "provider": "openai",
                "ollama_support": True,
                "fallback_used": True,
                "fallback_reason": ollama_result.get("error_code") or "ollama_failed",
                "ollama_model": model,
                "ollama_error": ollama_result.get("error", ""),
                "ollama_error_code": ollama_result.get("error_code", ""),
                "ollama_json_valid": bool(ollama_result.get("json_valid")),
                "ollama_low_confidence": bool(ollama_result.get("low_confidence")),
            }
            items[item_id] = fallback_item
            openai_fallback_success_count += 1
            _log_ollama_event(
                "openai_fallback_complete",
                entry,
                started=fallback_started,
                model=model,
                provider=provider,
                json_valid=ollama_result.get("json_valid"),
                low_confidence=ollama_result.get("low_confidence"),
                fallback_used=True,
                success=True,
            )
            continue

        failure = _fallback_failure(fallback_result, item_id)
        error = (
            failure.get("error")
            or fallback_result.get("error_message")
            or fallback_result.get("error")
            or ollama_result.get("error")
            or "Unable to generate recipe with Ollama or OpenAI fallback."
        )
        failures[item_id or str(len(failures) + 1)] = {
            "error": error,
            "provider": provider,
            "ollama_model": model,
            "ollama_error": ollama_result.get("error", ""),
            "ollama_error_code": ollama_result.get("error_code", ""),
            "openai_error": fallback_result.get("error_message") or fallback_result.get("error") or "",
        }
        _log_ollama_event(
            "openai_fallback_complete",
            entry,
            started=fallback_started,
            model=model,
            provider=provider,
            json_valid=ollama_result.get("json_valid"),
            low_confidence=ollama_result.get("low_confidence"),
            fallback_used=True,
            success=False,
            error=error,
        )

    provider_summary = {
        "ai_provider": provider,
        "provider": provider,
        "provider_label": ollama_provider_label(provider),
        "ollama_support": True,
        "ollama_model": model,
        "ollama_base_url": base_url,
        "openai_fallback_model": getattr(model_resolution, "model", "") if model_resolution else "",
        "openai_fallback_model_source": getattr(model_resolution, "source", "") if model_resolution else "",
        "ollama_success_count": ollama_success_count,
        "openai_fallback_count": openai_fallback_count,
        "openai_fallback_success_count": openai_fallback_success_count,
        "ollama_failed_count": ollama_failed_count,
        "ollama_low_confidence_count": ollama_low_confidence_count,
        "ollama_json_invalid_count": ollama_json_invalid_count,
        "fallback_used": openai_fallback_count > 0,
        "openai_fallback_summary": f"OpenAI fallback count: {openai_fallback_count}",
    }
    return {
        "ok": not failures,
        "items": items,
        "failures": failures,
        "model": model,
        "model_source": provider,
        "provider_summary": provider_summary,
        **provider_summary,
    }
