import json
from io import BytesIO

from PushShoppingList.app import create_app
from PushShoppingList.services import feedback_service
from PushShoppingList.services import user_account_service as accounts


def make_user(user_id, email):
    return {
        "user_id": user_id,
        "username": email,
        "email": email,
        "auth_provider": "local",
        "account_status": "active",
        "created_at": "2026-06-04T12:00:00Z",
    }


def seed_feedback(path):
    path.write_text(
        json.dumps({
            "feedback": [{
                "feedback_id": "FB-1001",
                "user": {
                    "user_id": "user-1",
                    "username": "user1@example.com",
                    "email": "user1@example.com",
                },
                "created_at": "2026-06-04T12:00:00Z",
                "updated_at": "2026-06-04T13:00:00Z",
                "feedback_type": "Bug Report",
                "subject": "Button error",
                "description": "Mark read fails.",
                "attachments": [],
                "status": "Investigating",
                "admin_notes": "Looking into it.",
                "resolution_notes": "",
                "admin_attachments": [],
                "timeline": [{
                    "status": "Submitted",
                    "timestamp": "2026-06-04T12:00:00Z",
                    "actor": "user1@example.com",
                }],
                "notifications": [{
                    "notification_id": "notice-1",
                    "user_id": "user-1",
                    "message": "Your feedback FB-1001 was updated.",
                    "created_at": "2026-06-04T13:00:00Z",
                    "read_at": "",
                }],
            }],
        }),
        encoding="utf-8",
    )


def configure_feedback(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    feedback_file = tmp_path / "feedback.json"

    monkeypatch.setattr(accounts, "USERS_FILE", users_file)
    monkeypatch.setattr(feedback_service, "FEEDBACK_FILE", feedback_file)
    monkeypatch.setattr(feedback_service, "FEEDBACK_UPLOAD_DIR", tmp_path / "uploads")
    accounts.save_users({"users": [
        make_user("user-1", "user1@example.com"),
        make_user("user-2", "user2@example.com"),
        make_user("admin-1", "admin@example.com"),
    ]})
    seed_feedback(feedback_file)
    return feedback_file


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def unread_notification(feedback_file):
    payload = json.loads(feedback_file.read_text(encoding="utf-8"))
    return payload["feedback"][0]["notifications"][0]


def stored_feedback(feedback_file):
    payload = json.loads(feedback_file.read_text(encoding="utf-8"))
    return payload["feedback"][0]


def stored_feedback_items(feedback_file):
    payload = json.loads(feedback_file.read_text(encoding="utf-8"))
    return payload["feedback"]


def test_feedback_owner_can_mark_updates_read(monkeypatch, tmp_path):
    feedback_file = configure_feedback(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "user-1")

        response = client.post("/feedback/FB-1001/mark-read")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#feedback-FB-1001")
        assert unread_notification(feedback_file)["read_at"]


def test_feedback_non_owner_cannot_mark_updates_read(monkeypatch, tmp_path):
    feedback_file = configure_feedback(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "user-2")

        response = client.post("/feedback/FB-1001/mark-read")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#feedback-FB-1001")
        assert unread_notification(feedback_file)["read_at"] == ""

        with client.session_transaction() as session:
            assert session["feedback_messages"] == [{
                "category": "error",
                "text": "Feedback item was not found.",
            }]


def test_feedback_owner_can_reply_and_reopen_resolved_ticket(monkeypatch, tmp_path):
    feedback_file = configure_feedback(monkeypatch, tmp_path)
    payload = json.loads(feedback_file.read_text(encoding="utf-8"))
    payload["feedback"][0]["status"] = "Resolved"
    feedback_file.write_text(json.dumps(payload), encoding="utf-8")
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "user-1")

        comment_response = client.post(
            "/feedback/FB-1001/comment",
            data={"commentText": "This is still happening."},
        )
        reopen_response = client.post("/feedback/FB-1001/reopen")

        feedback = stored_feedback(feedback_file)
        assert comment_response.status_code == 302
        assert reopen_response.status_code == 302
        assert feedback["comments"][0]["commentText"] == "This is still happening."
        assert feedback["comments"][0]["authorUid"] == "user-1"
        assert feedback["comments"][0]["authorEmail"] == "user1@example.com"
        assert feedback["comments"][0]["authorType"] == "user"
        assert "createdAt" in feedback["comments"][0]
        assert any(entry["event"] == "User Comment Added" for entry in feedback["timeline"])
        assert feedback["status"] == "Investigating"
        assert any(entry["event"] == "Reopened" for entry in feedback["timeline"])


