import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import menu_mega_json_service
from PushShoppingList.services import menu_store_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_recipe_editor_includes_inline_category_controls_above_ingredients():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")

    assert "recipeEditCategoriesSection" in template
    assert "Edit Recipe Categories" in template
    assert "recipeEditCategoryMealType" in template
    assert "recipeEditCategoryCuisine" in template
    assert "recipeEditCategoryMainIngredient" in template
    assert "recipeEditCategoryCookingMethod" in template
    assert "recipeEditCategoryOccasion" in template
    assert "recipeEditCategoryDietaryPreference" in template
    assert "recipeEditCategoryPrepTimeGroup" in template
    assert "recipeEditMenuSectionField" in template
    assert "recipeEditCategoryMenuSectionField" in template
    assert "recipeEditCategoryMenuSection" in template
    assert "recipeEditMenuSectionName" in template
    assert template.count("data-recipe-edit-menu-section-field") >= 2
    assert template.count("data-recipe-edit-menu-section-name") >= 2
    assert "data-recipe-edit-menu-section-option" in template
    assert "Edit Menu Section" in template
    assert "recipeEditCategoryCustomCategories" in template
    assert "recipe-edit-category-menu" in template
    assert "Have ChatGPT Decide All" in template
    assert "Have ChatGPT Decide Missing" in template
    assert template.index("recipeEditCategoriesSection") < template.index("recipeEditIngredientsTitle")
    assert template.index("recipeEditCategoryPrepTimeGroup") < template.index("recipeEditCategoryCustomCategories")
    assert template.index("recipeEditMenuItemDetails") < template.index("recipeEditCategoryMenuSection")
    assert template.index("recipeEditCategoryMenuSection") < template.index("recipeEditMenuOrderUrl")
    assert template.index("recipeEditCategoryPrepTimeGroup") < template.index("recipeEditCategoryMenuSectionField")
    assert template.index("recipeEditCategoryMenuSectionField") < template.index("recipeEditCategoryCustomCategories")

    assert "function populateRecipeEditCategories" in script
    assert "function saveRecipeEditorCategories" in script
    assert "function selectRecipeEditMenuSection" in script
    assert "function editRecipeEditMenuSection" in script
    assert "function updateRecipeEditorMenuSectionOptions" in script
    assert "function recipeEditorMenuSectionFields" in script
    assert "document.querySelectorAll(\"[data-recipe-edit-menu-section-name]\")" in script
    close_menu_block = script[
        script.index("function closeRecipeEditRowMenus"):
        script.index("function closeRecipeViewGenerateSubmenus")
    ]
    assert ".recipe-edit-row-menu-wrap button[aria-expanded]" in close_menu_block
    assert ".recipe-edit-section-menu-wrap button[aria-expanded]" in close_menu_block
    menu_section_options_block = script[
        script.index("function updateRecipeEditorMenuSectionOptions"):
        script.index("function ensureRecipeEditorMenuSectionOption")
    ]
    assert "ensureRecipeEditorMenuSectionOption(currentSection, activeCookbookId);" in menu_section_options_block
    assert menu_section_options_block.index("ensureRecipeEditorMenuSectionOption(currentSection, activeCookbookId);") < menu_section_options_block.index("recipeEditorMenuSectionMenus().forEach(menu =>")
    assert "function categorySourceFieldsForForm" in script
    assert '? [...CATEGORY_FIELD_NAMES, "menu_section", "custom_categories"]' in script
    assert "function decideRecipeEditCategoriesWithChatGPT" in script
    assert "function applyRecipeEditCategorySuggestions" in script
    assert 'const RECIPE_EDIT_MENU_SECTION_FIELD_NAME = "menu_section";' in script
    assert "const RECIPE_EDIT_CATEGORY_AI_FIELD_NAMES = CATEGORY_FIELD_NAMES;" in script
    assert "const RECIPE_EDIT_CATEGORY_FIELD_NAMES = [...CATEGORY_FIELD_NAMES, RECIPE_EDIT_MENU_SECTION_FIELD_NAME];" in script
    assert 'menu_section: "recipeEditCategoryMenuSection"' in script
    assert "ChatGPT will replace the current category selections. Continue?" in script
    assert "saveRecipeEditorCategories(sourceUrl, payload.original_url)" in script
    assert "cookbook_category_overwrite" in script


