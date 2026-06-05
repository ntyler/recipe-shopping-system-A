from PushShoppingList.services import recipe_extract_service


def test_social_video_import_handles_cover_image_when_local_parse_finds_no_recipe(monkeypatch):
    recipe_url = "https://www.youtube.com/shorts/Xao87NNSfiM"
    page_text = "Title: Quick dinner idea\n\nDescription: Follow for more cooking videos."
    cover_image = {
        "url": "https://img.youtube.com/vi/Xao87NNSfiM/hqdefault.jpg",
        "alt": "Recipe video cover image",
    }

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_text",
        lambda url, progress_callback=None: ("<html></html>", page_text),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_recipe_cover_image_from_html",
        lambda html_text, url: cover_image,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "has_meaningful_social_video_text",
        lambda text: True,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "archive_social_video_text_pdf",
        lambda *args, **kwargs: None,
    )

    result = recipe_extract_service.extract_recipe_from_social_video_url(recipe_url)

    assert result["ok"] is False
    assert result["source_url"] == recipe_url
    assert result["error"] == "Missing OPENAI_API_KEY environment variable."
    assert result["ingredients"] == []


def test_social_video_import_uses_audio_and_images_when_text_only_extraction_finds_no_ingredients(tmp_path, monkeypatch):
    recipe_url = "https://www.youtube.com/shorts/Xao87NNSfiM"
    page_text = "Title: Green enchiladas\n\nDescription: Watch me make dinner."
    cover_image = {
        "url": "https://img.youtube.com/vi/Xao87NNSfiM/hqdefault.jpg",
        "alt": "Green enchiladas",
    }
    calls = {}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path / "raw")
    recipe_extract_service.RAW_FOLDER.mkdir(parents=True)
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_text",
        lambda url, progress_callback=None: ("<html></html>", page_text),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_recipe_cover_image_from_html",
        lambda html_text, url: cover_image,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "has_meaningful_social_video_text",
        lambda text: True,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "archive_social_video_text_pdf",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "send_prompt_to_openai",
        lambda prompt: '{"source_url": "%s", "ingredients": [], "instructions": []}' % recipe_url,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_ytdlp_info",
        lambda url: {
            "title": "Green enchiladas",
            "description": "A quick dinner recipe.",
            "duration": 30,
            "thumbnail": cover_image["url"],
            "thumbnails": [
                {
                    "url": "https://img.youtube.com/vi/Xao87NNSfiM/maxresdefault.jpg",
                    "width": 1280,
                    "height": 720,
                }
            ],
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "transcribe_social_video_audio",
        lambda url, info, progress_callback=None: "Use tortillas, green enchilada sauce, jackfruit, and white beans. Bake until bubbly.",
    )

    def fake_audio_image_openai(prompt, image_urls):
        calls["prompt"] = prompt
        calls["image_urls"] = image_urls
        return """
        {
          "source_url": "https://www.youtube.com/shorts/Xao87NNSfiM",
          "recipe_title": "Green Enchiladas",
          "servings": "4 servings",
          "level": "Easy",
          "total_time": "35 min",
          "prep_time": "10 min",
          "inactive_time": "0 min",
          "cook_time": "25 min",
          "ingredients": [
            {"original_text": "about 2 cups green enchilada sauce", "ingredient": "green enchilada sauce", "quantity": "2", "unit": "cups"},
            {"original_text": "8 tortillas", "ingredient": "tortillas", "quantity": "8", "unit": null}
          ],
          "equipment": [],
          "instructions": [
            {"step_number": 1, "instruction": "Fill tortillas and bake until bubbly.", "equipment_used": []}
          ],
          "nutrition": {"serving_basis": "per serving (estimated)", "calories": "420 kcal", "other": []}
        }
        """

    monkeypatch.setattr(
        recipe_extract_service,
        "send_social_video_audio_image_prompt_to_openai",
        fake_audio_image_openai,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "save_json_response",
        lambda url, response_text, html_text=None: (True, recipe_extract_service.json.loads(response_text)),
    )

    result = recipe_extract_service.extract_recipe_from_social_video_url(recipe_url)

    assert result["ok"] is True
    assert result["extraction_method"] == "social_video_audio_image"
    assert result["ingredients"] == ["green enchilada sauce", "tortillas"]
    assert result["servings"] == "4 servings"
    assert result["level"] == "Easy"
    assert result["total_time"] == "35 min"
    assert result["nutrition"]["serving_basis"] == "per serving (estimated)"
    assert "Audio transcript" in calls["prompt"]
    assert "jackfruit" in calls["prompt"]
    assert calls["image_urls"]


