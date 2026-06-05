from flask import Blueprint
from flask import redirect
from flask import request
from flask import session
from flask import url_for

from PushShoppingList.services.feedback_service import add_feedback_comment
from PushShoppingList.services.feedback_service import create_feedback
from PushShoppingList.services.feedback_service import display_feedback_id
from PushShoppingList.services.feedback_service import mark_feedback_notifications_read
from PushShoppingList.services.feedback_service import reopen_feedback_ticket
from PushShoppingList.services.feedback_service import update_feedback_as_admin
from PushShoppingList.services.user_account_service import current_public_user


feedback_bp = Blueprint("feedback_bp", __name__)


def flash_feedback_result(result, success_message):
    if result.get("ok"):
        session["feedback_messages"] = [{"category": "success", "text": success_message}]
        return

    session["feedback_messages"] = [
        {"category": "error", "text": error}
        for error in result.get("errors", ["Something went wrong. Please try again."])
    ]


@feedback_bp.route("/feedback/submit", methods=["POST"])
def submit_feedback_route():
    result = create_feedback(
        current_public_user(),
        request.form,
        request.files,
    )
    message = (
        f"Feedback {display_feedback_id(result.get('feedback_id'))} submitted."
        if result.get("feedback_id")
        else "Feedback submitted."
    )
    flash_feedback_result(result, message)
    return redirect(url_for("main_bp.index", _anchor="feedbackSupportSection"))


@feedback_bp.route("/feedback/<feedback_id>/admin", methods=["POST"])
def update_feedback_admin_route(feedback_id):
    result = update_feedback_as_admin(
        current_public_user(),
        feedback_id,
        request.form,
        request.files,
    )
    flash_feedback_result(result, "Feedback updated.")
    return redirect(url_for("main_bp.index", _anchor=f"feedback-{feedback_id}"))


@feedback_bp.route("/feedback/<feedback_id>/comment", methods=["POST"])
def add_feedback_comment_route(feedback_id):
    result = add_feedback_comment(
        current_public_user(),
        feedback_id,
        request.form.get("commentText"),
    )
    flash_feedback_result(result, "Reply sent to support.")
    return redirect(url_for("main_bp.index", _anchor=f"feedback-{feedback_id}"))


@feedback_bp.route("/feedback/<feedback_id>/reopen", methods=["POST"])
def reopen_feedback_route(feedback_id):
    result = reopen_feedback_ticket(
        current_public_user(),
        feedback_id,
    )
    flash_feedback_result(result, "Ticket reopened.")
    return redirect(url_for("main_bp.index", _anchor=f"feedback-{feedback_id}"))


@feedback_bp.route("/feedback/<feedback_id>/mark-read", methods=["POST"])
def mark_feedback_read_route(feedback_id):
    result = mark_feedback_notifications_read(
        current_public_user(),
        feedback_id,
    )
    flash_feedback_result(result, "Feedback updates marked read.")
    return redirect(url_for("main_bp.index", _anchor=f"feedback-{feedback_id}"))
