import os

from flask import Blueprint
from flask import flash
from flask import make_response
from flask import redirect
from flask import request
from flask import session
from flask import url_for

from PushShoppingList.services.email_service import password_reset_email_configured
from PushShoppingList.services.email_service import send_account_delete_email
from PushShoppingList.services.email_service import send_password_reset_email
from PushShoppingList.services.email_service import send_two_factor_recovery_email
from PushShoppingList.services.sms_service import password_reset_sms_configured
from PushShoppingList.services.sms_service import send_password_reset_sms
from PushShoppingList.services.sms_service import send_phone_verification_sms
from PushShoppingList.services.user_account_service import authenticate_user
from PushShoppingList.services.user_account_service import cancel_two_factor_setup
from PushShoppingList.services.user_account_service import cancel_two_factor_sign_in
from PushShoppingList.services.user_account_service import complete_two_factor_sign_in
from PushShoppingList.services.user_account_service import create_user
from PushShoppingList.services.user_account_service import delete_account_with_token
from PushShoppingList.services.user_account_service import disable_two_factor
from PushShoppingList.services.user_account_service import enable_two_factor
from PushShoppingList.services.user_account_service import regenerate_two_factor_backup_codes
from PushShoppingList.services.user_account_service import request_account_delete
from PushShoppingList.services.user_account_service import request_password_reset
from PushShoppingList.services.user_account_service import request_phone_verification
from PushShoppingList.services.user_account_service import request_two_factor_recovery
from PushShoppingList.services.user_account_service import recover_two_factor_with_token
from PushShoppingList.services.user_account_service import reset_password_with_token
from PushShoppingList.services.user_account_service import sign_out_user
from PushShoppingList.services.user_account_service import start_two_factor_setup
from PushShoppingList.services.user_account_service import update_user_profile
from PushShoppingList.services.user_account_service import verify_phone_code


account_bp = Blueprint("account_bp", __name__)
TWO_FACTOR_TRUST_COOKIE = "shopping_2fa_trust"
TWO_FACTOR_TRUST_MAX_AGE = 30 * 24 * 60 * 60


def flash_account_result(result, success_message):
    if result.get("ok"):
        flash(success_message, "success")
        return

    for error in result.get("errors", ["Something went wrong. Please try again."]):
        flash(error, "error")


def password_reset_link(token):
    path = url_for(
        "account_bp.open_password_reset_route",
        token=token,
    )
    base_url = str(os.getenv("SHOPPING_APP_PASSWORD_RESET_BASE_URL") or "").strip().rstrip("/")

    if base_url:
        return f"{base_url}{path}"

    return url_for(
        "account_bp.open_password_reset_route",
        token=token,
        _external=True,
    )


def two_factor_recovery_link(token):
    path = url_for(
        "account_bp.open_two_factor_recovery_route",
        token=token,
    )
    base_url = str(os.getenv("SHOPPING_APP_PASSWORD_RESET_BASE_URL") or "").strip().rstrip("/")

    if base_url:
        return f"{base_url}{path}"

    return url_for(
        "account_bp.open_two_factor_recovery_route",
        token=token,
        _external=True,
    )


def account_delete_link(token):
    path = url_for(
        "account_bp.open_account_delete_route",
        token=token,
    )
    base_url = (
        str(os.getenv("SHOPPING_APP_ACCOUNT_LINK_BASE_URL") or "").strip().rstrip("/")
        or str(os.getenv("SHOPPING_APP_PASSWORD_RESET_BASE_URL") or "").strip().rstrip("/")
    )

    if base_url:
        return f"{base_url}{path}"

    return url_for(
        "account_bp.open_account_delete_route",
        token=token,
        _external=True,
    )


@account_bp.route("/account/create", methods=["POST"])
def create_account_route():
    result = create_user(
        request.form.get("username"),
        request.form.get("email"),
        request.form.get("password"),
        request.form.get("confirm_password"),
        request.files.get("avatar"),
        phone=request.form.get("phone"),
    )
    flash_account_result(result, "Account created. You are signed in.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/sign-in", methods=["POST"])
def sign_in_route():
    result = authenticate_user(
        request.form.get("identity"),
        request.form.get("password"),
        request.cookies.get(TWO_FACTOR_TRUST_COOKIE, ""),
    )

    if result.get("ok") and result.get("requires_2fa"):
        flash("Enter your authenticator code to finish signing in.", "success")
        return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

    flash_account_result(result, "Signed in.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/verify", methods=["POST"])
def verify_two_factor_route():
    result = complete_two_factor_sign_in(
        request.form.get("code"),
        remember_device=request.form.get("remember_device") == "1",
    )

    if result.get("ok"):
        flash("Signed in.", "success")
        response = make_response(redirect(url_for("main_bp.index", _anchor="userAccountSection")))

        if result.get("trust_token"):
            response.set_cookie(
                TWO_FACTOR_TRUST_COOKIE,
                result["trust_token"],
                max_age=TWO_FACTOR_TRUST_MAX_AGE,
                httponly=True,
                samesite="Lax",
                secure=request.is_secure,
            )

        return response

    flash_account_result(result, "")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/cancel-sign-in", methods=["POST"])
