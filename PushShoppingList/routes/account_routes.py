from flask import Blueprint
from flask import flash
from flask import redirect
from flask import request
from flask import session
from flask import url_for

from PushShoppingList.services.user_account_service import authenticate_user
from PushShoppingList.services.user_account_service import create_user
from PushShoppingList.services.user_account_service import request_password_reset
from PushShoppingList.services.user_account_service import reset_password_with_token
from PushShoppingList.services.user_account_service import sign_out_user
from PushShoppingList.services.user_account_service import update_user_profile


account_bp = Blueprint("account_bp", __name__)


def flash_account_result(result, success_message):
    if result.get("ok"):
        flash(success_message, "success")
        return

    for error in result.get("errors", ["Something went wrong. Please try again."]):
        flash(error, "error")


@account_bp.route("/account/create", methods=["POST"])
def create_account_route():
    result = create_user(
        request.form.get("username"),
        request.form.get("email"),
        request.form.get("password"),
        request.form.get("confirm_password"),
        request.files.get("avatar"),
    )
    flash_account_result(result, "Account created. You are signed in.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/sign-in", methods=["POST"])
def sign_in_route():
    result = authenticate_user(
        request.form.get("identity"),
        request.form.get("password"),
    )
    flash_account_result(result, "Signed in.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


@account_bp.route("/account/password-reset/request", methods=["POST"])
def request_password_reset_route():
    result = request_password_reset(request.form.get("identity"))

    if result.get("ok"):
        session.pop("password_reset_link", None)
        if result.get("sent") and result.get("token"):
            session["password_reset_link"] = url_for(
                "account_bp.open_password_reset_route",
                token=result["token"],
                _external=True,
            )
        flash(
            "If that account exists, a password reset link has been prepared.",
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
    )
    flash_account_result(result, "Profile updated.")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))
