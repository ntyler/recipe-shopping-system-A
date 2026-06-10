import json
import os
import threading
from datetime import datetime

from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import scoped_package_path
from PushShoppingList.services.storage_service import user_data_root


OPENAI_USAGE_FILE = scoped_package_path("openai_usage.json")
MAX_USAGE_RECORDS = int(os.getenv("SHOPPING_APP_OPENAI_USAGE_RECORD_LIMIT", "2000"))
RECIPE_IMPORT_FEATURES = {
    "audio-transcription",
    "social-video-audio-image-extraction",
    "video-recipe-pdf-extraction",
    "recipe-text-extraction",
    "recipe-image-extraction",
    "recipe-file-extraction",
}
PRODUCT_SEARCH_FEATURES = {
    "product-page-analysis",
    "rendered-html-product-reasoning",
    "store-product-ranking",
    "final-product-selection",
}
GENERATED_IMAGE_FEATURES = {
    "recipe-step-image",
}
RECIPE_IMPORT_ACTIVITY_FEATURES = {
    "recipe-import",
    "recipe-media-import",
}
OPENAI_RECORD_TYPE = "openai-api"
APP_ACTIVITY_RECORD_TYPE = "app-activity"
DEFAULT_BILLING_CURRENCY = "USD"
OPENAI_USAGE_LOCK = threading.RLock()


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
    resolved_feature = str(feature or "openai-api").strip() or "openai-api"
    resolved_model = str(model or extract_response_model(response) or "").strip()
    billing_costs = estimate_openai_billing_costs(
        usage,
        model=resolved_model,
        feature=resolved_feature,
    )

    if not usage.get("total_tokens") and billing_costs.get("estimatedCostUsd") is None:
        return None

    record_user_id = str(user_id if user_id is not None else active_user_id()).strip()
    if not record_user_id:
        return None

    usage_file = openai_usage_file_for_user(record_user_id)
    record = normalize_usage_record({
        "createdAt": now_iso(),
        "month": current_month_key(),
        "userId": record_user_id,
        "recordType": OPENAI_RECORD_TYPE,
        "feature": resolved_feature,
        "model": resolved_model,
        "promptTokens": usage.get("prompt_tokens", 0),
        "completionTokens": usage.get("completion_tokens", 0),
        "totalTokens": usage.get("total_tokens", 0),
        **billing_costs,
        "metadata": metadata if isinstance(metadata, dict) else {},
    })
    with OPENAI_USAGE_LOCK:
        payload = load_openai_usage_payload(usage_file)
        payload.setdefault("records", []).append(record)
        save_openai_usage_payload(payload, usage_file)
    return record


def record_app_activity(feature, metadata=None, user_id=None):
    record_user_id = str(user_id if user_id is not None else active_user_id()).strip()
    if not record_user_id:
        return None

    usage_file = openai_usage_file_for_user(record_user_id)
    record = normalize_usage_record({
        "createdAt": now_iso(),
        "month": current_month_key(),
        "userId": record_user_id,
        "recordType": APP_ACTIVITY_RECORD_TYPE,
        "feature": str(feature or "app-activity").strip() or "app-activity",
        "model": "",
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "estimatedCostUsd": None,
        "rawCostUsd": None,
        "billableCostUsd": None,
        "metadata": metadata if isinstance(metadata, dict) else {},
    })
    with OPENAI_USAGE_LOCK:
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
    return estimate_openai_billing_costs(usage).get("estimatedCostUsd")


def estimate_openai_billing_costs(usage, model=None, feature=None):
    pricing = openai_pricing_config(model=model, feature=feature)
    input_rate = pricing.get("inputCostPer1MTokens")
    output_rate = pricing.get("outputCostPer1MTokens")
    fixed_feature_cost = pricing.get("fixedFeatureCostUsd")
    token_cost = None

    if input_rate is not None and output_rate is not None:
        token_cost = (
            (usage.get("prompt_tokens", 0) / 1_000_000) * input_rate
            + (usage.get("completion_tokens", 0) / 1_000_000) * output_rate
        )

    raw_cost = None
    if token_cost is not None or fixed_feature_cost is not None:
        raw_cost = round((token_cost or 0) + (fixed_feature_cost or 0), 6)

    markup_percent = pricing.get("markupPercent")
    if markup_percent is None:
        markup_percent = 0

    billable_cost = None
    if raw_cost is not None:
        billable_cost = round(raw_cost * (1 + (markup_percent / 100)), 6)

    return {
        "estimatedCostUsd": raw_cost,
        "rawCostUsd": raw_cost,
        "billableCostUsd": billable_cost,
        "billingCurrency": pricing.get("billingCurrency") or DEFAULT_BILLING_CURRENCY,
        "pricingSource": pricing.get("pricingSource") or "unconfigured",
        "inputCostPer1MTokens": input_rate,
        "outputCostPer1MTokens": output_rate,
        "fixedFeatureCostUsd": fixed_feature_cost,
        "markupPercent": markup_percent,
    }


