import re


def normalize_item_key(text):
    return " ".join(str(text or "").strip().lower().split())


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def purchase_mapping_for_item(item, item_state=None):
    item = clean_text(item)
    item_key = normalize_item_key(item)
    state = (item_state or {}).get(item_key, {})
    if not isinstance(state, dict):
        state = {}

    purchasable_item = clean_text(
        state.get("purchasable_item")
        or state.get("buy_as")
        or automatic_purchasable_item(item)
        or item
    )
    purchase_group = purchase_group_for_item(purchasable_item or item)

    return {
        "recipe_ingredient": item,
        "ingredient": item,
        "item_key": item_key,
        "purchasable_item": purchasable_item or item,
        "buy_as": purchasable_item or item,
        "purchase_group": purchase_group,
        "purchase_group_key": normalize_item_key(purchase_group),
        "is_mapped": normalize_item_key(purchasable_item) != item_key,
    }


def purchase_mapping_lookup_for_items(items, item_state=None):
    return {
        mapping["item_key"]: mapping
        for item in items or []
        for mapping in [purchase_mapping_for_item(item, item_state=item_state)]
        if mapping["item_key"]
    }


def purchase_group_records_for_items(items, item_state=None):
    records = []
    seen = set()

    for item in items or []:
        mapping = purchase_mapping_for_item(item, item_state=item_state)
        group_key = mapping["purchase_group_key"]
        if not group_key or group_key in seen:
            continue

        records.append({
            "ingredient": mapping["purchase_group"],
            "purchasable_item": mapping["purchasable_item"],
            "purchase_group": mapping["purchase_group"],
            "purchase_group_key": group_key,
        })
        seen.add(group_key)

    return records


def purchase_mapping_for_recipe_ingredient(item, item_state=None):
    item = item if isinstance(item, dict) else {"ingredient": item}
    ingredient = clean_text(item.get("ingredient") or item.get("original_text") or "")
    item_key = normalize_item_key(ingredient)
    state = (item_state or {}).get(item_key, {})
    if not isinstance(state, dict):
        state = {}

    purchasable_item = clean_text(
        state.get("purchasable_item")
        or state.get("buy_as")
        or item.get("purchasable_item")
        or item.get("buy_as")
        or automatic_purchasable_item(
            ingredient,
            original_text=item.get("original_text"),
            preparation=item.get("preparation"),
        )
        or ingredient
    )
    purchase_group = purchase_group_for_item(item.get("purchase_group") or purchasable_item or ingredient)

    return {
        "recipe_ingredient": ingredient,
        "ingredient": ingredient,
        "item_key": item_key,
        "purchasable_item": purchasable_item or ingredient,
        "buy_as": purchasable_item or ingredient,
        "purchase_group": purchase_group,
        "purchase_group_key": normalize_item_key(purchase_group),
        "is_mapped": normalize_item_key(purchasable_item) != item_key,
    }


def apply_purchase_mapping_to_ingredient(item, purchasable_item=None):
    if not isinstance(item, dict):
        return item

    mapping = purchase_mapping_for_recipe_ingredient({
        **item,
        "purchasable_item": purchasable_item if purchasable_item is not None else item.get("purchasable_item"),
    })
    if item.get("recipe_qty") in (None, "") and item.get("quantity") not in (None, ""):
        item["recipe_qty"] = item.get("quantity")
    item["purchasable_item"] = mapping["purchasable_item"]
    item["purchase_group"] = mapping["purchase_group"]
    return item


def purchase_group_for_item(value):
    value = clean_text(value)
    normalized = normalized_phrase(value)

    if normalized in {"egg", "eggs"}:
        return "eggs"

    return value


def automatic_purchasable_item(ingredient, original_text="", preparation=""):
    text = clean_text(ingredient)
    source_text = " ".join(
        clean_text(value)
        for value in [ingredient, original_text, preparation]
        if clean_text(value)
    )
    normalized = normalized_phrase(text)
    source_normalized = normalized_phrase(source_text)

    if normalized in {
        "egg",
        "eggs",
        "whole egg",
        "whole eggs",
        "yolk",
        "yolks",
        "egg yolk",
        "egg yolks",
        "egg white",
        "egg whites",
    }:
        return "eggs"

    if normalized in {"garlic clove", "garlic cloves", "clove garlic", "cloves garlic"}:
        return "garlic"

    if re.search(r"\bcloves?\s+of\s+garlic\b", source_normalized):
        return "garlic"

    if normalized == "melted butter" or (normalized == "butter" and "melted" in source_normalized):
        return "butter"

    parmesan = grated_parmesan_mapping(normalized)
    if parmesan:
        return parmesan

    cheese = shredded_cheese_mapping(text)
    if cheese:
        return cheese

    if lemon_part_maps_to_lemons(normalized):
        return "lemons"

    return text


def grated_parmesan_mapping(normalized):
    if normalized in {
        "grated parmesan",
        "freshly grated parmesan",
        "finely grated parmesan",
        "grated parmesan cheese",
        "freshly grated parmesan cheese",
        "finely grated parmesan cheese",
    }:
        return "parmesan cheese"

    return ""


def shredded_cheese_mapping(text):
    cleaned = clean_text(text)
    normalized = normalized_phrase(cleaned)
    match = re.match(r"^(?:freshly\s+)?shredded\s+(?P<cheese>.+)$", normalized)
    if not match:
        return ""

    cheese = match.group("cheese").strip()
    if not cheese:
        return ""

    if cheese.endswith(" cheese"):
        return cheese

    return f"{cheese} cheese"


def lemon_part_maps_to_lemons(normalized):
    return normalized in {
        "lemon juice",
        "fresh lemon juice",
        "freshly squeezed lemon juice",
        "lemon zest",
        "fresh lemon zest",
        "lemon peel",
    }


def normalized_phrase(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def display_quantity_for_purchase_group(display, purchase_group):
    display = clean_text(display)
    purchase_group = clean_text(purchase_group)

    if not display or not purchase_group:
        return display

    if re.fullmatch(r"\d+(?:\s+\d+/\d+|/\d+)?(?:\s*(?:-|to)\s*\d+(?:\s+\d+/\d+|/\d+)?)?", display):
        return f"{display} {purchase_group}"

    return display
