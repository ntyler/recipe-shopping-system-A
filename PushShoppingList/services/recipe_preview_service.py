"""Read-only recipe preview projection and ephemeral, option-aware PDF exports.

The editor sends canonical base amounts. Saved legacy recipes can carry scaled
amounts, so all consumers use the same base-quantity helpers before applying the
requested multiplier once. Neither a preview nor an export saves the draft.
"""

from copy import deepcopy
from decimal import Decimal
from html import escape
from io import BytesIO
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory

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
        "text_size": size,
        "nutrition_mode": nutrition_mode,
    }


def preview_buy_as_name(item):
    buy_as = text(item.get("purchasable_item")) or text(item.get("buy_as"))
    ingredient = text(item.get("ingredient"))
    if " ".join(buy_as.casefold().split()) == " ".join(ingredient.casefold().split()):
        return ""
    return buy_as


def preview_option_items(recipe, requirement_id, option, scale):
    """Scale one bundle for display without borrowing its source requirement's amount."""
    rows = []
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
        rows.append(item)
    return rows


def resolve_preview_recipe(recipe, scale, selections=None):
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
        rows.extend(preview_option_items(recipe, requirement["id"], option, scale))
    resolved = deepcopy(recipe)
    resolved["ingredients"] = rows
    resolved["servings"] = scale_servings(recipe_base_servings(recipe), scale)
    resolved["quantity"] = 1
    resolved["scaling"] = {"base_servings": resolved["servings"], "selected_multiplier": 1}
    return resolved, resolution["selected_options"]


