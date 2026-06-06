from pathlib import Path

from PushShoppingList.services import recipe_edit_service


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
