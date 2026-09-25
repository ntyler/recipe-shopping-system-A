"""Read-only recipe preview projection and ephemeral, option-aware PDF exports.

The editor sends canonical base amounts. Saved legacy recipes can carry scaled
amounts, so all consumers use the same base-quantity helpers before applying the
requested multiplier once. Neither a preview nor an export saves the draft.
"""

from base64 import b64encode
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
from html import escape
from io import BytesIO
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from PushShoppingList.services import cuisine_category_service
from PushShoppingList.services import ingredient_type_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services.ingredient_option_service import (
    IngredientOptionSelectionRequired,
    ingredient_requirements,
    normalize_selection_map,
    resolve_ingredient_requirements,
)
from PushShoppingList.services.recipe_quantity_service import (
    recipe_base_ingredient_quantity,
    recipe_base_ingredient_unit,
    recipe_base_servings,
    recipe_selected_multiplier,
    scale_quantity,
    scale_servings,
)
from PushShoppingList.services.recipe_url_service import recipe_cover_image_url


class RecipePreviewError(ValueError):
    def __init__(self, message, status=400, **details):
        super().__init__(message)
        self.status = status
        self.details = details


def text(value):
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    return str(value).strip()


def preview_options(value, recipe=None):
    value = value if isinstance(value, dict) else {}
    raw_scale = value.get("scale", (recipe or {}).get("quantity") or recipe_selected_multiplier(recipe))
    try:
        scale = float(raw_scale)
    except (TypeError, ValueError):
        raise RecipePreviewError("Choose a valid recipe scale.")
    if not math.isfinite(scale) or not 0 < scale <= 1000:
        raise RecipePreviewError("Recipe scale must be greater than zero and at most 1000.")
    size = value.get("text_size", "normal")
    if size not in {"smaller", "normal", "larger"}:
        raise RecipePreviewError("Choose smaller, normal, or larger recipe text.")
    nutrition_mode = value.get("nutrition_mode", "per_serving")
    if nutrition_mode not in {"per_serving", "whole_recipe"}:
        raise RecipePreviewError("Choose per serving or whole recipe nutrition.")
    return {
        "scale": scale,
        "show_image": value.get("show_image") is not False,
        "show_nutrition": value.get("show_nutrition") is not False,
        "print_bundle_info": value.get("print_bundle_info") is not False,
        "print_notes": value.get("print_notes") is True,
        "text_size": size,
        "nutrition_mode": nutrition_mode,
    }


def preview_buy_as_name(item):
    buy_as = text(item.get("purchasable_item")) or text(item.get("buy_as"))
    ingredient = text(item.get("ingredient"))
    if " ".join(buy_as.casefold().split()) == " ".join(ingredient.casefold().split()):
        return ""
    return buy_as


def preview_ingredient_type(item, registry):
    """Project the workspace type label once for both live and PDF rendering."""
    value = text(item.get("section") or item.get("ingredient_type")
                 or item.get("ingredientType") or item.get("type"))
    optional = item.get("optional") is True or text(item.get("optional")).lower() in {"1", "true", "yes", "on"}
    value = value or ("optional" if optional else "main")
    key = ingredient_type_service.type_key(value)
    definition = next((entry for entry in registry.get("types", [])
                       if any(ingredient_type_service.type_key(entry.get(field)) == key
                              for field in ("id", "value", "name"))), None)
    if definition and definition.get("seeded"):
        key = ingredient_type_service.type_key(definition.get("value") or definition.get("id"))
    return key, text(definition.get("name")) if definition else value


def preview_option_items(recipe, requirement_id, option, scale, type_registry=None):
    """Scale one bundle for display without borrowing its source requirement's amount."""
    rows = []
    if type_registry is None:
        type_registry = ingredient_type_service.ingredient_type_registry_payload()
    for component_index, component in enumerate(option["items"]):
        item = deepcopy(component)
        item["quantity"] = scale_quantity(recipe_base_ingredient_quantity(component, recipe), scale)
        item["unit"] = recipe_base_ingredient_unit(component, recipe)
        item["base_quantity"] = item["quantity"]
        item["base_unit"] = item["unit"]
        item["requirement_id"] = requirement_id
        item["option_id"] = option["id"]
        item["component_index"] = component_index
        item["buy_as_label"] = preview_buy_as_name(item)
        item["ingredient_type_key"], item["ingredient_type_label"] = preview_ingredient_type(item, type_registry)
        rows.append(item)
    return rows


