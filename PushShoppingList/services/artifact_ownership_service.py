"""Dry-run-first ownership inventory and registration for durable artifacts.

Artifact bytes remain in files or object storage.  This module records only the
exact owner, immutable storage identity, checksum, and deletion safety metadata
needed by staged migration and the guest-purge saga.  Preview never opens a
write connection.  Apply requires an explicit approval phrase, revalidates the
preview, and commits the complete registry change in one database transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit


APPLY_APPROVAL_PHRASE = "APPLY ARTIFACT OWNERSHIP BACKFILL"
MIGRATION_KIND = "artifact_ownership_backfill"
GLOBAL_WORKSPACE_ID = "global:application"
GLOBAL_WORKSPACE_TYPE = "system"
GLOBAL_SUBJECT_ID = "application"

PACKAGE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PACKAGE_DIR.parent
LEGACY_EXTRACTOR_DIR = PACKAGE_DIR / "services" / "recipe-extractor"
PANTRY_GENERATED_DIR = PACKAGE_DIR / "static" / "generated" / "pantry_items"
RECIPE_DETAIL_GENERATED_DIR = PACKAGE_DIR / "static" / "generated" / "recipe_steps"
FEEDBACK_UPLOAD_DIR = PACKAGE_DIR / "static" / "uploads" / "feedback"
SHARED_PDF_DIR = LEGACY_EXTRACTOR_DIR / "data" / "pdf"
APPROVED_GLOBAL_GENERATED_ROOTS = (
    PANTRY_GENERATED_DIR,
    RECIPE_DETAIL_GENERATED_DIR,
)

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}
)
ARTIFACT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
MAX_SOURCE_BYTES = 32 * 1024 * 1024

_LOCAL_IMAGE_FIELDS = frozenset(
    {
        "image_url",
        "pantry_image_url",
        "ingredient_image_url",
        "equipment_image_url",
        "step_image_url",
        "image_path",
        "cover_image_path",
    }
)
_LOCAL_PDF_FIELDS = frozenset(
    {
        "pdf_path",
        "local_pdf_path",
        "source_pdf_path",
        "generated_pdf_path",
        "generated_recipe_pdf_path",
        "webpage_backup_pdf_path",
    }
)
_R2_FIELDS = frozenset(
    {
        "object_key",
        "r2_object_key",
        "pdf_object_key",
        "cloudflare_pdf_path",
        "generated_recipe_pdf_object_key",
        "webpage_backup_pdf_object_key",
    }
)


class ArtifactOwnershipError(RuntimeError):
    """Base error for ownership preview and backfill."""


class ArtifactOwnershipApprovalError(ArtifactOwnershipError):
    """Raised when mutation was not explicitly approved."""


class ArtifactOwnershipPreviewError(ArtifactOwnershipError):
    """Raised when a preview contains unsafe or ambiguous references."""


class StaleArtifactOwnershipPreviewError(ArtifactOwnershipPreviewError):
    """Raised when sources changed after preview."""


@dataclass(frozen=True)
class ArtifactDocumentSource:
    workspace_id: str
    workspace_type: str
    subject_id: str
    workspace_root: Path
    source_path: Path
    source_name: str
    lifecycle_state: str = "active"
    artifact_roots: Tuple[Path, ...] = ()

    def __post_init__(self):
        for name, value in (
            ("workspace_id", self.workspace_id),
            ("workspace_type", self.workspace_type),
            ("subject_id", self.subject_id),
            ("source_name", self.source_name),
            ("lifecycle_state", self.lifecycle_state),
        ):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ArtifactOwnershipPreviewError("%s is invalid." % name)
        object.__setattr__(self, "workspace_root", Path(self.workspace_root))
        object.__setattr__(self, "source_path", Path(self.source_path))
        object.__setattr__(self, "artifact_roots", tuple(Path(item) for item in self.artifact_roots))


@dataclass(frozen=True)
class ArtifactCandidate:
    workspace_id: str
    workspace_type: str
    subject_id: str
    lifecycle_state: str
    artifact_kind: str
    storage_backend: str
    storage_key: str
    exact_path: str
    content_sha256: str
    byte_count: int
    storage_etag: str
    storage_version_id: str
    exclusive_owner: bool
    state: str
    reference_count: int
    owner_count: int
    source_sha256s: Tuple[str, ...]
    error_code: str = ""
    trusted_write: bool = False

    @property
    def artifact_id(self) -> str:
        material = "\x1f".join((self.storage_backend, self.storage_key))
        return "artifact:" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    def report_dict(self):
        return {
            "artifact_ref": hashlib.sha256(
                (self.storage_backend + "\x1f" + self.storage_key).encode("utf-8")
            ).hexdigest()[:16],
            "artifact_kind": self.artifact_kind,
            "byte_count": self.byte_count,
            "error_code": self.error_code,
            "exclusive_owner": self.exclusive_owner,
            "owner_count": self.owner_count,
            "owner_ref": _fingerprint(self.workspace_id),
            "reference_count": self.reference_count,
            "state": self.state,
            "storage_backend": self.storage_backend,
        }


@dataclass(frozen=True)
class ArtifactOwnershipPreview:
    sources: Tuple[ArtifactDocumentSource, ...]
    source_sha256s: Tuple[Tuple[str, str], ...]
    candidates: Tuple[ArtifactCandidate, ...]
    manifest_sha256: str

    @property
    def counts(self):
        result = {
            "sources": len(self.sources),
            "references": sum(item.reference_count for item in self.candidates),
            "artifacts": len(self.candidates),
            "ready": 0,
            "shared": 0,
            "missing": 0,
            "blocked": 0,
            "local": 0,
            "r2": 0,
        }
        for item in self.candidates:
            result[item.state] = result.get(item.state, 0) + 1
            if item.state == "ready" and item.owner_count > 1:
                result["shared"] += 1
            if item.storage_backend in result:
                result[item.storage_backend] += 1
        return result

    def to_dict(self):
        return {
            "applied": False,
            "dry_run": True,
            "counts": self.counts,
            "manifest_sha256": self.manifest_sha256,
            "artifacts": [item.report_dict() for item in self.candidates],
        }


@dataclass(frozen=True)
class ArtifactOwnershipApplyResult:
    run_id: str
    manifest_sha256: str
    inserted: int
    updated: int
    unchanged: int
    validated: int

    def to_dict(self):
        return {
            "applied": True,
            "dry_run": False,
            "inserted": self.inserted,
            "manifest_sha256": self.manifest_sha256,
            "run_id": self.run_id,
            "unchanged": self.unchanged,
            "updated": self.updated,
            "validated": self.validated,
        }


@dataclass(frozen=True)
class _Reference:
    workspace_id: str
    workspace_type: str
    subject_id: str
    lifecycle_state: str
    source_sha256: str
    artifact_kind: str
    storage_backend: str
    storage_key: str
    exact_path: str
    content_sha256: str
    byte_count: int
    storage_etag: str
    storage_version_id: str
    exclusive_capable: bool
    state: str
    error_code: str


def _fingerprint(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_json_source(path: Path):
    if not path.is_file():
        raise ArtifactOwnershipPreviewError("An artifact source is missing.")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ArtifactOwnershipPreviewError("An artifact source is too large.")
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ArtifactOwnershipPreviewError("An artifact source is too large.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        document = json.loads(
            raw.decode("utf-8-sig", errors="strict"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ArtifactOwnershipPreviewError("An artifact source is invalid.") from exc
    return raw, document


def _field_reference_kind(field_name: str, parents: Sequence[str], value: str):
    field = str(field_name or "").lower()
    parent_set = {str(item or "").lower() for item in parents}
    suffix = Path(urlsplit(value).path).suffix.lower()
    if field in _R2_FIELDS or field.endswith("_object_key"):
        if value.startswith(("http://", "https://")):
            return None
        return "r2_pdf"
    if field in _LOCAL_PDF_FIELDS or (field.endswith("_pdf_path") and suffix == ".pdf"):
        return "local_pdf"
    if field in _LOCAL_IMAGE_FIELDS or field.endswith("_image_url"):
        return "local_image"
    if field in {"path", "local_path", "src"} and parent_set.intersection(
        {"cover_image", "image", "generated_recipe", "webpage_backup", "pdf"}
    ):
        if suffix == ".pdf" or "pdf" in parent_set:
            return "local_pdf"
        if suffix in IMAGE_EXTENSIONS:
            return "local_image"
    if field in {"path", "local_path"} and parent_set.intersection(
        {"attachment", "attachments", "admin_attachments"}
    ):
        return "local_attachment"
    if field in {"stored_path", "upload_path"} and parent_set.intersection(
        {"receipt", "receipts", "attachment", "attachments"}
    ):
        if suffix == ".pdf":
            return "local_pdf"
        if suffix in IMAGE_EXTENSIONS:
            return "local_image"
    return None


def _walk_reference_values(value: object, parents=()):
    if isinstance(value, Mapping):
        for key, child in value.items():
            field = str(key)
            if isinstance(child, str) and child.strip():
                kind = _field_reference_kind(field, parents, child.strip())
                if kind:
                    yield kind, child.strip(), value
            yield from _walk_reference_values(child, parents + (field,))
    elif isinstance(value, list):
        for child in value:
            yield from _walk_reference_values(child, parents)


def _safe_object_key(value: str):
    key = unquote(str(value or "").strip()).replace("\\", "/")
    if (
        not key
        or key.startswith("/")
        or "\x00" in key
        or "://" in key
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        return None
    return key


def _allowed_roots(workspace_root: Path, extra_roots=()):
    roots = [workspace_root]
    roots.extend(
        [
            workspace_root / "recipe-extractor",
            workspace_root / "recipe-extractor" / "data",
        ]
    )
    roots.extend(Path(root) for root in extra_roots)
    result = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in result:
            result.append(resolved)
    return result


def _within_roots(path: Path, roots: Iterable[Path]):
    for root in roots:
        if path == root or root in path.parents:
            return True
    return False


def _resolve_local_reference(
    value: str,
    workspace_root: Path,
    *,
    allow_any_file=False,
    extra_roots=(),
):
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme in {"http", "https"} or parsed.netloc:
        return None, "ignored_remote_url"
    text = unquote(parsed.path or "")
    if not text or "\x00" in text:
        return None, "invalid_local_path"
    suffix = Path(text).suffix.lower()
    if not allow_any_file and suffix not in ARTIFACT_EXTENSIONS:
        return None, "unsupported_local_type"
    roots = _allowed_roots(Path(workspace_root), extra_roots)
    raw_path = Path(text)
    if text.startswith("/static/"):
        raw_path = PACKAGE_DIR / "static" / text[len("/static/") :]
    candidates = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        for root in roots:
            candidates.append(root / raw_path)
    existing = []
    unsafe = False
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not _within_roots(resolved, roots):
            unsafe = True
            continue
        if resolved.is_file() and resolved not in existing:
            existing.append(resolved)
    if len(existing) > 1:
        return None, "ambiguous_local_path"
    if len(existing) == 1:
        return existing[0], ""
    if unsafe:
        return None, "unsafe_local_path"
    return None, "missing_local_file"


def _local_reference(
    *,
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    lifecycle_state: str,
    workspace_root: Path,
    source_sha256: str,
    kind: str,
    value: str,
    extra_roots=(),
    force_nonexclusive=False,
):
    path, error = _resolve_local_reference(
        value,
        workspace_root,
        allow_any_file=kind == "local_attachment",
        extra_roots=extra_roots,
    )
    artifact_kind = (
        "generated_image"
        if kind == "local_image"
        else ("attachment" if kind == "local_attachment" else "pdf")
    )
    if path is None:
        state = "blocked" if error in {"ambiguous_local_path", "unsafe_local_path"} else "missing"
        return [
            _Reference(
                workspace_id,
                workspace_type,
                subject_id,
                lifecycle_state,
                source_sha256,
                artifact_kind,
                "local",
                "unresolved:" + _fingerprint(value),
                "",
                "",
                0,
                "",
                "",
                False,
                state,
                error,
            )
        ]
    references = []
    paths = [path]
    if path.suffix.lower() in IMAGE_EXTENSIONS and "__" not in path.stem:
        paths.extend(sorted(path.parent.glob(path.stem + "__*.webp")))
    for resolved in paths:
        if not resolved.is_file():
            continue
        try:
            exact_workspace_root = Path(workspace_root).resolve()
        except OSError:
            exact_workspace_root = Path(workspace_root)
        exclusive_capable = bool(
            not force_nonexclusive
            and workspace_type != "system"
            and (
                resolved == exact_workspace_root
                or exact_workspace_root in resolved.parents
            )
        )
        references.append(
            _Reference(
                workspace_id,
                workspace_type,
                subject_id,
                lifecycle_state,
                source_sha256,
                "image_variant" if resolved != path else artifact_kind,
                "local",
                resolved.as_posix(),
                str(resolved),
                _sha256_file(resolved),
                int(resolved.stat().st_size),
                "",
                "",
                exclusive_capable,
                "ready",
                "",
            )
        )
    return references


def _references_for_document(
    document: object,
    *,
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    lifecycle_state: str = "active",
    workspace_root: Path,
    source_sha256: str,
    extra_roots=None,
    force_nonexclusive=False,
):
    if extra_roots is None:
        extra_roots = APPROVED_GLOBAL_GENERATED_ROOTS
    references = []
    for kind, value, context in _walk_reference_values(document):
        if kind == "r2_pdf":
            key = _safe_object_key(value)
            context = context if isinstance(context, Mapping) else {}
            expected_sha256 = str(
                context.get("sha256") or context.get("content_sha256") or ""
            ).strip().lower()
            if len(expected_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in expected_sha256
            ):
                expected_sha256 = ""
            expected_etag = str(
                context.get("etag") or context.get("remote_etag") or ""
            ).strip().strip('"')
            if not expected_etag or "\x00" in expected_etag or len(expected_etag) > 256:
                expected_etag = ""
            version_id = str(context.get("version_id") or context.get("versionId") or "").strip()
            if "\x00" in version_id or len(version_id) > 1024:
                version_id = ""
            try:
                byte_count = max(0, int(context.get("size_bytes") or context.get("size") or 0))
            except (TypeError, ValueError):
                byte_count = 0
            if key is None:
                references.append(
                    _Reference(
                        workspace_id,
                        workspace_type,
                        subject_id,
                        lifecycle_state,
                        source_sha256,
                        "pdf",
                        "r2",
                        "unresolved:" + _fingerprint(value),
                        "",
                        "",
                        0,
                        "",
                        "",
                        False,
                        "blocked",
                        "unsafe_object_key",
                    )
                )
            else:
                references.append(
                    _Reference(
                        workspace_id,
                        workspace_type,
                        subject_id,
                        lifecycle_state,
                        source_sha256,
                        "pdf",
                        "r2",
                        key,
                        "",
                        expected_sha256,
                        byte_count,
                        expected_etag,
                        version_id,
                        # A mutable JSON document is only a reference, not an
                        # owner-bound upload receipt.  Even a valid hash/ETag
                        # can describe another tenant's publicly discoverable
                        # object, so backfill must never grant physical-delete
                        # authority from document metadata alone.
                        False,
                        "ready",
                        "",
                    )
                )
            continue
        references.extend(
            _local_reference(
                workspace_id=workspace_id,
                workspace_type=workspace_type,
                subject_id=subject_id,
                lifecycle_state=lifecycle_state,
                workspace_root=workspace_root,
                source_sha256=source_sha256,
                kind=kind,
                value=value,
                extra_roots=extra_roots,
                force_nonexclusive=force_nonexclusive,
            )
        )
    return references


def _merge_references(references: Iterable[_Reference]):
    grouped = {}
    for reference in references:
        grouped.setdefault((reference.storage_backend, reference.storage_key), []).append(reference)
    candidates = []
    for (_backend, _key), rows in sorted(grouped.items()):
        owners = {
            (row.workspace_id, row.workspace_type, row.subject_id, row.lifecycle_state)
            for row in rows
        }
        states = {row.state for row in rows}
        state = "blocked" if "blocked" in states else ("ready" if "ready" in states else "missing")
        first = rows[0]
        if len(owners) > 1:
            owner = (GLOBAL_WORKSPACE_ID, GLOBAL_WORKSPACE_TYPE, GLOBAL_SUBJECT_ID, "active")
            exclusive = False
        else:
            owner = next(iter(owners))
            has_delete_verifier = bool(
                first.storage_backend == "local"
                or first.content_sha256
                or first.storage_etag
                or first.storage_version_id
            )
            exclusive = (
                owner[1] != "system"
                and state == "ready"
                and has_delete_verifier
                and all(row.exclusive_capable for row in rows)
            )
        candidates.append(
            ArtifactCandidate(
                workspace_id=owner[0],
                workspace_type=owner[1],
                subject_id=owner[2],
                lifecycle_state=owner[3],
                artifact_kind=first.artifact_kind,
                storage_backend=first.storage_backend,
                storage_key=first.storage_key,
                exact_path=first.exact_path,
                content_sha256=first.content_sha256,
                byte_count=first.byte_count,
                storage_etag=first.storage_etag,
                storage_version_id=first.storage_version_id,
                exclusive_owner=exclusive,
                state=state,
                reference_count=len(rows),
                owner_count=len(owners),
                source_sha256s=tuple(sorted({row.source_sha256 for row in rows})),
                error_code=next((row.error_code for row in rows if row.error_code), ""),
            )
        )
    return tuple(candidates)


def _manifest(candidates: Sequence[ArtifactCandidate], source_hashes):
    material = {
        "sources": sorted(source_hashes),
        "artifacts": [
            {
                "workspace_id": item.workspace_id,
                "workspace_type": item.workspace_type,
                "subject_id": item.subject_id,
                "lifecycle_state": item.lifecycle_state,
                "artifact_id": item.artifact_id,
                "artifact_kind": item.artifact_kind,
                "storage_backend": item.storage_backend,
                "storage_key": item.storage_key,
                "exact_path": item.exact_path,
                "content_sha256": item.content_sha256,
                "byte_count": item.byte_count,
                "storage_etag": item.storage_etag,
                "storage_version_id": item.storage_version_id,
                "exclusive_owner": item.exclusive_owner,
                "state": item.state,
                "reference_count": item.reference_count,
                "owner_count": item.owner_count,
                "source_sha256s": item.source_sha256s,
                "error_code": item.error_code,
            }
            for item in candidates
        ],
    }
    return _sha256_bytes(_canonical_json(material).encode("utf-8"))


def preview_artifact_ownership(sources: Iterable[ArtifactDocumentSource]):
    """Read exact JSON sources and return a payload-free ownership preview."""

    normalized_sources = tuple(sources)
    references = []
    source_hashes = []
    for source in normalized_sources:
        raw, document = _strict_json_source(source.source_path)
        digest = _sha256_bytes(raw)
        source_hashes.append((source.source_path.resolve().as_posix(), digest))
        if source.source_name == "pdf_share_tokens":
            links = document if isinstance(document, list) else document.get("links", [])
            normalized_links = []
            for record in links if isinstance(links, list) else []:
                if not isinstance(record, Mapping):
                    continue
                normalized = dict(record)
                raw_pdf_path = str(normalized.get("pdf_path") or "")
                if raw_pdf_path:
                    candidate = Path(raw_pdf_path)
                    if not candidate.is_absolute():
                        candidate = REPO_DIR / candidate
                    normalized["pdf_path"] = str(candidate.resolve())
                normalized_links.append(normalized)
            document = {"links": normalized_links}
        if source.source_name == "feedback" and isinstance(document, Mapping):
            for record in document.get("feedback", []):
                if not isinstance(record, Mapping):
                    continue
                user = record.get("user") if isinstance(record.get("user"), Mapping) else {}
                user_id = str(user.get("user_id") or "")
                owner = (
                    (user_id, "user", user_id)
                    if user_id and "\x00" not in user_id
                    else (GLOBAL_WORKSPACE_ID, GLOBAL_WORKSPACE_TYPE, GLOBAL_SUBJECT_ID)
                )
                references.extend(
                    _references_for_document(
                        {"attachments": record.get("attachments", [])},
                        workspace_id=owner[0],
                        workspace_type=owner[1],
                        subject_id=owner[2],
                        workspace_root=PACKAGE_DIR,
                        source_sha256=digest,
                        extra_roots=(FEEDBACK_UPLOAD_DIR,),
                        force_nonexclusive=True,
                    )
                )
                references.extend(
                    _references_for_document(
                        {"admin_attachments": record.get("admin_attachments", [])},
                        workspace_id=GLOBAL_WORKSPACE_ID,
                        workspace_type=GLOBAL_WORKSPACE_TYPE,
                        subject_id=GLOBAL_SUBJECT_ID,
                        workspace_root=PACKAGE_DIR,
                        source_sha256=digest,
                        extra_roots=(FEEDBACK_UPLOAD_DIR,),
                        force_nonexclusive=True,
                    )
                )
        else:
            references.extend(
                _references_for_document(
                    document,
                    workspace_id=source.workspace_id,
                    workspace_type=source.workspace_type,
                    subject_id=source.subject_id,
                    lifecycle_state=source.lifecycle_state,
                    workspace_root=source.workspace_root,
                    source_sha256=digest,
                    extra_roots=(
                        *APPROVED_GLOBAL_GENERATED_ROOTS,
                        *source.artifact_roots,
                    ),
                )
            )
    candidates = _merge_references(references)
    preview = ArtifactOwnershipPreview(
        sources=normalized_sources,
        source_sha256s=tuple(source_hashes),
        candidates=candidates,
        manifest_sha256=_manifest(candidates, source_hashes),
    )
    _emit_event(preview, outcome="preview", mode="dry_run")
    return preview


_WORKSPACE_SOURCE_FILES = (
    "cookbooks.json",
    "restaurant_menus.json",
    "pantry_inventory.json",
    "pantry_receipt_history.json",
    "recipe-extractor/data/recipe_ingredients.json",
)


def default_artifact_document_sources(inventory=None):
    """Return existing, explicitly reviewed source paths from migration inventory."""

    if inventory is None:
        from PushShoppingList.services.data_migration_inventory_service import (
            build_default_migration_inventory,
        )

        inventory = build_default_migration_inventory()
    config = inventory.config
    sources = []
    for key in ("pdf_share_tokens", "feedback"):
        path = config.global_sources.get(key)
        if path is not None and Path(path).is_file():
            sources.append(
                ArtifactDocumentSource(
                    GLOBAL_WORKSPACE_ID,
                    GLOBAL_WORKSPACE_TYPE,
                    GLOBAL_SUBJECT_ID,
                    SHARED_PDF_DIR if key == "pdf_share_tokens" else PACKAGE_DIR,
                    Path(path),
                    key,
                    "active",
                )
            )
    for workspace in config.workspaces:
        for relative in _WORKSPACE_SOURCE_FILES:
            path = workspace.root / relative
            if path.is_file():
                sources.append(
                    ArtifactDocumentSource(
                        workspace.workspace_id,
                        workspace.workspace_type,
                        workspace.subject_id,
                        workspace.root,
                        path,
                        Path(relative).name,
                        workspace.lifecycle_state,
                    )
                )
        output = workspace.root / "recipe-extractor" / "data" / "output"
        if output.is_dir():
            for path in sorted(output.glob("*.json"), key=lambda item: item.name.casefold()):
                if path.name != "sorted_ingredients.json" and path.is_file():
                    sources.append(
                        ArtifactDocumentSource(
                            workspace.workspace_id,
                            workspace.workspace_type,
                            workspace.subject_id,
                            workspace.root,
                            path,
                            "recipe_json",
                            workspace.lifecycle_state,
                        )
                    )
    return tuple(sources)


def preview_default_artifact_ownership(inventory=None):
    return preview_artifact_ownership(default_artifact_document_sources(inventory))


def _candidate_metadata(candidate: ArtifactCandidate):
    return {
        "owner_count": candidate.owner_count,
        "reference_count": candidate.reference_count,
        "shared": candidate.owner_count > 1,
        "expected_etag": candidate.storage_etag,
        "version_id": candidate.storage_version_id,
        "physical_delete_blocked": bool(
            candidate.storage_backend == "r2"
            and not (
                candidate.content_sha256
                or candidate.storage_etag
                or candidate.storage_version_id
            )
        ),
        "trusted_write": candidate.trusted_write,
        "source_fingerprints": [value[:16] for value in candidate.source_sha256s],
    }


def _upsert_candidate(application_data, connection, candidate: ArtifactCandidate):
    existing_storage = connection.execute(
        "SELECT * FROM artifacts WHERE storage_backend = ? AND storage_key = ?",
        (candidate.storage_backend, candidate.storage_key),
    ).fetchone()
    if existing_storage is not None and str(existing_storage["workspace_id"]) != candidate.workspace_id:
        # A second runtime owner makes the artifact shared.  Keep the immutable
        # first owner but revoke physical-delete authority immediately.
        try:
            metadata = json.loads(str(existing_storage["metadata_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        metadata.update(_candidate_metadata(candidate))
        metadata["shared"] = True
        result = application_data.upsert_artifact(
            str(existing_storage["id"]),
            str(existing_storage["workspace_id"]),
            str(existing_storage["artifact_kind"]),
            str(existing_storage["storage_backend"]),
            str(existing_storage["storage_key"]),
            exact_path=str(existing_storage["exact_path"] or ""),
            content_sha256=str(existing_storage["content_sha256"] or ""),
            byte_count=int(existing_storage["byte_count"] or 0),
            exclusive_owner=False,
            lifecycle_state=str(existing_storage["lifecycle_state"]),
            metadata=metadata,
            allow_update=True,
            connection=connection,
        )
        result["shared_collision"] = True
        return result
    exclusive_owner = candidate.exclusive_owner
    metadata = _candidate_metadata(candidate)
    if existing_storage is not None:
        try:
            existing_metadata = json.loads(str(existing_storage["metadata_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            existing_metadata = {}
        preserves_trusted_file = bool(
            existing_metadata.get("trusted_write")
            and existing_storage["exclusive_owner"]
            and candidate.storage_backend == "local"
            and candidate.content_sha256
            and str(existing_storage["content_sha256"] or "") == candidate.content_sha256
            and str(existing_storage["exact_path"] or "") == candidate.exact_path
        )
        if preserves_trusted_file:
            exclusive_owner = True
            metadata["trusted_write"] = True
    return application_data.upsert_artifact(
        str(existing_storage["id"]) if existing_storage is not None else candidate.artifact_id,
        candidate.workspace_id,
        candidate.artifact_kind,
        candidate.storage_backend,
        candidate.storage_key,
        exact_path=candidate.exact_path,
        content_sha256=candidate.content_sha256,
        byte_count=candidate.byte_count,
        exclusive_owner=exclusive_owner,
        lifecycle_state="active",
        metadata=metadata,
        allow_update=existing_storage is not None,
        connection=connection,
    )


def apply_artifact_ownership(
    preview: ArtifactOwnershipPreview,
    *,
    db_path=None,
    authorized: bool = False,
    approval: str = "",
    failure_injector=None,
):
    """Atomically apply one unchanged preview to an installed application DB."""

    if not authorized or approval != APPLY_APPROVAL_PHRASE:
        raise ArtifactOwnershipApprovalError("Artifact ownership apply was not approved.")
    if preview.counts.get("blocked"):
        raise ArtifactOwnershipPreviewError("Artifact ownership preview contains blocked paths.")
    current = preview_artifact_ownership(preview.sources)
    if current.manifest_sha256 != preview.manifest_sha256:
        raise StaleArtifactOwnershipPreviewError("Artifact ownership preview is stale.")
    from PushShoppingList.services import application_data_service as application_data

    status = application_data.application_schema_status(db_path)
    if not status.get("available"):
        raise ArtifactOwnershipPreviewError("Application-data schema is unavailable.")
    run_id = "artifact-backfill:" + uuid.uuid4().hex
    actions = {"inserted": 0, "updated": 0, "unchanged": 0}
    ready = [item for item in current.candidates if item.state == "ready"]
    try:
        with application_data.application_data_write_connection(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for workspace_id, workspace_type, subject_id, lifecycle_state in sorted(
                {
                    (
                        item.workspace_id,
                        item.workspace_type,
                        item.subject_id,
                        item.lifecycle_state,
                    )
                    for item in ready
                }
            ):
                application_data.ensure_workspace(
                    workspace_id,
                    workspace_type,
                    subject_id,
                    lifecycle_state=lifecycle_state,
                    connection=connection,
                )
            for index, candidate in enumerate(ready):
                if failure_injector is not None:
                    failure_injector("before_artifact", {"index": index})
                result = _upsert_candidate(application_data, connection, candidate)
                action = str(result.get("action") or "unchanged")
                actions[action] = actions.get(action, 0) + 1
                if failure_injector is not None:
                    failure_injector("after_artifact", {"index": index})
            for path_text, expected_sha256 in current.source_sha256s:
                path = Path(path_text)
                if not path.is_file() or _sha256_file(path) != expected_sha256:
                    raise StaleArtifactOwnershipPreviewError(
                        "An artifact source changed during apply."
                    )
            validated = 0
            for candidate in ready:
                row = connection.execute(
                    "SELECT * FROM artifacts WHERE storage_backend = ? AND storage_key = ?",
                    (candidate.storage_backend, candidate.storage_key),
                ).fetchone()
                if row is None:
                    raise ArtifactOwnershipPreviewError("Artifact validation count mismatched.")
                if candidate.owner_count == 1 and str(row["workspace_id"]) != candidate.workspace_id:
                    raise ArtifactOwnershipPreviewError("Artifact owner validation mismatched.")
                if candidate.owner_count > 1 and bool(row["exclusive_owner"]):
                    raise ArtifactOwnershipPreviewError("Shared artifact remained exclusive.")
                validated += 1
            application_data.record_application_migration_run(
                MIGRATION_KIND,
                "succeeded",
                run_id=run_id,
                source_sha256=current.manifest_sha256,
                summary={
                    "artifacts": len(ready),
                    "inserted": actions.get("inserted", 0),
                    "missing": current.counts.get("missing", 0),
                    "shared": current.counts.get("shared", 0),
                    "unchanged": actions.get("unchanged", 0),
                    "updated": actions.get("updated", 0),
                    "validated": validated,
                },
                connection=connection,
            )
    except Exception as exc:
        _emit_event(current, outcome="failed", mode="apply", run_id=run_id, error_code=type(exc).__name__)
        raise
    result = ArtifactOwnershipApplyResult(
        run_id=run_id,
        manifest_sha256=current.manifest_sha256,
        inserted=actions.get("inserted", 0),
        updated=actions.get("updated", 0),
        unchanged=actions.get("unchanged", 0),
        validated=len(ready),
    )
    _emit_event(current, outcome="complete", mode="apply", run_id=run_id)
    return result


def run_artifact_ownership_backfill(
    *,
    sources=None,
    inventory=None,
    apply: bool = False,
    authorized: bool = False,
    approval: str = "",
    db_path=None,
    failure_injector=None,
):
    """Preview by default; mutation is available only through the exact gate."""

    resolved_sources = (
        tuple(sources)
        if sources is not None
        else default_artifact_document_sources(inventory)
    )
    preview = preview_artifact_ownership(resolved_sources)
    if not apply:
        return preview
    return apply_artifact_ownership(
        preview,
        db_path=db_path,
        authorized=authorized,
        approval=approval,
        failure_injector=failure_injector,
    )


def register_document_artifacts(
    document: object,
    *,
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    source_sha256: str,
    connection,
    workspace_root=None,
):
    """Register references in the caller's durable-write transaction.

    Missing legacy references remain diagnostic only.  An unsafe reference
    fails closed; a storage identity already used by another workspace is
    immediately made non-exclusive so cleanup cannot delete shared bytes.
    """

    from PushShoppingList.services import application_data_service as application_data

    root = Path(workspace_root) if workspace_root is not None else _runtime_workspace_root(
        workspace_id, workspace_type, subject_id
    )
    references = _references_for_document(
        document,
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
        lifecycle_state="active",
        workspace_root=root,
        source_sha256=source_sha256,
    )
    candidates = _merge_references(references)
    blocked = [item for item in candidates if item.state == "blocked"]
    if blocked:
        raise ArtifactOwnershipPreviewError("A runtime artifact reference is unsafe.")
    results = []
    for candidate in candidates:
        if candidate.state == "ready":
            results.append(_upsert_candidate(application_data, connection, candidate))
    return {
        "registered": len(results),
        "missing": sum(item.state == "missing" for item in candidates),
        "artifacts": results,
    }


def _runtime_workspace_root(workspace_id: str, workspace_type: str, subject_id: str):
    from PushShoppingList.services import storage_service

    if workspace_type == "guest":
        return Path(storage_service.GUEST_DATA_DIR) / storage_service.safe_user_id(subject_id)
    if workspace_type == "user":
        return Path(storage_service.USER_DATA_DIR) / storage_service.safe_user_id(subject_id)
    return PACKAGE_DIR


def register_pdf_share_artifact(
    pdf_path,
    *,
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    connection,
):
    """Register one database-backed PDF share as non-exclusive global storage."""

    path = Path(pdf_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ArtifactOwnershipPreviewError("A shared PDF artifact is unavailable.")
    source_sha256 = _sha256_file(path)
    candidate = ArtifactCandidate(
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
        lifecycle_state="active",
        artifact_kind="shared_pdf",
        storage_backend="local",
        storage_key=path.as_posix(),
        exact_path=str(path),
        content_sha256=source_sha256,
        byte_count=int(path.stat().st_size),
        storage_etag="",
        storage_version_id="",
        exclusive_owner=False,
        state="ready",
        reference_count=1,
        owner_count=1,
        source_sha256s=(source_sha256,),
    )
    from PushShoppingList.services import application_data_service as application_data

    result = _upsert_candidate(application_data, connection, candidate)
    return result


def register_new_local_artifacts(
    paths_or_urls,
    *,
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    connection,
    workspace_root=None,
):
    """Grant delete authority only to files passed by their creation call site."""

    from PushShoppingList.services import application_data_service as application_data

    root = Path(workspace_root) if workspace_root is not None else _runtime_workspace_root(
        workspace_id, workspace_type, subject_id
    )
    results = []
    for value in tuple(paths_or_urls or ()):
        path, error = _resolve_local_reference(
            str(value or ""),
            root,
            extra_roots=APPROVED_GLOBAL_GENERATED_ROOTS,
        )
        if path is None:
            raise ArtifactOwnershipPreviewError(
                "A newly written artifact is outside approved ownership roots: %s."
                % error
            )
        paths = [path]
        if path.suffix.lower() in IMAGE_EXTENSIONS and "__" not in path.stem:
            paths.extend(sorted(path.parent.glob(path.stem + "__*.webp")))
        for candidate_path in paths:
            if not candidate_path.is_file():
                continue
            digest = _sha256_file(candidate_path)
            candidate = ArtifactCandidate(
                workspace_id=workspace_id,
                workspace_type=workspace_type,
                subject_id=subject_id,
                lifecycle_state="active",
                artifact_kind=(
                    "image_variant"
                    if candidate_path != path
                    else ("pdf" if path.suffix.lower() == ".pdf" else "generated_image")
                ),
                storage_backend="local",
                storage_key=candidate_path.as_posix(),
                exact_path=str(candidate_path),
                content_sha256=digest,
                byte_count=int(candidate_path.stat().st_size),
                storage_etag="",
                storage_version_id="",
                exclusive_owner=workspace_type != "system",
                state="ready",
                reference_count=1,
                owner_count=1,
                source_sha256s=(digest,),
                trusted_write=True,
            )
            results.append(_upsert_candidate(application_data, connection, candidate))
    return results


def remove_new_local_artifact_family(path_or_url, *, workspace_root=None):
    """Best-effort rollback of a just-written image and its generated variants."""

    root = Path(workspace_root) if workspace_root is not None else PACKAGE_DIR
    path, _error = _resolve_local_reference(str(path_or_url or ""), root)
    if path is None:
        return 0
    paths = [path]
    if path.suffix.lower() in IMAGE_EXTENSIONS and "__" not in path.stem:
        paths.extend(path.parent.glob(path.stem + "__*.webp"))
    removed = 0
    for candidate in paths:
        try:
            if candidate.is_file():
                candidate.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _emit_event(preview, *, outcome, mode, run_id="", error_code=""):
    try:
        from PushShoppingList.services.maintenance_log_service import emit_maintenance_event

        return emit_maintenance_event(
            event="artifact_ownership",
            run_id=run_id or ("preview:" + preview.manifest_sha256[:16]),
            phase="ownership_backfill",
            mode=mode,
            outcome=outcome,
            counts=preview.counts,
            source_sha256=preview.manifest_sha256,
            error_code=error_code,
        )
    except Exception:
        return None


__all__ = [
    "APPLY_APPROVAL_PHRASE",
    "ArtifactCandidate",
    "ArtifactDocumentSource",
    "ArtifactOwnershipApplyResult",
    "ArtifactOwnershipApprovalError",
    "ArtifactOwnershipError",
    "ArtifactOwnershipPreview",
    "ArtifactOwnershipPreviewError",
    "StaleArtifactOwnershipPreviewError",
    "apply_artifact_ownership",
    "default_artifact_document_sources",
    "preview_artifact_ownership",
    "preview_default_artifact_ownership",
    "register_document_artifacts",
    "register_new_local_artifacts",
    "register_pdf_share_artifact",
    "remove_new_local_artifact_family",
    "run_artifact_ownership_backfill",
]
