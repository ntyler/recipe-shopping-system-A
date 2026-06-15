import os

from flask import Blueprint
from flask import Response
from flask import abort
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import send_file
from flask import url_for

from PushShoppingList.services.pdf_share_service import create_pdf_share_link
from PushShoppingList.services.pdf_share_service import list_available_pdfs
from PushShoppingList.services.pdf_share_service import record_share_access
from PushShoppingList.services.pdf_share_service import resolve_share_token
from PushShoppingList.services.pdf_share_service import revoke_share_token
from PushShoppingList.services.pdf_share_service import safe_resolve_pdf_path
from PushShoppingList.services.cloudflare_pdf_admin_service import scan_unlinked_cloudflare_pdfs
from PushShoppingList.services.recipe_edit_service import recipe_pdf_kind_for_filename
from PushShoppingList.services.recipe_edit_service import recipe_url_for_pdf_filename
from PushShoppingList.services.recipe_edit_service import upload_local_pdf_path_to_cloudflare
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import is_admin_user


pdf_bp = Blueprint("pdf_bp", __name__)


def static_asset_version(filename):
    try:
        return int(os.path.getmtime(os.path.join(current_app.static_folder, filename)))
    except OSError:
        return 1


def require_pdf_account(wants_json=False):
    user = current_public_user()

    if user:
        return user

    if wants_json:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Sign in to manage PDF share links.",
        }), 401

    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


def require_pdf_admin():
    user = current_public_user()

    if not user:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Sign in to manage PDF storage.",
        }), 401

    if not is_admin_user(user):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
        }), 403

    return user


def pdf_share_url(token):
    return url_for("pdf_bp.share_pdf_route", token=token, _external=True)


def hydrate_pdf_share_view():
    rows = []

    for row in list_available_pdfs():
        active_share = row.get("active_share")
        if active_share:
            active_share = {
                **active_share,
                "share_url": pdf_share_url(active_share.get("token")),
            }

        rows.append({
            **row,
            "view_url": (
                row.get("r2_public_url")
                or url_for("pdf_bp.view_pdf_route", pdf_filename=row["pdf_filename"])
            ),
            "active_share": active_share,
        })

    return {
        "pdfs": rows,
    }


@pdf_bp.route("/pdfs")
def pdfs_route():
    account_response = require_pdf_account()

    if not isinstance(account_response, dict):
        return account_response

    return render_template(
        "pdfs.html",
        pdf_share_view=hydrate_pdf_share_view(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
    )


@pdf_bp.route("/pdfs/view/<path:pdf_filename>")
def view_pdf_route(pdf_filename):
    account_response = require_pdf_account()

    if not isinstance(account_response, dict):
        return account_response

    pdf_path = safe_resolve_pdf_path(pdf_filename)

    if not pdf_path or not pdf_path.exists():
        abort(404)

    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=pdf_path.name,
        max_age=0,
    )


@pdf_bp.route("/pdfs/share", methods=["POST"])
def create_pdf_share_route():
    account_response = require_pdf_account(wants_json=True)

    if not isinstance(account_response, dict):
        return account_response

    payload = request.get_json(silent=True) or {}
    pdf_filename = str(payload.get("pdf_filename") or request.form.get("pdf_filename") or "").strip()
    result = create_pdf_share_link(pdf_filename, current_user=account_response)

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "success": False,
            "error": result.get("error", "Unable to create PDF share link."),
        }), 400

    record = result["record"]
    return jsonify({
        "ok": True,
        "success": True,
        "created": bool(result.get("created")),
        "share_url": pdf_share_url(record["token"]),
        "expires_at": record.get("expires_at"),
        "allow_download": bool(record.get("allow_download", True)),
        "token": record["token"],
    })


@pdf_bp.route("/pdfs/share/revoke", methods=["POST"])
def revoke_pdf_share_route():
    account_response = require_pdf_account(wants_json=True)

    if not isinstance(account_response, dict):
        return account_response

    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or request.form.get("token") or "").strip()
    result = revoke_share_token(token)

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "success": False,
            "error": result.get("error", "Unable to revoke PDF share link."),
        }), 404

    return jsonify({
        "ok": True,
        "success": True,
    })


@pdf_bp.route("/pdfs/cloudflare_upload", methods=["POST"])
def upload_pdf_to_cloudflare_route():
    account_response = require_pdf_account(wants_json=True)

    if not isinstance(account_response, dict):
        return account_response

    payload = request.get_json(silent=True) or {}
    pdf_filename = str(payload.get("pdf_filename") or request.form.get("pdf_filename") or "").strip()
    pdf_path = safe_resolve_pdf_path(pdf_filename)

    if not pdf_path or not pdf_path.exists():
        return jsonify({
            "ok": False,
            "success": False,
            "error": "PDF file was not found.",
        }), 400

    recipe_url = recipe_url_for_pdf_filename(pdf_path.name)
    pdf_kind = recipe_pdf_kind_for_filename(pdf_path.name)
    result = upload_local_pdf_path_to_cloudflare(pdf_path, url=recipe_url, pdf_kind=pdf_kind)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


def cloudflare_unlinked_pdf_scan_response():
    account_response = require_pdf_admin()

    if not isinstance(account_response, dict):
        return account_response

    result = scan_unlinked_cloudflare_pdfs()
    return jsonify(result), 200 if result.get("ok") else 400


@pdf_bp.route("/pdfs/cloudflare_unlinked", methods=["GET"])
def cloudflare_unlinked_pdfs_route():
    return cloudflare_unlinked_pdf_scan_response()


@pdf_bp.route("/pdfs/cloudflare_orphans", methods=["GET"])
def cloudflare_orphan_pdfs_route():
    return cloudflare_unlinked_pdf_scan_response()


@pdf_bp.route("/pdfs/cloudflare_orphans/delete", methods=["POST"])
def delete_cloudflare_orphan_pdfs_route():
    account_response = require_pdf_admin()

    if not isinstance(account_response, dict):
        return account_response

    return jsonify({
        "ok": False,
        "success": False,
        "code": "delete_disabled",
        "error": "Deleting unlinked PDFs is disabled. Use Check Unlinked PDFs for a read-only audit.",
        "deleted_count": 0,
        "failed_count": 0,
        "unlinked_pdf_count": 0,
        "unlinked_pdfs": [],
        "orphaned_pdf_count": 0,
        "orphaned_pdfs": [],
    }), 405


@pdf_bp.route("/share/pdf/<token>")
def share_pdf_route(token):
    result = resolve_share_token(token)

    if not result.get("ok"):
        return Response(result.get("error", "PDF share link is not available."), status=result.get("status", 404))

    record_share_access(token)
    record = result["record"]

    return send_file(
        result["pdf_path"],
        mimetype="application/pdf",
        as_attachment=False,
        download_name=record.get("original_filename") or record.get("pdf_filename"),
        max_age=0,
    )


@pdf_bp.route("/share/pdf/<token>/download")
def download_shared_pdf_route(token):
    result = resolve_share_token(token)

    if not result.get("ok"):
        return Response(result.get("error", "PDF share link is not available."), status=result.get("status", 404))

    record = result["record"]
    if not record.get("allow_download", True):
        return Response("PDF download is not enabled for this share link.", status=403)

    record_share_access(token)
    return send_file(
        result["pdf_path"],
        mimetype="application/pdf",
        as_attachment=True,
        download_name=record.get("original_filename") or record.get("pdf_filename"),
        max_age=0,
    )
