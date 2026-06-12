import json

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