def test_recipe_editor_mobile_footer_uses_compact_ai_controls():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")

    footer = template[template.index('<div class="recipe-edit-actions">'):template.index("</div>", template.index('<div class="recipe-edit-actions">'))]
    assert 'data-short-label="Overwrite"' in footer
    assert 'data-short-label="Preview"' in footer
    assert 'data-short-label="Infer"' in footer

    mobile_start = css.index("@media (max-width: 760px)", css.index(".recipe-edit-ai-infer"))
    phone_start = css.index("@media (max-width: 520px)", mobile_start)
    mobile_css = css[mobile_start:phone_start]
    phone_css = css[phone_start:css.index("}", css.index("grid-template-columns: repeat(3", phone_start)) + 1]

    assert "grid-template-columns: repeat(6, minmax(0, 1fr));" in mobile_css
    assert ".recipe-edit-actions .recipe-edit-ai-overwrite-toggle" in mobile_css
    assert "width: auto;" in mobile_css
    assert "flex-basis: auto;" in mobile_css
    assert "content: attr(data-short-label);" in mobile_css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in phone_css
    assert ".recipe-edit-ai-overwrite-toggle {\n                width: 100%;" not in mobile_css
    assert ".recipe-edit-ai-infer {\n                flex-basis: 100%;" not in mobile_css


def test_recipe_editor_infer_missing_details_runs_full_ai_followups():
    script = read_text("PushShoppingList/static/js/app.js")
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")

    assert "async function estimateRecipeNutrition(button, options = {})" in script
    assert "async function decideRecipeEditCategoriesWithChatGPT(button, mode = \"missing\", options = {})" in script
    assert "async function runRecipeEditorInferenceFollowups()" in script
    assert "let recipeEditInferenceContext = {};" in script
    assert "cookbook_id: recipeEditInferenceContext.cookbook_id || \"\"" in script
    assert "cookbook_name: recipeEditInferenceContext.cookbook_name || \"\"" in script
    assert "await estimateRecipeNutrition(null, {" in script
    assert "forceEstimate: true" in script
    assert "force_estimate: forceEstimate" in script
    assert "await decideRecipeEditCategoriesWithChatGPT(null, \"all\", {" in script
    assert "const followupResult = previewOnly ? null : await runRecipeEditorInferenceFollowups();" in script
    assert "Save Recipe to keep nutrition/categories." in script
    assert "Recipe AI" in template
    assert "Re-run Recipe Prediction..." in template
    assert "onclick=\"return rerunRecipePredictionFromMenu(this)\"" in template
    assert "function rerunRecipePredictionFromMenu(button)" in script
    assert "previewOnly: true" in script
    assert "overwriteAiFields: true" in script
    assert "applyPreviewToEditor: true" in script
    assert "forceRecipeNotes: true" in script
    assert 'forceFields: ["recipe_notes"]' in script
    assert "recipe: payload.recipe" in script
    assert "force_recipe_notes: Boolean(optionObject.forceRecipeNotes)" in script
    assert "Preview loaded in the editor. Save Recipe to keep it." in script


def test_recipe_editor_estimate_per_serving_prompts_before_overwrite():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "let forceEstimate = Boolean(options.forceEstimate || options.force);" in script
    assert "function recipeHasNutritionData(recipe = {})" in script
    assert "recipeHasNutritionData(payload.recipe)" in script
    assert "const hasPerServingEstimate = recipeHasPerServingEstimate(payload.recipe);" in script
    assert "window.confirm(\"Nutrition data already exists. Overwrite it with a new per-serving estimate?\")" in script
    assert "forceEstimate = true;" in script
    assert "Existing nutrition data was kept." in script
    assert "canceled: shouldPromptOverwrite" in script
    assert "force_estimate: forceEstimate" in script


