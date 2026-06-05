import json
import os
from datetime import datetime

from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import scoped_package_path
from PushShoppingList.services.storage_service import user_data_root


OPENAI_USAGE_FILE = scoped_package_path("openai_usage.json")
MAX_USAGE_RECORDS = int(os.getenv("SHOPPING_APP_OPENAI_USAGE_RECORD_LIMIT", "2000"))


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def current_month_key():
    return datetime.utcnow().strftime("%Y-%m")


def openai_usage_file_for_user(user_id=None):
    user_id = str(user_id or "").strip()
    if user_id:
        return user_data_root(user_id) / "openai_usage.json"
    return OPENAI_USAGE_FILE


def load_openai_usage_payload(usage_file=None):
    usage_file = usage_file or OPENAI_USAGE_FILE
    try:
        if not usage_file.exists():
            return {"records": []}
        payload = json.loads(usage_file.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}

    records = payload.get("records") if isinstance(payload, dict) else []
    return {
        "records": [
            normalize_usage_record(record)
            for record in records
            if isinstance(record, dict)
        ]
    }


def save_openai_usage_payload(payload, usage_file=None):
    usage_file = usage_file or OPENAI_USAGE_FILE
    records = payload.get("records", []) if isinstance(payload, dict) else []
    payload = {"records": records[-MAX_USAGE_RECORDS:]}
    usage_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def record_openai_usage(response, feature, model=None, metadata=None, user_id=None):
    usage = extract_openai_usage(response)

    if not usage.get("total_tokens"):
        return None

    record_user_id = str(user_id if user_id is not None else active_user_id()).strip()
    if not record_user_id:
        return None

    usage_file = openai_usage_file_for_user(user_id)
    record = normalize_usage_record({
        "createdAt": now_iso(),
        "month": current_month_key(),
        "userId": record_user_id,
        "feature": str(feature or "openai-api").strip() or "openai-api",
        "model": str(model or extract_response_model(response) or "").strip(),
        "promptTokens": usage.get("prompt_tokens", 0),
        "completionTokens": usage.get("completion_tokens", 0),
        "totalTokens": usage.get("total_tokens", 0),
        "estimatedCostUsd": estimate_usage_cost_usd(usage),
        "metadata": metadata if isinstance(metadata, dict) else {},
    })
    payload = load_openai_usage_payload(usage_file)
    payload.setdefault("records", []).append(record)
    save_openai_usage_payload(payload, usage_file)
    return record


def extract_openai_usage(response):
    usage = getattr(response, "usage", None)

    if usage is None and isinstance(response, dict):
        usage = response.get("usage")

    prompt_tokens = usage_value(usage, "prompt_tokens", "input_tokens")
    completion_tokens = usage_value(usage, "completion_tokens", "output_tokens")
    total_tokens = usage_value(usage, "total_tokens")

    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def usage_value(usage, *names):
    for name in names:
        value = None
        if isinstance(usage, dict):
            value = usage.get(name)
        elif usage is not None:
            value = getattr(usage, name, None)
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return value
    return 0


def extract_response_model(response):
    if isinstance(response, dict):
        return response.get("model")
    return getattr(response, "model", "")


def estimate_usage_cost_usd(usage):
    input_rate = env_float("SHOPPING_APP_OPENAI_INPUT_COST_PER_1M_TOKENS")
    output_rate = env_float("SHOPPING_APP_OPENAI_OUTPUT_COST_PER_1M_TOKENS")

    if input_rate is None or output_rate is None:
        return None

    cost = (
        (usage.get("prompt_tokens", 0) / 1_000_000) * input_rate
        + (usage.get("completion_tokens", 0) / 1_000_000) * output_rate
    )
    return round(cost, 6)


def env_float(name):
    value = str(os.getenv(name, "") or "").strip()

    if not value:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def env_int(name):
    value = str(os.getenv(name, "") or "").strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def normalize_usage_record(record):
    prompt_tokens = int_or_zero(record.get("promptTokens") or record.get("prompt_tokens"))
    completion_tokens = int_or_zero(record.get("completionTokens") or record.get("completion_tokens"))
    total_tokens = int_or_zero(record.get("totalTokens") or record.get("total_tokens"))

    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "createdAt": str(record.get("createdAt") or record.get("created_at") or now_iso()),
        "month": str(record.get("month") or current_month_key()),
        "userId": str(record.get("userId") or record.get("user_id") or "").strip(),
        "feature": str(record.get("feature") or "openai-api").strip() or "openai-api",
        "model": str(record.get("model") or "").strip(),
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUsd": record.get("estimatedCostUsd"),
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
    }


