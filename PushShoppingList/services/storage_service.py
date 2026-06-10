import os
import re
from pathlib import Path

from flask import has_request_context
from flask import session


PACKAGE_DIR = Path(__file__).resolve().parent.parent
LEGACY_EXTRACTOR_DIR = PACKAGE_DIR / "services" / "recipe-extractor"
USER_DATA_DIR = Path(os.getenv("SHOPPING_APP_USER_DATA_DIR", PACKAGE_DIR / "user_data" / "users"))
GUEST_DATA_DIR = Path(os.getenv("SHOPPING_APP_GUEST_DATA_DIR", PACKAGE_DIR / "user_data" / "guests"))


def active_user_id():
    """Return the signed-in user id for request-scoped data isolation."""
    if not has_request_context():
        return ""

    return str(session.get("user_id") or "").strip()


def active_guest_session_id():
    """Return the active guest session id for request-scoped temporary data."""
    if not has_request_context() or not session.get("is_guest"):
        return ""

    return str(session.get("guest_session_id") or "").strip()


def safe_user_id(user_id):
    return re.sub(r"[^a-zA-Z0-9_-]+", "", str(user_id or ""))[:80]


def user_data_root(user_id=None):
    user_id = safe_user_id(user_id or active_user_id())

    if not user_id:
        return PACKAGE_DIR

    root = USER_DATA_DIR / user_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def guest_data_root(guest_session_id=None):
    guest_session_id = safe_user_id(guest_session_id or active_guest_session_id())

    if not guest_session_id:
        return PACKAGE_DIR

    root = GUEST_DATA_DIR / guest_session_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_data_root():
    if active_guest_session_id():
        return guest_data_root()

    return user_data_root()


def extractor_root(user_id=None):
    if not user_id and active_guest_session_id():
        root = guest_data_root() / "recipe-extractor"
        root.mkdir(parents=True, exist_ok=True)
        return root

    user_id = safe_user_id(user_id or active_user_id())

    if not user_id:
        return LEGACY_EXTRACTOR_DIR

    root = user_data_root(user_id) / "recipe-extractor"
    root.mkdir(parents=True, exist_ok=True)
    return root


def package_data_path(*parts):
    return workspace_data_root().joinpath(*parts)


def extractor_data_path(*parts):
    return extractor_root().joinpath("data", *parts)


class ScopedPath:
    """Path-like wrapper that resolves against the active Flask user session."""

    def __init__(self, resolver, *parts):
        self._resolver = resolver
        self._parts = tuple(str(part) for part in parts if str(part))

    @property
    def path(self):
        return self._resolver().joinpath(*self._parts)

    def __fspath__(self):
        return str(self.path)

    def __str__(self):
        return str(self.path)

    def __repr__(self):
        return f"ScopedPath({self.path!r})"

    def __truediv__(self, other):
        return ScopedPath(self._resolver, *self._parts, other)

    def __rtruediv__(self, other):
        return Path(other) / self.path

    def __getattr__(self, name):
        return getattr(self.path, name)

    def mkdir(self, *args, **kwargs):
        return self.path.mkdir(*args, **kwargs)

    def exists(self):
        return self.path.exists()

    def is_file(self):
        return self.path.is_file()

    def is_dir(self):
        return self.path.is_dir()

    def glob(self, *args, **kwargs):
        return self.path.glob(*args, **kwargs)

    def open(self, *args, **kwargs):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self.path.open(*args, **kwargs)

    def read_text(self, *args, **kwargs):
        return self.path.read_text(*args, **kwargs)

    def write_text(self, *args, **kwargs):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self.path.write_text(*args, **kwargs)

    def read_bytes(self):
        return self.path.read_bytes()

    def write_bytes(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self.path.write_bytes(data)

    def unlink(self, *args, **kwargs):
        return self.path.unlink(*args, **kwargs)

    def resolve(self, *args, **kwargs):
        return self.path.resolve(*args, **kwargs)


def scoped_package_path(*parts):
    return ScopedPath(workspace_data_root, *parts)


def scoped_extractor_path(*parts):
    return ScopedPath(extractor_root, *parts)


def scoped_extractor_data_path(*parts):
    return ScopedPath(lambda: extractor_root() / "data", *parts)
