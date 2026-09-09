"""Ingredient editor context and image previews; previews never update a record."""
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services.master_image_preview_service import prepare_master_image as prepare_ingredient_image
from PushShoppingList.services.master_image_preview_service import resolve_master_image as resolve_ingredient_image
from PushShoppingList.services import ingredient_deletion_service as ingredient_deletion


def ingredient_editor_context(record):
    owner = record["user_id"]
    with master_data.existing_recipe_master_read_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, normalized_name FROM ingredients WHERE user_id = ? ORDER BY id", (owner,),
        ).fetchall()
        aliases = connection.execute(
            "SELECT ingredient_id, alias_name FROM ingredient_aliases WHERE user_id = ? ORDER BY normalized_alias", (owner,),
        ).fetchall()
    by_id = {row["id"]: {**dict(row), "aliases": []} for row in rows}
    for alias in aliases:
        if alias["ingredient_id"] in by_id:
            by_id[alias["ingredient_id"]]["aliases"].append(alias["alias_name"])
    usage = master_data.list_master_record_recipe_references("ingredients", record["id"], user_id=owner, limit=1)
    # Ingredients are created from workspace recipes, not a system seed registry.
    # Section classifier provenance describes assignment, not ingredient origin.
    source_label = "User-created" if owner and owner != master_data.LOCAL_USER_ID else "Workspace ingredient"
    deletion_details = ingredient_deletion.ingredient_deletion_details([record]).get(record["id"], {})
    return {
        "record": {
            key: record[key] for key in ("id", "name", "normalized_name", "store_section", "image_url", "updated_at")
        } | {
            "aliases": by_id[record["id"]]["aliases"],
            "source_label": source_label,
            "usage_count": usage["total"],
            "section_editable": True,
            **deletion_details,
        },
        "registry": list(by_id.values()),
        "sections": [{key: section[key] for key in ("section_key", "display_name", "icon")}
                     for section in master_data.ingredient_store_section_details(user_id=owner)],
    }
