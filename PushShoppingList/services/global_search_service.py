"""User-scoped global search for the shared application header.

Most AI Pantry workspace records are stored in account/guest-scoped JSON or
text files.  This module builds a small inverted prefix index for those files
and reuses it until one of the source file signatures changes. Ingredient and
equipment master data stays in its existing SQLite store and is always queried
with the active workspace's scoped user id.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import threading
import unicodedata
from urllib.parse import quote
from urllib.parse import urlencode

from PushShoppingList.services import cookbook_service
from PushShoppingList.services import home_store_location_service
from PushShoppingList.services import meal_plan_service
from PushShoppingList.services import menu_store_service
from PushShoppingList.services import pantry_service
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services import recipe_master_data_service
from PushShoppingList.services import recipe_url_service
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import store_settings_service


MIN_QUERY_LENGTH = 2
DEFAULT_RESULT_LIMIT = 10
MAX_RESULT_LIMIT = 12
FULL_RESULTS_PER_GROUP = 50

GROUPS = (
    ("recipes", "RECIPES"),
    ("ingredients", "INGREDIENTS"),
    ("menus", "MENUS"),
    ("cookbooks", "COOKBOOKS"),
    ("shopping-lists", "SHOPPING LISTS"),
    ("pantry", "PANTRY"),
    ("meal-planner", "MEAL PLANNER"),
    ("stores", "STORES"),
    ("restaurants", "RESTAURANTS"),
    ("equipment", "EQUIPMENT"),
    ("pages", "PAGES"),
)
GROUP_LABELS = dict(GROUPS)
GROUP_ORDER = {key: index for index, (key, _label) in enumerate(GROUPS)}

PAGE_SHORTCUTS = (
    ("Home", "Home page", "/#appPageHeader"),
    ("Recipes", "Browse and edit recipes", "/#recipesPage"),
    ("Menus", "Restaurant and cookbook menus", "/#menusPage"),
    ("Cookbooks", "Recipe collections", "/#cookbooksPage"),
    ("Shopping Lists", "Current shopping-list workspace", "/#shoppingListsPage"),
    ("Pantry", "Pantry inventory", "/#pantryPage"),
    ("Meal Planner", "Weekly meal plan", "/#mealPlannerPage"),
    ("Stores and Store Links", "Store settings and links", "/#storesPage"),
    ("Price Comparison", "Compare store prices", "/#priceComparisonPage"),
    ("Import Recipes", "Import a recipe", "/#importPage"),
    ("Import Menus", "Import a restaurant menu", "/#menuImportPage"),
)


def normalize_search_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def search_tokens(value):
    return [token for token in normalize_search_text(value).split() if len(token) >= 2]


def clean_text(value):
    return " ".join(str(value or "").strip().split())


def flatten_text(value):
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(flatten_text(item) for item in value)
    return clean_text(value)


def first_text(*values):
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def result_url(path, **query):
    cleaned = {key: value for key, value in query.items() if value not in (None, "")}
    return f"{path}?{urlencode(cleaned)}" if cleaned else path


def cover_image_url(recipe_url):
    return result_url("/recipe_cover_image", url=recipe_url) if recipe_url else ""


def candidate(
    group,
    stable_id,
    title,
    result_type,
    url,
    *,
    secondary="",
    thumbnail_url="",
    icon="",
    searchable=(),
):
    title = clean_text(title)
    if not title or group not in GROUP_LABELS:
        return None
    search_value = normalize_search_text(" ".join([
        title,
        secondary,
        *(flatten_text(value) for value in searchable),
    ]))
    return {
        "group": group,
        "id": clean_text(stable_id) or f"{group}:{normalize_search_text(title)}",
        "title": title,
        "type": clean_text(result_type) or GROUP_LABELS[group].title(),
        "secondary": clean_text(secondary),
        "url": clean_text(url),
        "thumbnail_url": clean_text(thumbnail_url),
        "icon": clean_text(icon) or group,
        "_search": search_value,
        "_title": normalize_search_text(title),
    }


def result_context(*parts):
    seen = set()
    values = []
    for part in parts:
        text = clean_text(part)
        key = text.lower()
        if text and key not in seen:
            values.append(text)
            seen.add(key)
    return " • ".join(values)


def image_value(value):
    if isinstance(value, str):
        return clean_text(value)
    if not isinstance(value, dict):
        return ""
    return first_text(
        value.get("display_url"),
        value.get("thumbnail_url"),
        value.get("url"),
        value.get("image_url"),
        value.get("src"),
    )


def workspace_source_paths():
    return (
        Path(str(recipe_url_service.URLS_FILE)),
        Path(str(recipe_ingredient_service.RECIPE_INGREDIENTS_FILE)),
        Path(str(cookbook_service.COOKBOOKS_FILE)),
        Path(str(menu_store_service.MENU_STORE_FILE)),
        pantry_service.pantry_inventory_path(),
        Path(str(meal_plan_service.MEAL_PLAN_FILE)),
        Path(str(shopping_list_service.SHOPPING_LIST_FILE)),
        Path(str(store_settings_service.STORE_SETTINGS_FILE)),
        Path(str(home_store_location_service.NEAREST_STORE_RESULTS_FILE)),
    )


def source_signature(path):
    try:
        stat = Path(path).stat()
        return str(Path(path).resolve()), stat.st_mtime_ns, stat.st_size
    except OSError:
        return str(Path(path).resolve()), 0, 0


def workspace_signature():
    return tuple(source_signature(path) for path in workspace_source_paths())


def workspace_cache_key():
    return str(storage_service.workspace_data_root().resolve())


@dataclass(frozen=True)
class SearchProjection:
    signature: tuple
    candidates: tuple
    prefix_index: dict
    gram_index: dict

    def matching_candidates(self, query):
        tokens = search_tokens(query)
        if not tokens:
            return []
        candidate_ids = None
        for token in tokens:
            matches = set(self.prefix_index.get(token, frozenset()))
            grams = {token[index:index + 2] for index in range(max(1, len(token) - 1))}
            gram_matches = None
            for gram in grams:
                gram_ids = self.gram_index.get(gram, frozenset())
                gram_matches = set(gram_ids) if gram_matches is None else gram_matches.intersection(gram_ids)
            if gram_matches:
                matches.update(gram_matches)
            candidate_ids = set(matches) if candidate_ids is None else candidate_ids.intersection(matches)
            if not candidate_ids:
                return []
        return [self.candidates[index] for index in sorted(candidate_ids)]


_PROJECTION_CACHE = {}
_PROJECTION_LOCK = threading.RLock()


def clear_global_search_cache():
    with _PROJECTION_LOCK:
        _PROJECTION_CACHE.clear()


def build_prefix_index(candidates):
    index = {}
    for candidate_index, item in enumerate(candidates):
        for token in set(search_tokens(item.get("_search"))):
            for length in range(MIN_QUERY_LENGTH, len(token) + 1):
                index.setdefault(token[:length], set()).add(candidate_index)
    return {prefix: frozenset(candidate_ids) for prefix, candidate_ids in index.items()}


def build_gram_index(candidates):
    index = {}
    for candidate_index, item in enumerate(candidates):
        for token in set(search_tokens(item.get("_search"))):
            for offset in range(len(token) - 1):
                index.setdefault(token[offset:offset + 2], set()).add(candidate_index)
    return {gram: frozenset(candidate_ids) for gram, candidate_ids in index.items()}


def cached_projection():
    key = workspace_cache_key()
    signature = workspace_signature()
    with _PROJECTION_LOCK:
        existing = _PROJECTION_CACHE.get(key)
        if existing and existing.signature == signature:
            return existing

    candidates = tuple(build_workspace_candidates())
    projection = SearchProjection(
        signature=signature,
        candidates=candidates,
        prefix_index=build_prefix_index(candidates),
        gram_index=build_gram_index(candidates),
    )
    with _PROJECTION_LOCK:
        _PROJECTION_CACHE[key] = projection
        if len(_PROJECTION_CACHE) > 32:
            oldest_key = next(iter(_PROJECTION_CACHE))
            if oldest_key != key:
                _PROJECTION_CACHE.pop(oldest_key, None)
    return projection


def build_workspace_candidates():
    candidates = []
    recipe_candidates, recipe_lookup = build_recipe_candidates()
    candidates.extend(recipe_candidates)
    candidates.extend(build_menu_candidates())
    candidates.extend(build_cookbook_candidates())
    candidates.extend(build_shopping_candidates())
    candidates.extend(build_pantry_candidates())
    candidates.extend(build_meal_plan_candidates(recipe_lookup))
    candidates.extend(build_store_candidates())
    return [item for item in candidates if item]


def build_recipe_candidates():
    recipes = {}
    cookbook_names = {}

    for row in recipe_url_service.recipe_url_rows():
        recipe_url = clean_text(row.get("url"))
        key = recipe_url_service.normalize_recipe_url_key(recipe_url)
        if key:
            recipes[key] = {**row, "url": recipe_url}

    cookbook_payload = cookbook_service.load_cookbooks()
    for cookbook in cookbook_payload.get("cookbooks", []):
        cookbook_id = clean_text(cookbook.get("id"))
        cookbook_name = clean_text(cookbook.get("name"))
        for record in cookbook.get("recipes", []):
            if not isinstance(record, dict):
                continue
            recipe_url = clean_text(record.get("url") or record.get("recipe_url"))
            key = recipe_url_service.normalize_recipe_url_key(recipe_url)
            if not key:
                continue
            recipes[key] = {**recipes.get(key, {}), **record, "url": recipe_url}
            cookbook_names.setdefault(key, []).append(cookbook_name or cookbook_id)

    ingredients_by_recipe = recipe_ingredient_service.load_recipe_ingredients()
    for stored_key, record in ingredients_by_recipe.items():
        if not isinstance(record, dict):
            continue
        recipe_url = clean_text(record.get("url") or stored_key)
        key = recipe_url_service.normalize_recipe_url_key(recipe_url)
        if key:
            recipes[key] = {**recipes.get(key, {}), **record, "url": recipe_url}

    menu_store = menu_store_service.load_menu_store()
    restaurant_by_id = {
        clean_text(restaurant.get("id") or restaurant.get("restaurant_id")): restaurant
        for restaurant in menu_store.get("restaurants", [])
        if isinstance(restaurant, dict)
    }
    restaurant_by_source = {
        menu_store_service.menu_source_identity_key(restaurant.get("source_menu_url")): restaurant
        for restaurant in restaurant_by_id.values()
        if menu_store_service.menu_source_identity_key(restaurant.get("source_menu_url"))
    }

    output = []
    lookup = {}
    for key, recipe in recipes.items():
        recipe_url = clean_text(recipe.get("url"))
        title = first_text(recipe.get("name"), recipe.get("display_name"), recipe.get("recipe_title"))
        if not title:
            title = recipe_url_service.recipe_url_name(recipe_url)
        restaurant = restaurant_by_id.get(clean_text(recipe.get("restaurant_id")))
        if not restaurant:
            source_key = menu_store_service.menu_source_identity_key(
                recipe.get("source_menu_url") or recipe.get("menu_url") or recipe_url
            )
            restaurant = restaurant_by_source.get(source_key, {})
        restaurant_name = first_text(
            recipe.get("restaurant_name"),
            recipe.get("source_restaurant_name"),
            restaurant.get("restaurant_name") if isinstance(restaurant, dict) else "",
        )
        cookbook_context = result_context(*cookbook_names.get(key, []))
        secondary = result_context(restaurant_name, cookbook_context)
        ingredients = recipe.get("ingredients") or recipe.get("ingredient_items")
        equipment = recipe.get("equipment_items") or recipe.get("equipment")
        item = candidate(
            "recipes",
            key,
            title,
            "Recipe",
            result_url("/recipe/edit", url=recipe_url),
            secondary=secondary,
            thumbnail_url=image_value(recipe.get("cover_image")) or cover_image_url(recipe_url),
            icon="recipes",
            searchable=(ingredients, equipment, recipe.get("description"), recipe_url),
        )
        if item:
            output.append(item)
            lookup[key] = item
    return output, lookup


def build_menu_candidates():
    store = menu_store_service.load_menu_store()
    restaurants = {
        clean_text(restaurant.get("id") or restaurant.get("restaurant_id")): restaurant
        for restaurant in store.get("restaurants", [])
        if isinstance(restaurant, dict)
    }
    menus = {
        clean_text(menu.get("id")): menu
        for menu in store.get("menus", [])
        if isinstance(menu, dict)
    }
    sections = {
        clean_text(section.get("id")): section
        for section in store.get("sections", [])
        if isinstance(section, dict)
    }
    output = []

    for menu_id, menu in menus.items():
        restaurant = restaurants.get(clean_text(menu.get("restaurant_id")), {})
        title = first_text(menu.get("menu_title"), menu.get("source_name"), "Menu")
        output.append(candidate(
            "menus",
            menu_id,
            title,
            "Menu",
            f"/menus/{quote(menu_id, safe='')}",
            secondary=result_context(
                restaurant.get("restaurant_name"),
                menu.get("cookbook_name"),
            ),
            thumbnail_url=image_value(restaurant.get("logo_url")),
            icon="menus",
            searchable=(menu.get("menu_subtitle"), menu.get("menu_description"), menu.get("source_url")),
        ))

    for item in store.get("items", []):
        if not isinstance(item, dict):
            continue
        item_id = clean_text(item.get("id"))
        menu_id = clean_text(item.get("menu_id"))
        menu = menus.get(menu_id, {})
        restaurant = restaurants.get(clean_text(item.get("restaurant_id") or menu.get("restaurant_id")), {})
        section = sections.get(clean_text(item.get("menu_section_id")), {})
        recipe_url = clean_text(item.get("recipe_url"))
        url = result_url("/recipe/edit", url=recipe_url) if recipe_url else f"/menus/{quote(menu_id, safe='')}"
        output.append(candidate(
            "menus",
            item_id,
            item.get("item_name"),
            "Menu item",
            url,
            secondary=result_context(
                restaurant.get("restaurant_name"),
                section.get("section_name") or item.get("menu_section"),
                item.get("menu_price"),
            ),
            thumbnail_url=image_value(item.get("image_url")),
            icon="menu-items",
            searchable=(item.get("menu_description"), item.get("dietary_tags"), menu.get("menu_title")),
        ))

    for restaurant_id, restaurant in restaurants.items():
        related_menu = next(
            (menu for menu in menus.values() if clean_text(menu.get("restaurant_id")) == restaurant_id),
            None,
        )
        url = f"/menus/{quote(clean_text(related_menu.get('id')), safe='')}" if related_menu else "/#menusPage"
        output.append(candidate(
            "restaurants",
            restaurant_id,
            restaurant.get("restaurant_name"),
            "Restaurant source",
            url,
            secondary=result_context(
                restaurant.get("city"),
                restaurant.get("state") or restaurant.get("state_or_region"),
                restaurant.get("phone"),
            ),
            thumbnail_url=image_value(restaurant.get("logo_url") or restaurant.get("logo")),
            icon="restaurants",
            searchable=(
                restaurant.get("restaurant_website_url") or restaurant.get("website_url"),
                restaurant.get("source_menu_url"),
                restaurant.get("full_address"),
                restaurant.get("address_line"),
                restaurant.get("country"),
            ),
        ))
    return output


def build_cookbook_candidates():
    output = []
    for cookbook in cookbook_service.load_cookbooks().get("cookbooks", []):
        if not isinstance(cookbook, dict):
            continue
        recipes = cookbook.get("recipes", []) if isinstance(cookbook.get("recipes"), list) else []
        output.append(candidate(
            "cookbooks",
            cookbook.get("id"),
            cookbook.get("name"),
            "Cookbook",
            "/#cookbooksPage",
            secondary=f"{len(recipes)} recipe{'s' if len(recipes) != 1 else ''}",
            icon="cookbooks",
            searchable=([
                recipe.get("name")
                for recipe in recipes
                if isinstance(recipe, dict)
            ],),
        ))
    return output


def shopping_item_label(value):
    value = clean_text(value)
    if recipe_ingredient_service.is_section_header(value):
        return ""
    return value


def build_shopping_candidates():
    items = [shopping_item_label(item) for item in shopping_list_service.load_items()]
    items = [item for item in items if item]
    output = [candidate(
        "shopping-lists",
        "current",
        "My Shopping List",
        "Shopping list",
        "/#shoppingListsPage",
        secondary=f"{len(items)} item{'s' if len(items) != 1 else ''}",
        icon="shopping-lists",
        searchable=items,
    )]
    for index, item in enumerate(items):
        output.append(candidate(
            "shopping-lists",
            f"item:{index}:{normalize_search_text(item)}",
            item,
            "Shopping-list item",
            "/#shoppingListsPage",
            secondary="My Shopping List",
            icon="shopping-items",
        ))
    return output


def build_pantry_candidates():
    output = []
    for item in pantry_service.load_pantry_inventory().get("items", []):
        if not isinstance(item, dict):
            continue
        title = first_text(item.get("product_name"), item.get("ingredient_name"))
        output.append(candidate(
            "pantry",
            item.get("id"),
            title,
            "Pantry item",
            "/#pantryPage",
            secondary=result_context(
                item.get("storage_location"),
                item.get("store_section") or item.get("category"),
                item.get("status"),
            ),
            thumbnail_url=image_value(item.get("image_url")),
            icon="pantry",
            searchable=(item.get("ingredient_name"), item.get("normalized_name"), item.get("notes")),
        ))
    return output


def build_meal_plan_candidates(recipe_lookup):
    output = []
    for meal in meal_plan_service.load_meal_plan().get("meals", []):
        if not isinstance(meal, dict):
            continue
        recipe_url = clean_text(meal.get("recipe_url"))
        recipe_key = recipe_url_service.normalize_recipe_url_key(recipe_url)
        recipe_result = recipe_lookup.get(recipe_key, {})
        date_value = clean_text(meal.get("date"))
        output.append(candidate(
            "meal-planner",
            meal.get("id"),
            meal.get("recipe_name"),
            "Meal-plan entry",
            f"/?meal_week={quote(date_value, safe='')}#mealPlannerPage" if date_value else "/#mealPlannerPage",
            secondary=result_context(meal.get("meal_type"), date_value),
            thumbnail_url=recipe_result.get("thumbnail_url", ""),
            icon="meal-planner",
            searchable=(recipe_url,),
        ))
    return output


def build_store_candidates():
    settings = store_settings_service.load_store_settings()
    locations = home_store_location_service.load_nearest_store_results().get("store_locations", {})
    output = []
    for store_key, store in settings.get("stores", {}).items():
        if not isinstance(store, dict):
            continue
        location = locations.get(store_key, {}) if isinstance(locations, dict) else {}
        if isinstance(location, list):
            location = location[0] if location and isinstance(location[0], dict) else {}
        output.append(candidate(
            "stores",
            store_key,
            first_text(store.get("label"), store_key.replace("_", " ").title()),
            "Store / store link",
            "/#storesPage",
            secondary=result_context(
                location.get("address") if isinstance(location, dict) else "",
                location.get("city") if isinstance(location, dict) else "",
            ),
            icon="stores",
            searchable=(store.get("url"), store.get("urlStoreSelector")),
        ))
    return output


def master_data_candidates(query):
    scoped_user_id = recipe_master_data_service.scoped_recipe_user_id()
    rows_by_group = (
        (
            "ingredients",
            "Ingredient",
            "ingredients",
            recipe_master_data_service.list_ingredients(
                user_id=scoped_user_id,
                search=query,
                limit=24,
                sort="name_asc",
                include_all_users=False,
            ),
        ),
        (
            "equipment",
            "Equipment",
            "equipment",
            recipe_master_data_service.list_equipment(
                user_id=scoped_user_id,
                search=query,
                limit=24,
                sort="name_asc",
                include_all_users=False,
            ),
        ),
    )
    output = []
    for group, result_type, route_kind, rows in rows_by_group:
        for row in rows:
            usage_count = int(row.get("usage_count") or 0)
            section = row.get("store_section") if group == "ingredients" else row.get("equipment_section")
            output.append(candidate(
                group,
                row.get("id"),
                row.get("name"),
                result_type,
                result_url(f"/admin/master-data/{route_kind}", search=row.get("name")),
                secondary=result_context(
                    section,
                    f"Used by {usage_count} recipe{'s' if usage_count != 1 else ''}",
                ),
                thumbnail_url=image_value(row.get("image_url")),
                icon=group,
                searchable=(row.get("normalized_name"),),
            ))
    return [item for item in output if item]


def page_candidates(query):
    normalized_query = normalize_search_text(query)
    output = []
    for index, (title, secondary, url) in enumerate(PAGE_SHORTCUTS):
        item = candidate(
            "pages",
            f"page:{index}",
            title,
            "Page",
            url,
            secondary=secondary,
            icon="pages",
        )
        if not normalized_query or normalized_query in item["_search"]:
            output.append(item)
    return output


def match_score(item, query):
    query = normalize_search_text(query)
    title = item.get("_title", "")
    searchable = item.get("_search", "")
    if not query:
        return 0
    if title == query:
        return 1000
    if title.startswith(query):
        return 900
    if f" {query}" in title:
        return 825
    if query in title:
        return 775
    if query in searchable:
        return 600
    tokens = search_tokens(query)
    if tokens and all(any(word.startswith(token) for word in searchable.split()) for token in tokens):
        return 500
    return 0


def public_result(item):
    return {
        key: item.get(key, "")
        for key in ("id", "title", "type", "secondary", "url", "thumbnail_url", "icon")
    }


def normalize_group_filter(group_filter):
    if not group_filter:
        return set()
    if isinstance(group_filter, str):
        group_filter = group_filter.split(",")
    return {
        clean_text(group).lower()
        for group in group_filter
        if clean_text(group).lower() in GROUP_LABELS
    }


def global_search(query, limit=DEFAULT_RESULT_LIMIT, group_filter=None, full=False, include_pages=True):
    """Search only the active session's workspace and return grouped results."""
    query = clean_text(query)[:160]
    normalized_query = normalize_search_text(query)
    selected_groups = normalize_group_filter(group_filter)
    too_short = bool(normalized_query) and len(normalized_query) < MIN_QUERY_LENGTH

    matches = page_candidates(query) if include_pages else []
    if normalized_query and not too_short:
        matches.extend(cached_projection().matching_candidates(query))
        matches.extend(master_data_candidates(query))

    deduplicated = {}
    for item in matches:
        if not item:
            continue
        group = item["group"]
        score = match_score(item, query) if normalized_query else (100 if group == "pages" else 0)
        if normalized_query and score <= 0:
            continue
        dedupe_key = (group, clean_text(item.get("id")) or normalize_search_text(item.get("title")))
        previous = deduplicated.get(dedupe_key)
        if not previous or score > previous[0]:
            deduplicated[dedupe_key] = (score, item)

    all_ranked = sorted(
        deduplicated.values(),
        key=lambda value: (
            -value[0],
            GROUP_ORDER.get(value[1]["group"], 999),
            value[1]["title"].lower(),
        ),
    )
    counts = {}
    for _score, item in all_ranked:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    ranked = [
        entry
        for entry in all_ranked
        if not selected_groups or entry[1]["group"] in selected_groups
    ]

    if full:
        grouped_ranked = {}
        for score, item in ranked:
            grouped_ranked.setdefault(item["group"], []).append((score, item))
        visible = [
            entry
            for group, _label in GROUPS
            for entry in grouped_ranked.get(group, [])[:FULL_RESULTS_PER_GROUP]
        ]
    else:
        try:
            limit = max(1, min(MAX_RESULT_LIMIT, int(limit)))
        except (TypeError, ValueError):
            limit = DEFAULT_RESULT_LIMIT
        visible = ranked[:limit]

    grouped_results = []
    for group, label in GROUPS:
        results = [public_result(item) for _score, item in visible if item["group"] == group]
        if results:
            grouped_results.append({
                "key": group,
                "label": label,
                "count": counts.get(group, len(results)),
                "results": results,
            })

    all_total_count = sum(counts.values())
    total_count = sum(
        count
        for group, count in counts.items()
        if not selected_groups or group in selected_groups
    )
    return {
        "ok": True,
        "query": query,
        "normalized_query": normalized_query,
        "min_query_length": MIN_QUERY_LENGTH,
        "query_too_short": too_short,
        "total_count": total_count,
        "all_total_count": all_total_count,
        "groups": grouped_results,
        "available_groups": [
            {"key": group, "label": label, "count": counts.get(group, 0)}
            for group, label in GROUPS
            if counts.get(group, 0)
        ],
        "view_all_url": result_url("/search", q=query),
    }
