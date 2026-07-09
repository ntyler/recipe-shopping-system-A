from pathlib import Path

from PushShoppingList.routes import main_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_recipe_rating_clamps_to_five_star_range():
    assert recipe_edit_service.normalize_recipe_rating(-1) == 0
    assert recipe_edit_service.normalize_recipe_rating(0) == 0
    assert recipe_edit_service.normalize_recipe_rating(3) == 3
    assert recipe_edit_service.normalize_recipe_rating("5") == 5
    assert recipe_edit_service.normalize_recipe_rating(9) == 5
    assert recipe_edit_service.normalize_recipe_rating("not a number") == 0


def test_reflection_notes_timestamp_and_preserve_feedback():
    existing = [{
        "note_id": "note-1",
        "text": "Needed more salt.",
        "created_at": "2026-06-03T12:00:00+00:00",
        "chatgpt_feedback": "Try seasoning in two passes.",
        "chatgpt_feedback_created_at": "2026-06-03T12:05:00+00:00",
    }]

    sanitized = recipe_edit_service.sanitize_reflection_notes(
        [{"note_id": "note-1", "text": "Needed more salt and a longer rest."}],
        existing,
    )

    assert sanitized == [{
        "note_id": "note-1",
        "text": "Needed more salt and a longer rest.",
        "created_at": "2026-06-03T12:00:00+00:00",
        "chatgpt_feedback": "Try seasoning in two passes.",
        "chatgpt_feedback_created_at": "2026-06-03T12:05:00+00:00",
    }]

    new_note = recipe_edit_service.sanitize_reflection_notes([{"text": "Great texture."}], [])

    assert new_note[0]["text"] == "Great texture."
    assert new_note[0]["note_id"]
    assert new_note[0]["created_at"]


def test_recipe_note_feedback_validates_note_and_key(monkeypatch):
    assert recipe_edit_service.recipe_note_feedback({"note": "  "}) == {
        "ok": False,
        "error": "Add a recipe note before asking ChatGPT for feedback.",
    }

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = recipe_edit_service.recipe_note_feedback({
        "note": "Crust browned too quickly.",
        "recipe": {"recipe_title": "Pie"},
    })

    assert result == {
        "ok": False,
        "error": "Missing OPENAI_API_KEY environment variable.",
    }


def test_recipe_rating_note_ui_and_endpoint_hooks_present():
    script = read_text("PushShoppingList/static/js/app.js")
    current_recipes = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    recipe_view = read_text("PushShoppingList/templates/sections/items.html")
    cookbooks = read_text("PushShoppingList/templates/sections/cookbooks.html")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    for token in (
        "recipeEditRating",
        "setRecipeRating",
        "currentRecipeRating",
        "recipeEditReflectionNotes",
        "addRecipeReflectionNoteRow",
        "collectRecipeReflectionNotes",
        "askRecipeNoteFeedback",
        "/api/recipe_note_feedback",
    ):
        assert token in script

    assert "/api/recipe_note_feedback" in routes
    assert "recipeEditRatingStars" in current_recipes
    assert "recipe-edit-reflection-section" in current_recipes
    assert "recipe-rating-display" in current_recipes
    assert "recipe-rating-display" in recipe_view
    assert "recipe-rating-display" in cookbooks


def test_recipe_view_rating_is_only_metadata_row_under_cookbook():
    recipe_view = read_text("PushShoppingList/templates/sections/items.html")
    css = read_text("PushShoppingList/static/css/app.css")

    title_group = recipe_view[
        recipe_view.index('<span class="recipe-view-name-group">'):
        recipe_view.index('<div class="recipe-view-title-actions">')
    ]

    assert "recipe-rating-display" not in title_group
    assert recipe_view.count("recipe-rating-display") == 1
    assert recipe_view.index("recipe-view-cookbook") < recipe_view.index("recipe-view-rating")
    assert ".recipe-view-rating .recipe-rating-display" in css
    assert "background: transparent;" in css
    assert "border: 0;" in css


def test_current_recipe_food_review_badge_sits_with_menu_status_badges():
    current_recipes = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")

    status_start = current_recipes.index('<span class="recipe-url-summary-status-row">')
    status_end = current_recipes.index('<div class="recipe-url-summary-body">', status_start)
    status_block = current_recipes[status_start:status_end]

    assert "recipe-url-summary-status-row" in current_recipes
    assert status_block.index("menu-recipe-status-stub") < status_block.index("recipe-url-summary-food-review")
    assert status_block.index("menu-recipe-status-generated") < status_block.index("recipe-url-summary-food-review")
    assert status_block.index("recipe-url-summary-food-review") < status_block.index("Generate Fast Recipe")
    assert status_block.index("Generate Fast Recipe") < status_block.index("View Mega Menu JSON")
    assert "justify-self: start;" in css
    assert ".recipe-url-summary-status-row" in css