def test_social_video_text_parse_uses_openai_to_fill_missing_estimates(monkeypatch):
    recipe_url = "https://www.youtube.com/shorts/localRecipe"
    page_text = (
        "Title: Simple Pasta\n\n"
        "Description: Ingredients 8 oz pasta; 1 cup tomato sauce "
        "Instructions 1. Boil pasta. 2. Heat sauce and toss together."
    )
    cover_image = {
        "url": "https://img.youtube.com/vi/localRecipe/hqdefault.jpg",
        "alt": "Simple Pasta",
    }
    saved = {}
    archived = {}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_text",
        lambda url, progress_callback=None: ("<html></html>", page_text),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_recipe_cover_image_from_html",
        lambda html_text, url: cover_image,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "has_meaningful_social_video_text",
        lambda text: True,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_video_recipe_pdf_data_with_openai",
        lambda url, text, progress_callback=None: {
            "source_url": url,
            "recipe_title": "Simple Pasta",
            "servings": "2 servings",
            "level": "Easy",
            "total_time": "20 min",
            "prep_time": "5 min",
            "inactive_time": "0 min",
            "cook_time": "15 min",
            "ingredients": [
                {
                    "original_text": "8 oz pasta",
                    "ingredient": "pasta",
                    "quantity": "8",
                    "unit": "oz",
                },
                {
                    "original_text": "1 cup tomato sauce",
                    "ingredient": "tomato sauce",
                    "quantity": "1",
                    "unit": "cup",
                },
            ],
            "equipment": [],
            "instructions": [
                {
                    "step_number": 1,
                    "instruction": "Boil pasta, heat sauce, and toss together.",
                    "equipment_used": [],
                }
            ],
            "nutrition": {
                "serving_basis": "per serving (estimated)",
                "calories": "430 kcal",
                "other": [],
            },
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "archive_social_video_text_pdf",
        lambda *args, **kwargs: archived.update({"args": args, "kwargs": kwargs}),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda url, data: saved.update({"url": url, "data": data}),
    )

    result = recipe_extract_service.extract_recipe_from_social_video_url(recipe_url)

    assert result["ok"] is True
    assert result["extraction_method"] == "social_video_text_openai_estimates"
    assert result["servings"] == "2 servings"
    assert result["level"] == "Easy"
    assert result["nutrition"]["serving_basis"] == "per serving (estimated)"
    assert saved["data"]["cover_image"] == cover_image
    assert archived["kwargs"]["structured_recipe_data"]["servings"] == "2 servings"
    assert archived["kwargs"]["prefer_openai"] is False


def test_social_video_prompt_places_estimation_override_after_conservative_rules():
    prompt = recipe_extract_service.build_social_video_audio_image_prompt(
        "https://www.youtube.com/shorts/Xao87NNSfiM",
        "Title: Lasagna\n\nAudio transcript: Layer pasta with sauce and cheese.",
    )

    conservative_index = prompt.index("Do NOT calculate, estimate, or invent nutrition values.")
    override_index = prompt.index("SOCIAL / VIDEO ESTIMATION OVERRIDE")

    assert override_index > conservative_index
    assert "estimate reasonable values instead of leaving them null" in prompt
    assert "Fill nutrition as an estimated per serving basis" in prompt
    assert "estimate quantity and unit" in prompt


def test_video_text_pdf_includes_title_image_and_estimated_recipe_metadata():
    pdf_html = recipe_extract_service.build_video_text_pdf_html(
        "https://www.youtube.com/shorts/Xao87NNSfiM",
        "",
        recipe_data={
            "recipe_title": "Video Lasagna",
            "cover_image": {
                "url": "https://example.com/lasagna.jpg",
                "alt": "Finished lasagna",
            },
            "servings": "6 servings",
            "level": "Intermediate",
            "total_time": "1 hr 10 min",
            "prep_time": "25 min",
            "inactive_time": "10 min",
            "cook_time": "35 min",
            "ingredients": [
                {
                    "quantity": "12",
                    "unit": None,
                    "ingredient": "lasagna noodles",
                    "preparation": "",
                }
            ],
            "instructions": [
                {
                    "step_number": 1,
                    "instruction": "Layer noodles with sauce and cheese.",
                    "equipment_used": [],
                }
            ],
            "nutrition": {
                "serving_basis": "per serving (estimated)",
                "calories": "520 kcal",
            },
        },
    )

    assert '<img src="https://example.com/lasagna.jpg" alt="Finished lasagna">' in pdf_html
    assert "Recipe Amount: 6 servings" in pdf_html
    assert "Level: Intermediate" in pdf_html
    assert "Total: 1 hr 10 min" in pdf_html
    assert "per serving (estimated)" in pdf_html


def test_build_extract_result_includes_recipe_info_fields():
    result = recipe_extract_service.build_extract_result(
        "https://example.com/recipe",
        {
            "recipe_title": "Quick Dinner",
            "servings": "4 servings",
            "level": "Easy",
            "total_time": "30 min",
            "prep_time": "10 min",
            "inactive_time": "0 min",
            "cook_time": "20 min",
            "ingredients": [
                {
                    "original_text": "1 cup rice",
                    "ingredient": "rice",
                    "quantity": "1",
                    "unit": "cup",
                }
            ],
        },
        "social_video_audio_image",
    )

    assert result["servings"] == "4 servings"
    assert result["level"] == "Easy"
    assert result["total_time"] == "30 min"
    assert result["prep_time"] == "10 min"
    assert result["inactive_time"] == "0 min"
    assert result["cook_time"] == "20 min"


def test_youtube_audio_download_uses_android_player_client_by_default(monkeypatch):
    monkeypatch.delenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", raising=False)

    options = recipe_extract_service.build_ytdlp_options(
        "https://www.youtube.com/shorts/Xao87NNSfiM",
        download=True,
    )

    assert options["extractor_args"]["youtube"]["player_client"] == ["android"]


def test_youtube_player_client_can_be_configured(monkeypatch):
    monkeypatch.setenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", "android,web")

    options = recipe_extract_service.build_ytdlp_options(
        "https://www.youtube.com/shorts/Xao87NNSfiM",
        download=True,
    )

    assert options["extractor_args"]["youtube"]["player_client"] == ["android", "web"]


def test_youtube_player_client_can_be_disabled(monkeypatch):
    monkeypatch.setenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", "off")

    options = recipe_extract_service.build_ytdlp_options(
        "https://www.youtube.com/shorts/Xao87NNSfiM",
        download=True,
    )

    assert "extractor_args" not in options
