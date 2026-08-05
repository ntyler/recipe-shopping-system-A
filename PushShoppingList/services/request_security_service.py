"""Shared request identity, canonical URL, and private-cache helpers.

Query values passed to this module are decoded values (for example,
``request.args``).  Encoding happens once, when ``build_canonical_url`` calls
``urlencode``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from flask import abort
from flask import make_response
from flask import request

from PushShoppingList.services.guest_session_service import is_guest_session
from PushShoppingList.services.user_account_service import current_user


PRIVATE_CACHE_CONTROL = "private, no-store"


@dataclass(frozen=True)
class ViewerValidation:
    """The authenticated viewer state for one request.

    ``viewer_user_id`` is derived only from the resolved Flask session.  A
    query parameter is never returned as workspace authority.
    """

    viewer_user_id: str
    is_guest: bool
    parameter_present: bool
    canonical_redirect_required: bool


def _query_pairs(parameters):
    if parameters is None:
        return []

    if hasattr(parameters, "items"):
        try:
            return list(parameters.items(multi=True))
        except TypeError:
            pass

    if isinstance(parameters, Mapping):
        pairs = []
        for key, value in parameters.items():
            values = value if isinstance(value, (list, tuple)) else (value,)
            pairs.extend((key, item) for item in values)
        return pairs

    return list(parameters)


def parameter_values(parameters, key):
    """Return every decoded value for ``key`` without collapsing duplicates."""

    key = str(key or "")
    if hasattr(parameters, "getlist"):
        return list(parameters.getlist(key))
    return [value for pair_key, value in _query_pairs(parameters) if str(pair_key) == key]


def has_duplicate_parameter(parameters, key):
    return len(parameter_values(parameters, key)) > 1


def reject_duplicate_parameters(parameters, *keys):
    """Reject duplicate security-sensitive parameters with a generic 400."""

    if any(has_duplicate_parameter(parameters, key) for key in keys):
        abort(400)


def validate_authenticated_viewer(parameters=None, parameter="viewer_user_id"):
    """Validate an asserted viewer against the resolved authenticated session.

    Registered accounts match exactly and case-sensitively.  Missing or blank
    assertions require a canonical redirect.  Guest URLs remain userless and
    reject nonblank assertions.  Anonymous requests are left for the normal
    application authentication guard so its established redirect/401 behavior
    is preserved.
    """

    parameters = request.args if parameters is None else parameters
    values = parameter_values(parameters, parameter)
    if len(values) > 1:
        abort(400)

    parameter_present = bool(values)
    supplied = "" if not values or values[0] is None else str(values[0])
    supplied_nonblank = bool(supplied.strip())
    guest_active = is_guest_session()
    user = None if guest_active else current_user()
    viewer_user_id = str((user or {}).get("user_id") or "")

    if user:
        if supplied_nonblank and supplied != viewer_user_id:
            abort(403)
        return ViewerValidation(
            viewer_user_id=viewer_user_id,
            is_guest=False,
            parameter_present=parameter_present,
            canonical_redirect_required=not supplied_nonblank,
        )

    if guest_active:
        if supplied_nonblank:
            abort(403)
        return ViewerValidation(
            viewer_user_id="",
            is_guest=True,
            parameter_present=parameter_present,
            canonical_redirect_required=parameter_present,
        )

    return ViewerValidation(
        viewer_user_id="",
        is_guest=False,
        parameter_present=parameter_present,
        canonical_redirect_required=False,
    )


def clean_query_parameters(
    parameters=None,
    *,
    remove_keys=(),
    overrides=None,
    allowed_keys=None,
    defaults=None,
):
    """Return canonical decoded query pairs.

    Blank values and values equal to configured defaults are removed.
    ``overrides`` replace every original occurrence of their keys; a blank or
    ``None`` override therefore removes that key.  Unknown nonblank keys are
    retained unless ``allowed_keys`` is supplied.
    """

    removed = {str(key) for key in remove_keys}
    allowed = None if allowed_keys is None else {str(key) for key in allowed_keys}
    default_values = {
        str(key): str(value)
        for key, value in dict(defaults or {}).items()
    }
    override_pairs = _query_pairs(overrides)
    overridden = {str(key) for key, _value in override_pairs}

    def include_pair(key, value):
        key = str(key or "")
        if not key or key in removed:
            return False
        if allowed is not None and key not in allowed:
            return False
        value = "" if value is None else str(value)
        if not value.strip():
            return False
        if key in default_values and value == default_values[key]:
            return False
        return True

    cleaned = []
    for key, value in override_pairs:
        if include_pair(key, value):
            cleaned.append((str(key), str(value)))

    for key, value in _query_pairs(parameters):
        if str(key) in overridden:
            continue
        if include_pair(key, value):
            cleaned.append((str(key), str(value)))

    return cleaned


def build_canonical_url(
    path,
    *,
    parameters=None,
    remove_keys=(),
    overrides=None,
    allowed_keys=None,
    defaults=None,
):
    """Build a URL from decoded values, encoding each value exactly once."""

    path = str(path or "")
    pairs = clean_query_parameters(
        parameters,
        remove_keys=remove_keys,
        overrides=overrides,
        allowed_keys=allowed_keys,
        defaults=defaults,
    )
    query = urlencode(pairs, doseq=True)
    return f"{path}?{query}" if query else path


def apply_private_no_store(response):
    """Apply the authoritative cache policy to an existing response."""

    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
    response.headers["Pragma"] = "no-cache"
    response.headers.pop("Expires", None)
    return response


def private_no_store_response(*args, **kwargs):
    """Create a Flask response and apply the authoritative cache policy."""

    return apply_private_no_store(make_response(*args, **kwargs))