def cancel_two_factor_sign_in_route():
    cancel_two_factor_sign_in()
    flash("Two-factor sign-in canceled.", "success")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/recovery/request", methods=["POST"])
def request_two_factor_recovery_route():
    result = request_two_factor_recovery(session.get("pending_2fa_user_id"))

    if result.get("ok"):
        session.pop("two_factor_recovery_link", None)
        recovery_link = two_factor_recovery_link(result["token"])

        if password_reset_email_configured():
            email_result = send_two_factor_recovery_email(result.get("user"), recovery_link)

            if not email_result.get("ok"):
                flash(
                    email_result.get("error")
                    or "Two-factor recovery email could not be sent. Check SMTP settings.",
                    "error",
                )
                return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
        else:
            session["two_factor_recovery_link"] = recovery_link
            flash(
                "Email is not configured yet, so a local two-factor recovery link is available below.",
                "success",
            )
            return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

        flash("A two-factor recovery email has been sent.", "success")
    else:
        flash_account_result(result, "")

    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/recovery/<token>", methods=["GET"])
def open_two_factor_recovery_route(token):
    return redirect(url_for("main_bp.index", two_factor_recovery_token=token, _anchor="userAccountSection"))


@account_bp.route("/account/2fa/recovery/complete", methods=["POST"])
def complete_two_factor_recovery_route():
    result = recover_two_factor_with_token(
        request.form.get("two_factor_recovery_token"),
        request.form.get("password"),
    )

    response = make_response(redirect(url_for("main_bp.index", _anchor="userAccountSection")))

    if result.get("ok"):
        session.pop("two_factor_recovery_link", None)
        flash("Two-factor authentication disabled. Sign in with your password and set up a new authenticator.", "success")
        response.delete_cookie(TWO_FACTOR_TRUST_COOKIE)
        return response

    flash_account_result(result, "")
    return redirect(
        url_for(
            "main_bp.index",
            two_factor_recovery_token=request.form.get("two_factor_recovery_token", ""),
            _anchor="userAccountSection",
        )
    )


@account_bp.route("/account/password-reset/request", methods=["POST"])
def request_password_reset_route():
    reset_method = str(request.form.get("reset_method") or "email").strip().lower()
    result = request_password_reset(request.form.get("identity"), reset_method)

    if result.get("ok"):
        session.pop("password_reset_link", None)
        if result.get("sent") and result.get("token"):
            reset_link = password_reset_link(result["token"])

            if reset_method == "phone":
                if password_reset_sms_configured():
                    sms_result = send_password_reset_sms(result.get("user"), reset_link)

                    if not sms_result.get("ok"):
                        flash(
                            sms_result.get("error")
                            or "Password reset text could not be sent. Check SMS settings.",
                            "error",
                        )
                        return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
                else:
                    session["password_reset_link"] = reset_link
                    flash(
                        "Text messaging is not configured yet, so a local password reset link is available below.",
                        "success",
                    )
                    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
            elif password_reset_email_configured():
                email_result = send_password_reset_email(result.get("user"), reset_link)

                if not email_result.get("ok"):
                    flash(
                        email_result.get("error")
                        or "Password reset email could not be sent. Check SMTP settings.",
                        "error",
                    )
                    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
            else:
                session["password_reset_link"] = reset_link
                flash(
                    "Email is not configured yet, so a local password reset link is available below.",
                    "success",
                )
                return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

        flash(
            (
                "If that account exists, a password reset text has been sent."
                if reset_method == "phone" and password_reset_sms_configured()
                else "If that account exists, a password reset email has been sent."
                if password_reset_email_configured()
                else "If that account exists, a password reset link has been prepared."
            ),
            "success",
        )
    else:
        flash_account_result(result, "")

    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/password-reset/<token>", methods=["GET"])
def open_password_reset_route(token):
    return redirect(url_for("main_bp.index", reset_token=token, _anchor="userAccountSection"))


@account_bp.route("/account/password-reset/complete", methods=["POST"])
def complete_password_reset_route():
    result = reset_password_with_token(
        request.form.get("reset_token"),
        request.form.get("password"),
        request.form.get("confirm_password"),
    )

    if result.get("ok"):
        session.pop("password_reset_link", None)
        flash("Password reset. Sign in with your new password.", "success")
        return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

    flash_account_result(result, "")
    return redirect(
        url_for(
            "main_bp.index",
            reset_token=request.form.get("reset_token", ""),
            _anchor="userAccountSection",
        )
    )