def resolve_preview_recipe(recipe, scale, selections=None, type_registry=None):
    """Return resolved/scaled recipe data and the actual selection map, without writes."""
    requirements = ingredient_requirements(recipe)
    requested = normalize_selection_map(selections)
    # An option can disappear while editing. In that case use the authored
    # default, not an arbitrary first alternative or an omitted requirement.
    effective = {
        requirement["id"]: requested[requirement["id"]]
        for requirement in requirements
        if any(option["id"] == requested.get(requirement["id"])
               for option in requirement["options"])
    }
    try:
        resolution = resolve_ingredient_requirements(recipe, effective, require_all=True)
    except IngredientOptionSelectionRequired as exc:
        raise RecipePreviewError(
            "Choose a default option for each ingredient choice before previewing.",
            409,
            selection_needed=True,
            requirements=exc.requirements,
        ) from exc
    rows = []
    for requirement in requirements:
        option_id = resolution["selected_options"][requirement["id"]]
        option = next(item for item in requirement["options"] if item["id"] == option_id)
        rows.extend(preview_option_items(recipe, requirement["id"], option, scale, type_registry))
    resolved = deepcopy(recipe)
    resolved["ingredients"] = rows
    resolved["servings"] = scale_servings(recipe_base_servings(recipe), scale)
    resolved["quantity"] = 1
    resolved["scaling"] = {"base_servings": resolved["servings"], "selected_multiplier": 1}
    return resolved, resolution["selected_options"]


def preview_ingredient_groups(recipe, rows, selected, scale, type_registry=None):
    """Keep authored requirement headings separate from the purchasable bundle."""
    by_requirement = {}
    for row in rows:
        by_requirement.setdefault(row["requirement_id"], []).append(row)
    return [{"requirement_id": requirement["id"],
             "is_choice": len(requirement["options"]) > 1,
             "source_text": requirement["source_text"] or requirement["label"],
             "selected_option_id": selected[requirement["id"]],
             "options": [{"id": option["id"], "label": option["label"],
                          "is_default": option["id"] == requirement["default_option_id"],
                          "items": preview_option_items(recipe, requirement["id"], option, scale, type_registry)}
                         for option in requirement["options"]],
             "items": by_requirement.get(requirement["id"], [])}
            for requirement in ingredient_requirements(recipe)]