def int_or_zero(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def openai_usage_dashboard_for_user(user=None):
    user_id = ""
    if isinstance(user, dict):
        user_id = str(user.get("user_id") or "").strip()
    payload = load_openai_usage_payload(openai_usage_file_for_user(user_id))
    records = payload.get("records", [])
    month = current_month_key()
    month_records = [record for record in records if record.get("month") == month]
    monthly_limit = env_int("SHOPPING_APP_OPENAI_MONTHLY_TOKEN_LIMIT")
    monthly_budget = env_float("SHOPPING_APP_OPENAI_MONTHLY_BUDGET_USD")
    month_prompt = sum_tokens(month_records, "promptTokens")
    month_completion = sum_tokens(month_records, "completionTokens")
    month_total = sum_tokens(month_records, "totalTokens")
    lifetime_total = sum_tokens(records, "totalTokens")
    estimated_month_cost = sum_estimated_cost(month_records)
    limit_remaining = monthly_limit - month_total if monthly_limit is not None else None
    budget_remaining = monthly_budget - estimated_month_cost if monthly_budget is not None and estimated_month_cost is not None else None

    return {
        "plan_label": os.getenv("SHOPPING_APP_OPENAI_PLAN_LABEL", "Personal Workspace"),
        "subscription_label": os.getenv("SHOPPING_APP_OPENAI_SUBSCRIPTION_LABEL", "OpenAI API pay-as-you-go"),
        "month_label": month,
        "monthly_token_limit": monthly_limit,
        "monthly_token_limit_label": number_label(monthly_limit) if monthly_limit is not None else "Not set",
        "monthly_budget_usd": monthly_budget,
        "monthly_budget_label": money_label(monthly_budget) if monthly_budget is not None else "Not set",
        "monthly_prompt_tokens": month_prompt,
        "monthly_completion_tokens": month_completion,
        "monthly_total_tokens": month_total,
        "monthly_request_count": len(month_records),
        "monthly_estimated_cost": estimated_month_cost,
        "monthly_estimated_cost_label": money_label(estimated_month_cost) if estimated_month_cost is not None else "Cost rates not set",
        "monthly_tokens_remaining": limit_remaining,
        "monthly_tokens_remaining_label": number_label(max(0, limit_remaining)) if limit_remaining is not None else "No limit set",
        "monthly_budget_remaining": budget_remaining,
        "monthly_budget_remaining_label": money_label(max(0, budget_remaining)) if budget_remaining is not None else "No budget set",
        "limit_percent": percent_used(month_total, monthly_limit),
        "budget_percent": percent_used(estimated_month_cost, monthly_budget) if estimated_month_cost is not None else None,
        "lifetime_total_tokens": lifetime_total,
        "lifetime_request_count": len(records),
        "last_used_at": latest_record_timestamp(records),
        "last_used_at_label": display_datetime(latest_record_timestamp(records)),
        "records_tracked": len(records),
        "has_usage": bool(records),
        "tracking_note": (
            "These are OpenAI API tokens recorded by this app from API responses. "
            "ChatGPT app or website subscription usage is not exposed to this local dashboard."
        ),
    }


def sum_tokens(records, key):
    return sum(int_or_zero(record.get(key)) for record in records)


def sum_estimated_cost(records):
    values = []
    for record in records:
        value = record.get("estimatedCostUsd")
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return round(sum(values), 6)


def percent_used(value, limit):
    if limit in (None, 0):
        return None
    try:
        return min(100, round((float(value or 0) / float(limit)) * 100, 1))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def latest_record_timestamp(records):
    values = [str(record.get("createdAt") or "") for record in records if record.get("createdAt")]
    return max(values) if values else ""


def number_label(value):
    if value is None:
        return "Not set"
    return f"{int_or_zero(value):,}"


def money_label(value):
    if value is None:
        return "Not set"
    return f"${float(value):,.4f}"


def display_datetime(value):
    if not value:
        return "Not recorded yet"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return str(value)
    return parsed.strftime("%b %-d, %Y %-I:%M %p UTC") if os.name != "nt" else parsed.strftime("%b %#d, %Y %#I:%M %p UTC")