def openai_pricing_config(model=None, feature=None):
    model_rates = env_json_object("SHOPPING_APP_OPENAI_MODEL_RATES_JSON")
    feature_costs = env_json_object("SHOPPING_APP_OPENAI_FEATURE_COSTS_JSON")
    model_config = lookup_case_insensitive(model_rates, model)
    feature_config = lookup_case_insensitive(feature_costs, feature)
    default_markup = env_float("SHOPPING_APP_OPENAI_BILLING_MARKUP_PERCENT")
    default_markup = default_markup if default_markup is not None else 0
    default_currency = env_label(
        "SHOPPING_APP_OPENAI_BILLING_CURRENCY",
        default=DEFAULT_BILLING_CURRENCY,
    ).upper()

    input_rate = env_float("SHOPPING_APP_OPENAI_INPUT_COST_PER_1M_TOKENS")
    output_rate = env_float("SHOPPING_APP_OPENAI_OUTPUT_COST_PER_1M_TOKENS")
    fixed_feature_cost = None
    markup_percent = default_markup
    pricing_parts = []

    if isinstance(model_config, dict):
        model_input_rate = config_float(
            model_config,
            "inputCostPer1MTokens",
            "input_cost_per_1m_tokens",
            "input_rate_per_1m",
        )
        model_output_rate = config_float(
            model_config,
            "outputCostPer1MTokens",
            "output_cost_per_1m_tokens",
            "output_rate_per_1m",
        )
        input_rate = model_input_rate if model_input_rate is not None else input_rate
        output_rate = model_output_rate if model_output_rate is not None else output_rate
        model_markup = config_float(
            model_config,
            "billableMarkupPercent",
            "markupPercent",
            "markup_percent",
        )
        if model_markup is not None:
            markup_percent = model_markup
        pricing_parts.append("model")

    if isinstance(feature_config, dict):
        fixed_feature_cost = config_float(
            feature_config,
            "fixedFeatureCostUsd",
            "fixedCostUsd",
            "fixed_cost_usd",
            "costUsd",
            "cost_usd",
        )
        feature_markup = config_float(
            feature_config,
            "billableMarkupPercent",
            "markupPercent",
            "markup_percent",
        )
        if feature_markup is not None:
            markup_percent = feature_markup
        pricing_parts.append("feature")
    elif feature_config is not None:
        fixed_feature_cost = float_or_none(feature_config)
        pricing_parts.append("feature")

    if not pricing_parts and input_rate is not None and output_rate is not None:
        pricing_parts.append("default")

    return {
        "inputCostPer1MTokens": input_rate,
        "outputCostPer1MTokens": output_rate,
        "fixedFeatureCostUsd": fixed_feature_cost,
        "markupPercent": markup_percent,
        "billingCurrency": default_currency or DEFAULT_BILLING_CURRENCY,
        "pricingSource": "+".join(pricing_parts) if pricing_parts else "unconfigured",
    }


def env_json_object(name):
    value = str(os.getenv(name, "") or "").strip()

    if not value:
        return {}

    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return {}

    return payload if isinstance(payload, dict) else {}


def lookup_case_insensitive(payload, key):
    key = str(key or "").strip().lower()
    if not isinstance(payload, dict) or not key:
        return None

    for candidate, value in payload.items():
        if str(candidate or "").strip().lower() == key:
            return value
    return None


def config_float(payload, *names):
    if not isinstance(payload, dict):
        return None

    normalized = {
        str(key or "").strip().lower(): value
        for key, value in payload.items()
    }

    for name in names:
        value = normalized.get(str(name or "").strip().lower())
        converted = float_or_none(value)
        if converted is not None:
            return converted
    return None