def preview_nutrition(recipe, scale, requested_mode):
    source = recipe.get("nutrition")
    if isinstance(source, list):
        rows = [
            {"key": text(row.get("key") or row.get("name") or row.get("label")),
             "value": text(row.get("value"))}
            for row in source if isinstance(row, dict)
        ]
    else:
        rows = recipe_edit_service.normalize_nutrition_rows(source)
        if isinstance(source, dict):
            present = {row["key"] for row in rows}
            rows.extend({"key": key, "value": "0"} for key in recipe_edit_service.NUTRITION_FIELDS
                        if key not in present and source.get(key) == 0 and not isinstance(source.get(key), bool))
    basis = next((text(row.get("value")) for row in rows if row.get("key") == "serving_basis"), "")
    basis = basis or text(recipe.get("nutrition_serving_basis"))
    normalized_basis = basis.lower().strip()
    whole_recipe = bool(re.fullmatch(r"(?:per |for (?:the )?)?(?:whole|full|entire|total) recipe", normalized_basis))
    per_serving = normalized_basis in {"per serving", "per portion", "1 serving", "one serving"}
    source_mode = "whole_recipe" if whole_recipe else "per_serving" if per_serving else None
    count_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:servings?|portions?|people)?", text(recipe_base_servings(recipe)), re.I)
    count = Decimal(count_match[1]) if count_match else None
    valid_count = count is not None and count > 0
    modes = (["per_serving", "whole_recipe"] if valid_count else [source_mode]) if source_mode else []
    mode = requested_mode if requested_mode in modes else source_mode
    notice = ("Set the saved nutrition basis to per serving or whole recipe to enable conversion." if not source_mode
              else "Set a valid base serving count to convert nutrition between per serving and whole recipe." if not valid_count else "")
    factor = Decimal(1)
    if mode == "whole_recipe":
        factor = Decimal(str(scale)) * (count if per_serving else 1)
    elif mode == "per_serving" and whole_recipe:
        factor = Decimal(1) / count
    result = []
    for row in rows:
        key, value = text(row.get("key")), text(row.get("value"))
        if not key or not value or key == "serving_basis":
            continue
        if factor != 1:
            match = re.fullmatch(r"([<>≤≥]?)\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(kcal|cal|kj|g|mg|mcg|µg|μg|ug|iu)?", value, re.I)
            if match:
                number = Decimal(match[2].replace(",", "")) * factor
                formatted = format(Decimal(format(number, ".10g")), "f")
                if "." in formatted:
                    formatted = formatted.rstrip("0").rstrip(".")
                value = f"{match[1]}{formatted}{(' ' + match[3]) if match[3] else ''}"
            else:
                value = f"Not converted (saved: {value})"
        result.append({"key": key, "value": value})
    label = {"per_serving": "Per serving", "whole_recipe": "Whole recipe"}.get(mode, basis or "Serving basis not specified")
    return result, label, mode, modes, notice


def preview_nutrition_summary(rows):
    """Group the same available amounts for screen and PDF, without estimating gaps."""
    primary = {key: {"key": key, "label": label, "value": "", "icon": icon}
               for key, label, icon in (("calories", "Calories", "calories"),
                                       ("carbohydrates", "Carbohydrates", "carbs"),
                                       ("protein", "Protein", "protein"), ("fat", "Total fat", "fat"))}
    groups = {label: [] for label in ("Fats & cholesterol", "Carbohydrate details", "Vitamins & minerals", "Other nutrients")}
    aliases = {"energy": "calories", "carbs": "carbohydrates", "carbohydrate": "carbohydrates", "totalfat": "fat"}
    for row in rows:
        key = re.sub(r"[^a-z0-9]", "", row["key"].lower()).removesuffix("content")
        key = aliases.get(key, key)
        label = re.sub(r"([a-z])([A-Z])", r"\1 \2", row["key"]).replace("_", " ").strip().capitalize()
        label = re.sub(r"\bvitamin ([a-z]\d*)\b", lambda m: "Vitamin " + m[1].upper(), label, flags=re.I)
        if key in primary and not primary[key]["value"]:
            primary[key]["value"] = row["value"]
            continue
        group = ("Fats & cholesterol" if key in {"saturatedfat", "transfat", "polyunsaturatedfat", "monounsaturatedfat", "cholesterol"}
                 else "Carbohydrate details" if key in {"fiber", "dietaryfiber", "sugar", "sugars", "addedsugar", "addedsugars", "starch"}
                 else "Vitamins & minerals" if key.startswith("vitamin") or key in {"sodium", "potassium", "calcium", "iron", "magnesium", "zinc", "phosphorus", "selenium", "copper", "manganese", "folate", "folicacid", "niacin", "riboflavin", "thiamin", "thiamine"}
                 else "Other nutrients")
        groups[group].append({"key": row["key"], "label": label, "value": row["value"]})
    return {"primary": list(primary.values()),
            "groups": [{"label": label, "rows": values} for label, values in groups.items() if values],
            "note": "Only available nutrition values are shown; missing values are not zero. Nutrition is not recalculated for ingredient choices."}


