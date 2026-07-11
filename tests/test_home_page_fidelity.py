from datetime import datetime
from datetime import timezone
from pathlib import Path

from PIL import Image

from PushShoppingList.routes import main_routes


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


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


def test_home_template_has_supported_overflow_and_no_fake_favorite():
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
    assert "Time TBD" not in home
    assert "favorite" not in home.lower()
    assert "heart" not in home.lower()


def test_home_css_and_javascript_cover_fidelity_and_menu_interactions():
    template = read_text("PushShoppingList/templates/index.html")
    css = read_text("PushShoppingList/static/css/app.css")
    script = read_text("PushShoppingList/static/js/app.js")

    assert ".app-shell-body:has(.app-home-dashboard:not([hidden])) .app-content" in css
    assert "width: calc(100% - 60px);" in css
    assert 'class="app-home-hero-copy"' in template
    assert "ai-pantry-home-banner-v4.png" in css
    assert "app-home-hero-logo" not in template
    assert ".app-home-hero-logo" not in css
    assert "background-color: transparent;" in css
    assert "background-position: center;" in css
    assert "background-size: contain;" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);" in css
    assert "column-gap: 24px;" in css
    assert "grid-column: 2;\n        grid-row: 1;" in css
    assert "aspect-ratio: 310 / 197;" in css
    assert "align-self: center;\n        justify-self: end;" in css
    assert "transform: translateX(18px);" in css
    assert "@media (min-width: 760px) and (max-width: 1099px)" in css
    assert "@media (max-width: 759px)" in css
    assert "grid-row: 2;" in css
    assert "width: min(100%, 320px);" in css
    assert ".app-home-summary-icon .app-icon-svg" in css
    assert ".app-home-recipe-menu-toggle" in css
    assert ".app-home-recipe-rating .is-unselected" in css
    assert ".app-home-import-status.is-running::before" in css
    assert "(min-width: 1100px) and (prefers-color-scheme: dark)" in css
    assert "function toggleHomeRecipeMenu" in script
    assert "function closeHomeRecipeMenus" in script
    assert "function openHomeRecipeAction" in script
    assert "function openHomeRecentImport" in script


def test_home_banner_image_asset_exists():
    image_path = ROOT / "PushShoppingList/static/images/ai-pantry-home-banner-v4.png"

    assert image_path.is_file()
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


def test_home_dashboard_uses_common_grid_and_stronger_sidebar_collapse():
    css = read_text("PushShoppingList/static/css/app.css")

    assert "--app-dashboard-gap: 18px;" in css
    assert "--app-dashboard-card-padding: 18px;" in css
    assert "grid-template-columns: repeat(12, minmax(0, 1fr));" in css
    assert ".app-home-recent-recipes {\n        grid-column: span 7;" in css
    assert ".app-home-meal-preview {\n        grid-column: span 5;" in css
    assert ".app-home-smart-suggestions,\n    .app-home-price-preview,\n    .app-home-recent-imports" in css
    assert ".app-home-empty-state button {\n        width: auto;" in css
    assert ".app-sidebar-collapse span" in css
    assert ".app-sidebar-collapse span::before" in css
    assert '.app-sidebar-collapse[aria-pressed="true"] span::before' in css
    assert "font-size: 32px;" in css