def test_recipe_nutrition_estimate_force_bypasses_existing_nutrition(monkeypatch, tmp_path):
    calls = []

    def fake_estimate(recipe):
        calls.append(recipe)
        return {
            "ok": True,
            "nutrition": [
                {"key": "serving_basis", "value": "per serving"},
                {"key": "calories", "value": "210 kcal"},
            ],
        }

    monkeypatch.setattr(recipe_routes, "estimate_recipe_nutrition", fake_estimate)
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [{
            "user_id": "nutrition-user",
            "email": "nutrition@example.com",
            "username": "nutrition",
            "account_status": "active",
        }],
    })

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "nutrition-user"

        response = client.post(
            "/api/recipe_nutrition_estimate",
            json={
                "force_estimate": True,
                "recipe": {
                    "recipe_title": "Spring Roll",
                    "ingredients": [{"ingredient": "rice paper"}],
                    "nutrition": [
                        {"key": "serving_basis", "value": "per serving"},
                        {"key": "calories", "value": "165 kcal"},
                    ],
                },
            },
        )

    data = response.get_json()

    assert response.status_code == 200
    assert calls
    assert data["nutrition"][1] == {"key": "calories", "value": "210 kcal"}


def test_recipe_editor_category_metadata_preserves_saved_values_without_live_inference():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        choices = cookbook_service.cookbook_category_choices()
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/enchiladas"],
            [{"name": "Enchiladas Verde", "url": "https://example.com/enchiladas"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/enchiladas",
            {
                "meal_type": choices["meal_type"][1],
                "cuisine": choices["cuisine"][1],
                "custom_categories": "Sophia's Favorites, Weeknight Dinners",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor(
            "https://example.com/enchiladas",
            {
                "recipe_title": "Enchiladas Verde with Jackfruit and White Beans",
                "prep_time": "20 min",
                "ingredients": [
                    {"ingredient": "young green jackfruit"},
                    {"ingredient": "white beans"},
                    {"ingredient": "green enchilada sauce"},
                ],
                "instructions": [
                    {"instruction": "Bake the filled tortillas until hot."},
                ],
            },
            {"name": "Enchiladas Verde"},
        )

        assert metadata["meal_type"] == choices["meal_type"][1]
        assert metadata["cuisine"] == choices["cuisine"][1]
        assert metadata["main_ingredient"] == ""
        assert metadata["cooking_method"] == ""
        assert metadata["prep_time_group"] == ""
        assert metadata["custom_categories"] == ["Sophia's Favorites", "Weeknight Dinners"]
        assert metadata["category_metadata_source"] == "Saved"
        assert metadata["category_metadata_sources"]["meal_type"] == "user_selected"
        assert metadata["category_metadata_sources"]["main_ingredient"] == "blank"


def test_recipe_category_metadata_preserves_ai_inferred_sources():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        choices = cookbook_service.cookbook_category_choices()
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/beans"],
            [{"name": "Bean Enchiladas", "url": "https://example.com/beans"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/beans",
            {
                "meal_type": choices["meal_type"][2],
                "main_ingredient": next(item for item in choices["main_ingredient"] if "Beans" in item),
            },
            category_sources={
                "meal_type": "user_selected",
                "main_ingredient": "ai_inferred",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor("https://example.com/beans")

        assert metadata["category_metadata_sources"]["meal_type"] == "user_selected"
        assert metadata["category_metadata_sources"]["main_ingredient"] == "ai_inferred"
        assert metadata["category_metadata_sources"]["cuisine"] == "blank"


def test_recipe_menu_section_saves_as_cookbook_specific_metadata():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/spring-roll"],
            [{"name": "Spring Roll", "url": "https://example.com/spring-roll"}],
        )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/spring-roll",
            {
                "menu_section": "Kitchen Appetizers",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor(
            "https://example.com/spring-roll",
            {"recipe_title": "Spring Roll", "menu_section": "Imported Section"},
        )

        assert metadata["menu_section"] == "Kitchen Appetizers"
        assert metadata["category_metadata_user_set"] is True
        assert metadata["category_metadata_source"] == "Saved"

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/spring-roll",
            {
                "meal_type": cookbook_service.cookbook_category_choices()["meal_type"][1],
            },
            confirm_overwrite=True,
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor("https://example.com/spring-roll")

        assert metadata["menu_section"] == "Kitchen Appetizers"
        view = cookbook_service.cookbook_view([])
        assert "Kitchen Appetizers" in view["cookbooks"][0]["menu_section_choices"]


def test_cookbook_view_hydrates_blank_menu_sections_from_menu_store():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ), patch.object(
        menu_store_service,
        "MENU_STORE_FILE",
        Path(temp_dir) / "restaurant_menus.json",
    ):
        recipe_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-98-Chow_Mein"
        cookbook = cookbook_service.create_cookbook("Vel Asian Cuisine")
        cookbook_service.move_recipes_to_cookbook(
            cookbook["id"],
            [recipe_url],
            [{"name": "Chow Mein", "url": recipe_url}],
        )
        menu_store_service.save_menu_store({
            "restaurants": [],
            "menus": [],
            "sections": [{
                "id": "section-fried-rice",
                "section_name": "Fried Rice & Noodles",
            }, {
                "id": "section-other",
                "section_name": "Other Recipes",
            }],
            "items": [{
                "id": "item-ai-chow-mein",
                "cookbook_id": cookbook["id"],
                "menu_section_id": "section-other",
                "recipe_url": "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-98-AI-Inferred_Chow_Mein",
                "item_name": "Chow Mein",
                "menu_price": "$18.49",
            }, {
                "id": "item-chow-mein",
                "cookbook_id": "vel-asian-cusine",
                "menu_id": "menu-velasian",
                "restaurant_id": "restaurant-velasian",
                "menu_section_id": "section-fried-rice",
                "recipe_url": recipe_url,
                "item_name": "Chow Mein",
                "menu_price": "$13.99",
                "menu_description": "Egg, carrot, napa, bok choy, onion, scallion serve with sweet chili sauce.",
            }],
            "pdf_logs": [],
        })

        view = cookbook_service.cookbook_view([])
        recipe = view["cookbooks"][0]["recipes"][0]

        assert recipe["menu_section"] == "Fried Rice & Noodles"
        assert recipe["section_name"] == "Fried Rice & Noodles"
        assert recipe["menu_item_name"] == "Chow Mein"
        assert recipe["menu_price"] == "$13.99"
        assert "Fried Rice & Noodles" in view["cookbooks"][0]["menu_section_choices"]


def test_lightweight_recipe_edit_views_keep_all_hydrated_menu_section_choices():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ), patch.object(
        menu_store_service,
        "MENU_STORE_FILE",
        Path(temp_dir) / "restaurant_menus.json",
    ):
        spring_roll_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-1-Spring_Roll"
        chow_mein_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-98-Chow_Mein"
        cookbook = cookbook_service.create_cookbook("Vel Asian Cuisine")
        cookbook_service.move_recipes_to_cookbook(
            cookbook["id"],
            [spring_roll_url, chow_mein_url],
            [
                {"name": "Spring Roll", "url": spring_roll_url},
                {"name": "Chow Mein", "url": chow_mein_url},
            ],
        )
        menu_store_service.save_menu_store({
            "restaurants": [],
            "menus": [],
            "sections": [
                {"id": "section-appetizers", "section_name": "Kitchen Appetizers"},
                {"id": "section-noodles", "section_name": "Fried Rice & Noodles"},
            ],
            "items": [
                {
                    "id": "item-spring-roll",
                    "cookbook_id": cookbook["id"],
                    "menu_section_id": "section-appetizers",
                    "recipe_url": spring_roll_url,
                    "item_name": "Spring Roll",
                },
                {
                    "id": "item-chow-mein",
                    "cookbook_id": cookbook["id"],
                    "menu_section_id": "section-noodles",
                    "recipe_url": chow_mein_url,
                    "item_name": "Chow Mein",
                },
            ],
            "pdf_logs": [],
        })

        for view in (recipe_routes.recipe_edit_cookbook_view(), main_routes.lightweight_cookbook_view()):
            cookbook_view = view["cookbooks"][0]
            assert cookbook_view["recipes"] == []
            assert cookbook_view["menu_sections"] == {}
            assert cookbook_view["menu_section_choices"] == ["Kitchen Appetizers", "Fried Rice & Noodles"]


def test_lightweight_recipe_edit_views_keep_menu_snapshot_section_choices():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ), patch.object(
        menu_store_service,
        "MENU_STORE_FILE",
        Path(temp_dir) / "restaurant_menus.json",
    ), patch.object(
        menu_mega_json_service,
        "workspace_data_root",
        lambda: Path(temp_dir) / "workspace",
    ):
        source_url = "https://piscomarindy.com/Menu.html"
        recipe_url = f"{source_url}?menu_item=menu-item-20-Tallarin_Saltado"
        cookbook = cookbook_service.create_cookbook("piscomarindy")
        cookbook_service.move_recipes_to_cookbook(
            cookbook["id"],
            [recipe_url],
            [{
                "name": "Tallarin Saltado",
                "url": recipe_url,
                "menu_section": "PESCADOS Y MARISCOS",
            }],
        )
        mega_json = menu_mega_json_service.build_mega_menu_json(
            source_url,
            [
                {
                    "section_name": "APPETIZERS",
                    "items": [],
                },
                {
                    "section_name": "CEVICHE",
                    "items": [],
                },
                {
                    "section_name": "PESCADOS Y MARISCOS",
                    "items": [{"item_name": "Jalea Real", "menu_section": "PESCADOS Y MARISCOS"}],
                },
                {
                    "section_name": "CHAUFAS",
                    "items": [{"item_name": "Chaufa Amazonico", "menu_section": "CHAUFAS"}],
                },
                {
                    "section_name": "CLASICOS",
                    "items": [],
                },
                {
                    "section_name": "SALTADOS",
                    "items": [{"item_name": "Tallarin Saltado", "menu_section": "SALTADOS"}],
                },
                {
                    "section_name": "FETTUCCINE PASTAS",
                    "items": [{"item_name": "Fettuccine Pisco Mar", "menu_section": "FETTUCCINE PASTAS"}],
                },
                {
                    "section_name": "SOPA",
                    "items": [],
                },
                {
                    "section_name": "GRILL",
                    "items": [],
                },
                {
                    "section_name": "GARDEN SALAD",
                    "items": [],
                },
                {
                    "section_name": "KIDS",
                    "items": [],
                },
                {
                    "section_name": "SIDES",
                    "items": [],
                },
                {
                    "section_name": "JUGOS",
                    "items": [],
                },
                {
                    "section_name": "DESERTS",
                    "items": [],
                },
            ],
            diagnostics={"restaurant": {"restaurant_name": "Piscomar"}},
        )
        menu_mega_json_service.save_menu_mega_json_snapshot(
            mega_json,
            job_id="job-piscomar",
            cookbook_id=cookbook["id"],
            cookbook_name=cookbook["name"],
        )

        view = recipe_routes.recipe_edit_cookbook_view()
        cookbook_view = view["cookbooks"][0]

        assert cookbook_view["recipes"] == []
        assert cookbook_view["menu_sections"] == {}
        assert cookbook_view["menu_section_choices"] == [
            "APPETIZERS",
            "CEVICHE",
            "PESCADOS Y MARISCOS",
            "CHAUFAS",
            "CLASICOS",
            "SALTADOS",
            "FETTUCCINE PASTAS",
            "SOPA",
            "GRILL",
            "GARDEN SALAD",
            "KIDS",
            "SIDES",
            "JUGOS",
            "DESERTS",
        ]


def test_chatgpt_category_decision_normalizes_to_dropdown_choices():
    choices = cookbook_service.cookbook_category_choices()
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "meal_type": "Dinner",
                        "cuisine": "Italian",
                        "main_ingredient": "Pasta",
                        "cooking_method": "Oven Baked",
                        "occasion": "Family Dinner",
                        "dietary_preference": "High Protein",
                        "prep_time_group": "15-30 Minutes",
                        "custom_categories": ["Weeknight Dinners", "Comfort Food"],
                    })
                )
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: response
            )
        )
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch.object(
        recipe_edit_service,
        "get_openai_client",
        return_value=client,
    ), patch.object(recipe_edit_service, "record_openai_usage"):
        result = recipe_edit_service.decide_recipe_categories_with_chatgpt({
            "recipe_title": "Baked Stuffed Pasta",
            "prep_time": "20 min",
            "cook_time": "35 min",
            "ingredients": [
                {"ingredient": "pasta shells"},
                {"ingredient": "ricotta cheese"},
                {"ingredient": "tomato sauce"},
            ],
            "instructions": [
                {"instruction": "Stuff the pasta and bake until bubbling."},
            ],
        })

    assert result["ok"] is True
    categories = result["categories"]
    assert categories["meal_type"] == next(item for item in choices["meal_type"] if "Dinner" in item)
    assert categories["cuisine"] == next(item for item in choices["cuisine"] if "Italian" in item)
    assert categories["main_ingredient"] == next(item for item in choices["main_ingredient"] if "Pasta" in item)
    assert categories["cooking_method"] == next(item for item in choices["cooking_method"] if "Oven Baked" in item)
    assert categories["occasion"] == next(item for item in choices["occasion"] if "Family Dinner" in item)
    assert categories["dietary_preference"] == next(item for item in choices["dietary_preference"] if "High Protein" in item)
    assert categories["prep_time_group"] == next(item for item in choices["prep_time_group"] if "15" in item and "30" in item)
    assert categories["custom_categories"] == ["Weeknight Dinners", "Comfort Food"]


