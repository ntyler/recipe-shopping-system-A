import json

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
    accounts.save_users({"users": [
        make_user("user-1", "user1@example.com"),
        make_user("user-2", "user2@example.com"),
    ]})
    seed_feedback(feedback_file)
    return feedback_file


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def unread_notification(feedback_file):
    payload = json.loads(feedback_file.read_text(encoding="utf-8"))
    return payload["feedback"][0]["notifications"][0]


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
