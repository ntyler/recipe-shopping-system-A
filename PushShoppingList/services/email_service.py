import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


DEFAULT_FROM_NAME = "Recipe Shopping System"


def env_value(name, default=""):
    return str(os.getenv(name, default) or "").strip()


def env_bool(name, default=False):
    value = env_value(name)

    if not value:
        return default

    return value.lower() in {"1", "true", "yes", "on"}


def smtp_config():
    use_ssl = env_bool("SHOPPING_APP_SMTP_USE_SSL", False)
    default_port = 465 if use_ssl else 587

    return {
        "host": env_value("SHOPPING_APP_SMTP_HOST"),
        "port": env_int("SHOPPING_APP_SMTP_PORT", default_port),
        "username": env_value("SHOPPING_APP_SMTP_USERNAME"),
        "password": env_value("SHOPPING_APP_SMTP_PASSWORD"),
        "from_email": env_value("SHOPPING_APP_SMTP_FROM_EMAIL"),
        "from_name": env_value("SHOPPING_APP_SMTP_FROM_NAME", DEFAULT_FROM_NAME),
        "use_tls": env_bool("SHOPPING_APP_SMTP_USE_TLS", not use_ssl),
        "use_ssl": use_ssl,
    }


def password_reset_email_configured():
    config = smtp_config()
    return bool(config["host"] and config["from_email"])


def env_int(name, default):
    try:
        return int(env_value(name, str(default)))
    except ValueError:
        return default


def send_password_reset_email(user, reset_url):
    config = smtp_config()

    if not password_reset_email_configured():
        return {
            "ok": False,
            "configured": False,
            "error": "Password reset email is not configured.",
        }

    recipient = str((user or {}).get("email") or "").strip()
    username = str((user or {}).get("username") or "there").strip()

    if not recipient:
        return {
            "ok": False,
            "configured": True,
            "error": "This account does not have an email address.",
        }

    message = EmailMessage()
    message["Subject"] = "Reset your Recipe Shopping System password"
    message["From"] = formataddr((config["from_name"], config["from_email"]))
    message["To"] = recipient
    message.set_content(
        "\n".join([
            f"Hi {username},",
            "",
            "Use this one-time link to reset your password:",
            reset_url,
            "",
            "This link expires in 1 hour. If you did not request this reset, you can ignore this email.",
        ])
    )

    context = ssl.create_default_context()

    try:
        if config["use_ssl"]:
            with smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context) as smtp:
                login_smtp(smtp, config)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(config["host"], config["port"], timeout=15) as smtp:
                smtp.ehlo()
                if config["use_tls"]:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                login_smtp(smtp, config)
                smtp.send_message(message)
    except Exception as err:
        return {
            "ok": False,
            "configured": True,
            "error": f"Password reset email could not be sent. Check SMTP settings. ({err})",
        }

    return {"ok": True, "configured": True}


def login_smtp(smtp, config):
    if config["username"]:
        smtp.login(config["username"], config["password"])