def test_recipe_category_inference_uses_total_time_and_keeps_vegan_out_of_main_ingredient():
    categories = cookbook_service.infer_recipe_categories({
        "name": "Vegan Enchiladas Verde with Jackfruit and White Beans",
        "prep_time": "20 min",
        "total_time": "45 min",
        "sections": {
            "INGREDIENTS": [
                {"name": "young green jackfruit"},
                {"name": "white beans"},
                {"name": "green enchilada sauce"},
            ],
        },
        "instruction_items": ["Bake the filled tortillas until hot."],
    })

    assert "Vegan" not in categories["main_ingredient"]
    assert categories["main_ingredient"] == next(
        item for item in cookbook_service.cookbook_category_choices()["main_ingredient"] if "Beans" in item
    )
    assert categories["dietary_preference"] == next(
        item for item in cookbook_service.cookbook_category_choices()["dietary_preference"] if "Vegan" in item
    )
    assert categories["prep_time_group"] == next(
        item for item in cookbook_service.cookbook_category_choices()["prep_time_group"] if "30" in item and "60" in item
    )


def test_chatgpt_category_decision_logs_and_sanitizes_vegan_and_total_time(capsys):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "meal_type": "Dinner",
                        "cuisine": "Mexican",
                        "main_ingredient": "Vegan",
                        "cooking_method": "Oven Baked",
                        "occasion": "Family Dinner",
                        "dietary_preference": "Vegan",
                        "prep_time_group": "15-30 Minutes",
                        "custom_categories": ["Comfort Food"],
                    })
                )
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: response
            )
        )
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch.object(
        recipe_edit_service,
        "get_openai_client",
        return_value=client,
    ), patch.object(recipe_edit_service, "record_openai_usage"):
        result = recipe_edit_service.decide_recipe_categories_with_chatgpt(
            {
                "source_url": "manual://recipe/test-vegan-enchiladas",
                "recipe_title": "Vegan Enchiladas Verde with White Beans",
                "prep_time": "20 min",
                "total_time": "45 min",
                "ingredients": [
                    {"ingredient": "white beans"},
                    {"ingredient": "green enchilada sauce"},
                ],
                "instructions": [
                    {"instruction": "Bake until hot."},
                ],
            },
            mode="missing",
            trigger_source="recipe_editor:missing",
            current_categories={"meal_type": "🍽️ Dinner"},
        )

    assert result["ok"] is True
    assert "Vegan" not in result["categories"]["main_ingredient"]
    assert result["categories"]["prep_time_group"] == next(
        item for item in cookbook_service.cookbook_category_choices()["prep_time_group"] if "30" in item and "60" in item
    )

    log_output = capsys.readouterr().out
    assert "[recipe_category_inference]" in log_output
    assert "manual://recipe/test-vegan-enchiladas" in log_output
    assert "recipe_editor:missing" in log_output
    assert '"meal_type"' not in log_output.split('"fields_changed":', 1)[1]
