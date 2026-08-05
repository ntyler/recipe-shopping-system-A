"""Canonical URL helpers for the session-scoped master-data pages.

The query values accepted here must already be decoded (for example, values
from ``request.args`` or ``parse_qsl``).  ``urlencode`` is deliberately used in
one place so callers do not accidentally double-encode search text or user
identifiers.
"""

from collections.abc import Mapping
from urllib.parse import urlencode


MASTER_DATA_PAGE_PATHS = {
    "ingredients": "/admin/master-data/ingredients",
    "equipment": "/admin/master-data/equipment",
    "store_sections": "/admin/master-data/store-sections",
}

MASTER_DATA_IDENTITY_QUERY_KEYS = frozenset({
    "viewer_user_id",
    "scope",
    "user_id",
})


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


def clean_master_data_query_parameters(
    parameters=None,
    *,
    viewer_user_id="",
    scope="mine",
    target_user_id="",
    overrides=None,
):
    """Return canonical, decoded query pairs for a master-data page.

    Unknown nonblank parameters are retained so future filters and old
    bookmarks survive canonical redirects. Identity parameters are always
    rebuilt from the validated session/scope values supplied by the caller.
    """

    pairs = _query_pairs(parameters)
    override_pairs = _query_pairs(overrides)
    overridden_keys = {str(key) for key, _value in override_pairs}
    if overridden_keys:
        pairs = [
            (key, value)
            for key, value in pairs
            if str(key) not in overridden_keys
        ]
    pairs.extend(override_pairs)

    cleaned = []
    viewer_user_id = str(viewer_user_id or "")
    if viewer_user_id:
        cleaned.append(("viewer_user_id", viewer_user_id))

    normalized_scope = str(scope or "mine").strip().lower()
    target_user_id = str(target_user_id or "").strip()
    if normalized_scope == "all":
        cleaned.append(("scope", "all"))
    elif normalized_scope == "user" and target_user_id:
        cleaned.extend((
            ("scope", "user"),
            ("user_id", target_user_id),
        ))

    for key, value in pairs:
        key = str(key or "")
        if not key or key in MASTER_DATA_IDENTITY_QUERY_KEYS:
            continue
        value = "" if value is None else str(value)
        if not value.strip():
            continue
        if key == "page" and value.strip() == "1":
            continue
        cleaned.append((key, value))

    return cleaned


def build_master_data_url(
    page,
    *,
    parameters=None,
    viewer_user_id="",
    scope="mine",
    target_user_id="",
    overrides=None,
    base_path="",
):
    """Build one canonical master-data URL from decoded values."""

    path = str(base_path or MASTER_DATA_PAGE_PATHS.get(page) or "").strip()
    if not path:
        raise ValueError(f"Unsupported master-data page: {page!r}")

    pairs = clean_master_data_query_parameters(
        parameters,
        viewer_user_id=viewer_user_id,
        scope=scope,
        target_user_id=target_user_id,
        overrides=overrides,
    )
    query = urlencode(pairs, doseq=True)
    return f"{path}?{query}" if query else path
