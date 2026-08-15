"""Inventory and staged backfill for durable legacy application JSON.

This module deliberately has no import-time filesystem or database effects.  A
caller supplies every legacy root and an application-data adapter.  Preview is
read-only; apply requires an exact approval phrase, rechecks every selected
source, and uses one transaction supplied by the application-data service.

The narrow application-data contract is intentionally expressed by
``MigrationDatabaseAdapter`` while ``application_data_service`` is introduced:

* the connection context manager must not install schema and must commit or
  roll back normally;
* ``ensure_workspace`` preserves the supplied opaque workspace/subject IDs;
* ``upsert_durable_document`` must be a no-op when the key, canonical payload,
  and source hash are unchanged; and
* ``upsert_source_coverage`` records the same source hash without storing a
  legacy payload or a raw source pathname.

Accounts/auth and guest sessions are inventoried but delegated to their
specialized migrations.  Cache and artifact descriptors are inventory-only.
Recoverable store credentials require an injected encryptor.  PDF share tokens
are replaced with deterministic SHA-256 digests before a document is prepared.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Tuple


APPLY_APPROVAL_PHRASE = "APPLY DURABLE JSON MIGRATION"

SCOPE_GLOBAL = "global"
SCOPE_WORKSPACE = "workspace"

CLASSIFICATION_DURABLE = "durable"
CLASSIFICATION_CACHE = "cache"
CLASSIFICATION_ARTIFACT = "artifact"
CLASSIFICATION_SKIPPED = "skipped"

HANDLER_CANONICAL_JSON = "canonical_json"
HANDLER_RECIPE_JSON = "recipe_json"
HANDLER_SHARE_TOKEN_DIGEST = "share_token_digest"
HANDLER_ENCRYPTED_JSON = "encrypted_json"
HANDLER_SPECIALIZED_JSON = "specialized_json"
HANDLER_DELEGATED_JSON = "delegated_json"
HANDLER_SPECIALIZED_TEXT = "specialized_text"
HANDLER_EXCLUDED_FILE = "excluded_file"
HANDLER_EXCLUDED_TREE = "excluded_tree"

STATUS_READY = "ready"
STATUS_MISSING = "missing"
STATUS_UNCONFIGURED = "unconfigured"
STATUS_EXCLUDED = "excluded"
STATUS_SPECIALIZED = "specialized"
STATUS_DELEGATED = "delegated"
STATUS_BLOCKED = "blocked"
STATUS_INVALID = "invalid"

ROOT_OBJECT = "object"
ROOT_ARRAY = "array"
ROOT_OBJECT_OR_ARRAY = "object_or_array"
ROOT_ANY = "any"

_VALID_CLASSIFICATIONS = {
    CLASSIFICATION_DURABLE,
    CLASSIFICATION_CACHE,
    CLASSIFICATION_ARTIFACT,
    CLASSIFICATION_SKIPPED,
}
_VALID_SCOPES = {SCOPE_GLOBAL, SCOPE_WORKSPACE}
_VALID_ROOT_SHAPES = {ROOT_OBJECT, ROOT_ARRAY, ROOT_OBJECT_OR_ARRAY, ROOT_ANY}
_VALID_HANDLERS = {
    HANDLER_CANONICAL_JSON,
    HANDLER_RECIPE_JSON,
    HANDLER_SHARE_TOKEN_DIGEST,
    HANDLER_ENCRYPTED_JSON,
    HANDLER_SPECIALIZED_JSON,
    HANDLER_DELEGATED_JSON,
    HANDLER_SPECIALIZED_TEXT,
    HANDLER_EXCLUDED_FILE,
    HANDLER_EXCLUDED_TREE,
}
_APPLY_HANDLERS = {
    HANDLER_CANONICAL_JSON,
    HANDLER_RECIPE_JSON,
    HANDLER_SHARE_TOKEN_DIGEST,
    HANDLER_ENCRYPTED_JSON,
}
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_relative_pattern(pattern: str) -> None:
    if not pattern or Path(pattern).is_absolute():
        raise MigrationConfigurationError("Workspace source patterns must be relative.")
    normalized = pattern.replace("\\", "/")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise MigrationConfigurationError("Workspace source pattern is unsafe.")


def _validate_opaque_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or value == "" or "\x00" in value:
        raise MigrationConfigurationError("%s must be a non-empty opaque string." % field_name)


class DurableDataMigrationError(RuntimeError):
    """Base error for a safe durable-data migration operation."""


class MigrationConfigurationError(DurableDataMigrationError):
    """Raised when source roots, descriptors, or adapters are ambiguous."""


class MigrationApprovalError(DurableDataMigrationError):
    """Raised when apply was not explicitly authorized."""


class MigrationPreviewError(DurableDataMigrationError):
    """Raised when a preview cannot safely be applied."""


class StaleMigrationPreviewError(MigrationPreviewError):
    """Raised when a source or configuration changed after preview."""


class SensitiveSourceError(MigrationPreviewError):
    """Raised when recoverable secrets would be imported without encryption."""


class _DuplicateJsonKeyError(ValueError):
    pass


class _SourceShapeError(ValueError):
    pass


class SecretEncryptor(Protocol):
    """Trusted encryption boundary used only for recoverable JSON secrets."""

    @property
    def key_id(self) -> str:
        ...

    def encrypt_json(self, value: object, *, associated_data: str) -> str:
        ...


class DatabaseConnection(Protocol):
    """Minimal DB-API transaction surface required by apply."""

    def execute(self, statement: str, parameters: Sequence[object] = ()) -> Any:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


@dataclass(frozen=True)
class SourceDescriptor:
    """Strict description of one known legacy source family."""

    key: str
    scope: str
    relative_pattern: str
    domain: str
    document_key: str
    classification: str
    handler: str
    root_shape: str = ROOT_OBJECT
    collection_keys: Tuple[str, ...] = ()
    exclude_names: Tuple[str, ...] = ()
    multiple: bool = False

    def __post_init__(self) -> None:
        if not _KEY_PATTERN.fullmatch(self.key):
            raise MigrationConfigurationError("Source descriptor key is invalid.")
        if self.scope not in _VALID_SCOPES:
            raise MigrationConfigurationError("Source descriptor scope is invalid.")
        if self.classification not in _VALID_CLASSIFICATIONS:
            raise MigrationConfigurationError("Source classification is invalid.")
        if self.handler not in _VALID_HANDLERS:
            raise MigrationConfigurationError("Source handler is invalid.")
        if self.root_shape not in _VALID_ROOT_SHAPES:
            raise MigrationConfigurationError("Source root shape is invalid.")
        if not _KEY_PATTERN.fullmatch(self.domain):
            raise MigrationConfigurationError("Source domain is invalid.")
        if not self.document_key:
            raise MigrationConfigurationError("Document key cannot be empty.")
        if self.scope == SCOPE_WORKSPACE:
            _validate_relative_pattern(self.relative_pattern)
        elif self.relative_pattern:
            raise MigrationConfigurationError(
                "Global descriptors use injected exact paths, not relative patterns."
            )
        if self.multiple and self.handler not in {HANDLER_RECIPE_JSON}:
            raise MigrationConfigurationError("Only a supported multi-document handler may glob.")
        if self.handler in {HANDLER_EXCLUDED_FILE, HANDLER_EXCLUDED_TREE}:
            if self.classification not in {CLASSIFICATION_CACHE, CLASSIFICATION_ARTIFACT}:
                raise MigrationConfigurationError("Excluded sources must be cache or artifact data.")
        elif self.classification in {CLASSIFICATION_CACHE, CLASSIFICATION_ARTIFACT}:
            raise MigrationConfigurationError("Cache and artifact sources require an exclusion handler.")


@dataclass(frozen=True)
class WorkspaceSource:
    """One explicitly identified workspace root; IDs are preserved verbatim."""

    workspace_id: str
    workspace_type: str
    subject_id: str
    root: Path
    lifecycle_state: str = "active"

    def __post_init__(self) -> None:
        _validate_opaque_id(self.workspace_id, "workspace_id")
        _validate_opaque_id(self.workspace_type, "workspace_type")
        _validate_opaque_id(self.subject_id, "subject_id")
        _validate_opaque_id(self.lifecycle_state, "lifecycle_state")
        object.__setattr__(self, "root", Path(self.root))


@dataclass(frozen=True)
class DurableMigrationConfig:
    """All paths and identities needed for inventory, supplied by the caller."""

    global_sources: Mapping[str, Path]
    workspaces: Tuple[WorkspaceSource, ...]
    global_workspace: WorkspaceSource
    max_source_bytes: int = 32 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_source_bytes <= 0:
            raise MigrationConfigurationError("max_source_bytes must be positive.")
        object.__setattr__(
            self,
            "global_sources",
            {str(key): Path(value) for key, value in self.global_sources.items()},
        )
        object.__setattr__(self, "workspaces", tuple(self.workspaces))
        workspace_ids = [workspace.workspace_id for workspace in self.workspaces]
        workspace_ids.append(self.global_workspace.workspace_id)
        if len(workspace_ids) != len(set(workspace_ids)):
            raise MigrationConfigurationError("Workspace IDs must be unique and explicit.")


@dataclass(frozen=True)
class PreviewEntry:
    """Payload-free inventory metadata for one exact source/document."""

    entry_id: str
    source_key: str
    classification: str
    status: str
    workspace_id: str
    domain: str
    document_key: str
    source_name: str
    source_sha256: Optional[str]
    document_sha256: Optional[str]
    byte_count: int
    record_count: int
    secret_field_count: int
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        """Return a report-safe form without raw workspace IDs or source paths."""

        result = asdict(self)
        result.pop("workspace_id", None)
        result["workspace_ref"] = _short_digest(self.workspace_id)
        return result


@dataclass(frozen=True)
class MigrationPreview:
    created_at: str
    catalog_sha256: str
    config_sha256: str
    entries: Tuple[PreviewEntry, ...]

    @property
    def counts_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def counts_by_classification(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.entries:
            counts[entry.classification] = counts.get(entry.classification, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> Dict[str, object]:
        return {
            "catalog_sha256": self.catalog_sha256,
            "config_sha256": self.config_sha256,
            "counts_by_classification": self.counts_by_classification,
            "counts_by_status": self.counts_by_status,
            "created_at": self.created_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class ApplyResult:
    applied_at: str
    attempted_documents: int
    adapter_actions: Mapping[str, int]
    workspace_count: int
    source_sha256: str


@dataclass(frozen=True)
class MigrationDatabaseAdapter:
    """Injected application-data operations; this module never installs DDL."""

    connection: Callable[[], AbstractContextManager[DatabaseConnection]]
    ensure_workspace: Callable[..., object]
    upsert_durable_document: Callable[..., object]
    upsert_source_coverage: Callable[..., object]
    get_source_coverage: Optional[Callable[..., object]] = None


@dataclass(frozen=True)
class _SourceInstance:
    descriptor: SourceDescriptor
    workspace: WorkspaceSource
    path: Optional[Path]
    source_ref: str
    missing: bool = False
    unconfigured: bool = False


@dataclass(frozen=True)
class _PreparedSource:
    instance: _SourceInstance
    entry: PreviewEntry
    value: object
    document_json: Optional[str]


def _descriptor(
    key: str,
    scope: str,
    relative_pattern: str,
    domain: str,
    document_key: str,
    classification: str,
    handler: str,
    root_shape: str = ROOT_OBJECT,
    collection_keys: Tuple[str, ...] = (),
    exclude_names: Tuple[str, ...] = (),
    multiple: bool = False,
) -> SourceDescriptor:
    return SourceDescriptor(
        key=key,
        scope=scope,
        relative_pattern=relative_pattern,
        domain=domain,
        document_key=document_key,
        classification=classification,
        handler=handler,
        root_shape=root_shape,
        collection_keys=collection_keys,
        exclude_names=exclude_names,
        multiple=multiple,
    )


# The catalog is intentionally explicit.  New durable files must be reviewed
# and added here; an unconstrained recursive JSON scan is not a safe migration.
DEFAULT_SOURCE_DESCRIPTORS: Tuple[SourceDescriptor, ...] = (
    _descriptor(
        "accounts_auth", SCOPE_GLOBAL, "", "identity", "accounts",
        CLASSIFICATION_SKIPPED, HANDLER_SPECIALIZED_JSON,
        collection_keys=("users",),
    ),
    _descriptor(
        "guest_sessions", SCOPE_GLOBAL, "", "identity", "guest_sessions",
        CLASSIFICATION_SKIPPED, HANDLER_DELEGATED_JSON,
        collection_keys=("guest_sessions",),
    ),
    _descriptor(
        "feedback", SCOPE_GLOBAL, "", "support", "feedback",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("feedback",),
    ),
    _descriptor(
        "admin_audit", SCOPE_GLOBAL, "", "audit", "admin_support",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        root_shape=ROOT_OBJECT_OR_ARRAY, collection_keys=("entries",),
    ),
    _descriptor(
        "pdf_share_tokens", SCOPE_GLOBAL, "", "sharing", "pdf_share_links",
        CLASSIFICATION_DURABLE, HANDLER_SHARE_TOKEN_DIGEST,
        root_shape=ROOT_OBJECT_OR_ARRAY, collection_keys=("links",),
    ),
    _descriptor(
        "feedback_attachments", SCOPE_GLOBAL, "", "artifacts", "feedback_attachments",
        CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "avatar_uploads", SCOPE_GLOBAL, "", "artifacts", "avatar_uploads",
        CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "shared_pdf_files", SCOPE_GLOBAL, "", "artifacts", "shared_pdf_files",
        CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "cookbooks", SCOPE_WORKSPACE, "cookbooks.json", "cookbooks", "catalog",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("cookbooks",),
    ),
    _descriptor(
        "recipe_metadata", SCOPE_WORKSPACE,
        "recipe-extractor/data/recipe_ingredients.json", "recipes", "ingredients_index",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
    ),
    _descriptor(
        "recipe_json", SCOPE_WORKSPACE, "recipe-extractor/data/output/*.json",
        "recipes", "recipe", CLASSIFICATION_DURABLE, HANDLER_RECIPE_JSON,
        exclude_names=("sorted_ingredients.json",), multiple=True,
    ),
    _descriptor(
        "restaurant_menus", SCOPE_WORKSPACE, "restaurant_menus.json", "menus", "store",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("restaurants", "menus", "sections", "items", "pdf_logs"),
    ),
    _descriptor(
        "pantry_inventory", SCOPE_WORKSPACE, "pantry_inventory.json", "pantry", "inventory",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("items", "storage_locations"),
    ),
    _descriptor(
        "pantry_receipt_history", SCOPE_WORKSPACE, "pantry_receipt_history.json",
        "pantry", "receipt_history", CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("receipts",),
    ),
    _descriptor(
        "meal_plan", SCOPE_WORKSPACE, "meal_plan.json", "meal_plans", "current",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("meals",),
    ),
    _descriptor(
        "shopping_recipe_selections", SCOPE_WORKSPACE,
        "shopping_list_recipe_selections.json", "shopping", "recipe_selections",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("recipes",),
    ),
    _descriptor(
        "shopping_item_state", SCOPE_WORKSPACE,
        "recipe-extractor/data/shopping_item_state.json", "shopping", "item_state",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
    ),
    _descriptor(
        "shopping_product_choices", SCOPE_WORKSPACE,
        "recipe-extractor/data/product_choices.json", "shopping", "product_choices",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("items",),
    ),
    _descriptor(
        "openai_usage", SCOPE_WORKSPACE, "openai_usage.json", "usage", "openai",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
        collection_keys=("records",),
    ),
    _descriptor(
        "store_settings", SCOPE_WORKSPACE,
        "recipe-extractor/data/store_settings.json", "stores", "settings",
        CLASSIFICATION_DURABLE, HANDLER_CANONICAL_JSON,
    ),
    _descriptor(
        "store_credentials", SCOPE_WORKSPACE,
        "recipe-extractor/data/store_credentials.json", "stores", "credentials",
        CLASSIFICATION_DURABLE, HANDLER_ENCRYPTED_JSON,
        collection_keys=("credentials",),
    ),
    _descriptor(
        "shopping_list_text", SCOPE_WORKSPACE, "shopping_list.txt", "shopping", "list_text",
        CLASSIFICATION_SKIPPED, HANDLER_SPECIALIZED_TEXT, root_shape=ROOT_ANY,
    ),
    _descriptor(
        "recipe_url_queue", SCOPE_WORKSPACE, "urls.txt", "recipes", "url_queue",
        CLASSIFICATION_SKIPPED, HANDLER_SPECIALIZED_TEXT, root_shape=ROOT_ANY,
    ),
    _descriptor(
        "extract_progress_cache", SCOPE_WORKSPACE,
        "recipe-extractor/data/extract_progress.json", "cache", "extract_progress",
        CLASSIFICATION_CACHE, HANDLER_EXCLUDED_FILE,
    ),
    _descriptor(
        "recipe_image_progress_cache", SCOPE_WORKSPACE,
        "recipe-extractor/data/recipe_image_progress.json", "cache", "recipe_image_progress",
        CLASSIFICATION_CACHE, HANDLER_EXCLUDED_FILE,
    ),
    _descriptor(
        "product_progress_cache", SCOPE_WORKSPACE,
        "recipe-extractor/data/product_progress.json", "cache", "product_progress",
        CLASSIFICATION_CACHE, HANDLER_EXCLUDED_FILE,
    ),
    _descriptor(
        "product_results_cache", SCOPE_WORKSPACE,
        "recipe-extractor/data/product_results.json", "cache", "product_results",
        CLASSIFICATION_CACHE, HANDLER_EXCLUDED_FILE,
    ),
    _descriptor(
        "nearest_store_cache", SCOPE_WORKSPACE, "shopping_stores_Results.json",
        "cache", "nearest_stores", CLASSIFICATION_CACHE, HANDLER_EXCLUDED_FILE,
    ),
    _descriptor(
        "restaurant_scan_cache", SCOPE_WORKSPACE, "restaurant_information_scans.json",
        "cache", "restaurant_scans", CLASSIFICATION_CACHE, HANDLER_EXCLUDED_FILE,
    ),
    _descriptor(
        "recipe_raw_artifacts", SCOPE_WORKSPACE, "recipe-extractor/data/raw",
        "artifacts", "recipe_raw", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "recipe_log_artifacts", SCOPE_WORKSPACE, "recipe-extractor/data/logs",
        "artifacts", "recipe_logs", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "recipe_upload_artifacts", SCOPE_WORKSPACE, "recipe-extractor/data/uploads",
        "artifacts", "recipe_uploads", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "recipe_video_artifacts", SCOPE_WORKSPACE, "recipe-extractor/data/video",
        "artifacts", "recipe_video", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "recipe_pdf_artifacts", SCOPE_WORKSPACE, "recipe-extractor/data/pdf",
        "artifacts", "recipe_pdf", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "menu_pdf_artifacts", SCOPE_WORKSPACE, "recipe-extractor/data/menu_pdf",
        "artifacts", "menu_pdf", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "browser_profile_artifacts", SCOPE_WORKSPACE,
        "recipe-extractor/data/browser_profiles", "artifacts", "browser_profiles",
        CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
    _descriptor(
        "pantry_receipt_artifacts", SCOPE_WORKSPACE, "pantry_receipts",
        "artifacts", "pantry_receipts", CLASSIFICATION_ARTIFACT, HANDLER_EXCLUDED_TREE,
    ),
)


def preview_durable_data(
    config: DurableMigrationConfig,
    *,
    descriptors: Sequence[SourceDescriptor] = DEFAULT_SOURCE_DESCRIPTORS,
    encryptor: Optional[SecretEncryptor] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> MigrationPreview:
    """Read and classify configured sources without opening a database."""

    checked_descriptors = _validate_catalog(descriptors)
    entries, _ = _scan_sources(
        config,
        checked_descriptors,
        encryptor_available=encryptor is not None,
    )
    entries = _mark_document_collisions(entries)
    return MigrationPreview(
        created_at=_timestamp(clock),
        catalog_sha256=_catalog_hash(checked_descriptors),
        config_sha256=_config_hash(config),
        entries=tuple(entries),
    )


def apply_durable_data(
    preview: MigrationPreview,
    config: DurableMigrationConfig,
    adapter: MigrationDatabaseAdapter,
    *,
    approval: str,
    source_keys: Optional[Iterable[str]] = None,
    descriptors: Sequence[SourceDescriptor] = DEFAULT_SOURCE_DESCRIPTORS,
    encryptor: Optional[SecretEncryptor] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> ApplyResult:
    """Transactionally apply an unchanged, explicitly approved preview.

    With no ``source_keys`` selection, every configured apply-capable source is
    selected.  Consequently, an existing credential document makes the default
    apply fail closed until an encryptor is supplied.  A staged caller may pass
    an explicit safe subset and migrate credentials in a later approved run.
    """

    if approval != APPLY_APPROVAL_PHRASE:
        raise MigrationApprovalError("The exact durable-data approval phrase is required.")

    checked_descriptors = _validate_catalog(descriptors)
    if preview.catalog_sha256 != _catalog_hash(checked_descriptors):
        raise StaleMigrationPreviewError("The source catalog changed after preview.")
    if preview.config_sha256 != _config_hash(config):
        raise StaleMigrationPreviewError("The source configuration changed after preview.")

    descriptor_by_key = {descriptor.key: descriptor for descriptor in checked_descriptors}
    if source_keys is None:
        selected_keys = {
            descriptor.key
            for descriptor in checked_descriptors
            if descriptor.handler in _APPLY_HANDLERS
        }
    else:
        selected_keys = set(source_keys)
        unknown = selected_keys.difference(descriptor_by_key)
        if unknown:
            raise MigrationConfigurationError("An unknown source key was selected.")
        unsupported = {
            key
            for key in selected_keys
            if descriptor_by_key[key].handler not in _APPLY_HANDLERS
        }
        if unsupported:
            raise MigrationPreviewError("A delegated, skipped, cache, or artifact source was selected.")

    current_entries, prepared_by_id = _scan_sources(
        config,
        checked_descriptors,
        encryptor_available=encryptor is not None,
    )
    current_entries = _mark_document_collisions(current_entries)
    _assert_selected_preview_is_current(preview.entries, current_entries, selected_keys)

    selected_entries = [
        entry
        for entry in current_entries
        if entry.source_key in selected_keys and entry.status != STATUS_MISSING
    ]
    blocked = [entry for entry in selected_entries if entry.status == STATUS_BLOCKED]
    if blocked:
        if any(entry.source_key == "store_credentials" for entry in blocked):
            raise SensitiveSourceError(
                "Recoverable store credentials require an injected configured encryptor."
            )
        raise SensitiveSourceError("A selected source contains unsupported recoverable secrets.")
    invalid = [entry for entry in selected_entries if entry.status != STATUS_READY]
    if invalid:
        raise MigrationPreviewError("A selected source is not ready for apply.")

    applied_at = _timestamp(clock)
    documents: list[_PreparedSource] = []
    for entry in selected_entries:
        prepared = prepared_by_id.get(entry.entry_id)
        if prepared is None or prepared.document_json is None:
            raise MigrationPreviewError("A selected document was not prepared.")
        documents.append(prepared)

    actions: Dict[str, int] = {}
    workspaces = {
        prepared.instance.workspace.workspace_id: prepared.instance.workspace
        for prepared in documents
    }
    source_rollup = hashlib.sha256()

    with adapter.connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for workspace in sorted(workspaces.values(), key=lambda item: item.workspace_id):
                adapter.ensure_workspace(
                    connection,
                    workspace.workspace_id,
                    workspace.workspace_type,
                    workspace.subject_id,
                    state=workspace.lifecycle_state,
                )

            for prepared in sorted(
                documents,
                key=lambda item: (
                    item.entry.workspace_id,
                    item.entry.domain,
                    item.entry.document_key,
                ),
            ):
                entry = prepared.entry
                if not entry.source_sha256:
                    raise MigrationPreviewError("A selected source hash is missing.")
                existing_coverage = None
                if adapter.get_source_coverage is not None:
                    existing_coverage = adapter.get_source_coverage(
                        connection,
                        entry.workspace_id,
                        entry.domain,
                        entry.entry_id,
                    )
                if _coverage_matches(existing_coverage, entry.source_sha256):
                    actions["unchanged"] = actions.get("unchanged", 0) + 1
                    source_rollup.update(entry.entry_id.encode("ascii"))
                    source_rollup.update(entry.source_sha256.encode("ascii"))
                    continue

                document_json = prepared.document_json
                if document_json is None:
                    raise MigrationPreviewError("A selected document was not prepared.")
                if prepared.instance.descriptor.handler == HANDLER_ENCRYPTED_JSON:
                    if encryptor is None:
                        raise SensitiveSourceError(
                            "Recoverable store credentials require an injected configured encryptor."
                        )
                    if adapter.get_source_coverage is None:
                        raise MigrationConfigurationError(
                            "Encrypted imports require source-coverage reads for idempotency."
                        )
                    document_json = _encrypt_document(prepared, encryptor)
                action = adapter.upsert_durable_document(
                    connection,
                    entry.workspace_id,
                    entry.domain,
                    entry.document_key,
                    document_json,
                    entry.source_name,
                    entry.source_sha256,
                    applied_at,
                )
                action_name = _adapter_action_name(action)
                actions[action_name] = actions.get(action_name, 0) + 1
                coverage_summary = canonical_json(
                    {
                        "byte_count": entry.byte_count,
                        "classification": entry.classification,
                        "document_sha256": entry.document_sha256,
                        "record_count": entry.record_count,
                    }
                )
                adapter.upsert_source_coverage(
                    connection,
                    entry.workspace_id,
                    entry.domain,
                    entry.entry_id,
                    entry.source_sha256,
                    "covered",
                    applied_at,
                    coverage_summary,
                )
                source_rollup.update(entry.entry_id.encode("ascii"))
                source_rollup.update(entry.source_sha256.encode("ascii"))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    return ApplyResult(
        applied_at=applied_at,
        attempted_documents=len(documents),
        adapter_actions=dict(sorted(actions.items())),
        workspace_count=len(workspaces),
        source_sha256=source_rollup.hexdigest(),
    )


def application_data_service_adapter(
    db_path: Optional[Path] = None,
) -> MigrationDatabaseAdapter:
    """Bind the migration contract to ``application_data_service`` lazily.

    The lazy import keeps previews usable before the application schema exists
    and ensures importing this module never creates or opens a database.
    """

    from PushShoppingList.services import application_data_service

    def connection() -> AbstractContextManager[DatabaseConnection]:
        return application_data_service.application_data_write_connection(db_path=db_path)

    def ensure_workspace(
        database: DatabaseConnection,
        workspace_id: str,
        workspace_type: str,
        subject_id: str,
        *,
        state: str,
    ) -> object:
        return application_data_service.ensure_workspace(
            workspace_id,
            workspace_type,
            subject_id,
            lifecycle_state=state,
            connection=database,
        )

    def upsert_document(
        database: DatabaseConnection,
        workspace_id: str,
        domain: str,
        document_key: str,
        document_json: str,
        source_name: str,
        source_sha256: str,
        migrated_at: str,
    ) -> object:
        return application_data_service.upsert_durable_document(
            workspace_id,
            domain,
            document_key,
            _strict_json_loads(document_json.encode("utf-8")),
            source_kind="legacy_json",
            source_name=source_name,
            source_sha256=source_sha256,
            source_version="1",
            updated_at=migrated_at,
            connection=database,
        )

    def upsert_coverage(
        database: DatabaseConnection,
        workspace_id: str,
        domain: str,
        source_key: str,
        source_sha256: str,
        status: str,
        covered_at: str,
        summary_json: str,
    ) -> object:
        return application_data_service.upsert_source_coverage(
            workspace_id,
            domain,
            source_key,
            source_sha256,
            status=status,
            summary=_strict_json_loads(summary_json.encode("utf-8")),
            covered_at=covered_at,
            connection=database,
        )

    def get_coverage(
        database: DatabaseConnection,
        workspace_id: str,
        domain: str,
        source_key: str,
    ) -> object:
        return application_data_service.get_source_coverage(
            workspace_id,
            domain,
            source_key,
            connection=database,
        )

    return MigrationDatabaseAdapter(
        connection=connection,
        ensure_workspace=ensure_workspace,
        upsert_durable_document=upsert_document,
        upsert_source_coverage=upsert_coverage,
        get_source_coverage=get_coverage,
    )


def safe_source_keys(preview: MigrationPreview) -> Tuple[str, ...]:
    """Return ready durable source families suitable for an explicit safe stage."""

    return tuple(
        sorted(
            {
                entry.source_key
                for entry in preview.entries
                if entry.classification == CLASSIFICATION_DURABLE
                and entry.status == STATUS_READY
                and entry.source_key != "store_credentials"
            }
        )
    )


def canonical_json(value: object) -> str:
    """Serialize JSON deterministically, rejecting NaN and non-JSON values."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _scan_sources(
    config: DurableMigrationConfig,
    descriptors: Tuple[SourceDescriptor, ...],
    *,
    encryptor_available: bool,
) -> Tuple[list[PreviewEntry], Dict[str, _PreparedSource]]:
    entries: list[PreviewEntry] = []
    prepared_by_id: Dict[str, _PreparedSource] = {}
    for descriptor in descriptors:
        for instance in _source_instances(config, descriptor):
            prepared = _inspect_instance(
                instance,
                max_source_bytes=config.max_source_bytes,
                encryptor_available=encryptor_available,
            )
            entries.append(prepared.entry)
            prepared_by_id[prepared.entry.entry_id] = prepared
    entries.sort(key=lambda item: (item.source_key, item.workspace_id, item.entry_id))
    return entries, prepared_by_id