def preview_tags(recipe):
    categories = recipe.get("recipe_categories") or recipe.get("categories") or {}
    categories = categories if isinstance(categories, dict) else {}
    values = [categories.get("meal_type"), recipe.get("meal_type"), recipe.get("course")]
    for key in ("cuisine_tags", "dietary_preferences", "custom_tags", "custom_categories", "tags"):
        value = recipe.get(key) or categories.get(key)
        values.extend(value if isinstance(value, list) else re.split(r"[,;]", value) if isinstance(value, str) else [])
    values.extend(recipe.get(key) or categories.get(key) for key in ("main_ingredient", "cooking_method", "occasion"))
    return list(dict.fromkeys(text(value) for value in values if text(value)))


def preview_classification_text(*values):
    labels, seen = [], set()
    for value in values:
        for row in recipe_edit_service.normalize_text_rows(value):
            for label in re.split(r"[,;]", row):
                label = text(label)
                if label and label.casefold() not in seen:
                    labels.append(label)
                    seen.add(label.casefold())
    return ", ".join(labels)


@lru_cache(maxsize=1)
def preview_flag_symbols():
    """Read only the bundled artwork; PDF flags must not depend on emoji fonts."""
    sprite = Path(__file__).resolve().parents[1] / "static/vendor/flag-icons/flags-4x3.svg"
    root = ElementTree.parse(sprite).getroot()
    return {symbol.get("id"): symbol for symbol in root}


