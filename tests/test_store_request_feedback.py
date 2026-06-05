import re

from flask import render_template
from werkzeug.datastructures import MultiDict

from PushShoppingList.app import create_app
from PushShoppingList.services import feedback_service


def test_store_request_feedback_type_can_be_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback_service, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(feedback_service, "FEEDBACK_UPLOAD_DIR", tmp_path / "uploads")

    result = feedback_service.create_feedback(
        {
            "user_id": "user-1",
            "username": "user@example.com",
            "email": "user@example.com",
        },
        MultiDict({
            "feedback_type": "Store Request",
            "subject": "Request store: Fresh Market",
            "description": "Store name: Fresh Market",
        }),
        MultiDict(),
    )

    assert result["ok"] is True
    assert result["feedback_id"] == "FB-1001"

    saved = feedback_service.load_feedback_payload()
    assert saved["feedback"][0]["feedback_type"] == "Store Request"
    assert saved["feedback"][0]["subject"] == "Request store: Fresh Market"


def test_store_request_button_starts_feedback_workflow():
    store_template = open(
        "PushShoppingList/templates/sections/store_options.html",
        encoding="utf-8",
    ).read()
    feedback_template = open(
        "PushShoppingList/templates/sections/feedback_support.html",
        encoding="utf-8",
    ).read()
    script = open("PushShoppingList/static/js/app.js", encoding="utf-8").read()

    assert "data-feedback-store-request" in store_template
    assert "openStoreRequestFeedback(this)" in store_template
    assert "feedbackTypeInput" in feedback_template
    assert "feedbackSubjectInput" in feedback_template
    assert "feedbackDescriptionInput" in feedback_template
    assert "function openStoreRequestFeedback" in script
    assert "function prefillStoreRequestFeedback" in script
    assert "Store Request" in script
    assert "Store selector/location URL:" in script


def test_store_request_button_is_directly_under_find_nearest_stores():
    store_template = open(
        "PushShoppingList/templates/sections/store_options.html",
        encoding="utf-8",
    ).read()

    find_index = store_template.index("Find Nearest Stores")
    request_index = store_template.index("Request Store")
    search_index = store_template.index("Search stores by name")

    assert find_index < request_index < search_index


def test_feedback_support_header_counts_current_user_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback_service, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(feedback_service, "FEEDBACK_UPLOAD_DIR", tmp_path / "uploads")

    current_user = {
        "user_id": "user-1",
        "username": "user@example.com",
        "email": "user@example.com",
    }
    other_user = {
        "user_id": "user-2",
        "username": "other@example.com",
        "email": "other@example.com",
    }

    for subject in ("Request store: Fresh Market", "Request store: H Mart"):
        feedback_service.create_feedback(
            current_user,
            MultiDict({
                "feedback_type": "Store Request",
                "subject": subject,
                "description": "Store name:",
            }),
            MultiDict(),
        )

    feedback_service.create_feedback(
        other_user,
        MultiDict({
            "feedback_type": "Store Request",
            "subject": "Request store: Other Store",
            "description": "Store name:",
        }),
        MultiDict(),
    )

    app = create_app()
    with app.test_request_context("/"):
        html = render_template(
            "sections/feedback_support.html",
            current_user=current_user,
            feedback_dashboard=feedback_service.feedback_dashboard_for_user(current_user),
            feedback_messages=[],
        )

    assert "feedback-support-header-count" in html
    assert re.search(r"feedback-support-header-count\">\s*2\s*requests", html)
    assert not re.search(r"feedback-support-header-count\">\s*3\s*requests", html)
    assert "support@recipeshoppinglist.com" in html


def test_feedback_support_header_shows_zero_request_count_for_guest():
    app = create_app()
    with app.test_request_context("/"):
        html = render_template(
            "sections/feedback_support.html",
            current_user=None,
            feedback_dashboard=feedback_service.feedback_dashboard_for_user(None),
            feedback_messages=[],
        )

    assert "feedback-support-header-count" in html
    assert re.search(r"feedback-support-header-count\">\s*0\s*requests", html)
    assert "support@recipeshoppinglist.com" in html
