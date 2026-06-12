import copy
import json

from PushShoppingList.services.cookbook_service import COOKBOOK_MENU_MODES
from PushShoppingList.services.cookbook_service import apply_recipe_menu_metadata
from PushShoppingList.services.cookbook_service import cookbook_menu_sections
from PushShoppingList.services.cookbook_service import prepare_cookbook_menu_view
from PushShoppingList.services.cookbook_service import recipe_key
from PushShoppingList.services.menu_store_service import upsert_menu_from_facts
from PushShoppingList.services.recipe_extract_service import build_openai_chat_payload
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import resolve_menu_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_model_source
from PushShoppingList.services.openai_usage_service import record_openai_usage


PRICE_LEVEL_GUIDANCE = {
    "budget": "Most items should feel affordable, with simple pricing.",
    "casual": "Use approachable neighborhood restaurant prices.",
    "upscale": "Use elevated restaurant pricing and polished dish names.",
    "premium": "Use premium pricing, refined ingredients, and restrained luxury.",
}

COOKBOOK_GENERATED_SOURCE_TYPE = "cookbook_generated_menu"
DEFAULT_COOKBOOK_MENU_MODE = "restaurant_menu"
PRICE_STYLE_BASES = {
    "budget": 8,
    "casual": 12,
    "upscale": 18,
    "premium": 26,
}


def clean_text(value):
    return " ".join(str(value or "").strip().split())


