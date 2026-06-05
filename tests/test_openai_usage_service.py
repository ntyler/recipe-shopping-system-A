from pathlib import Path

from PushShoppingList.services import openai_usage_service
from PushShoppingList.services import storage_service


ROOT = Path(__file__).resolve().parents[1]


class FakeUsage:
    prompt_tokens = 100
    completion_tokens = 50
    total_tokens = 150


class FakeResponse:
    usage = FakeUsage()
    model = "gpt-test"


def test_openai_usage_records_response_tokens_and_dashboard_totals(tmp_path, monkeypatch):
    usage_file = tmp_path / "openai_usage.json"
    monkeypatch.setattr(openai_usage_service, "OPENAI_USAGE_FILE", usage_file)
    monkeypatch.setattr(openai_usage_service, "active_user_id", lambda: "user-123")
    monkeypatch.setenv("SHOPPING_APP_OPENAI_MONTHLY_TOKEN_LIMIT", "300")
    monkeypatch.setenv("SHOPPING_APP_OPENAI_MONTHLY_BUDGET_USD", "10")
    monkeypatch.setenv("SHOPPING_APP_OPENAI_INPUT_COST_PER_1M_TOKENS", "5")
    monkeypatch.setenv("SHOPPING_APP_OPENAI_OUTPUT_COST_PER_1M_TOKENS", "15")
    monkeypatch.setenv("SHOPPING_APP_OPENAI_PLAN_LABEL", "Kitchen Test Plan")
    monkeypatch.setenv("SHOPPING_APP_OPENAI_SUBSCRIPTION_LABEL", "API Usage Billing")

    record = openai_usage_service.record_openai_usage(
        FakeResponse(),
        "unit-test-feature",
        metadata={"source": "pytest"},
    )

    assert record["userId"] == "user-123"
    assert record["feature"] == "unit-test-feature"
    assert record["model"] == "gpt-test"
    assert record["promptTokens"] == 100
    assert record["completionTokens"] == 50
    assert record["totalTokens"] == 150
    assert record["metadata"] == {"source": "pytest"}

    dashboard = openai_usage_service.openai_usage_dashboard_for_user()

    assert dashboard["has_usage"] is True
    assert dashboard["plan_label"] == "Kitchen Test Plan"
    assert dashboard["subscription_label"] == "API Usage Billing"
    assert dashboard["monthly_token_limit_label"] == "300"
    assert dashboard["monthly_total_tokens"] == 150
    assert dashboard["monthly_prompt_tokens"] == 100
    assert dashboard["monthly_completion_tokens"] == 50
    assert dashboard["monthly_request_count"] == 1
    assert dashboard["monthly_tokens_remaining_label"] == "150"
    assert dashboard["limit_percent"] == 50.0
    assert dashboard["monthly_estimated_cost_label"] == "$0.0013"
    assert dashboard["monthly_budget_label"] == "$10.0000"
    assert dashboard["lifetime_total_tokens"] == 150
    assert dashboard["last_used_at_label"] != "Not recorded yet"
    assert "ChatGPT app or website subscription usage is not exposed" in dashboard["tracking_note"]


def test_openai_usage_dashboard_defaults_when_no_tokens_are_recorded(tmp_path, monkeypatch):
    usage_file = tmp_path / "openai_usage.json"
    monkeypatch.setattr(openai_usage_service, "OPENAI_USAGE_FILE", usage_file)
    monkeypatch.delenv("SHOPPING_APP_OPENAI_MONTHLY_TOKEN_LIMIT", raising=False)
    monkeypatch.delenv("SHOPPING_APP_OPENAI_MONTHLY_BUDGET_USD", raising=False)

    dashboard = openai_usage_service.openai_usage_dashboard_for_user()

    assert dashboard["has_usage"] is False
    assert dashboard["monthly_token_limit_label"] == "Not set"
    assert dashboard["monthly_tokens_remaining_label"] == "No limit set"
    assert dashboard["monthly_budget_label"] == "Not set"
    assert dashboard["monthly_estimated_cost_label"] == "Cost rates not set"
    assert dashboard["monthly_total_tokens"] == 0
    assert dashboard["monthly_request_count"] == 0
    assert dashboard["last_used_at_label"] == "Not recorded yet"


def test_openai_usage_does_not_write_anonymous_usage_file(tmp_path, monkeypatch):
    usage_file = tmp_path / "openai_usage.json"
    monkeypatch.setattr(openai_usage_service, "OPENAI_USAGE_FILE", usage_file)
    monkeypatch.setattr(openai_usage_service, "active_user_id", lambda: "")

    record = openai_usage_service.record_openai_usage(FakeResponse(), "anonymous-test")

    assert record is None
    assert not usage_file.exists()


def test_openai_usage_can_record_for_explicit_user_from_worker_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(openai_usage_service, "active_user_id", lambda: "")

    record = openai_usage_service.record_openai_usage(
        FakeResponse(),
        "threaded-product-test",
        user_id="thread-user",
    )

    usage_file = tmp_path / "users" / "thread-user" / "openai_usage.json"
    dashboard = openai_usage_service.openai_usage_dashboard_for_user({"user_id": "thread-user"})

    assert record["userId"] == "thread-user"
    assert usage_file.exists()
    assert dashboard["monthly_total_tokens"] == 150
    assert dashboard["monthly_request_count"] == 1


def test_openai_usage_tracking_is_wired_to_app_openai_call_sites():
    expected_features = {
        "address-completion",
        "audio-transcription",
        "video-recipe-pdf-extraction",
        "recipe-text-extraction",
        "recipe-image-extraction",
        "recipe-file-extraction",
        "product-page-analysis",
        "rendered-html-product-reasoning",
        "store-product-ranking",
        "final-product-selection",
        "food-rules",
        "ingredient-text-review",
        "food-review-alternatives",
        "recipe-quantity-scaling",
        "nutrition-estimate",
        "recipe-note-feedback",
        "recipe-step-image",
    }
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "PushShoppingList/routes/main_routes.py",
            ROOT / "PushShoppingList/services/recipe_extract_service.py",
            ROOT / "PushShoppingList/services/product_selection_service.py",
            ROOT / "PushShoppingList/services/food_rules_service.py",
            ROOT / "PushShoppingList/services/ingredient_text_review_service.py",
            ROOT / "PushShoppingList/services/food_review_alternative_service.py",
            ROOT / "PushShoppingList/services/recipe_quantity_service.py",
            ROOT / "PushShoppingList/services/recipe_edit_service.py",
        ]
    )

    for feature in expected_features:
        assert f'"{feature}"' in source_text
