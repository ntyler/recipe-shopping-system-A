from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from PIL import ImageChops

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service
from PushShoppingList.services.recipe_extract_service import safe_filename


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_recipe_favorite_route_updates_saved_recipe_state(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    recipe_url = "https://example.com/beans"

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        output_dir = temp_path / "output"
        output_dir.mkdir()
        with patch.object(recipe_edit_service, "OUTPUT_FOLDER", output_dir):
            recipe_edit_service.save_recipe_output(
                recipe_url,
                {
                    "source_url": recipe_url,
                    "recipe_title": "Beans",
                    "favorite": False,
                },
            )

            with app.test_client() as client:
                monkeypatch.setattr(storage_service, "USER_DATA_DIR", temp_path / "users")
                monkeypatch.setattr(user_account_service, "USERS_FILE", temp_path / "users.json")
                user_account_service.save_users({
                    "users": [{
                        "user_id": "favorite-user",
                        "email": "favorite@example.com",
                        "username": "favorite",
                        "account_status": "active",
                    }],
                })
                with client.session_transaction() as session:
                    session["user_id"] = "favorite-user"

                response = client.post(
                    "/api/recipe_favorite",
                    json={"url": recipe_url, "favorite": True},
                )

            saved = json.loads(
                (output_dir / f"{safe_filename(recipe_url)}.json").read_text(encoding="utf-8")
            )

    assert response.status_code == 200
    assert response.get_json()["favorite"] is True
    assert saved["favorite"] is True


def test_home_recipe_badge_uses_real_metadata_priority():
    assert main_routes.recipe_home_badge_label(
        {"meal_type": "Dinner", "menu_section": "Entrees"},
        {"custom_categories": ["Weeknight"]},
    ) == "Dinner"
    assert main_routes.recipe_home_badge_label(
        {"recipe_category": "Breakfast", "menu_section": "Brunch"},
        {"meal_type": ""},
    ) == "Breakfast"
    assert main_routes.recipe_home_badge_label(
        {"menu_section": "Appetizers"},
        {"custom_categories": ["Party"]},
    ) == "Appetizers"
    assert main_routes.recipe_home_badge_label(
        {"recipe_tags": ["Vegetarian"]},
        {},
    ) == "Vegetarian"
    assert main_routes.recipe_home_badge_label({}, {}) == ""


def test_home_recipe_time_uses_requested_priority_without_placeholder():
    assert main_routes.recipe_home_preview_time_label({
        "total_time": "1 hr 5 min",
        "prep_time": "10 min",
        "cook_time": "20 min",
    }) == "1 hr 5 min"
    assert main_routes.recipe_home_preview_time_label({
        "prep_time": "15 min",
        "cook_time": "35 min",
    }) == "50 min"
    assert main_routes.recipe_home_preview_time_label({"cook_time": "90"}) == "1 hr 30 min"
    assert main_routes.recipe_home_preview_time_label({"prep_time": "10 min"}) == ""
    assert main_routes.recipe_home_preview_time_label({}) == ""


def test_recipe_card_metadata_labels_use_existing_recipe_fields():
    assert main_routes.recipe_card_cook_time_label({"cook_time": "55"}) == "55 min"
    assert main_routes.recipe_card_cook_time_label({"cook_time": "1 hr 20 min"}) == "1 hr 20 min"
    assert main_routes.recipe_card_cook_time_label({"total_time": "55", "prep_time": "10"}) == ""

    assert main_routes.recipe_card_calories_label("420") == "420 cal"
    assert main_routes.recipe_card_calories_label("420.0") == "420 cal"
    assert main_routes.recipe_card_calories_label("420 kcal") == "420 kcal"
    assert main_routes.recipe_card_calories_label("") == ""


def test_recipe_rating_stars_treat_empty_or_zero_values_as_unrated():
    for value in (None, "", " ", "not-a-number", float("nan"), 0, "0"):
        assert main_routes.recipe_rating_for_view({"rating": value}) == 0
        assert main_routes.recipe_rating_stars_for_view({"rating": value}) == "☆☆☆☆☆"

    assert main_routes.recipe_rating_stars_for_view({"rating": 1}) == "★☆☆☆☆"
    assert main_routes.recipe_rating_stars_for_view({"rating": 3}) == "★★★☆☆"
    assert main_routes.recipe_rating_stars_for_view({"rating": 5}) == "★★★★★"


def test_relative_time_formatter_is_compact_and_shared_by_import_rows():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    assert main_routes.relative_time_label("2026-07-10T11:59:45Z", now) == "just now"
    assert main_routes.relative_time_label("2026-07-10T11:48:00Z", now) == "12m ago"
    assert main_routes.relative_time_label("2026-07-10T10:00:00Z", now) == "2h ago"
    assert main_routes.relative_time_label("2026-07-09T12:00:00Z", now) == "yesterday"
    assert main_routes.relative_time_label("2026-07-07T12:00:00Z", now) == "3d ago"


def test_home_recent_import_rows_use_real_counts_timestamps_and_statuses():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    rows = main_routes.home_recent_import_rows([
        {
            "id": "done-job",
            "job_type": "recipe-import",
            "status": "completed",
            "completed_items": 4,
            "failed_items": 0,
            "result_payload": {"created_urls": ["a", "b", "c"]},
            "source_items": [{"label": "https://example.test/recipes/weeknight-pasta"}],
            "completed_at": "2026-07-10T10:00:00Z",
        },
        {
            "id": "running-job",
            "job_type": "doc-photo-import",
            "status": "running",
            "progress_percent": 40,
            "source_items": [{"label": "family-recipes.pdf"}],
            "updated_at": "2026-07-10T11:48:00Z",
        },
        {"id": "not-an-import", "job_type": "create-recipe-pdf", "status": "completed"},
    ], reference_time=now)

    assert rows == [
        {
            "job_id": "done-job",
            "title": "weeknight pasta",
            "count_text": "3 recipes imported",
            "time_label": "2h ago",
            "status": "completed",
            "source_icon": "link",
            "error_message": "",
        },
        {
            "job_id": "running-job",
            "title": "family-recipes.pdf",
            "count_text": "40% complete",
            "time_label": "12m ago",
            "status": "running",
            "source_icon": "document",
            "error_message": "",
        },
    ]


def test_home_template_has_supported_overflow_and_favorite_action():
    template = read_text("PushShoppingList/templates/index.html")
    home_start = template.index('<section class="app-home-dashboard"')
    home_end = template.index("{% include \"sections/app_workspaces.html\" %}")
    home = template[home_start:home_end]

    assert "toggleHomeRecipeMenu(this, event)" in home
    assert "More actions for {{ recipe.name }}" in home
    assert "Open Recipe" in home
    assert "Edit Recipe" in home
    assert "openHomeRecentImport" in home
    assert "home_recent_imports" in home
    assert "app-home-panel-title" in home
    assert 'recipe.rating_stars | default("☆☆☆☆☆", true)' in home
    assert "Unrated recipe" in home
    assert "star_number <= recipe.rating" not in home
    assert "&#9733;" not in home
    assert "Time TBD" not in home
    assert '<article class="app-recipe-card app-home-recipe-card"' in home
    assert '<div class="app-recipe-card-body app-home-recipe-body">' in home
    assert "app-recipe-card-metadata app-home-recipe-metadata" in home
    assert "recipe.card_cook_time" in home
    assert "recipe.card_calories" in home
    assert "recipe.cookbook_name and not recipe.cookbook_is_unclassified" in home
    assert "recipe.home_badge" in home
    assert "&#9201;" in home
    assert "&#128293;" in home
    assert "&#128218;" in home
    assert "&#127991;&#65039;" in home
    assert home.index("app-home-recipe-rating") < home.index("recipe.card_cook_time")
    assert home.index("recipe.card_cook_time") < home.index("recipe.card_calories")
    assert home.index("recipe.card_calories") < home.index("recipe.cookbook_name and not recipe.cookbook_is_unclassified")
    assert home.index("recipe.cookbook_name and not recipe.cookbook_is_unclassified") < home.index("recipe.home_badge")
    assert "data-recipe-favorite" in home
    assert 'aria-pressed="{% if recipe.favorite %}true{% else %}false{% endif %}"' in home
    assert 'onclick="return toggleRecipeFavorite(this, event)"' in home
    assert 'shell.svg_icon("heart")' in home


def test_home_css_and_javascript_cover_fidelity_and_menu_interactions():
    template = read_text("PushShoppingList/templates/index.html")
    css = read_text("PushShoppingList/static/css/app.css")
    script = read_text("PushShoppingList/static/js/app.js")

    assert ".app-shell-body:has(.app-home-dashboard:not([hidden])) .app-content" in css
    assert ".app-shell-body:has(.app-home-dashboard:not([hidden])) .app-topbar" in css
    assert "padding-inline: 24px;" in css
    assert "width: calc(100% - 48px);" in css
    assert "max-width: none;" in css
    assert 'class="app-home-hero-copy"' in template
    assert "ai-pantry-home-banner-v4.png" in css
    assert "app-home-hero-logo" not in template
    assert ".app-home-hero-logo" not in css
    assert "background-color: transparent;" in css
    assert "background-position: center;" in css
    assert "background-size: contain;" in css
    assert "grid-template-columns: minmax(0, 1fr) max-content;" in css
    assert "column-gap: clamp(24px, 2.5vw, 40px);" in css
    assert "width: min(100%, 1120px);" in css
    assert "margin: 0 0 14px;" in css
    assert "align-items: start;" in css
    assert "width: clamp(280px, 20vw, 320px);" in css
    assert "max-width: min(38vw, 100%);" in css
    assert "grid-column: 2;\n        grid-row: 1;" in css
    assert "aspect-ratio: 310 / 197;" in css
    assert "align-self: start;\n        justify-self: end;" in css
    assert "transform: none;" in css
    assert "min-height: 267px;" not in css
    assert "@media (min-width: 760px) and (max-width: 1099px)" in css
    assert "@media (max-width: 759px)" in css
    assert "grid-row: 2;" in css
    assert "width: clamp(240px, 72vw, 320px);" in css
    assert ".app-home-recipe-media img {\n        display: block;" in css
    assert "max-width: 100%;" in css
    assert ".app-home-summary-icon .app-icon-svg" in css
    assert ".app-home-recipe-favorite" in css
    assert ".app-home-recipe-menu-toggle" in css
    assert (
        ".app-recipe-card {\n"
        "    display: grid;\n"
        "    grid-template-rows: auto 1fr;\n"
        "    min-width: 0;\n"
        "    overflow: hidden;\n"
        "    border: 1px solid var(--app-border);\n"
        "    border-radius: var(--app-radius-lg);\n"
        "    background: var(--app-surface);"
    ) in css
    assert (
        ".app-recipe-card-body {\n"
        "    display: grid;\n"
        "    gap: 9px;\n"
        "    padding: 14px 14px 16px;"
    ) in css
    assert ".app-recipe-card-metadata" in css
    assert ".app-recipe-card-meta-text" in css
    assert "text-overflow: ellipsis;" in css
    assert ".app-home-recipe-metadata" in css
    assert ".app-home-recipe-rating .is-unselected" in css
    assert ".app-home-import-status.is-running::before" in css
    assert "(min-width: 1100px) and (prefers-color-scheme: dark)" in css
    assert "function toggleRecipeFavorite" in script
    assert "function toggleHomeRecipeMenu" in script
    assert "function closeHomeRecipeMenus" in script
    assert "function openHomeRecipeAction" in script
    assert "function openHomeRecentImport" in script


def test_home_banner_image_asset_exists():
    image_path = ROOT / "PushShoppingList/static/images/ai-pantry-home-banner-v4.png"
    clean_bag_path = ROOT / "PushShoppingList/static/images/ai-pantry-home-banner-v3.png"

    assert image_path.is_file()
    assert clean_bag_path.is_file()
    with Image.open(image_path) as banner:
        assert banner.mode == "RGBA"
        assert banner.size == (620, 394)
        assert all(
            banner.getpixel(point)[3] == 0
            for point in ((0, 0), (619, 0), (0, 393), (619, 393))
        )
        dark_green_logo_pixels = sum(
            1
            for y in range(190, 365)
            for x in range(115, 310)
            if (
                banner.getpixel((x, y))[3] > 180
                and banner.getpixel((x, y))[0] < 45
                and banner.getpixel((x, y))[1] > 45
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[0] * 1.7
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[2] * 1.3
            )
        )
        assert dark_green_logo_pixels > 2500

        right_handle_pixels = sum(
            1
            for y in range(255, 305)
            for x in range(250, 310)
            if (
                banner.getpixel((x, y))[3] > 180
                and banner.getpixel((x, y))[0] < 55
                and banner.getpixel((x, y))[1] > 55
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[0] * 1.5
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[2] * 1.2
            )
        )
        left_wheel_pixels = sum(
            1
            for y in range(325, 360)
            for x in range(165, 215)
            if (
                banner.getpixel((x, y))[3] > 180
                and banner.getpixel((x, y))[0] < 55
                and banner.getpixel((x, y))[1] > 55
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[0] * 1.5
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[2] * 1.2
            )
        )
        right_wheel_pixels = sum(
            1
            for y in range(325, 360)
            for x in range(205, 255)
            if (
                banner.getpixel((x, y))[3] > 180
                and banner.getpixel((x, y))[0] < 55
                and banner.getpixel((x, y))[1] > 55
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[0] * 1.5
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[2] * 1.2
            )
        )
        assert right_handle_pixels > 300
        assert left_wheel_pixels > 40
        assert right_wheel_pixels > 40
        left_wheel_points = [
            (x, y)
            for y in range(315, 360)
            for x in range(165, 220)
            if (
                banner.getpixel((x, y))[3] > 180
                and banner.getpixel((x, y))[0] < 55
                and banner.getpixel((x, y))[1] > 55
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[0] * 1.5
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[2] * 1.2
            )
        ]
        right_wheel_points = [
            (x, y)
            for y in range(310, 355)
            for x in range(210, 260)
            if (
                banner.getpixel((x, y))[3] > 180
                and banner.getpixel((x, y))[0] < 55
                and banner.getpixel((x, y))[1] > 55
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[0] * 1.5
                and banner.getpixel((x, y))[1] > banner.getpixel((x, y))[2] * 1.2
            )
        ]
        assert sum(y for _, y in right_wheel_points) / len(right_wheel_points) < (
            sum(y for _, y in left_wheel_points) / len(left_wheel_points)
        )

    with Image.open(image_path) as banner, Image.open(clean_bag_path) as clean_bag:
        diff = ImageChops.difference(banner.convert("RGBA"), clean_bag.convert("RGBA"))
        changed_points = [
            (x, y)
            for y in range(diff.height)
            for x in range(diff.width)
            if diff.getpixel((x, y)) != (0, 0, 0, 0)
        ]
        assert changed_points
        assert all(120 <= x <= 320 and 185 <= y <= 365 for x, y in changed_points)


def test_home_dashboard_uses_common_grid_and_stronger_sidebar_collapse():
    template = read_text("PushShoppingList/templates/index.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "--app-dashboard-gap: clamp(12px, 1.2vw, 20px);" in css
    assert "--app-dashboard-card-padding: clamp(14px, 1vw, 18px);" in css
    assert ".app-home-dashboard {\n    display: grid;" in css
    assert "grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);" in css
    assert "grid-template-columns: repeat(12, minmax(0, 1fr));" not in css
    assert ".app-home-summary-grid {\n    display: grid;\n    grid-column: 1 / -1;" in css
    assert ".app-home-primary-grid,\n.app-home-secondary-grid {\n    display: contents;" in css
    assert 'class="app-home-secondary-left"' in template
    assert ".app-home-recent-recipes {\n    grid-column: 1;" in css
    assert ".app-home-meal-preview {\n    grid-column: 2;" in css
    assert ".app-home-secondary-left {\n    display: grid;\n    grid-column: 1;" in css
    assert ".app-home-recent-imports {\n    grid-column: 2;" in css
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in css
    assert ".app-home-meal-preview .app-home-empty-state {\n    min-height: 0;" in css
    assert "@media (max-width: 1099px)" in css
    assert ".app-home-summary-grid {\n        grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert ".app-home-recent-recipes,\n    .app-home-meal-preview,\n    .app-home-secondary-left,\n    .app-home-recent-imports {\n        grid-column: 1 / -1;" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert "@media (max-width: 620px)" in css
    assert ".app-home-dashboard {\n        --app-dashboard-gap: 12px;\n        --app-dashboard-card-padding: 14px;\n        grid-template-columns: minmax(0, 1fr);" in css
    assert "@media (max-width: 620px)" in css
    assert ".app-home-empty-state button {\n        width: auto;" in css
    assert ".app-search-submit {\n        min-width: 64px;" not in css
    assert ".app-sidebar-collapse span" in css
    assert ".app-sidebar-collapse span::before" in css
    assert '.app-sidebar-collapse[aria-pressed="true"] span::before' in css
    assert "font-size: 32px;" in css