def clean_bool(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def prepared_cookbook_for_menu_builder(cookbook):
    cookbook = copy.deepcopy(cookbook if isinstance(cookbook, dict) else {})
    cookbook.setdefault("recipes", [])
    view = prepare_cookbook_menu_view({
        "cookbooks": [cookbook],
        "recipes": [],
        "menu_sort_options": [],
        "menu_views": {},
    })
    return (view.get("cookbooks") or [{}])[0]


def valid_cookbook_menu_mode(value):
    value = clean_text(value) or DEFAULT_COOKBOOK_MENU_MODE
    valid_modes = {mode.get("key") for mode in COOKBOOK_MENU_MODES}
    return value if value in valid_modes else DEFAULT_COOKBOOK_MENU_MODE


def cookbook_builder_form_defaults(cookbook):
    cookbook = cookbook if isinstance(cookbook, dict) else {}
    cookbook_name = clean_text(cookbook.get("name")) or "Cookbook"
    return {
        "menu_title": f"{cookbook_name} Menu",
        "menu_subtitle": f"Created from cookbook: {cookbook_name}",
        "restaurant_name": cookbook_name,
        "cuisine_type": "",
        "theme": "restaurant-style cookbook menu",
        "price_style": "casual",
        "category_mode": DEFAULT_COOKBOOK_MENU_MODE,
        "source_content": "all",
        "include_descriptions": True,
        "include_prices": True,
        "include_dietary_tags": True,
        "include_images": True,
        "include_ai_generated_descriptions": True,
        "include_ai_generated_prices": True,
        "exclude_sparse_recipe_info": False,
        "is_public": False,
    }


def cookbook_builder_stats(cookbook, existing_menus=None, menu_pdf_logs=None, category_mode=DEFAULT_COOKBOOK_MENU_MODE):
    cookbook = cookbook if isinstance(cookbook, dict) else {}
    category_mode = valid_cookbook_menu_mode(category_mode)
    sections = cookbook.get("menu_sections", {}).get(category_mode, [])
    categories_with_recipes = [
        section for section in sections if section.get("recipes")
    ]
    return {
        "recipe_count": len(cookbook.get("recipes", [])),
        "category_count": len(categories_with_recipes),
        "menu_count": len(existing_menus or []),
        "menu_pdf_count": len(menu_pdf_logs or []),
    }


def recipe_has_menu_information(recipe):
    if not isinstance(recipe, dict):
        return False
    return bool(
        clean_text(recipe.get("description"))
        or clean_text(recipe.get("short_description"))
        or recipe.get("sections")
        or recipe.get("instruction_items")
        or recipe.get("menu_tags")
    )


def cover_image_url(recipe):
    cover = recipe.get("cover_image") if isinstance(recipe.get("cover_image"), dict) else {}
    return clean_text(
        cover.get("thumb_url")
        or cover.get("card_url")
        or cover.get("src")
        or cover.get("url")
        or cover.get("path")
    )


def generated_price_for_recipe(index, price_style):
    price_style = clean_text(price_style).lower() or "casual"
    base = PRICE_STYLE_BASES.get(price_style, PRICE_STYLE_BASES["casual"])
    dollars = base + ((index % 5) * 2)
    cents = 49 if index % 2 else 95
    return f"${dollars}.{cents:02d}"


def cookbook_recipe_description(recipe, include_generated):
    description = (
        clean_text(recipe.get("menu_description"))
        or clean_text(recipe.get("description"))
        or clean_text(recipe.get("short_description"))
    )
    if description:
        return description
    if not include_generated:
        return None
    ingredients = []
    for section_items in (recipe.get("sections") or {}).values():
        for item in section_items or []:
            name = clean_text((item or {}).get("display_name") or (item or {}).get("name"))
            if name:
                ingredients.append(name)
            if len(ingredients) >= 3:
                break
        if len(ingredients) >= 3:
            break
    if ingredients:
        return f"Featuring {', '.join(ingredients)}."
    return f"A polished restaurant-style take on {clean_text(recipe.get('name')) or 'this recipe'}."


def cookbook_recipe_menu_item(recipe, item_index, options):
    include_descriptions = clean_bool(options.get("include_descriptions"), True)
    include_prices = clean_bool(options.get("include_prices"), True)
    include_dietary_tags = clean_bool(options.get("include_dietary_tags"), True)
    include_images = clean_bool(options.get("include_images"), True)
    include_generated_descriptions = clean_bool(options.get("include_ai_generated_descriptions"), True)
    include_generated_prices = clean_bool(options.get("include_ai_generated_prices"), True)
    price_style = clean_text(options.get("price_style") or options.get("price_level") or "casual")
    existing_price = clean_text(recipe.get("menu_price") or recipe.get("price"))
    menu_price = None
    if include_prices:
        menu_price = existing_price or (generated_price_for_recipe(item_index, price_style) if include_generated_prices else None)

    return {
        "item_name": clean_text(recipe.get("name")) or clean_text(recipe.get("url")) or "Cookbook Recipe",
        "menu_price": menu_price,
        "menu_description": cookbook_recipe_description(recipe, include_generated_descriptions) if include_descriptions else None,
        "dietary_tags": recipe.get("menu_tags", []) if include_dietary_tags else [],
        "spice_level": "medium" if any("spicy" in clean_text(tag).lower() for tag in recipe.get("menu_tags", [])) else "none",
        "chef_recommended": False,
        "image_url": cover_image_url(recipe) if include_images else None,
        "display_order": item_index + 1,
        "source_type": "cookbook_recipe",
        "recipe_id": recipe_key(recipe.get("url")),
        "recipe_url": clean_text(recipe.get("url")),
    }


def selected_cookbook_menu_sections(cookbook, options=None, selected_recipe_urls=None, selected_category_names=None):
    cookbook = prepared_cookbook_for_menu_builder(cookbook)
    options = {**cookbook_builder_form_defaults(cookbook), **(options if isinstance(options, dict) else {})}
    category_mode = valid_cookbook_menu_mode(options.get("category_mode"))
    source_content = clean_text(options.get("source_content")) or "all"
    selected_recipe_keys = {
        recipe_key(url)
        for url in selected_recipe_urls or []
        if recipe_key(url)
    }
    selected_categories = {
        clean_text(name)
        for name in selected_category_names or []
        if clean_text(name)
    }
    exclude_sparse = clean_bool(options.get("exclude_sparse_recipe_info"), False)
    sections = cookbook.get("menu_sections", {}).get(category_mode)
    if sections is None:
        sections = cookbook_menu_sections(cookbook.get("recipes", [])).get(category_mode, [])

    built_sections = []
    seen_recipe_keys = set()
    item_index = 0
    for section in sections or []:
        section_name = clean_text(section.get("label"))
        if source_content == "categories" and section_name not in selected_categories:
            continue

        items = []
        for recipe in section.get("recipes", []):
            apply_recipe_menu_metadata(recipe)
            key = recipe_key(recipe.get("url"))
            if not key or key in seen_recipe_keys:
                continue
            if source_content == "selected" and key not in selected_recipe_keys:
                continue
            if exclude_sparse and not recipe_has_menu_information(recipe):
                continue

            items.append(cookbook_recipe_menu_item(recipe, item_index, options))
            seen_recipe_keys.add(key)
            item_index += 1

        if items:
            built_sections.append({
                "section_name": section_name or "Cookbook Recipes",
                "section_description": f"{section_name} from {clean_text(cookbook.get('name'))}" if section_name else "",
                "display_order": len(built_sections) + 1,
                "items": items,
            })

    return built_sections


def create_menu_from_cookbook(cookbook, options=None, selected_recipe_urls=None, selected_category_names=None):
    cookbook = prepared_cookbook_for_menu_builder(cookbook)
    cookbook_id = clean_text(cookbook.get("id"))
    cookbook_name = clean_text(cookbook.get("name")) or "Cookbook"
    options = {**cookbook_builder_form_defaults(cookbook), **(options if isinstance(options, dict) else {})}
    sections = selected_cookbook_menu_sections(
        cookbook,
        options=options,
        selected_recipe_urls=selected_recipe_urls,
        selected_category_names=selected_category_names,
    )
    if not sections:
        raise ValueError("Select at least one cookbook recipe with enough menu information.")

    menu_title = clean_text(options.get("menu_title")) or f"{cookbook_name} Menu"
    restaurant_name = clean_text(options.get("restaurant_name")) or cookbook_name
    cuisine_type = clean_text(options.get("cuisine_type"))
    theme = clean_text(options.get("theme"))
    detail = upsert_menu_from_facts(
        {
            "source_type": COOKBOOK_GENERATED_SOURCE_TYPE,
            "source_input_type": COOKBOOK_GENERATED_SOURCE_TYPE,
            "source_name": cookbook_name,
            "created_from_cookbook_id": cookbook_id,
            "restaurant": {
                "restaurant_name": restaurant_name,
                "cuisine_tags": [cuisine_type] if cuisine_type else [],
            },
            "menu": {
                "menu_title": menu_title,
                "menu_subtitle": clean_text(options.get("menu_subtitle")) or f"Created from cookbook: {cookbook_name}",
                "menu_description": clean_text(options.get("menu_description")) or f"Restaurant-style menu generated from {cookbook_name}.",
                "menu_theme": theme,
                "menu_style": clean_text(options.get("menu_style")) or clean_text(options.get("price_style")),
                "is_public": clean_bool(options.get("is_public"), False),
            },
            "sections": sections,
        },
        cookbook_id=cookbook_id,
        cookbook_name=cookbook_name,
    )
    return {
        "ok": True,
        "success": True,
        "menu_id": detail.get("menu", {}).get("id", ""),
        "menu": detail,
        "source_type": COOKBOOK_GENERATED_SOURCE_TYPE,
        "created_from_cookbook_id": cookbook_id,
    }


def build_custom_menu_prompt(options):
    options = options if isinstance(options, dict) else {}
    restaurant_name = str(options.get("restaurant_name") or "Custom Restaurant").strip()
    cuisine_type = str(options.get("cuisine_type") or "seasonal").strip()
    theme = str(options.get("theme") or options.get("menu_theme") or "chef-driven").strip()
    price_level = str(options.get("price_level") or "casual").strip().lower()
    section_count = int(options.get("section_count") or options.get("number_of_sections") or 4)
    items_per_section = int(options.get("items_per_section") or 6)
    include_descriptions = bool(options.get("include_descriptions", True))
    include_prices = bool(options.get("include_prices", True))
    include_dietary_tags = bool(options.get("include_dietary_tags", True))
    include_spicy = bool(options.get("include_spicy_indicators", True))
    notes = str(options.get("notes") or "").strip()

    return f"""
Generate a fictional restaurant menu as structured JSON only.

Restaurant name: {restaurant_name}
Cuisine type: {cuisine_type}
Theme / vibe: {theme}
Price level: {price_level}
Price guidance: {PRICE_LEVEL_GUIDANCE.get(price_level, PRICE_LEVEL_GUIDANCE["casual"])}
Number of menu sections: {section_count}
Items per section: {items_per_section}
Include descriptions: {include_descriptions}
Include prices: {include_prices}
Include dietary tags: {include_dietary_tags}
Include spicy indicators: {include_spicy}
Optional notes: {notes}

Rules:
- Return only valid JSON.
- This is AI-generated; do not claim real awards, certifications, locations, or press.
- Prices must match the selected price level when prices are included.
- Items must match the cuisine and theme.
- If descriptions are not included, use null for menu_description.
- If prices are not included, use null for menu_price.

Return exactly this shape:
{{
  "restaurant": {{
    "restaurant_name": "string",
    "cuisine_tags": ["string"],
    "phone": null,
    "full_address": null,
    "hours_text": null,
    "promotions": []
  }},
  "menu": {{
    "menu_title": "string",
    "menu_subtitle": "string",
    "menu_description": "string",
    "menu_theme": "string",
    "menu_style": "string"
  }},
  "sections": [
    {{
      "section_name": "string",
      "section_description": "string",
      "display_order": 1,
      "items": [
        {{
          "item_name": "string",
          "menu_price": "$9.99",
          "menu_description": "string",
          "dietary_tags": ["string"],
          "spice_level": "none | mild | medium | hot",
          "chef_recommended": false,
          "display_order": 1
        }}
      ]
    }}
  ]
}}
"""


def validate_generated_menu_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    restaurant = payload.get("restaurant") if isinstance(payload.get("restaurant"), dict) else {}
    menu = payload.get("menu") if isinstance(payload.get("menu"), dict) else {}
    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []

    if not sections:
        raise ValueError("Generated menu JSON did not include sections.")

    item_count = 0
    for section in sections:
        if not isinstance(section, dict) or not str(section.get("section_name") or "").strip():
            raise ValueError("Every generated menu section needs a section_name.")
        items = section.get("items") if isinstance(section.get("items"), list) else []
        if not items:
            raise ValueError("Every generated menu section needs at least one item.")
        for item in items:
            if not isinstance(item, dict) or not str(item.get("item_name") or "").strip():
                raise ValueError("Every generated menu item needs an item_name.")
            item_count += 1

    if item_count <= 0:
        raise ValueError("Generated menu JSON did not include items.")

    return {
        "restaurant": restaurant,
        "menu": menu,
        "sections": sections,
    }


def generate_custom_menu(options, cookbook_id="", cookbook_name=""):
    model = resolve_menu_model()
    model_source = resolve_menu_model_source()
    action_name = "custom-menu-generation"
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        model,
        action_name,
        [
            {
                "role": "system",
                "content": (
                    "You generate fictional restaurant menus as valid JSON. "
                    "Do not claim real awards or certifications."
                ),
            },
            {
                "role": "user",
                "content": build_custom_menu_prompt(options),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action={action_name} model={resolved_model} "
        f"model_source={model_source} temperature_included={temperature_included}"
    )
    response = get_openai_client().chat.completions.create(**payload)
    record_openai_usage(response, action_name, model=resolved_model)
    generated = json.loads(clean_json_response(response.choices[0].message.content))
    validated = validate_generated_menu_payload(generated)
    detail = upsert_menu_from_facts(
        {
            **validated,
            "source_type": "ai_generated_menu",
            "source_input_type": "ai_generated_menu",
            "generated_by_model": resolved_model,
            "model_used": resolved_model,
            "model_source": model_source,
        },
        cookbook_id=cookbook_id,
        cookbook_name=cookbook_name,
    )
    return {
        "ok": True,
        "success": True,
        "menu_id": detail.get("menu", {}).get("id", ""),
        "menu": detail,
        "model_used": resolved_model,
        "model_source": model_source,
        "ai_generated": True,
    }