def _source_instances(
    config: DurableMigrationConfig,
    descriptor: SourceDescriptor,
) -> Tuple[_SourceInstance, ...]:
    if descriptor.scope == SCOPE_GLOBAL:
        path = config.global_sources.get(descriptor.key)
        if path is None:
            return (
                _SourceInstance(
                    descriptor=descriptor,
                    workspace=config.global_workspace,
                    path=None,
                    source_ref=descriptor.key,
                    unconfigured=True,
                ),
            )
        return (
            _SourceInstance(
                descriptor=descriptor,
                workspace=config.global_workspace,
                path=Path(path),
                source_ref=descriptor.key,
                missing=not Path(path).exists(),
            ),
        )

    instances: list[_SourceInstance] = []
    for workspace in config.workspaces:
        if descriptor.multiple:
            paths = sorted(
                (
                    path
                    for path in workspace.root.glob(descriptor.relative_pattern)
                    if path.name not in descriptor.exclude_names and path.is_file()
                ),
                key=lambda path: path.as_posix(),
            )
            if not paths:
                instances.append(
                    _SourceInstance(
                        descriptor=descriptor,
                        workspace=workspace,
                        path=None,
                        source_ref=descriptor.relative_pattern,
                        missing=True,
                    )
                )
            for path in paths:
                instances.append(
                    _SourceInstance(
                        descriptor=descriptor,
                        workspace=workspace,
                        path=path,
                        source_ref=_relative_source_ref(workspace.root, path),
                    )
                )
        else:
            path = workspace.root / descriptor.relative_pattern
            instances.append(
                _SourceInstance(
                    descriptor=descriptor,
                    workspace=workspace,
                    path=path,
                    source_ref=descriptor.relative_pattern,
                    missing=not path.exists(),
                )
            )
    return tuple(instances)