def test_current_recipe_menu_can_hide_ai_inferred_badges():
    current_recipes = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")
    script = read_text("PushShoppingList/static/js/app.js")

    assert "data-current-recipes-ai-inferred-toggle" in current_recipes
    assert "Hide AI-Inferred Recipe" in current_recipes
    assert "toggleCurrentRecipesAiInferredBadges(this, event)" in current_recipes
    assert "#currentRecipeUrlLogCard.current-recipes-hide-ai-inferred .menu-recipe-status-generated" in css
    assert "CURRENT_RECIPES_HIDE_AI_INFERRED_BADGE_KEY" in script
    assert "function restoreCurrentRecipesAiInferredBadgeSetting" in script
    assert "restoreCurrentRecipesAiInferredBadgeSetting()" in script


def test_recipe_view_notes_render_as_collapsible_detail_section():
    recipe_view = read_text("PushShoppingList/templates/sections/items.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "{% if recipe.recipe_notes %}" in recipe_view
    assert 'data-detail-key="notes|{{ recipe.url }}"' in recipe_view
    assert 'data-detail-content="notes|{{ recipe.url }}"' in recipe_view
    assert recipe_view.index('data-detail-key="instructions|{{ recipe.url }}"') < recipe_view.index('data-detail-key="notes|{{ recipe.url }}"')
    assert recipe_view.index('data-detail-key="notes|{{ recipe.url }}"') < recipe_view.index('data-nutrition-key="nutrition|{{ recipe.url }}"')
    assert "recipe-note-section" in recipe_view
    assert ".recipe-note-section" in css
    assert "border-bottom: 1px solid #263447;" in css
    assert ".recipe-note-section li:empty" in css


def test_recipe_notes_are_editable_between_instructions_and_nutrition():
    script = read_text("PushShoppingList/static/js/app.js")
    current_recipes = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")
    service = read_text("PushShoppingList/services/recipe_edit_service.py")

    assert 'id="recipeEditRecipeNotes"' in current_recipes
    assert "recipe-edit-recipe-notes-section" in current_recipes
    assert current_recipes.index('id="recipeEditInstructions"') < current_recipes.index('id="recipeEditRecipeNotes"')
    assert current_recipes.index('id="recipeEditRecipeNotes"') < current_recipes.index('id="recipeEditNutrition"')
    assert current_recipes.index('id="recipeEditNutrition"') < current_recipes.index('id="recipeEditReflectionNotes"')
    assert 'data-recipe-note-preset="Substitutions & Variations"' in current_recipes
    assert 'data-recipe-note-preset="Storing & Reheating"' in current_recipes
    assert 'data-recipe-note-preset="Top Tips"' in current_recipes
    assert "data-recipe-notes-empty" in current_recipes

    for token in (
        "recipe.recipe_notes || []",
        "recipeNotesHeaderHtml",
        "addRecipePresetNoteSection",
        "addRecipeNoteSectionRow",
        "collectRecipeNoteSections",
        "normalizeRecipeNoteSectionsSnapshot",
        "updateRecipeNoteSectionCount",
        "updateRecipeNotesEmptyState",
        ".recipe-edit-note-section-row, .recipe-edit-reflection-note-row",
        'return ".recipe-edit-note-section-row";',
        "Delete note section",
        "recipe_notes: collectRecipeNoteSections()",
    ):
        assert token in script

    assert ".recipe-edit-note-presets" in css
    assert ".recipe-edit-note-section-row" in css
    assert ".recipe-edit-note-section-main" in css
    assert ".recipe-edit-note-count" in css
    assert ".recipe-edit-recipe-notes-empty" in css
    assert ".recipe-edit-panel-icon-notes" in css
    assert "from PushShoppingList.services.recipe_extract_service import normalize_recipe_note_sections" in service
    assert '"recipe_notes": normalize_recipe_note_sections' in service
    assert '"recipe_notes": sanitize_recipe_notes' in service


def test_recipe_notes_sanitize_through_shared_normalizer():
    notes = recipe_edit_service.sanitize_recipe_notes([
        {
            "heading": "Top Tips",
            "items": ["Keep warm while serving.", " "],
        },
        "Use a wide pan.",
    ])

    assert notes == [
        {
            "heading": "Top Tips",
            "items": ["Keep warm while serving."],
        },
        {
            "heading": "",
            "items": ["Use a wide pan."],
        },
    ]

    assert recipe_edit_service.sanitize_recipe_notes(None, notes) == notes


def test_recipe_notes_for_view_drops_empty_items_and_dedupes_sections():
    sections = main_routes.recipe_notes_for_view({
        "recipe_notes": [
            {
                "heading": "Top Tips",
                "items": [
                    "Keep the slow cooker on warm.",
                    " ",
                ],
            },
            {
                "heading": "Top Tips",
                "items": [
                    "Keep the slow cooker on warm.",
                ],
            },
        ],
    })

    assert sections == [{
        "heading": "Top Tips",
        "items": ["Keep the slow cooker on warm."],
    }]


def test_recipe_extraction_prompt_preserves_notes_separately():
    prompt = recipe_extract_service.build_prompt(
        "https://example.test/chili",
        "NOTES\nTOP TIPS:\n- Keep warm while serving.",
    )

    assert "RECIPE NOTE RULES" in prompt
    assert "recipe_notes" in prompt
    assert 'return those as separate recipe_notes entries with those exact headings' in prompt
    assert 'Do NOT collapse those sections into one generic "Notes" section.' in prompt
    assert "Do NOT put recipe notes into ingredients, equipment, or cooking instructions." in prompt


def test_recipe_notes_import_normalizer_splits_common_source_sections():
    notes = recipe_extract_service.normalize_recipe_note_sections({
        "heading": "Notes",
        "items": [
            "Substitutions and Variations: Use ground turkey instead.",
            "Storing & Reheating: Reheat in the microwave for 30-60 seconds.",
            "Top Tips: Keep warm while serving.",
        ],
    })

    assert notes == [
        {
            "heading": "Substitutions & Variations",
            "items": ["Use ground turkey instead."],
        },
        {
            "heading": "Storing & Reheating",
            "items": ["Reheat in the microwave for 30-60 seconds."],
        },
        {
            "heading": "Top Tips",
            "items": ["Keep warm while serving."],
        },
    ]


def test_recipe_notes_import_normalizer_preserves_generic_notes_without_subsections():
    notes = recipe_extract_service.normalize_recipe_note_sections({
        "heading": "Notes",
        "items": ["Let the chili rest before serving."],
    })

    assert notes == [{
        "heading": "Notes",
        "items": ["Let the chili rest before serving."],
    }]


def test_structured_import_extracts_recipe_notes_from_html_container():
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@type": "Recipe",
          "name": "Slow Cooker Chili",
          "recipeYield": "6 servings",
          "recipeIngredient": ["1 pound ground beef"],
          "recipeInstructions": [{"@type": "HowToStep", "text": "Cook until done."}]
        }
        </script>
      </head>
      <body>
        <div class="wprm-recipe-notes-container">
          <h2>Notes</h2>
          <h3>Substitutions & Variations:</h3>
          <ul><li>Use ground turkey instead.</li></ul>
          <h3>Storing & Reheating:</h3>
          <ul><li>Reheat in the microwave for 30-60 seconds.</li></ul>
          <h3>Top Tips:</h3>
          <ul><li>Keep warm while serving.</li></ul>
        </div>
      </body>
    </html>
    """

    recipe = recipe_extract_service.extract_recipe_from_structured_data(
        "https://example.test/slow-cooker-chili",
        html,
    )

    assert recipe["recipe_notes"] == [
        {
            "heading": "Substitutions & Variations",
            "items": ["Use ground turkey instead."],
        },
        {
            "heading": "Storing & Reheating",
            "items": ["Reheat in the microwave for 30-60 seconds."],
        },
        {
            "heading": "Top Tips",
            "items": ["Keep warm while serving."],
        },
    ]


def test_source_pdf_notes_sanitizer_removes_empty_wprm_bullets():
    html = """
    <html>
      <body>
        <div class="wprm-recipe-notes-container">
          <div class="wprm-recipe-notes">
            <ul>
              <li>Store leftovers up to 5 days.</li>
              <li>   </li>
              <li><br></li>
            </ul>
          </div>
        </div>
      </body>
    </html>
    """

    sanitized = recipe_extract_service.sanitize_html_for_pdf_source(html)

    assert sanitized.count("<li>") == 1
    assert "Store leftovers up to 5 days." in sanitized
    assert ".wprm-recipe-notes-container" in recipe_extract_service.PDF_PRINT_FIX_CSS
