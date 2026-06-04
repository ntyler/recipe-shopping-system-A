import requests

from PushShoppingList.services.email_service import env_value


def sms_config():
    return {
        "account_sid": env_value("SHOPPING_APP_TWILIO_ACCOUNT_SID") or env_value("TWILIO_ACCOUNT_SID"),
        "auth_token": env_value("SHOPPING_APP_TWILIO_AUTH_TOKEN") or env_value("TWILIO_AUTH_TOKEN"),
        "from_phone": env_value("SHOPPING_APP_TWILIO_FROM_PHONE") or env_value("TWILIO_FROM_PHONE"),
    }


def password_reset_sms_configured():
    config = sms_config()

    return bool(config["account_sid"] and config["auth_token"] and config["from_phone"])


def send_password_reset_sms(user, reset_url):
    config = sms_config()

    if not password_reset_sms_configured():
        return {
            "ok": False,
            "configured": False,
            "error": "Password reset text messaging is not configured.",
        }

    recipient = str((user or {}).get("phone") or "").strip()

    if not recipient:
        return {
            "ok": False,
            "configured": True,
            "error": "This account does not have a phone number.",
        }

    try:
        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config['account_sid']}/Messages.json",
            data={
                "From": config["from_phone"],
                "To": recipient,
                "Body": (
                    "Reset your Recipe Shopping System password with this one-time link: "
                    f"{reset_url} This link expires in 1 hour."
                ),
            },
            auth=(config["account_sid"], config["auth_token"]),
            timeout=15,
        )
    except Exception as err:
        return {
            "ok": False,
            "configured": True,
            "error": f"Password reset text could not be sent. Check SMS settings. {err}",
        }

    if response.status_code >= 400:
        error = "Password reset text could not be sent. Check SMS settings."
        try:
            payload = response.json()
            error = str(payload.get("message") or error)
        except Exception:
            if response.text:
                error = response.text[:240]

        return {
            "ok": False,
            "configured": True,
            "error": error,
        }

    return {"ok": True, "configured": True}


def send_phone_verification_sms(user, code):
    config = sms_config()

    if not password_reset_sms_configured():
        return {
            "ok": False,
            "configured": False,
            "error": "Phone verification text messaging is not configured.",
        }

    recipient = str((user or {}).get("phone") or "").strip()

    if not recipient:
        return {
            "ok": False,
            "configured": True,
            "error": "This account does not have a phone number.",
        }

    try:
        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config['account_sid']}/Messages.json",
            data={
                "From": config["from_phone"],
                "To": recipient,
                "Body": (
                    "Your Recipe Shopping System phone verification code is "
                    f"{code}. This code expires in 10 minutes."
                ),
            },
            auth=(config["account_sid"], config["auth_token"]),
            timeout=15,
        )
    except Exception as err:
        return {
            "ok": False,
            "configured": True,
            "error": f"Phone verification text could not be sent. Check SMS settings. {err}",
        }

    if response.status_code >= 400:
        error = "Phone verification text could not be sent. Check SMS settings."
        try:
            payload = response.json()
            error = str(payload.get("message") or error)
        except Exception:
            if response.text:
                error = response.text[:240]

        return {
            "ok": False,
            "configured": True,
            "error": error,
        }

    return {"ok": True, "configured": True}