def _inspect_instance(
    instance: _SourceInstance,
    *,
    max_source_bytes: int,
    encryptor_available: bool,
) -> _PreparedSource:
    descriptor = instance.descriptor
    entry_id = _entry_id(instance)
    source_name = _redacted_source_name(instance)
    document_key = descriptor.document_key
    base = dict(
        entry_id=entry_id,
        source_key=descriptor.key,
        classification=descriptor.classification,
        workspace_id=instance.workspace.workspace_id,
        domain=descriptor.domain,
        document_key=document_key,
        source_name=source_name,
        source_sha256=None,
        document_sha256=None,
        byte_count=0,
        record_count=0,
        secret_field_count=0,
    )
    if instance.unconfigured:
        return _PreparedSource(
            instance,
            PreviewEntry(status=STATUS_UNCONFIGURED, **base),
            None,
            None,
        )
    if instance.missing or instance.path is None:
        return _PreparedSource(
            instance,
            PreviewEntry(status=STATUS_MISSING, **base),
            None,
            None,
        )

    path = instance.path
    try:
        _assert_safe_instance_path(instance)
        if descriptor.handler in {HANDLER_EXCLUDED_FILE, HANDLER_EXCLUDED_TREE}:
            file_count, byte_count = _excluded_metadata(path, descriptor.handler)
            entry = PreviewEntry(
                status=STATUS_EXCLUDED,
                byte_count=byte_count,
                record_count=file_count,
                **{key: value for key, value in base.items() if key not in {"byte_count", "record_count"}},
            )
            return _PreparedSource(instance, entry, None, None)
        if not path.is_file():
            raise _SourceShapeError("source_not_regular_file")
        if path.stat().st_size > max_source_bytes:
            raise _SourceShapeError("source_too_large")
        raw = path.read_bytes()
        if len(raw) > max_source_bytes:
            raise _SourceShapeError("source_too_large")
        source_sha256 = hashlib.sha256(raw).hexdigest()

        if descriptor.handler == HANDLER_SPECIALIZED_TEXT:
            text = raw.decode("utf-8-sig", errors="strict")
            entry = PreviewEntry(
                status=STATUS_SPECIALIZED,
                source_sha256=source_sha256,
                byte_count=len(raw),
                record_count=len(text.splitlines()),
                **{
                    key: value
                    for key, value in base.items()
                    if key not in {"source_sha256", "byte_count", "record_count"}
                },
            )
            return _PreparedSource(instance, entry, None, None)

        value = _strict_json_loads(raw)
        _validate_root_shape(value, descriptor)
        record_count = _record_count(value, descriptor)
        secret_count = _count_recoverable_secret_fields(value)
        transformed = value
        status = STATUS_READY

        if descriptor.handler == HANDLER_SHARE_TOKEN_DIGEST:
            transformed = _digest_share_tokens(value)
        elif descriptor.handler == HANDLER_ENCRYPTED_JSON:
            status = STATUS_READY if encryptor_available else STATUS_BLOCKED
        elif descriptor.handler == HANDLER_SPECIALIZED_JSON:
            status = STATUS_BLOCKED if secret_count else STATUS_SPECIALIZED
        elif descriptor.handler == HANDLER_DELEGATED_JSON:
            status = STATUS_DELEGATED

        if descriptor.handler in {HANDLER_CANONICAL_JSON, HANDLER_RECIPE_JSON} and secret_count:
            status = STATUS_BLOCKED
        transformed_secret_count = _count_recoverable_secret_fields(transformed)
        if descriptor.handler == HANDLER_SHARE_TOKEN_DIGEST and transformed_secret_count:
            raise _SourceShapeError("share_token_transform_left_secret")

        if descriptor.handler == HANDLER_RECIPE_JSON:
            document_key = _recipe_document_key(value)
            record_count = 1
        document_json = canonical_json(transformed)
        entry = PreviewEntry(
            status=status,
            document_key=document_key,
            source_sha256=source_sha256,
            document_sha256=hashlib.sha256(document_json.encode("utf-8")).hexdigest(),
            byte_count=len(raw),
            record_count=record_count,
            secret_field_count=secret_count,
            **{
                key: value
                for key, value in base.items()
                if key not in {
                    "document_key",
                    "source_sha256",
                    "document_sha256",
                    "byte_count",
                    "record_count",
                    "secret_field_count",
                }
            },
        )
        return _PreparedSource(instance, entry, value, document_json)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        error_code = _safe_error_code(exc)
        entry = PreviewEntry(status=STATUS_INVALID, error_code=error_code, **base)
        return _PreparedSource(instance, entry, None, None)


