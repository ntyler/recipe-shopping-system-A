from PushShoppingList.services import user_account_service as accounts


def configure_users_file(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")


def seed_user():
    return {
        "user_id": "user-1",
        "username": "user@example.com",
        "email": "user@example.com",
        "first_name": "Recipe",
        "last_name": "User",
        "created_at": "2026-06-05T10:00:00Z",
    }


def test_update_notification_settings_stores_topic_and_browser_subscription(monkeypatch, tmp_path):
    configure_users_file(monkeypatch, tmp_path)
    monkeypatch.setattr(accounts, "generate_ntfy_topic", lambda: "shopping-user-test-token")
    accounts.save_users({"users": [seed_user()]})

    subscription = {
        "endpoint": "https://push.example/subscription",
        "keys": {
            "p256dh": "public-key",
            "auth": "auth-key",
        },
    }

    result = accounts.update_notification_settings(
        "user-1",
        enabled=True,
        browser_subscription=subscription,
        browser_permission="granted",
        preferences={
            "recipe_import_complete": True,
            "feedback_response": False,
        },
    )

    assert result["ok"] is True
    public = result["user"]
    assert public["notification_topic"] == "shopping-user-test-token"
    assert public["ntfy_topic"] == "shopping-user-test-token"
    assert public["notifications_enabled"] is True
    assert public["browser_push_connected"] is True
    assert public["notification_preferences"]["feedback_response"] is False
    assert public["notification_devices"][0]["name"] == "Browser"
    assert public["notification_devices"][0]["status"] == "Connected"

    stored_user = accounts.load_users()["users"][0]
    assert stored_user["notification_topic"] == "shopping-user-test-token"
    assert stored_user["ntfy_topic"] == "shopping-user-test-token"
    assert stored_user["browser_push_subscription"] == subscription


def test_device_subscribe_returns_ntfy_deep_link_and_marks_pending(monkeypatch, tmp_path):
    configure_users_file(monkeypatch, tmp_path)
    monkeypatch.setattr(accounts, "generate_ntfy_topic", lambda: "shopping-user-phone-token")
    accounts.save_users({"users": [seed_user()]})

    result = accounts.start_device_notification_subscription("user-1", "iphone")

    assert result["ok"] is True
    assert result["deep_link"] == "ntfy://subscribe/shopping-user-phone-token"
    assert result["history_url"] == "https://ntfy.sh/shopping-user-phone-token"
    assert result["user"]["notification_devices"][1]["name"] == "iPhone"
    assert result["user"]["notification_devices"][1]["status"] == "Pending"


def test_send_test_notification_posts_expected_message_and_stores_timestamp(monkeypatch, tmp_path):
    configure_users_file(monkeypatch, tmp_path)
    posted = {}

    user = seed_user()
    user["notification_topic"] = "shopping-user-test-token"
    user["ntfy_topic"] = "shopping-user-test-token"
    user["notifications_enabled"] = True
    accounts.save_users({"users": [user]})

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, data=None, headers=None, timeout=None):
        posted["url"] = url
        posted["data"] = data
        posted["headers"] = headers
        posted["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(accounts.requests, "post", fake_post)
    result = accounts.send_test_notification("user-1")

    assert result["ok"] is True
    assert posted["url"] == "https://ntfy.sh/shopping-user-test-token"
    assert posted["data"] == b"Test notification from Recipe Shopping List"
    assert posted["headers"]["Title"] == "Recipe Shopping List"
    assert result["user"]["last_test_notification"]
    assert result["user"]["last_notification_sent"] == result["user"]["last_test_notification"]