def preview_ingredient_groups(recipe, rows, selected, scale):
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
                          "items": preview_option_items(recipe, requirement["id"], option, scale)}
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
            "recipe_author", "cuisine_tags", "dietary_preferences", "recipe_categories", "categories",
            "meal_type", "course", "main_ingredient", "cooking_method", "occasion", "custom_categories",
            "custom_tags", "tags", "servings", "quantity", "scaling", "rating",
            "level", "prep_time", "cook_time", "total_time", "inactive_time", "ingredients", "instructions",
            "nutrition", "nutrition_serving_basis", "menu_description", "equipment",
            "cookbook_name", "menu_section", "menu_price", "menu_price_amount", "menu_price_currency",
        }
        recipe.update({key: deepcopy(value) for key, value in draft.items() if key in allowed})
        if "instructions" in draft:
            recipe["instructions"] = preview_instruction_rows(draft["instructions"], saved.get("instructions", []))
    options = preview_options(payload.get("options"), recipe)
    resolved, selected = resolve_preview_recipe(recipe, options["scale"], payload.get("ingredient_option_selections"))
    nutrition, basis, nutrition_mode, nutrition_modes, nutrition_notice = preview_nutrition(recipe, options["scale"], options["nutrition_mode"])
    cover = saved.get("cover_image") if isinstance(saved.get("cover_image"), dict) else {}
    image_url = recipe_cover_image_url(url) if cover.get("path") else text(cover.get("url") or cover.get("src"))
    author = recipe.get("author") or recipe.get("author_name") or recipe.get("recipe_author")
    if isinstance(author, dict):
        author = author.get("name")
    elif isinstance(author, list):
        author = ", ".join(text(item.get("name") if isinstance(item, dict) else item) for item in author)
    instructions = recipe_edit_service.normalize_instruction_rows(recipe.get("instructions", []))
    view = {
        "title": text(recipe.get("display_name") or recipe.get("recipe_title")) or "Recipe",
        "description": text(recipe.get("description") if "description" in recipe else recipe.get("menu_description")),
        "image_url": image_url,
        "author": text(author),
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
        "ingredient_groups": preview_ingredient_groups(recipe, resolved["ingredients"], selected, options["scale"]),
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
    """Render the same projected amounts with existing ingredient/step formatters."""
    title = escape(view["title"])
    image = recipe_extract_service.format_video_recipe_title_image_for_pdf(resolved) if options["show_image"] else ""
    description = f'<p class="description">{escape(view["description"])}</p>' if view["description"] else ""
    attribution = " · ".join(escape(value) for value in (view["author"], view["source_url"]) if value)
    tags = " ".join(f'<span>{escape(tag)}</span>' for tag in view["tags"])
    assignment = " · ".join(f'{label}: {escape(view.get(key) or fallback)}' for key, label, fallback in (
        ("cookbook_name", "Cookbook", "Unassigned"), ("menu_section", "Section", "Not specified"),
        ("menu_price", "Menu Price (optional)", "Not set")))
    metrics = "".join(f'<div><small>{label}</small><strong>{escape(text(view.get(key))) or "Not specified"}</strong></div>'
                      for key, label in (("prep_time", "Prep Time"), ("cook_time", "Cook Time"),
                                         ("total_time", "Total Time"), ("servings", "Servings")))
    def ingredient_table(items):
        print_ingredients = deepcopy(items)
        for row in print_ingredients:
            buy_as = preview_buy_as_name(row)
            if buy_as:
                row["ingredient"] = f'{text(row.get("ingredient"))} (Buy as: {buy_as})'
            row["preparation"] = "; ".join(dict.fromkeys(
                value for value in (text(row.get("preparation")), text(row.get("notes"))) if value
            ))
        return recipe_extract_service.format_video_recipe_ingredients_for_pdf(print_ingredients)

    ingredient_blocks, standard = [], []
    for group in view["ingredient_groups"]:
        if not group["is_choice"]:
            standard.extend(group["items"])
            continue
        if standard:
            ingredient_blocks.append(ingredient_table(standard))
            standard = []
        ingredient_blocks.append('<div class="choice-heading"><small>Original recipe requirement · Selected bundle below</small>'
                                 f'<h3>{escape(group["source_text"])}</h3></div>' + ingredient_table(group["items"]))
    if standard:
        ingredient_blocks.append(ingredient_table(standard))
    ingredients = "".join(ingredient_blocks)
    equipment = recipe_extract_service.format_video_recipe_equipment_for_pdf(view.get("equipment", [])) or '<p class="source">No equipment specified.</p>'
    instructions = recipe_extract_service.format_video_recipe_instructions_for_pdf(resolved["instructions"])
    nutrition = ""
    if options["show_nutrition"]:
        summary = view["nutrition_summary"]
        rows = "".join(f'<div><span>{escape(row["label"])}</span><strong>{escape(row["value"] or "Not provided")}</strong></div>' for row in summary["primary"])
        groups = "".join(f'<div class="nutrient-group"><h3>{escape(group["label"])}</h3><dl>' +
                         "".join(f'<div><dt>{escape(row["label"])}</dt><dd>{escape(row["value"])}</dd></div>' for row in group["rows"]) + '</dl></div>' for group in summary["groups"])
        nutrition = (f'<section class="nutrition"><h2>Nutrition <small>{escape(view["nutrition_basis"])}</small></h2>'
                     f'<p class="source">{escape(view["nutrition_context"])}</p>'
                     + (f'<p class="source">{escape(view["nutrition_notice"])}</p>' if view["nutrition_notice"] else '') +
                     f'<div class="nutrients">{rows}</div><div class="nutrient-details">{groups}</div><p class="source">{escape(summary["note"])}</p></section>'
                     if view["nutrition"] else '<section><h2>Nutrition</h2><p>Nutrition information is not available.</p></section>')
    size = {"smaller": "10pt", "normal": "11.5pt", "larger": "13pt"}[options["text_size"]]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https: http:; style-src 'unsafe-inline'">
<style>
@page {{ margin: 14mm; }}
* {{ box-sizing: border-box; }}
body {{ font: {size}/1.5 Arial,sans-serif; color: #18252a; background: white; margin: 0; overflow-wrap: anywhere; }}
h1 {{ font-size: 2em; line-height: 1.15; margin: 0 0 8px; }} h2 {{ font-size: 1.25em; margin: 0 0 14px; break-after: avoid; }}
h3 {{ font-size: 1em; break-after: avoid; }} p {{ margin: 8px 0; }}
header {{ min-height: 132px; }} .source {{ color: #52636a; font-size: .8em; }}
.title-image {{ float: right; margin: 0 0 14px 20px; }} .title-image img {{ width: 140px; height: 140px; object-fit: cover; border-radius: 8px; }}
.tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }} .tags span {{ border: 1px solid #c5d5d0; padding: 2px 8px; border-radius: 20px; font-size: .8em; }}
.metrics {{ clear: both; display: flex; gap: 12px; border-block: 1px solid #ccd6d3; padding: 12px 0; margin: 18px 0; break-inside: avoid; }}
.metrics div {{ flex: 1; }} .metrics small,.metrics strong {{ display: block; }} small {{ font-size: .8em; color: #52636a; font-weight: normal; }}
.ingredients {{ margin-bottom: 22px; }} table {{ width: 100%; border-collapse: collapse; }} thead {{ display: table-header-group; }}
.preparation {{ display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 24px; }}
.preparation > section {{ min-width: 0; }} .equipment-list {{ padding-left: 20px; margin-top: 0; }} .equipment-list li {{ margin-bottom: 6px; }}
.choice-heading {{ margin: 16px 0 8px; break-after: avoid; break-inside: avoid; }} .choice-heading h3 {{ margin: 4px 0; }}
th,td {{ text-align: left; border-bottom: 1px solid #e3e8e6; padding: 7px; vertical-align: top; }} th {{ font-size: .8em; }}
tr,li,.title-image {{ break-inside: avoid; }} li {{ padding-left: 6px; margin-bottom: 14px; white-space: pre-line; }} li::marker {{ color: #087958; font-weight: bold; }}
.step-meta {{ font-size: .8em; color: #52636a; }} ol {{ padding-left: 24px; }}
.nutrition {{ border-top: 1px solid #ccd6d3; margin-top: 24px; padding-top: 16px; }} .nutrition h2 small {{ margin-left: 8px; }}
.nutrients {{ display: flex; flex-wrap: wrap; gap: 12px 24px; }} .nutrients div {{ min-width: 105px; break-inside: avoid; }} .nutrients span,.nutrients strong {{ display: block; }} .nutrients span {{ font-size: .8em; }}
.nutrient-details {{ display: flex; flex-wrap: wrap; gap: 18px; margin-top: 18px; }} .nutrient-group {{ flex: 1 1 170px; break-inside: avoid; }} .nutrient-group h3 {{ margin-bottom: 8px; }} .nutrient-group dl {{ margin: 0; }} .nutrient-group dl div {{ display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; border-bottom: 1px solid #e3e8e6; }} .nutrient-group dd {{ margin: 0; white-space: nowrap; }}
</style></head><body><header>{image}<h1>{title}</h1><div class="source">{attribution}</div>{description}<div class="tags">{tags}</div><p class="source">{assignment}</p></header>
<div class="metrics">{metrics}</div><div class="preparation"><section class="ingredients"><h2>Ingredients</h2>{ingredients}</section>
<section class="equipment"><h2>Equipment</h2>{equipment}</section></div>
<section class="instructions"><h2>Instructions</h2>{instructions}</section>{nutrition}</body></html>'''


def create_recipe_preview_pdf(payload):
    response, resolved = prepare_recipe_preview(payload)
    view = response["recipe"]
    html = build_recipe_preview_pdf_html(view, resolved, response["options"])
    with TemporaryDirectory(prefix="ai-pantry-preview-") as directory:
        path = Path(directory) / "recipe-preview.pdf"
        recipe_extract_service.write_recipe_page_pdf(
            text(payload.get("original_url") or payload.get("url")), html, None, path,
            expected_recipe=resolved, expected_title=view["title"],
            print_options={
                "paperWidth": 8.5, "paperHeight": 11, "scale": 1,
                "printBackground": True, "displayHeaderFooter": False,
                "preferCSSPageSize": True,
                "marginTop": 0.55, "marginBottom": 0.55,
                "marginLeft": 0.55, "marginRight": 0.55,
            },
        )
        content = path.read_bytes()
    return BytesIO(content), view["title"]
