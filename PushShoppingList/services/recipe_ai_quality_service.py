"""Traceable AI quality reports for saved recipes.

The report deliberately projects stored evidence. It never calls a model and it
never manufactures confidence scores when the saved recipe has none.
"""

from copy import deepcopy
import re
from urllib.parse import urlparse

from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services.ingredient_unit_service import normalize_recipe_unit_fields


INFERRED_FIELD_KEYS = (
    "ai_inferred_fields", "inferred_fields", "cookbook_item_inferred_fields",
)
GENERATED_FIELD_KEYS = ("ai_generated_fields", "generated_fields")
VERIFIED_FIELD_KEYS = ("user_verified_fields", "verified_fields", "confirmed_fields")
ESTIMATED_FIELD_KEYS = ("estimated_fields", "ai_estimated_fields")
MANUAL_FIELD_KEYS = ("manual_fields", "user_entered_fields")
EXTRACTED_FIELD_KEYS = ("extracted_fields", "source_extracted_fields")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        return ""
    return str(value).strip()


def _present(value):
    if isinstance(value, bool):
        return True
    if isinstance(value, dict):
        return any(_present(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_present(item) for item in value)
    return bool(_text(value))


def _first(*values):
    for value in values:
        if _present(value):
            return value
    return ""


def _url(value):
    value = _text(value)
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _media_url(value):
    value = _text(value)
    if value.startswith("/") and not value.startswith("//"):
        return value
    return _url(value)


def _score(value):
    """Return only explicit numeric confidence, normalized to a whole percent."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip().rstrip("%")
        if not normalized:
            return None
        try:
            value = float(normalized)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    if 0 <= value <= 1:
        value *= 100
    if not 0 <= value <= 100:
        return None
    return round(value)


def _first_score(source, keys):
    source = source if isinstance(source, dict) else {}
    for key in keys:
        value = _score(source.get(key))
        if value is not None:
            return value
    return None


def _coalesce_score(*values):
    return next((value for value in values if value is not None), None)


def _average_item_score(items, keys):
    values = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        value = _first_score(item, keys)
        if value is not None:
            values.append(value)
    return round(sum(values) / len(values)) if values else None


def _field_key(value):
    key = _text(value).casefold().replace("&", "and")
    return "_".join(filter(None, (part for part in re.split(r"[^a-z0-9]+", key))))


def _metadata_fields(recipe, keys):
    fields = []
    for key in keys:
        value = recipe.get(key) if isinstance(recipe, dict) else None
        if isinstance(value, str):
            value = value.replace(";", ",").split(",")
        elif isinstance(value, dict):
            value = [name for name, enabled in value.items() if enabled]
        if not isinstance(value, (list, tuple, set)):
            continue
        for item in value:
            if isinstance(item, dict):
                item = item.get("field") or item.get("name") or item.get("label")
            field = _field_key(item)
            if field and field not in fields:
                fields.append(field)
    return fields


def _provenance_index(recipe):
    rows = []
    for key in ("field_provenance", "provenance", "data_provenance", "source_evidence"):
        value = recipe.get(key) if isinstance(recipe, dict) else None
        if isinstance(value, dict):
            for field, evidence in value.items():
                if isinstance(evidence, dict):
                    rows.append({"field": field, **evidence})
                elif _present(evidence):
                    rows.append({"field": field, "source_name": _text(evidence)})
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    index = {}
    for row in rows:
        field = _field_key(row.get("field") or row.get("field_name") or row.get("name"))
        if field and field not in index:
            index[field] = row
    return index


def _field_provenance(field, provenance):
    """Return the saved provenance row that best represents a report field."""
    key = _field_key(field)
    aliases = {
        "title": ("title", "recipe_title", "display_name", "menu_item_name"),
        "recipe_image": ("recipe_image", "cover_image", "image"),
        "cookbook_assignment": ("cookbook_assignment", "cookbook", "cookbook_id", "cookbook_name"),
        "source_information": (
            "source_information", "source", "source_url", "source_menu_url", "source_pdf", "generated_pdf",
        ),
        "restaurant_information": (
            "restaurant_information", "restaurant", "restaurant_id", "restaurant_name",
            "restaurant_address", "restaurant_phone",
        ),
    }.get(key, (key,))
    provenance = provenance if isinstance(provenance, dict) else {}
    return next((provenance.get(alias) for alias in aliases if isinstance(provenance.get(alias), dict)), {})


def _health_provenance_details(field, provenance):
    evidence = _field_provenance(field, provenance)
    source_type = _text(_first(evidence.get("source_type"), evidence.get("type")))
    source_name = _text(_first(
        evidence.get("source_name"), evidence.get("document"), evidence.get("source"), evidence.get("name"),
    ))
    return {
        "source": source_name or source_type or "Not available",
        "source_type": source_type or "Not available",
        "source_name": source_name or "Not available",
        "last_updated": _text(_first(evidence.get("updated_at"), evidence.get("last_updated"))) or "Not available",
    }


def _field_state(field, value, recipe, provenance):
    key = _field_key(field)
    field_aliases = {
        "title": {"title", "recipe_title", "display_name", "menu_item_name"},
        "recipe_image": {"recipe_image", "cover_image", "image"},
        "cookbook_assignment": {"cookbook_assignment", "cookbook", "cookbook_id", "cookbook_name"},
        "source_information": {"source_information", "source", "source_url", "source_menu_url"},
        "restaurant_information": {"restaurant_information", "restaurant", "restaurant_id", "restaurant_name"},
    }
    aliases = field_aliases.get(key, {key})
    evidence = next((provenance.get(alias) for alias in aliases if provenance.get(alias)), {})
    explicit_status = _field_key(
        evidence.get("status") or evidence.get("origin") or evidence.get("method") or evidence.get("source_status")
    )
    generated = set(_metadata_fields(recipe, GENERATED_FIELD_KEYS))
    inferred = set(_metadata_fields(recipe, INFERRED_FIELD_KEYS))
    verified = set(_metadata_fields(recipe, VERIFIED_FIELD_KEYS))
    estimated = set(_metadata_fields(recipe, ESTIMATED_FIELD_KEYS))
    manual = set(_metadata_fields(recipe, MANUAL_FIELD_KEYS))
    extracted = set(_metadata_fields(recipe, EXTRACTED_FIELD_KEYS))

    if not _present(value):
        return "missing", "Missing"
    if explicit_status:
        if "conflict" in explicit_status or "mismatch" in explicit_status:
            return "conflicting", "Conflicting"
        if "stale" in explicit_status or "outdated" in explicit_status:
            return "stale", "Stale"
        if "verif" in explicit_status or explicit_status in {"confirmed", "approved"}:
            return "verified", "Verified"
        if "generat" in explicit_status:
            return "generated", "AI Generated"
        if "infer" in explicit_status or "estimat" in explicit_status:
            return "inferred", "AI Inferred"
        if "extract" in explicit_status or "download" in explicit_status:
            return "extracted", "Extracted"
        if "manual" in explicit_status or "user" in explicit_status or "upload" in explicit_status:
            return "manual", "Manually Entered"
    if aliases & verified:
        return "verified", "Verified"
    if aliases & extracted:
        return "extracted", "Extracted"
    if aliases & generated:
        return "generated", "AI Generated"
    if aliases & (inferred | estimated):
        return "inferred", "AI Inferred"
    if aliases & manual or _field_key(recipe.get("source_type")) == "manual":
        return "manual", "Manually Entered"
    return "unknown", "Origin Unknown"


def _confidence_label(score):
    if score is None:
        return "Unknown"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Needs Review"


def _category(label, score, relevant, explanation):
    if score is None and not relevant:
        return None
    status = "unavailable" if score is None else (
        "high" if score >= 75 else "medium" if score >= 50 else "low"
    )
    return {
        "label": label,
        "score": score,
        "status": status,
        "explanation": explanation if score is not None else f"No saved {label.casefold()} score is available.",
    }


def _merged_recipe(url):
    """Build a read-only report projection without invoking editor backfills."""
    raw = deepcopy(recipe_edit_service.load_recipe_output(url) or {"source_url": url})
    merged = deepcopy(raw)

    supplemental = {}
    menu_metadata = recipe_edit_service.editable_recipe_menu_metadata(raw)
    if isinstance(menu_metadata, dict):
        supplemental.update(menu_metadata)

    cookbook = recipe_edit_service.cookbook_recipe_assignment_for_url(url)
    if isinstance(cookbook, dict):
        supplemental.update(cookbook)

    recipe_index = recipe_edit_service.load_recipe_ingredients()
    recipe_meta = recipe_index.get(
        recipe_edit_service.normalize_recipe_url_key(url),
        {},
    ) if isinstance(recipe_index, dict) else {}
    if isinstance(recipe_meta, dict):
        supplemental["display_name"] = recipe_meta.get("name")
        supplemental["servings"] = recipe_meta.get("servings")
    cover_image = recipe_edit_service.editable_recipe_cover_image(url, raw, recipe_meta)
    if cover_image:
        supplemental["cover_image"] = cover_image

    pdf = recipe_edit_service.editable_recipe_pdf_info(raw.get("source_url") or url, raw)
    if isinstance(pdf, dict):
        generated = pdf.get("generated_recipe", {})
        source = pdf.get("webpage_backup", {})
        if isinstance(generated, dict):
            supplemental["generated_pdf_path"] = generated.get("path")
            supplemental["generated_cloudflare_pdf_url"] = generated.get("public_url")
        if isinstance(source, dict):
            supplemental["source_pdf_path"] = source.get("path")
            supplemental["source_cloudflare_pdf_url"] = source.get("public_url")

    for key, value in supplemental.items():
        if _present(value) or key not in merged:
            merged[key] = value
    return raw, merged


def _field_confidence(recipe, field, provenance):
    evidence = provenance.get(_field_key(field), {})
    score = _first_score(evidence, ("confidence", "confidence_score", "score"))
    if score is not None:
        return score
    aliases = {
        "ingredients": ("ingredients_confidence", "ingredient_confidence", "ingredients_inference_confidence"),
        "instructions": ("instructions_confidence", "instruction_confidence"),
        "nutrition": ("nutrition_confidence_score", "nutrition_confidence"),
        "recipe_image": ("image_confidence_score", "image_confidence", "cover_image_confidence"),
        "restaurant_information": ("restaurant_information_confidence", "restaurant_confidence_score"),
        "source_information": ("source_quality_score", "source_quality_confidence"),
    }
    return _first_score(recipe, aliases.get(_field_key(field), ()))


def _health_item(key, label, value, recipe, provenance, action):
    status, status_label = _field_state(key, value, recipe, provenance)
    confidence = _field_confidence(recipe, key, provenance)
    if status == "missing":
        reason = f"No saved {label.casefold()} is available."
        recommendation = f"Add or review {label.casefold()}."
    elif status in {"inferred", "generated"}:
        reason = f"Saved provenance marks {label.casefold()} as {status_label.casefold()}."
        recommendation = f"Review {label.casefold()} before publishing."
    elif status == "verified":
        reason = f"Saved metadata marks {label.casefold()} as verified."
        recommendation = "No review is currently required."
    elif status == "manual":
        reason = f"Saved metadata identifies {label.casefold()} as user-entered."
        recommendation = "Review only if the recipe has changed."
    elif status == "conflicting":
        reason = f"Saved provenance flags conflicting values for {label.casefold()}."
        recommendation = f"Resolve the conflicting {label.casefold()} values."
    elif status == "stale":
        reason = f"Saved provenance marks {label.casefold()} as stale."
        recommendation = f"Refresh or verify {label.casefold()}."
    else:
        reason = f"The value is saved, but field-level provenance is not available."
        recommendation = f"Verify {label.casefold()} if source traceability is required."
    return {
        "key": key,
        "label": label,
        "status": status,
        "status_label": status_label,
        "confidence": confidence,
        "reason": reason,
        "recommendation": recommendation,
        "action": action,
        **_health_provenance_details(key, provenance),
    }


def _ingredient_analysis(recipe):
    inferred_fields = set(_metadata_fields(recipe, INFERRED_FIELD_KEYS + GENERATED_FIELD_KEYS))
    extracted_fields = set(_metadata_fields(recipe, EXTRACTED_FIELD_KEYS))
    rows = []
    for index, item in enumerate(recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []):
        if not isinstance(item, dict):
            continue
        alternatives = item.get("alternatives") or item.get("matches") or item.get("match_candidates") or []
        alternatives = alternatives if isinstance(alternatives, list) else []
        master_name = _text(_first(
            item.get("master_ingredient_name"), item.get("matched_master_ingredient"),
            item.get("master_normalized_name"),
        ))
        has_master_id = _present(_first(item.get("ingredient_id"), item.get("master_ingredient_id")))
        match_confidence = _first_score(item, (
            "match_confidence", "master_match_confidence", "normalization_confidence", "confidence_score", "confidence",
        ))
        item_origin = _field_key(_first(
            item.get("origin"), item.get("source_type"), item.get("source_status"), item.get("method"),
        ))
        inferred = bool(
            item.get("inferred") or item.get("ai_inferred") or "ingredients" in inferred_fields
            or "infer" in item_origin or "generat" in item_origin or "estimat" in item_origin
        )
        if inferred:
            origin = "AI Inferred"
        elif "extract" in item_origin or "download" in item_origin or "ingredients" in extracted_fields:
            origin = "Extracted"
        elif "manual" in item_origin or "user" in item_origin or _field_key(recipe.get("source_type")) == "manual":
            origin = "Manually Entered"
        elif "verif" in item_origin or "confirm" in item_origin:
            origin = "Verified"
        else:
            origin = "Unknown"
        unit = _text(item.get("unit"))
        quantity = _text(_first(item.get("quantity"), item.get("amount")))
        store_section = _text(item.get("store_section"))
        flags = []
        if match_confidence is not None and match_confidence < 60:
            flags.append("Low match confidence")
        if item.get("unit_review_required") or item.get("unknown_unit"):
            flags.append("Unknown unit")
        if not has_master_id and not master_name:
            flags.append("No master-data match")
        if len(alternatives) > 1:
            flags.append("Ambiguous match")
        if not quantity:
            flags.append("Missing amount")
        if not store_section or store_section.casefold() == "misc":
            flags.append("Missing store section")
        if inferred:
            heavily_inferred = match_confidence is None or match_confidence < 60 or not quantity or not (has_master_id or master_name)
            flags.append("Heavily AI inferred" if heavily_inferred else "AI inferred")
        match_status = "Matched" if has_master_id or master_name else "Ambiguous" if alternatives else "Not matched"
        actions = [{"key": "review_ingredient", "label": "Review Ingredient", "index": index}]
        if item.get("unit_review_required") or item.get("unknown_unit"):
            actions.append({"key": "normalize_unit", "label": "Normalize Unit", "index": index})
        if not quantity:
            actions.append({"key": "add_missing_amount", "label": "Add Missing Amount", "index": index})
        if alternatives:
            actions.append({"key": "change_match", "label": "Change Match", "index": index})
        rows.append({
            "index": index,
            "image_url": _media_url(_first(item.get("ingredient_image_url"), item.get("image_url"))),
            "name": _text(_first(item.get("ingredient"), item.get("name"), item.get("original_text"))) or "Unnamed ingredient",
            "original_text": _text(_first(item.get("original_text"), item.get("original_recipe_text"))) or "Not available",
            "normalized_name": _text(item.get("normalized_name")) or "Not available",
            "amount": quantity or "Not available",
            "unit": unit or "Not available",
            "store_section": store_section or "Not available",
            "ingredient_type": _text(_first(item.get("section"), item.get("type"))) or "Not available",
            "match_status": match_status,
            "match_confidence": match_confidence,
            "matched_master_ingredient": master_name or "Not available",
            "origin": origin,
            "alternatives": [_text(_first(value.get("ingredient"), value.get("name"), value.get("normalized_name"))) for value in alternatives if isinstance(value, dict)],
            "flags": flags,
            "actions": actions,
        })
    return rows


def _source_evidence(recipe, provenance):
    definitions = [
        ("recipe_title", "Recipe Title", recipe.get("recipe_title")),
        ("menu_item_name", "Menu Item Name", recipe.get("menu_item_name")),
        ("description", "Description", _first(recipe.get("description"), recipe.get("menu_description"))),
        ("menu_price", "Price", recipe.get("menu_price")),
        ("servings", "Servings", recipe.get("servings")),
        ("prep_time", "Prep Time", recipe.get("prep_time")),
        ("cook_time", "Cook Time", recipe.get("cook_time")),
        ("ingredients", "Ingredients", recipe.get("ingredients")),
        ("instructions", "Instructions", recipe.get("instructions")),
        ("nutrition", "Nutrition", recipe.get("nutrition")),
        ("recipe_image", "Recipe Image", recipe.get("cover_image")),
        ("restaurant_name", "Restaurant Name", recipe.get("restaurant_name")),
        ("restaurant_address", "Restaurant Address", recipe.get("restaurant_address")),
        ("restaurant_phone", "Restaurant Phone", recipe.get("restaurant_phone")),
        ("source_url", "Source URL", recipe.get("source_url")),
        ("source_menu_url", "Menu URL", recipe.get("source_menu_url")),
        ("source_pdf", "Source PDF", _first(recipe.get("source_cloudflare_pdf_url"), recipe.get("source_pdf_path"))),
        ("generated_pdf", "Generated PDF", _first(recipe.get("generated_cloudflare_pdf_url"), recipe.get("generated_pdf_path"))),
        ("cookbook_assignment", "Cookbook Assignment", _first(recipe.get("cookbook_name"), recipe.get("cookbook_id"))),
    ]
    inferred = set(_metadata_fields(recipe, INFERRED_FIELD_KEYS + GENERATED_FIELD_KEYS))
    verified = set(_metadata_fields(recipe, VERIFIED_FIELD_KEYS))
    rows = []
    for key, label, value in definitions:
        evidence = provenance.get(_field_key(key), {})
        status, status_label = _field_state(key, value, recipe, provenance)
        source_type = _text(_first(evidence.get("source_type"), evidence.get("type")))
        if not source_type:
            if _field_key(key) in inferred:
                source_type = "AI Inference"
            elif _field_key(key) in verified:
                source_type = "Verified source"
            else:
                source_type = "Not available"
        source_name = _text(_first(
            evidence.get("source_name"), evidence.get("document"), evidence.get("source"), evidence.get("name")
        )) or "Not available"
        link = _url(_first(evidence.get("url"), evidence.get("source_url"), value if key.endswith("url") else ""))
        action = None
        if key == "source_pdf" and _present(value):
            action = {"key": "open_document", "label": "Open Source PDF", "document": "recipeEditSourcePdfPath"}
        elif key == "generated_pdf" and _present(value):
            action = {"key": "open_document", "label": "Open Generated PDF", "document": "recipeEditGeneratedPdfPath"}
        rows.append({
            "key": key,
            "field": label,
            "value": _text(value) if not isinstance(value, (list, dict)) else (f"{len(value)} saved item(s)" if value else "Not available"),
            "source_type": source_type,
            "source_name": source_name,
            "status": status,
            "status_label": status_label,
            "confidence": _coalesce_score(
                _first_score(evidence, ("confidence", "confidence_score", "score")),
                _field_confidence(recipe, key, provenance),
            ),
            "updated_at": _text(_first(evidence.get("updated_at"), evidence.get("last_updated"))) or "Not available",
            "url": link,
            "action": action,
        })
    return rows


def _restaurant_analysis(recipe, provenance):
    definitions = [
        ("restaurant_name", "Restaurant name"),
        ("restaurant_id", "Restaurant match status"),
        ("restaurant_website_url", "Official website"),
        ("source_menu_url", "Menu URL"),
        ("restaurant_phone", "Phone"),
        ("restaurant_address", "Address"),
        ("restaurant_hours_text", "Hours"),
        ("restaurant_current_status", "Current status"),
        ("restaurant_online_payment_available", "Online payment"),
        ("restaurant_delivery_available", "Delivery"),
        ("restaurant_logo_url", "Logo"),
        ("restaurant_rating", "Rating"),
        ("restaurant_address", "Google Maps status"),
    ]
    locked = set(_field_key(value) for value in recipe.get("restaurant_information_locked_fields", []) if _text(value))
    fields = []
    for key, label in definitions:
        value = recipe.get(key)
        status, status_label = _field_state(key, value, recipe, provenance)
        if _field_key(key) in locked:
            status, status_label = "unknown", "Locked"
        if label == "Restaurant match status":
            value = "Linked" if _present(value) else "Not linked"
            status, status_label = ("verified", "Linked") if _present(recipe.get(key)) else ("missing", "Missing")
        elif label == "Google Maps status":
            value = "Available" if _present(value) else "Not available"
        fields.append({
            "key": key,
            "label": label,
            "value": _text(value) or "Not available",
            "status": status,
            "status_label": status_label,
        })
    available = any(_present(recipe.get(key)) for key in (
        "restaurant_id", "restaurant_name", "restaurant_website_url", "source_menu_url",
        "restaurant_phone", "restaurant_address",
    ))
    actions = [{"key": "edit_restaurant", "label": "Edit Restaurant"}]
    if available:
        actions.append({"key": "refresh_restaurant", "label": "Refresh Restaurant Information"})
    if _url(recipe.get("restaurant_website_url")):
        actions.append({"key": "open_restaurant_website", "label": "Open Website"})
    if _url(recipe.get("source_menu_url")):
        actions.append({"key": "open_restaurant_menu", "label": "Open Menu"})
    if _present(recipe.get("restaurant_address")):
        actions.append({"key": "open_restaurant_map", "label": "Open Google Maps"})
    return {
        "available": available,
        "fields": fields,
        "last_scanned_at": _text(recipe.get("restaurant_information_last_scanned_at")) or "Not available",
        "actions": actions,
    }


def _image_analysis(recipe, provenance):
    cover = recipe.get("cover_image") if isinstance(recipe.get("cover_image"), dict) else {}
    image_value = _first(cover.get("url"), cover.get("src"), cover.get("path"), recipe.get("cover_image_url"))
    status, status_label = _field_state("recipe_image", image_value, recipe, provenance)
    concerns = recipe.get("image_warnings") or recipe.get("cover_image_warnings") or []
    concerns = concerns if isinstance(concerns, list) else [_text(concerns)] if _present(concerns) else []
    return {
        "available": _present(image_value),
        "image_url": _media_url(_first(cover.get("src"), cover.get("url"), recipe.get("cover_image_url"))),
        "source": _text(_first(cover.get("source"), recipe.get("cover_image_provider"))) or "Not available",
        "status": status,
        "status_label": status_label,
        "original_url": _url(_first(cover.get("original_url"), cover.get("source_url"))),
        "confidence": _field_confidence(recipe, "recipe_image", provenance),
        "dimensions": " × ".join(filter(None, (_text(cover.get("width")), _text(cover.get("height"))))) or "Not available",
        "title_match": _text(_first(
            cover.get("title_match"), cover.get("matches_title"), recipe.get("image_title_match"),
        )) or "Not available",
        "ingredient_match": _text(_first(
            cover.get("ingredient_match"), cover.get("matches_ingredients"), recipe.get("image_ingredient_match"),
        )) or "Not available",
        "prompt": _text(_first(recipe.get("cover_image_prompt"), cover.get("prompt"))) or "Not available",
        "concerns": [_text(value) for value in concerns if _text(value)],
        "actions": [
            {"key": "change_image", "label": "Change Image"},
            {"key": "regenerate_image", "label": "Regenerate Image"},
            *([{"key": "open_original_image", "label": "Open Original Image", "url": _url(_first(cover.get("original_url"), cover.get("source_url")))}] if _url(_first(cover.get("original_url"), cover.get("source_url"))) else []),
            *([{"key": "review_image_prompt", "label": "Review Image Prompt"}] if _present(_first(recipe.get("cover_image_prompt"), cover.get("prompt"))) else []),
        ],
    }


def _recommendations(health, ingredients, categories, restaurant, image):
    recommendations = []
    action_by_field = {item["key"]: item.get("action") for item in health}
    for item in health:
        if item["status"] == "missing":
            recommendations.append({
                "priority": "High", "title": f"Add {item['label']}", "reason": item["reason"],
                "benefit": "Completes an important recipe record.", "action": item.get("action"),
            })
        elif item["status"] in {"inferred", "generated"}:
            recommendations.append({
                "priority": "Medium", "title": f"Review {item['label']}", "reason": item["reason"],
                "benefit": "Confirms AI-provided content before publishing.", "action": item.get("action"),
            })
        elif item["status"] in {"conflicting", "stale"}:
            recommendations.append({
                "priority": "High" if item["status"] == "conflicting" else "Medium",
                "title": f"Review {item['label']}", "reason": item["reason"],
                "benefit": "Restores a current, consistent recipe record.", "action": item.get("action"),
            })
    flagged = [item for item in ingredients if item.get("flags")]
    if flagged:
        recommendations.append({
            "priority": "High" if any("Missing amount" in item["flags"] or "Unknown unit" in item["flags"] for item in flagged) else "Medium",
            "title": "Review flagged ingredients",
            "reason": f"{len(flagged)} ingredient(s) have saved-data or normalization concerns.",
            "benefit": "Improves quantities, shopping-list mapping, and ingredient traceability.",
            "action": {"key": "review_ingredient", "label": "Review Ingredients", "index": flagged[0]["index"]},
        })
    for category in categories.values():
        if category and category.get("score") is not None and category["score"] < 60:
            recommendations.append({
                "priority": "High", "title": f"Review {category['label']}",
                "reason": f"The saved confidence score is {category['score']}%.",
                "benefit": "Addresses a stored low-confidence signal.",
                "action": action_by_field.get(_field_key(category["label"].replace(" Confidence", ""))),
            })
    if restaurant.get("available") and any(field["status"] == "missing" for field in restaurant["fields"]):
        recommendations.append({
            "priority": "Low", "title": "Complete restaurant information",
            "reason": "One or more restaurant fields are not available.",
            "benefit": "Improves source context and restaurant actions.",
            "action": {"key": "edit_restaurant", "label": "Edit Restaurant"},
        })
    if image.get("available") and image.get("confidence") is not None and image["confidence"] < 60:
        recommendations.append({
            "priority": "Medium", "title": "Review recipe image",
            "reason": f"The saved image confidence score is {image['confidence']}%.",
            "benefit": "Improves visual relevance for the recipe.",
            "action": {"key": "change_image", "label": "Change Image"},
        })
    unique = []
    seen = set()
    for item in recommendations:
        key = item["title"]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _summary(recipe, overall, health, categories):
    source_type = _text(recipe.get("source_type"))
    source_phrase = source_type.replace("_", " ") if source_type else "a saved recipe record"
    inferred = _metadata_fields(recipe, INFERRED_FIELD_KEYS + GENERATED_FIELD_KEYS)
    extracted = _metadata_fields(recipe, ("extracted_fields", "source_extracted_fields"))
    reliable = [item["label"] for item in categories.values() if item and item.get("score") is not None and item["score"] >= 75]
    review = [item["label"] for item in health if item["status"] in {"missing", "inferred", "generated"}]
    parts = [f"This recipe is stored from {source_phrase}."]
    if extracted:
        parts.append(f"Saved provenance marks {', '.join(extracted)} as extracted.")
    if inferred:
        parts.append(f"Saved metadata marks {', '.join(inferred)} as AI inferred or generated.")
    if reliable:
        parts.append(f"Stored confidence is strongest for {', '.join(reliable)}.")
    if review:
        parts.append(f"Review is recommended for {', '.join(review)}.")
    if overall is None:
        parts.append("No overall AI confidence score is stored.")
    return " ".join(parts)


def build_recipe_ai_quality_report(url):
    raw, recipe = _merged_recipe(url)
    provenance = _provenance_index(raw)
    overall = _first_score(raw, (
        "ai_confidence", "ai_confidence_score", "inference_confidence_score", "confidence_score",
    ))
    ingredients = recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []
    instructions = recipe.get("instructions") if isinstance(recipe.get("instructions"), list) else []
    nutrition = recipe.get("nutrition") if isinstance(recipe.get("nutrition"), list) else []
    cover = recipe.get("cover_image") if isinstance(recipe.get("cover_image"), dict) else {}

    categories = {
        "source_reliability": _category(
            "Source Reliability", _first_score(raw, ("source_quality_score", "source_quality_confidence")),
            _present(_first(recipe.get("source_url"), recipe.get("source_menu_url"), recipe.get("source_type"))),
            "Stored source-quality confidence for this recipe.",
        ),
        "extraction_accuracy": _category(
            "Extraction Accuracy", _first_score(raw, ("extraction_confidence_score", "extraction_confidence")),
            _present(_first(raw.get("extracted_fields"), raw.get("source_type"))),
            "Stored extraction confidence for the imported recipe.",
        ),
        "ingredients": _category(
            "Ingredient Confidence",
            _coalesce_score(
                _first_score(raw, ("ingredients_confidence", "ingredient_confidence", "ingredients_inference_confidence")),
                _average_item_score(ingredients, ("match_confidence", "normalization_confidence", "confidence_score", "confidence")),
            ),
            bool(ingredients), "Average of explicit saved ingredient confidence values.",
        ),
        "instructions": _category(
            "Instruction Confidence",
            _coalesce_score(
                _first_score(raw, ("instructions_confidence", "instruction_confidence")),
                _average_item_score(instructions, ("confidence_score", "confidence")),
            ),
            bool(instructions), "Average of explicit saved instruction confidence values.",
        ),
        "nutrition": _category(
            "Nutrition Confidence",
            _coalesce_score(
                _first_score(raw, ("nutrition_confidence_score", "nutrition_confidence")),
                _average_item_score(nutrition, ("confidence_score", "confidence")),
            ),
            bool(nutrition), "Stored nutrition confidence for the current values.",
        ),
        "image": _category(
            "Image Confidence", _coalesce_score(
                _first_score(raw, ("image_confidence_score", "image_confidence", "cover_image_confidence")),
                _first_score(cover, ("confidence_score", "confidence")),
            ),
            bool(cover), "Stored confidence for the current recipe image.",
        ),
        "restaurant": _category(
            "Restaurant Information Confidence",
            _first_score(raw, ("restaurant_information_confidence", "restaurant_confidence_score")),
            _present(_first(recipe.get("restaurant_id"), recipe.get("restaurant_name"))),
            "Stored confidence for linked restaurant information.",
        ),
    }

    health = [
        _health_item("title", "Title", _first(recipe.get("recipe_title"), recipe.get("display_name")), raw, provenance, {"key": "focus_field", "label": "Review Title", "target": "recipeEditTitleInput"}),
        _health_item("ingredients", "Ingredients", ingredients, raw, provenance, {"key": "switch_tab", "label": "Review Ingredients", "target": "ingredients"}),
        _health_item("instructions", "Instructions", instructions, raw, provenance, {"key": "switch_tab", "label": "Review Instructions", "target": "instructions"}),
        _health_item("equipment", "Equipment", recipe.get("equipment"), raw, provenance, {"key": "switch_tab", "label": "Review Equipment", "target": "equipment"}),
        _health_item("nutrition", "Nutrition", nutrition, raw, provenance, {"key": "switch_tab", "label": "Review Nutrition", "target": "nutrition"}),
        _health_item("recipe_image", "Recipe Image", cover, raw, provenance, {"key": "change_image", "label": "Change Image"}),
        _health_item("cookbook_assignment", "Cookbook Assignment", _first(recipe.get("cookbook_id"), recipe.get("cookbook_name")), raw, provenance, {"key": "focus_field", "label": "Review Cookbook", "target": "recipeEditCookbookSearch"}),
        _health_item("source_information", "Source Information", _first(recipe.get("source_url"), recipe.get("source_menu_url"), recipe.get("source_pdf_path")), raw, provenance, {"key": "open_source_documents", "label": "Review Sources"}),
        _health_item("restaurant_information", "Restaurant Information", _first(recipe.get("restaurant_id"), recipe.get("restaurant_name")), raw, provenance, {"key": "edit_restaurant", "label": "Edit Restaurant"}),
    ]
    ingredient_analysis = _ingredient_analysis(recipe)
    restaurant = _restaurant_analysis(recipe, provenance)
    image = _image_analysis(recipe, provenance)
    recommendations = _recommendations(health, ingredient_analysis, categories, restaurant, image)
    last_analyzed = _text(_first(
        raw.get("ai_analysis_updated_at"), raw.get("ai_analyzed_at"), raw.get("last_analyzed_at"),
        raw.get("inference_updated_at"),
    ))
    _, safe_fix_changes, _ = _prepare_recipe_ai_quality_safe_fixes(raw)
    return {
        "overall_confidence": overall,
        "confidence_label": _confidence_label(overall),
        "recipe_name": _text(_first(recipe.get("recipe_title"), recipe.get("display_name"))) or "Untitled Recipe",
        "last_analyzed": last_analyzed or None,
        "summary": _summary(raw, overall, health, categories),
        "categories": categories,
        "field_analysis": health,
        "ingredient_analysis": ingredient_analysis,
        "source_evidence": _source_evidence(recipe, provenance),
        "restaurant_analysis": restaurant,
        "image_analysis": image,
        "recommendations": recommendations,
        "safe_fix_count": len(safe_fix_changes),
        "safe_fixes_available": bool(safe_fix_changes),
    }


def _strip_safe_whitespace(recipe):
    changes = []
    updates = []
    top_level_fields = (
        "source_url", "document_source_url", "menu_item_url", "source_menu_url",
        "restaurant_website_url", "menu_order_url", "source_pdf_path", "generated_pdf_path",
    )
    for field in top_level_fields:
        value = recipe.get(field)
        if isinstance(value, str) and value != value.strip():
            recipe[field] = value.strip()
            changes.append(f"Trimmed {field.replace('_', ' ')}")
            updates.append({"scope": "recipe", "field": field, "before": value, "after": recipe[field]})
    for index, item in enumerate(recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []):
        if not isinstance(item, dict):
            continue
        for field in ("ingredient", "normalized_name", "quantity", "unit", "store_section", "original_text"):
            value = item.get(field)
            if isinstance(value, str) and value != value.strip():
                item[field] = value.strip()
                changes.append(f"Trimmed ingredient {index + 1} {field.replace('_', ' ')}")
                updates.append({
                    "scope": "ingredient", "index": index, "field": field,
                    "before": value, "after": item[field],
                })
    return changes, updates


def _prepare_recipe_ai_quality_safe_fixes(recipe):
    """Project deterministic safe fixes onto a copy without persisting them."""
    updated = deepcopy(recipe if isinstance(recipe, dict) else {})
    changes, safe_updates = _strip_safe_whitespace(updated)

    before_units = [
        (_text(item.get("unit")), bool(item.get("unit_review_required")))
        for item in updated.get("ingredients", []) if isinstance(item, dict)
    ]
    normalize_recipe_unit_fields(updated, log_unrecognized=False)
    after_units = [
        (_text(item.get("unit")), bool(item.get("unit_review_required")))
        for item in updated.get("ingredients", []) if isinstance(item, dict)
    ]
    for index, (before, after) in enumerate(zip(before_units, after_units)):
        if before != after:
            changes.append(f"Normalized ingredient {index + 1} unit metadata")
            if before[0] != after[0]:
                safe_updates.append({
                    "scope": "ingredient", "index": index, "field": "unit",
                    "before": before[0], "after": after[0],
                })

    store_review = recipe_edit_service.review_recipe_store_sections(updated)
    proposed = store_review.get("recipe", {}).get("ingredients", [])
    for index, item in enumerate(updated.get("ingredients", [])):
        if not isinstance(item, dict) or index >= len(proposed) or not isinstance(proposed[index], dict):
            continue
        current_section = _text(item.get("store_section"))
        proposed_section = _text(proposed[index].get("store_section"))
        if (not current_section or current_section.casefold() == "misc") and proposed_section and proposed_section != current_section:
            item["store_section"] = proposed_section
            item["store_section_order"] = proposed[index].get("store_section_order")
            changes.append(f"Mapped ingredient {index + 1} store section to {proposed_section}")
            safe_updates.append({
                "scope": "ingredient", "index": index, "field": "store_section",
                "before": current_section, "after": proposed_section,
            })

    return updated, list(dict.fromkeys(changes)), safe_updates


def apply_recipe_ai_quality_safe_fixes(url):
    current = recipe_edit_service.load_recipe_output(url)
    if not isinstance(current, dict) or not current:
        return {"ok": False, "error": "Recipe not found."}
    updated, changes, safe_updates = _prepare_recipe_ai_quality_safe_fixes(current)
    if changes:
        recipe_edit_service.save_recipe_output(url, updated)
    return {
        "ok": True,
        "changed_count": len(changes),
        "changes": changes,
        "safe_updates": safe_updates,
        "report": build_recipe_ai_quality_report(url),
        "recipe": updated,
    }