@lru_cache(maxsize=250)
def preview_flag_image_url(country_code):
    symbol = preview_flag_symbols().get(f"flag-icons-{country_code.lower()}")
    if symbol is None:
        return ""
    svg = ElementTree.Element("{http://www.w3.org/2000/svg}svg", {
        "viewBox": symbol.get("viewBox", "0 0 640 480"), "width": "640", "height": "480",
    })
    svg.extend(deepcopy(list(symbol)))
    encoded = b64encode(ElementTree.tostring(svg, encoding="utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def preview_cuisine_items(value):
    """Resolve the same workspace icons as the editor, including explicit no-icon choices."""
    labels = preview_classification_text(value)
    if not labels:
        return []
    registry = cuisine_category_service.cuisine_category_registry_payload()
    lookup = {}
    for category in registry.get("categories", []):
        for alias in (category.get("value"), category.get("category_name"), category.get("name"),
                      *category.get("aliases", [])):
            _, plain = cuisine_category_service.split_legacy_cuisine_category_label(alias)
            key = cuisine_category_service.cuisine_category_key(plain)
            if key:
                lookup[key] = category
    items = []
    for source_label in labels.split(", "):
        _, plain = cuisine_category_service.split_legacy_cuisine_category_label(source_label)
        category = lookup.get(cuisine_category_service.cuisine_category_key(plain))
        parts = cuisine_category_service.resolve_cuisine_category_parts(
            category.get("value") or category.get("category_name") or plain,
            icon=category.get("icon", ""),
        ) if category else cuisine_category_service.resolve_cuisine_category_parts(source_label)
        country_code = cuisine_category_service.country_code_from_flag(parts["icon"])
        items.append({
            "label": parts["name"], "source_label": source_label, "icon": parts["icon"],
            "image_url": preview_flag_image_url(country_code) if country_code else "",
            "glyph": "" if country_code else cuisine_category_service.cuisine_category_icon_display(parts["icon"]),
        })
    return items


def preview_instruction_rows(draft, saved):
    """Retain step metadata by identity, never by its old list position."""
    existing = recipe_edit_service.normalize_instruction_records(saved)
    identities = ("instruction_id", "step_id", "row_id", "id")
    by_id = {recipe_edit_service.recipe_edit_row_identity(row, *identities): row
             for row in existing if recipe_edit_service.recipe_edit_row_identity(row, *identities)}
    by_text = {}
    for row in existing:
        key = recipe_edit_service.instruction_match_text_key(row.get("instruction"))
        by_text.setdefault(key, []).append(row)
    result = []
    for row in recipe_edit_service.normalize_instruction_records(draft):
        identity = recipe_edit_service.recipe_edit_row_identity(row, *identities)
        candidates = by_text.get(recipe_edit_service.instruction_match_text_key(row.get("instruction")), [])
        original = by_id.get(identity, {}) if identity else candidates[0] if len(candidates) == 1 else {}
        result.append({**original, **row})
    return sorted(result, key=lambda row: row["step_number"])


def prepare_recipe_preview(payload):
    """Build the public projection plus raw resolved data for export/shopping.

    Draft cover paths are deliberately ignored: image replacement/removal already
    saves through the existing cover handlers, and arbitrary client paths must
    never be embedded by the PDF renderer.
    """
    if not isinstance(payload, dict):
        raise RecipePreviewError("Recipe preview data must be an object.")
    url = text(payload.get("original_url") or payload.get("url"))
    if not url:
        raise RecipePreviewError("Recipe URL is required.")
    saved = recipe_edit_service.load_recipe_output(url)
    if not saved:
        raise RecipePreviewError("Recipe was not found.", 404)
    recipe = deepcopy(saved)
    draft = payload.get("recipe")
    if draft is not None and not isinstance(draft, dict):
        raise RecipePreviewError("Recipe draft must be an object.")
    if draft:
        allowed = {
            "recipe_title", "display_name", "description", "source_url", "author", "author_name",
            "recipe_author", "cuisine", "cuisine_tags", "dietary_preferences", "dietary_preference", "recipe_categories", "categories", "prep_time_group",
            "meal_type", "course", "main_ingredient", "cooking_method", "occasion", "custom_categories",
            "custom_tags", "tags", "servings", "quantity", "scaling", "rating",
            "level", "prep_time", "cook_time", "total_time", "inactive_time", "ingredients", "instructions",
            "nutrition", "nutrition_serving_basis", "menu_description", "equipment", "recipe_notes",
            "cookbook_name", "menu_section", "menu_price", "menu_price_amount", "menu_price_currency",
        }
        recipe.update({key: deepcopy(value) for key, value in draft.items() if key in allowed})
        if "instructions" in draft:
            recipe["instructions"] = preview_instruction_rows(draft["instructions"], saved.get("instructions", []))
    options = preview_options(payload.get("options"), recipe)
    type_registry = ingredient_type_service.ingredient_type_registry_payload()
    resolved, selected = resolve_preview_recipe(recipe, options["scale"], payload.get("ingredient_option_selections"), type_registry)
    nutrition, basis, nutrition_mode, nutrition_modes, nutrition_notice = preview_nutrition(recipe, options["scale"], options["nutrition_mode"])
    cover = saved.get("cover_image") if isinstance(saved.get("cover_image"), dict) else {}
    image_url = recipe_cover_image_url(url) if cover.get("path") else text(cover.get("url") or cover.get("src"))
    author = recipe.get("author") or recipe.get("author_name") or recipe.get("recipe_author")
    if isinstance(author, dict):
        author = author.get("name")
    elif isinstance(author, list):
        author = ", ".join(text(item.get("name") if isinstance(item, dict) else item) for item in author)
    instructions = recipe_edit_service.normalize_instruction_rows(recipe.get("instructions", []))
    categories = recipe.get("recipe_categories") or recipe.get("categories") or {}
    categories = categories if isinstance(categories, dict) else {}
    course = recipe.get("course") or recipe.get("meal_type") or categories.get("meal_type")
    cuisine = recipe.get("cuisine") or categories.get("cuisine") or recipe.get("cuisine_tags") or categories.get("cuisine_tags")
    if isinstance(draft, dict) and "cuisine_tags" in draft:
        cuisine = draft["cuisine_tags"]
    elif not (isinstance(draft, dict) and "cuisine" in draft):
        cuisine = recipe.get("cuisine_tags") or categories.get("cuisine_tags") or cuisine
    view = {
        "title": text(recipe.get("display_name") or recipe.get("recipe_title")) or "Recipe",
        "description": text(recipe.get("description") if "description" in recipe else recipe.get("menu_description")),
        "image_url": image_url,
        "author": text(author),
        "recipe_notes": recipe_edit_service.normalize_recipe_note_sections(recipe.get("recipe_notes") if "recipe_notes" in recipe else recipe.get("recipe_note_sections") or recipe.get("source_notes") or []),
        "saved_recipe_notes": recipe_edit_service.normalize_recipe_note_sections(saved.get("recipe_notes") if "recipe_notes" in saved else saved.get("recipe_note_sections") or saved.get("source_notes") or []),
        "course": ", ".join(recipe_edit_service.normalize_text_rows(course)),
        "cuisine": preview_classification_text(cuisine),
        "cuisine_items": preview_cuisine_items(cuisine),
        "dietary_preferences": preview_classification_text(recipe.get("dietary_preferences", categories.get("dietary_preferences")), recipe.get("dietary_preference", categories.get("dietary_preference"))),
        "main_ingredient": preview_classification_text(recipe.get("main_ingredient", categories.get("main_ingredient"))),
        "cooking_method": preview_classification_text(recipe.get("cooking_method", categories.get("cooking_method"))),
        "occasion": preview_classification_text(recipe.get("occasion", categories.get("occasion"))),
        "custom_tags": preview_classification_text(recipe.get("custom_categories", categories.get("custom_categories")), recipe.get("custom_tags", categories.get("custom_tags")), recipe.get("tags", categories.get("tags"))),
        "prep_time_group": preview_classification_text(recipe.get("prep_time_group", categories.get("prep_time_group"))),
        "source_url": text(recipe.get("source_url")),
        "tags": preview_tags(recipe),
        "cookbook_name": text(recipe.get("cookbook_name")),
        "menu_section": text(recipe.get("menu_section")),
        "menu_price": (" ".join(filter(None, [text(recipe.get("menu_price_amount")), text(recipe.get("menu_price_currency"))]))
                       if text(recipe.get("menu_price_amount")) else "")
                      if "menu_price_amount" in recipe else text(recipe.get("menu_price")),
        "prep_time": text(recipe.get("prep_time")),
        "cook_time": text(recipe.get("cook_time")),
        "total_time": text(recipe.get("total_time")),
        "servings": resolved["servings"],
        "base_servings": recipe_base_servings(recipe),
        "scale": options["scale"],
        "ingredients": [{**row, "ingredient": text(row.get("ingredient")),
                         "preparation": text(row.get("preparation")), "notes": text(row.get("notes"))}
                        for row in resolved["ingredients"]],
        "ingredient_groups": preview_ingredient_groups(recipe, resolved["ingredients"], selected, options["scale"], type_registry),
        "equipment": [{"id": text(row.get("equipment_row_id") or row.get("row_id") or row.get("id")) or str(index),
                       "name": row["equipment"]}
                      for index, row in enumerate(recipe_edit_service.normalize_equipment_records(recipe.get("equipment", [])), start=1)],
        "instructions": instructions,
        "nutrition": nutrition,
        "nutrition_summary": preview_nutrition_summary(nutrition),
        "nutrition_basis": basis,
        "nutrition_mode": nutrition_mode,
        "nutrition_modes": nutrition_modes,
        "nutrition_notice": nutrition_notice,
        "nutrition_context": (("Total for " if nutrition_mode == "whole_recipe" else "Per serving · Makes " if nutrition_mode == "per_serving" else "Recipe yield: ")
                              + text(resolved["servings"]) + (" servings" if re.fullmatch(r"\d+(?:\.\d+)?", text(resolved["servings"])) else ""))
                             if text(resolved["servings"]) else "Recipe yield not specified",
        "favorite": bool(saved.get("favorite")),
        "rating": recipe.get("rating") or 0,
    }
    resolved["cover_image"] = deepcopy(cover)
    resolved["instructions"] = instructions
    resolved["recipe_title"] = view["title"]
    response = {"ok": True, "recipe": view, "options": options, "ingredient_option_selections": selected}
    return response, resolved


def build_recipe_preview(payload):
    return prepare_recipe_preview(payload)[0]


def build_recipe_preview_pdf_html(view, resolved, options):
    """Create only the app Print shell; the trusted shared renderer owns its card."""
    static = Path(__file__).resolve().parents[1] / "static"
    styles = "\n".join(
        f'<style data-preview-stylesheet="{name}">{(static / "css" / name).read_text(encoding="utf-8")}</style>'
        for name in ("app.css", "ingredient-choices.css", "recipe-preview.css")
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https: http:; style-src 'unsafe-inline'">
<title>{escape(view["title"])}</title>{styles}</head>
<body class="app-shell-body recipe-preview-active"><div class="app-shell" data-app-layout>
<div class="app-main-shell" data-app-main-shell><main id="appContent" class="app-content" data-app-content>
<section id="recipePreviewPage" class="recipe-preview-page"><article class="recipe-preview-card"></article></section>
</main></div></div></body></html>'''


def prepare_recipe_preview_pdf_document(driver, view, options, renderer_source):
    """Render server-projected data with a repository-owned script, never client HTML."""
    driver.execute_script(
        renderer_source + """
        const model = arguments[0], options = arguments[1];
        const page = document.getElementById('recipePreviewPage');
        page.querySelector('.recipe-preview-card').innerHTML = recipePreviewCardHtml(model);
        recipePreviewApplyPrintOptions(page, options, model);
        page.querySelectorAll('details[data-preview-choice]').forEach(details => { details.open = true; });
        page.querySelectorAll('img').forEach(image => {
            image.loading = 'eager';
            image.addEventListener('error', () => { image.hidden = true; }, {once: true});
            if (image.complete && !image.naturalWidth) image.hidden = true;
        });
        """,
        view, options,
    )
    driver.set_script_timeout(20)
    result = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const images = Array.from(document.images);
        const ready = Promise.all([
            document.fonts ? document.fonts.ready : Promise.resolve(),
            ...images.map(image => image.complete ? Promise.resolve() : new Promise(resolve => {
                image.addEventListener('load', resolve, {once: true});
                image.addEventListener('error', resolve, {once: true});
            }))
        ]);
        Promise.race([ready, new Promise(resolve => setTimeout(resolve, 10000))]).then(() => {
            images.forEach(image => {
                if (!image.complete || !image.naturalWidth) image.hidden = true;
            });
            done({ready: true});
        }).catch(error => done({error: String(error)}));
        """
    )
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"Recipe preview assets could not be prepared: {result['error']}")


def create_recipe_preview_pdf(payload):
    response, resolved = prepare_recipe_preview(payload)
    view = deepcopy(response["recipe"])
    # Keep the live projection's URL preference. A saved local cover uses an
    # authenticated route there, so embed only that same file for this renderer.
    # A missing saved file also has no fallback in the live cover-image route.
    cover = resolved.get("cover_image", {})
    if cover.get("path"):
        view["image_url"] = recipe_extract_service.recipe_pdf_cover_image_src({
            "path": cover["path"], "mime_type": cover.get("mime_type"),
        })
    options = response["options"]
    html = build_recipe_preview_pdf_html(view, resolved, options)
    renderer_source = (Path(__file__).resolve().parents[1] / "static/js/recipe-preview-renderer.js").read_text(encoding="utf-8")
    with TemporaryDirectory(prefix="ai-pantry-preview-") as directory:
        path = Path(directory) / "recipe-preview.pdf"
        recipe_extract_service.write_recipe_page_pdf(
            text(payload.get("original_url") or payload.get("url")), html, None, path,
            expected_recipe=resolved, expected_title=view["title"],
            prepare_document=lambda driver: prepare_recipe_preview_pdf_document(driver, view, options, renderer_source),
            preserve_source_styles=True,
            print_options={
                "paperWidth": 8.5, "paperHeight": 11, "scale": 1,
                "printBackground": True, "displayHeaderFooter": False,
                "preferCSSPageSize": True,
                "marginTop": 0, "marginBottom": 0,
                "marginLeft": 0, "marginRight": 0,
            },
        )
        content = path.read_bytes()
    return BytesIO(content), view["title"]