def test_feedback_admin_update_saves_priority_support_comment_and_public_identity(monkeypatch, tmp_path):
    feedback_file = configure_feedback(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "admin-1")

        response = client.post(
            "/feedback/FB-1001/admin",
            data={
                "status": "Waiting on User",
                "priority": "Critical",
                "admin_notes": "Please send a screenshot.",
                "resolution_notes": "Pending user screenshot.",
                "support_comment": "Thanks for the report.",
            },
        )

        feedback = stored_feedback(feedback_file)
        assert response.status_code == 302
        assert feedback["status"] == "Waiting on User"
        assert feedback["priority"] == "Critical"
        assert feedback["comments"][0]["authorType"] == "support"
        assert feedback["comments"][0]["authorEmail"] == "admin@example.com"
        assert feedback["comments"][0]["authorPublicEmail"] == "support@recipeshoppinglist.com"
        assert any(entry["event"] == "Support Update Added" for entry in feedback["timeline"])
        assert any(entry["event"] == "Resolution Notes Added" for entry in feedback["timeline"])
        assert any("RSL-FB-1001" in notification["message"] for notification in feedback["notifications"])


def test_feedback_submit_labels_attachments_for_ticket_display(monkeypatch, tmp_path):
    feedback_file = configure_feedback(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "user-1")

        response = client.post(
            "/feedback/submit",
            data={
                "feedback_type": "Bug Report",
                "subject": "Upload labels",
                "description": "Files should be visible in the ticket.",
                "screenshot": (BytesIO(b"fake image"), "screen.png"),
                "attachment": (BytesIO(b"fake pdf"), "details.pdf"),
            },
            content_type="multipart/form-data",
        )

        feedback = stored_feedback_items(feedback_file)[-1]
        dashboard = feedback_service.feedback_dashboard_for_user(make_user("user-1", "user1@example.com"))
        view = next(item for item in dashboard["my_feedback"] if item["feedback_id"] == feedback["feedback_id"])

        assert response.status_code == 302
        assert feedback["attachments"][0]["attachment_type"] == "screenshot"
        assert feedback["attachments"][1]["attachment_type"] == "file"
        assert [item["display_label"] for item in view["user_attachments"]] == ["Screenshot", "Uploaded File"]
        assert [item["original_name"] for item in view["user_attachments"]] == ["screen.png", "details.pdf"]


def test_feedback_user_view_uses_public_support_identity(monkeypatch, tmp_path):
    feedback_file = configure_feedback(monkeypatch, tmp_path)
    payload = json.loads(feedback_file.read_text(encoding="utf-8"))
    payload["feedback"][0]["timeline"].append({
        "event": "Investigating",
        "timestamp": "2026-06-04T13:30:00Z",
        "actorPrivateEmail": "admin@example.com",
        "actorType": "support",
    })
    payload["feedback"][0]["comments"] = [{
        "commentText": "Support reply.",
        "authorEmail": "admin@example.com",
        "authorPrivateEmail": "admin@example.com",
        "authorType": "support",
        "createdAt": "2026-06-04T13:35:00Z",
    }]
    feedback_file.write_text(json.dumps(payload), encoding="utf-8")

    dashboard = feedback_service.feedback_dashboard_for_user(make_user("user-1", "user1@example.com"))
    feedback = dashboard["my_feedback"][0]

    assert feedback["timeline"][-1]["display_actor"] == "support@recipeshoppinglist.com"
    assert feedback["comments"][0]["display_author"] == "support@recipeshoppinglist.com"
    assert feedback["comments"][0]["author_type_label"] == "Support Team"