def float_or_none(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def env_label(*names, default=""):
    for name in names:
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
    return default


def normalize_usage_record(record):
    prompt_tokens = int_or_zero(record.get("promptTokens") or record.get("prompt_tokens"))
    completion_tokens = int_or_zero(record.get("completionTokens") or record.get("completion_tokens"))
    total_tokens = int_or_zero(record.get("totalTokens") or record.get("total_tokens"))

    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    estimated_cost = float_or_none(record.get("estimatedCostUsd"))
    raw_cost = float_or_none(record.get("rawCostUsd"))
    billable_cost = float_or_none(record.get("billableCostUsd"))

    if raw_cost is None:
        raw_cost = estimated_cost
    if billable_cost is None:
        billable_cost = raw_cost
    pricing_source = str(record.get("pricingSource") or "").strip()
    if not pricing_source:
        pricing_source = "legacy" if billable_cost is not None else "unconfigured"

    return {
        "createdAt": str(record.get("createdAt") or record.get("created_at") or now_iso()),
        "month": str(record.get("month") or current_month_key()),
        "userId": str(record.get("userId") or record.get("user_id") or "").strip(),
        "recordType": normalize_record_type(record.get("recordType") or record.get("record_type")),
        "feature": str(record.get("feature") or "openai-api").strip() or "openai-api",
        "model": str(record.get("model") or "").strip(),
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUsd": estimated_cost,
        "rawCostUsd": raw_cost,
        "billableCostUsd": billable_cost,
        "billingCurrency": str(record.get("billingCurrency") or DEFAULT_BILLING_CURRENCY).strip().upper() or DEFAULT_BILLING_CURRENCY,
        "pricingSource": pricing_source,
        "inputCostPer1MTokens": float_or_none(record.get("inputCostPer1MTokens")),
        "outputCostPer1MTokens": float_or_none(record.get("outputCostPer1MTokens")),
        "fixedFeatureCostUsd": float_or_none(record.get("fixedFeatureCostUsd")),
        "markupPercent": float_or_none(record.get("markupPercent")) or 0,
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
    }


def int_or_zero(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_record_type(value):
    value = str(value or "").strip().lower()
    if value == APP_ACTIVITY_RECORD_TYPE:
        return APP_ACTIVITY_RECORD_TYPE
    return OPENAI_RECORD_TYPE


def openai_usage_dashboard_for_user(user=None):
    user_id = ""
    if isinstance(user, dict):
        user_id = str(user.get("user_id") or "").strip()
    payload = load_openai_usage_payload(openai_usage_file_for_user(user_id))
    records = payload.get("records", [])
    api_records = [
        record
        for record in records
        if record.get("recordType") != APP_ACTIVITY_RECORD_TYPE
    ]
    month = current_month_key()
    month_records = [record for record in records if record.get("month") == month]
    month_api_records = [record for record in api_records if record.get("month") == month]
    monthly_limit = env_int("SHOPPING_APP_OPENAI_MONTHLY_TOKEN_LIMIT")
    monthly_budget = env_float("SHOPPING_APP_OPENAI_MONTHLY_BUDGET_USD")
    month_prompt = sum_tokens(month_api_records, "promptTokens")
    month_completion = sum_tokens(month_api_records, "completionTokens")
    month_total = sum_tokens(month_api_records, "totalTokens")
    lifetime_total = sum_tokens(api_records, "totalTokens")
    estimated_month_cost = sum_record_cost(month_api_records, "estimatedCostUsd")
    billable_month_cost = sum_record_cost(month_api_records, "billableCostUsd")
    unavailable_cost_label = "Pricing not configured" if month_api_records else "Not available yet"
    limit_remaining = monthly_limit - month_total if monthly_limit is not None else None
    budget_spend = billable_month_cost if billable_month_cost is not None else (estimated_month_cost or 0)
    budget_remaining = monthly_budget - budget_spend if monthly_budget is not None else None
    activity_counts = openai_activity_counts(month_records)
    billing_type_label = env_label(
        "SHOPPING_APP_OPENAI_BILLING_TYPE_LABEL",
        "SHOPPING_APP_OPENAI_SUBSCRIPTION_LABEL",
        default="OpenAI API Pay-As-You-Go",
    )

    return {
        "plan_label": os.getenv("SHOPPING_APP_OPENAI_PLAN_LABEL", "Personal Workspace"),
        "billing_type_label": billing_type_label,
        "subscription_label": billing_type_label,
        "month_label": month,
        "monthly_token_limit": monthly_limit,
        "monthly_token_limit_label": number_label(monthly_limit) if monthly_limit is not None else "Not set",
        "monthly_budget_usd": monthly_budget,
        "monthly_budget_label": money_label(monthly_budget) if monthly_budget is not None else "Not set",
        "monthly_prompt_tokens": month_prompt,
        "monthly_completion_tokens": month_completion,
        "monthly_total_tokens": month_total,
        "monthly_request_count": len(month_api_records),
        "monthly_estimated_cost": estimated_month_cost,
        "monthly_estimated_cost_label": money_label(estimated_month_cost) if estimated_month_cost is not None else unavailable_cost_label,
        "monthly_billable_cost": billable_month_cost,
        "monthly_billable_cost_label": money_label(billable_month_cost) if billable_month_cost is not None else unavailable_cost_label,
        "monthly_tokens_remaining": limit_remaining,
        "monthly_tokens_remaining_label": number_label(max(0, limit_remaining)) if limit_remaining is not None else "No limit set",
        "monthly_budget_remaining": budget_remaining,
        "monthly_budget_remaining_label": money_label(max(0, budget_remaining)) if budget_remaining is not None else "No budget set",
        "limit_percent": percent_used(month_total, monthly_limit),
        "budget_percent": percent_used(budget_spend, monthly_budget) if monthly_budget is not None and budget_spend is not None else None,
        "monthly_recipe_import_count": activity_counts["recipe_imports"],
        "monthly_pantry_scan_count": activity_counts["pantry_scans"],
        "monthly_product_search_count": activity_counts["product_searches"],
        "monthly_generated_image_count": activity_counts["generated_images"],
        "monthly_budget_configured": monthly_budget is not None,
        "lifetime_total_tokens": lifetime_total,
        "lifetime_request_count": len(api_records),
        "last_used_at": latest_record_timestamp(api_records),
        "last_used_at_label": display_datetime(latest_record_timestamp(api_records)),
        "records_tracked": len(records),
        "api_records_tracked": len(api_records),
        "has_usage": bool(api_records),
        "has_activity": bool(records),
        "tracking_note": (
            "This dashboard tracks only OpenAI API usage returned from requests made by this shopping-list app. "
            "ChatGPT website/app subscription usage is separate and cannot be shown here. "
            "Billable AI Cost uses this app's configured pricing ledger and can differ from the raw OpenAI API estimate."
        ),
        "pricing_note": (
            "Configure OpenAI API pricing rates to calculate Estimated API Cost and Billable AI Cost."
            if month_api_records and estimated_month_cost is None
            else ""
        ),
        "empty_state_message": (
            "No OpenAI API usage has been recorded for this app yet. "
            "When this app makes OpenAI API requests, token usage and estimated costs will appear here. "
            "Note: ChatGPT website/app subscription usage is separate and cannot be shown in this local dashboard."
        ),
    }


def openai_activity_counts(records):
    counts = {
        "recipe_imports": 0,
        "pantry_scans": 0,
        "product_searches": 0,
        "generated_images": 0,
    }
    recipe_import_activity_count = 0
    legacy_recipe_import_count = 0

    for record in records:
        feature = str(record.get("feature") or "").strip().lower()
        record_type = record.get("recordType")

        if feature in RECIPE_IMPORT_ACTIVITY_FEATURES:
            recipe_import_activity_count += 1
        elif feature in RECIPE_IMPORT_FEATURES and record_type != APP_ACTIVITY_RECORD_TYPE:
            legacy_recipe_import_count += 1
        elif feature in PRODUCT_SEARCH_FEATURES:
            counts["product_searches"] += 1
        elif feature in GENERATED_IMAGE_FEATURES:
            counts["generated_images"] += 1
        elif "pantry" in feature or "scan" in feature or "photo" in feature:
            counts["pantry_scans"] += 1

    counts["recipe_imports"] = recipe_import_activity_count or legacy_recipe_import_count
    return counts


def sum_tokens(records, key):
    return sum(int_or_zero(record.get(key)) for record in records)


def sum_record_cost(records, key):
    values = []
    for record in records:
        value = record_cost_value(record, key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return round(sum(values), 6)


def record_cost_value(record, key):
    value = float_or_none(record.get(key))
    if value is not None:
        return value

    derived_costs = estimate_openai_billing_costs(
        {
            "prompt_tokens": int_or_zero(record.get("promptTokens")),
            "completion_tokens": int_or_zero(record.get("completionTokens")),
            "total_tokens": int_or_zero(record.get("totalTokens")),
        },
        model=record.get("model"),
        feature=record.get("feature"),
    )
    return derived_costs.get(key)


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
