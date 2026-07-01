import re
import json

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


def test_store_request_button_sits_next_to_find_nearest_stores():
    store_template = open(
        "PushShoppingList/templates/sections/store_options.html",
        encoding="utf-8",
    ).read()
    css = open("PushShoppingList/static/css/app.css", encoding="utf-8").read()

    find_index = store_template.index("Find Nearest Stores")
    request_index = store_template.index("Request Store")
    search_index = store_template.index("Search stores by name")

    assert find_index < request_index < search_index
    assert ".store-options-sticky-toolbar .address-actions-grid" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert ".store-options-toolbar-search" in css
    assert "grid-column: 1 / -1;" in css


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


def test_feedback_ticket_portal_renders_public_support_identity(monkeypatch, tmp_path):
    feedback_file = tmp_path / "feedback.json"
    monkeypatch.setattr(feedback_service, "FEEDBACK_FILE", feedback_file)

    user = {
        "user_id": "user-1",
        "username": "user@example.com",
        "email": "user@example.com",
    }
    feedback_file.write_text(
        json.dumps({
            "feedback": [{
                "feedback_id": "FB-1001",
                "user": user,
                "created_at": "2026-06-04T12:00:00Z",
                "updated_at": "2026-06-04T13:00:00Z",
                "feedback_type": "Bug Report",
                "subject": "Button error",
                "description": "Mark read fails.",
                "attachments": [],
                "status": "Resolved",
                "admin_notes": "We found the issue.",
                "resolution_notes": "A fix was shipped.",
                "admin_attachments": [],
                "timeline": [{
                    "event": "Support Update Added",
                    "status": "Investigating",
                    "timestamp": "2026-06-04T13:00:00Z",
                    "actor": "admin@example.com",
                }],
                "notifications": [{
                    "notification_id": "notice-1",
                    "user_id": "user-1",
                    "message": "Your feedback FB-1001 was updated.",
                    "created_at": "2026-06-04T13:00:00Z",
                    "read_at": "",
                }],
                "comments": [{
                    "commentText": "Can you try it again?",
                    "authorUid": "admin-1",
                    "authorEmail": "admin@example.com",
                    "authorType": "support",
                    "createdAt": "2026-06-04T13:01:00Z",
                }],
            }],
        }),
        encoding="utf-8",
    )

    app = create_app()
    with app.test_request_context("/"):
        feedback = feedback_service.feedback_dashboard_for_user(user)["my_feedback"][0]
        html = render_template(
            "sections/feedback_ticket.html",
            current_user=user,
            feedback=feedback,
        )

    assert "RSL-FB-1001" in html
    assert "Support Team" in html
    assert "Admin Update" not in html
    assert "support@recipeshoppinglist.com" in html
    assert "admin@example.com" not in html
    assert "Normal Priority" in html
    assert "Reply to Support" in html
    assert "Reopen Ticket" in html