@account_bp.route("/account/sign-out", methods=["POST"])
def sign_out_route():
    sign_out_user()
    flash("Signed out. You are using the guest workspace.", "success")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/profile", methods=["POST"])
def update_profile_route():
    user_id = session.get("user_id")
    result = update_user_profile(
        user_id,
        request.form.get("username"),
        request.form.get("email"),
        request.form.get("password"),
        request.form.get("confirm_password"),
        request.files.get("avatar"),
        phone=request.form.get("phone"),
    )
    flash_account_result(result, "Profile updated.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/phone/verification/request", methods=["POST"])
def request_phone_verification_route():
    result = request_phone_verification(session.get("user_id"))

    if result.get("ok"):
        session.pop("phone_verification_code", None)

        if password_reset_sms_configured():
            sms_result = send_phone_verification_sms(result.get("user"), result.get("code"))

            if not sms_result.get("ok"):
                flash(
                    sms_result.get("error")
                    or "Phone verification text could not be sent. Check SMS settings.",
                    "error",
                )
                return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
        else:
            session["phone_verification_code"] = result.get("code")
            flash(
                "Text messaging is not configured yet, so a local phone verification code is available below.",
                "success",
            )
            return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

        flash("A phone verification code has been sent.", "success")
    else:
        flash_account_result(result, "")

    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/phone/verification/confirm", methods=["POST"])
def confirm_phone_verification_route():
    result = verify_phone_code(
        session.get("user_id"),
        request.form.get("phone_verification_code"),
    )

    if result.get("ok"):
        session.pop("phone_verification_code", None)
        flash("Phone number verified.", "success")
    else:
        flash_account_result(result, "")

    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/delete/request", methods=["POST"])
def request_account_delete_route():
    result = request_account_delete(session.get("user_id"))

    if result.get("ok"):
        session.pop("account_delete_link", None)
        delete_link = account_delete_link(result["token"])

        if password_reset_email_configured():
            email_result = send_account_delete_email(result.get("user"), delete_link)

            if not email_result.get("ok"):
                flash(
                    email_result.get("error")
                    or "Account deletion email could not be sent. Check SMTP settings.",
                    "error",
                )
                return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
        else:
            session["account_delete_link"] = delete_link
            flash(
                "Email is not configured yet, so a local account deletion verification link is available below.",
                "success",
            )
            return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

        flash("An account deletion verification email has been sent.", "success")
    else:
        flash_account_result(result, "")

    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/delete/<token>", methods=["GET"])
def open_account_delete_route(token):
    return redirect(url_for("main_bp.index", account_delete_token=token, _anchor="userAccountSection"))


@account_bp.route("/account/delete/complete", methods=["POST"])
def complete_account_delete_route():
    result = delete_account_with_token(request.form.get("account_delete_token"))
    response = make_response(redirect(url_for("main_bp.index", _anchor="userAccountSection")))

    if result.get("ok"):
        session.pop("account_delete_link", None)
        flash("Account deleted. You are using the guest workspace.", "success")
        response.delete_cookie(TWO_FACTOR_TRUST_COOKIE)
        return response

    flash_account_result(result, "")
    return redirect(
        url_for(
            "main_bp.index",
            account_delete_token=request.form.get("account_delete_token", ""),
            _anchor="userAccountSection",
        )
    )


@account_bp.route("/account/2fa/start", methods=["POST"])
def start_two_factor_setup_route():
    result = start_two_factor_setup(session.get("user_id"))
    flash_account_result(result, "Two-factor setup started.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/enable", methods=["POST"])
def enable_two_factor_route():
    result = enable_two_factor(
        session.get("user_id"),
        request.form.get("code"),
    )

    if result.get("ok"):
        session["two_factor_backup_codes"] = result.get("backup_codes", [])

    flash_account_result(result, "Two-factor authentication enabled.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/cancel-setup", methods=["POST"])
def cancel_two_factor_setup_route():
    result = cancel_two_factor_setup(session.get("user_id"))
    flash_account_result(result, "Two-factor setup canceled.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/2fa/disable", methods=["POST"])
def disable_two_factor_route():
    result = disable_two_factor(
        session.get("user_id"),
        request.form.get("password"),
        request.form.get("code"),
    )
    flash_account_result(result, "Two-factor authentication disabled.")
    response = make_response(redirect(url_for("main_bp.index", _anchor="userAccountSection")))

    if result.get("ok"):
        response.delete_cookie(TWO_FACTOR_TRUST_COOKIE)

    return response


@account_bp.route("/account/2fa/backup-codes/regenerate", methods=["POST"])
def regenerate_two_factor_backup_codes_route():
    result = regenerate_two_factor_backup_codes(
        session.get("user_id"),
        request.form.get("password"),
        request.form.get("code"),
    )

    if result.get("ok"):
        session["two_factor_backup_codes"] = result.get("backup_codes", [])

    flash_account_result(result, "Backup codes regenerated.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