def _strict_json_loads(raw: bytes) -> object:
    text = raw.decode("utf-8-sig", errors="strict")

    def object_pairs(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKeyError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("non_finite_json_number")

    return json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _validate_root_shape(value: object, descriptor: SourceDescriptor) -> None:
    if descriptor.root_shape == ROOT_OBJECT and not isinstance(value, dict):
        raise _SourceShapeError("expected_object")
    if descriptor.root_shape == ROOT_ARRAY and not isinstance(value, list):
        raise _SourceShapeError("expected_array")
    if descriptor.root_shape == ROOT_OBJECT_OR_ARRAY and not isinstance(value, (dict, list)):
        raise _SourceShapeError("expected_object_or_array")


def _record_count(value: object, descriptor: SourceDescriptor) -> int:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 1
    if not descriptor.collection_keys:
        return len(value)
    present = False
    count = 0
    for key in descriptor.collection_keys:
        if key not in value:
            continue
        present = True
        collection = value[key]
        if not isinstance(collection, (dict, list)):
            raise _SourceShapeError("collection_has_invalid_shape")
        count += len(collection)
    if not present:
        raise _SourceShapeError("expected_collection_missing")
    return count


def _digest_share_tokens(value: object) -> object:
    if isinstance(value, list):
        links = value
    elif isinstance(value, dict):
        links = value.get("links")
    else:
        raise _SourceShapeError("share_links_invalid_root")
    if not isinstance(links, list):
        raise _SourceShapeError("share_links_missing")

    transformed_links = []
    seen_digests = set()
    for record in links:
        if not isinstance(record, dict):
            raise _SourceShapeError("share_link_invalid_record")
        transformed = dict(record)
        raw_token = transformed.pop("token", None)
        existing_digest = str(transformed.get("token_digest") or "").strip().lower()
        if raw_token is not None:
            if not isinstance(raw_token, str) or not raw_token:
                raise _SourceShapeError("share_token_empty")
            digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            if existing_digest and existing_digest != digest:
                raise _SourceShapeError("share_token_digest_mismatch")
        else:
            digest = existing_digest
        if not _HEX_SHA256_PATTERN.fullmatch(digest):
            raise _SourceShapeError("share_token_digest_invalid")
        if digest in seen_digests:
            raise _SourceShapeError("share_token_digest_collision")
        seen_digests.add(digest)
        transformed["token_digest"] = digest
        transformed["token_digest_algorithm"] = "sha256"
        transformed_links.append(transformed)
    return {"links": transformed_links}


def _recipe_document_key(value: object) -> str:
    if not isinstance(value, dict):
        raise _SourceShapeError("recipe_expected_object")
    identity = None
    for key in (
        "recipe_uuid",
        "recipe_id",
        "id",
        "source_url",
        "recipe_url",
        "url",
        "original_url",
    ):
        candidate = value.get(key)
        if isinstance(candidate, (str, int)) and str(candidate):
            identity = "%s:%s" % (key, candidate)
            break
    if identity is None:
        raise _SourceShapeError("recipe_identity_missing")
    return "identity-sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _count_recoverable_secret_fields(value: object) -> int:
    count = 0
    if isinstance(value, list):
        return sum(_count_recoverable_secret_fields(item) for item in value)
    if not isinstance(value, dict):
        return 0
    for key, child in value.items():
        normalized = _normalized_field_name(key)
        if _is_recoverable_secret_field(normalized, child):
            count += 1
        count += _count_recoverable_secret_fields(child)
    return count


def _normalized_field_name(value: object) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _is_recoverable_secret_field(name: str, value: object) -> bool:
    if value in (None, "", [], {}):
        return False
    if name.endswith("_hash") or name.endswith("_digest"):
        return False
    if name in {
        "password_hash",
        "token_hash",
        "code_hash",
        "backup_code_hashes",
        "firebase_uid",
    }:
        return False
    return name in {
        "password",
        "passphrase",
        "secret",
        "totp_secret",
        "mfa_secret",
        "two_factor_secret",
        "api_key",
        "access_token",
        "refresh_token",
        "auth_token",
        "token",
        "private_key",
        "client_secret",
    }


def _encrypt_document(prepared: _PreparedSource, encryptor: SecretEncryptor) -> str:
    entry = prepared.entry
    associated_data = "\x1f".join(
        (entry.workspace_id, entry.domain, entry.document_key, entry.source_sha256 or "")
    )
    envelope_json = encryptor.encrypt_json(
        prepared.value,
        associated_data=associated_data,
    )
    if not isinstance(envelope_json, str):
        raise SensitiveSourceError("The configured encryptor returned an invalid envelope.")
    try:
        envelope = _strict_json_loads(envelope_json.encode("utf-8"))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise SensitiveSourceError("The configured encryptor returned an invalid envelope.") from exc
    if not isinstance(envelope, dict):
        raise SensitiveSourceError("The configured encryptor returned an invalid envelope.")
    required = {"algorithm", "key_id", "nonce", "ciphertext"}
    if set(envelope) != required or any(
        not isinstance(envelope.get(key), str) or not envelope.get(key)
        for key in required
    ):
        raise SensitiveSourceError("The configured encryptor returned an invalid envelope.")
    if envelope.get("key_id") != encryptor.key_id:
        raise SensitiveSourceError("The encryption envelope key ID did not match the encryptor.")
    return canonical_json(envelope)


def _mark_document_collisions(entries: list[PreviewEntry]) -> list[PreviewEntry]:
    by_key: Dict[Tuple[str, str, str], list[int]] = {}
    for index, entry in enumerate(entries):
        if entry.status in {STATUS_MISSING, STATUS_UNCONFIGURED, STATUS_EXCLUDED}:
            continue
        key = (entry.workspace_id, entry.domain, entry.document_key)
        by_key.setdefault(key, []).append(index)
    result = list(entries)
    for indices in by_key.values():
        if len(indices) <= 1:
            continue
        for index in indices:
            result[index] = replace(
                result[index],
                status=STATUS_INVALID,
                error_code="document_identity_collision",
            )
    return result


def _assert_selected_preview_is_current(
    preview_entries: Sequence[PreviewEntry],
    current_entries: Sequence[PreviewEntry],
    selected_keys: set[str],
) -> None:
    def signatures(entries: Sequence[PreviewEntry]) -> Dict[str, Tuple[object, ...]]:
        return {
            entry.entry_id: (
                entry.source_key,
                entry.workspace_id,
                entry.domain,
                entry.document_key,
                entry.status,
                entry.source_sha256,
                entry.document_sha256,
                entry.byte_count,
                entry.record_count,
                entry.secret_field_count,
                entry.error_code,
            )
            for entry in entries
            if entry.source_key in selected_keys
        }

    if signatures(preview_entries) != signatures(current_entries):
        raise StaleMigrationPreviewError("A selected legacy source changed after preview.")


def _excluded_metadata(path: Path, handler: str) -> Tuple[int, int]:
    if handler == HANDLER_EXCLUDED_FILE:
        if not path.is_file():
            raise _SourceShapeError("excluded_file_not_regular")
        return 1, path.stat().st_size
    if not path.is_dir():
        raise _SourceShapeError("excluded_tree_not_directory")
    count = 0
    byte_count = 0
    root = path.resolve()
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        _assert_path_within(root, candidate.resolve())
        count += 1
        byte_count += candidate.stat().st_size
    return count, byte_count


def _assert_safe_instance_path(instance: _SourceInstance) -> None:
    if instance.path is None:
        raise _SourceShapeError("source_path_missing")
    if instance.descriptor.scope == SCOPE_WORKSPACE:
        _assert_path_within(instance.workspace.root.resolve(), instance.path.resolve())


def _assert_path_within(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _SourceShapeError("source_path_outside_workspace") from exc


def _relative_source_ref(root: Path, path: Path) -> str:
    _assert_path_within(root.resolve(), path.resolve())
    return path.resolve().relative_to(root.resolve()).as_posix()


def _entry_id(instance: _SourceInstance) -> str:
    material = "\x1f".join(
        (
            instance.workspace.workspace_id,
            instance.descriptor.key,
            instance.source_ref,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _redacted_source_name(instance: _SourceInstance) -> str:
    if not instance.descriptor.multiple:
        return instance.descriptor.key
    suffix = Path(instance.source_ref).suffix.lower()
    if suffix not in {".json", ".txt"}:
        suffix = ""
    return "%s-%s%s" % (
        instance.descriptor.key,
        hashlib.sha256(instance.source_ref.encode("utf-8")).hexdigest()[:16],
        suffix,
    )


def _validate_catalog(descriptors: Sequence[SourceDescriptor]) -> Tuple[SourceDescriptor, ...]:
    result = tuple(descriptors)
    keys = [descriptor.key for descriptor in result]
    if not result:
        raise MigrationConfigurationError("At least one source descriptor is required.")
    if len(keys) != len(set(keys)):
        raise MigrationConfigurationError("Source descriptor keys must be unique.")
    return result


def _catalog_hash(descriptors: Sequence[SourceDescriptor]) -> str:
    payload = [asdict(descriptor) for descriptor in descriptors]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _config_hash(config: DurableMigrationConfig) -> str:
    payload = {
        "global_sources": {
            key: str(path.resolve())
            for key, path in sorted(config.global_sources.items())
        },
        "global_workspace": _workspace_config_payload(config.global_workspace),
        "max_source_bytes": config.max_source_bytes,
        "workspaces": [
            _workspace_config_payload(workspace)
            for workspace in sorted(config.workspaces, key=lambda item: item.workspace_id)
        ],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _workspace_config_payload(workspace: WorkspaceSource) -> Dict[str, object]:
    return {
        "lifecycle_state": workspace.lifecycle_state,
        "root": str(workspace.root.resolve()),
        "subject_id": workspace.subject_id,
        "workspace_id": workspace.workspace_id,
        "workspace_type": workspace.workspace_type,
    }


def _safe_error_code(exc: BaseException) -> str:
    if isinstance(exc, _DuplicateJsonKeyError):
        return "duplicate_json_key"
    if isinstance(exc, UnicodeError):
        return "invalid_utf8"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, OSError):
        return "source_io_error"
    if isinstance(exc, _SourceShapeError):
        code = str(exc)
        return code if _KEY_PATTERN.fullmatch(code) else "invalid_source_shape"
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_json_value"
    return "invalid_source"


def _adapter_action_name(value: object) -> str:
    if isinstance(value, str) and value in {"inserted", "updated", "unchanged"}:
        return value
    if isinstance(value, Mapping):
        action = value.get("action")
        if isinstance(action, str) and action in {"inserted", "updated", "unchanged"}:
            return action
    return "applied"


def _coverage_matches(value: object, source_sha256: str) -> bool:
    if value is None:
        return False
    if isinstance(value, Mapping):
        return (
            value.get("source_sha256") == source_sha256
            and value.get("status") == "covered"
        )
    try:
        return (
            value["source_sha256"] == source_sha256
            and value["status"] == "covered"
        )
    except (KeyError, TypeError, IndexError):
        return False


def _timestamp(clock: Optional[Callable[[], datetime]]) -> str:
    value = clock() if clock is not None else datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _short_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "APPLY_APPROVAL_PHRASE",
    "ApplyResult",
    "CLASSIFICATION_ARTIFACT",
    "CLASSIFICATION_CACHE",
    "CLASSIFICATION_DURABLE",
    "CLASSIFICATION_SKIPPED",
    "DEFAULT_SOURCE_DESCRIPTORS",
    "DurableDataMigrationError",
    "DurableMigrationConfig",
    "MigrationApprovalError",
    "MigrationConfigurationError",
    "MigrationDatabaseAdapter",
    "MigrationPreview",
    "MigrationPreviewError",
    "PreviewEntry",
    "SensitiveSourceError",
    "SourceDescriptor",
    "StaleMigrationPreviewError",
    "WorkspaceSource",
    "application_data_service_adapter",
    "apply_durable_data",
    "canonical_json",
    "preview_durable_data",
    "safe_source_keys",
]
