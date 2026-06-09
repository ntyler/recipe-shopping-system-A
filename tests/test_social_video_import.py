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
          "display_name": "Green Enchiladas",
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
            {"step_number": 1, "instruction": "Warm the tortillas, fill them with jackfruit and white beans, cover with green enchilada sauce, and bake until bubbly.", "equipment_used": []}
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
    assert result["display_name"] == "Green Enchiladas"
    assert result["ingredients"] == ["green enchilada sauce", "tortillas"]
    assert result["servings"] == "4 servings"
    assert result["level"] == "Easy"
    assert result["total_time"] == "35 min"
    assert result["nutrition"]["serving_basis"] == "per serving (estimated)"
    assert "Audio transcript" in calls["prompt"]
    assert "jackfruit" in calls["prompt"]
    assert calls["image_urls"]


def test_social_video_audio_image_uses_video_frame_cover_when_metadata_thumbnail_missing(tmp_path, monkeypatch):
    recipe_url = "https://www.youtube.com/shorts/frameOnly"
    extractor_folder = tmp_path / "extractor"
    raw_folder = extractor_folder / "data" / "raw"
    raw_folder.mkdir(parents=True)
    frame_path = raw_folder / "frameOnly_TITLE_FRAME.jpg"
    frame_path.write_bytes(b"fake-jpeg")
    frame_cover = {
        "path": "data/raw/frameOnly_TITLE_FRAME.jpg",
        "mime_type": "image/jpeg",
        "alt": "Frame-only pasta",
        "source": "video_frame",
    }
    calls = {}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(recipe_extract_service, "EXTRACTOR_FOLDER", extractor_folder)
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", raw_folder)
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_ytdlp_info",
        lambda url: {
            "title": "Frame-only pasta",
            "description": "",
            "duration": 20,
            "thumbnail": None,
            "thumbnails": [],
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_social_video_frame_cover_image",
        lambda url, info=None: frame_cover,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "transcribe_social_video_audio",
        lambda url, info, progress_callback=None: "Layer pasta with tomato sauce and cheese.",
    )

    def fake_audio_image_openai(prompt, image_urls):
        calls["image_urls"] = image_urls
        return """
        {
          "source_url": "https://www.youtube.com/shorts/frameOnly",
          "display_name": "Frame-only Pasta",
          "recipe_title": "Frame-only Pasta",
          "ingredients": [
            {"original_text": "8 ounces pasta", "ingredient": "pasta", "quantity": "8", "unit": "ounces"}
          ],
          "equipment": [],
          "instructions": [
            {"step_number": 1, "instruction": "Layer pasta with sauce and cheese, then bake until hot.", "equipment_used": []}
          ],
          "nutrition": {"other": []}
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

    result = recipe_extract_service.extract_recipe_from_social_video_audio_images(recipe_url)

    assert result["ok"] is True
    assert result["cover_image"]["source"] == "video_frame"
    assert result["raw"]["cover_image"]["path"] == "data/raw/frameOnly_TITLE_FRAME.jpg"
    assert calls["image_urls"][0].startswith("data:image/jpeg;base64,")


def test_social_video_audio_image_repairs_missing_ingredient_amounts(tmp_path, monkeypatch):
    recipe_url = "https://www.youtube.com/shorts/blankAmounts"
    raw_folder = tmp_path / "raw"
    raw_folder.mkdir(parents=True)
    responses = []
    saved = {}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", raw_folder)
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_ytdlp_info",
        lambda url: {
            "title": "Baked stuffed pasta",
            "description": "",
            "duration": 30,
            "thumbnail": "https://img.youtube.com/vi/blankAmounts/hqdefault.jpg",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "transcribe_social_video_audio",
        lambda url, info, progress_callback=None: "Add cherry tomatoes, mozzarella balls, basil, and marinara to pasta.",
    )

    api_responses = [
        """
        {
          "source_url": "https://www.youtube.com/shorts/blankAmounts",
          "display_name": "Baked Stuffed Pasta",
          "recipe_title": "Baked Stuffed Pasta",
          "ingredients": [
            {"original_text": "small cherry tomatoes", "ingredient": "cherry tomato", "quantity": null, "unit": null},
            {"original_text": "small mozzarella balls", "ingredient": "mozzarella ball", "quantity": null, "unit": null}
          ],
          "equipment": [],
          "instructions": [
            {"step_number": 1, "instruction": "Fill the pasta with tomatoes, mozzarella, basil, and marinara, then bake until hot.", "equipment_used": []}
          ],
          "nutrition": {"other": []}
        }
        """,
        """
        {
          "source_url": "https://www.youtube.com/shorts/blankAmounts",
          "display_name": "Baked Stuffed Pasta",
          "recipe_title": "Baked Stuffed Pasta",
          "ingredients": [
            {"original_text": "1 cup small cherry tomatoes", "ingredient": "cherry tomato", "quantity": "1", "unit": "cup", "base_quantity": "1", "base_unit": "cup", "recipe_qty": "1"},
            {"original_text": "8 ounces small mozzarella balls", "ingredient": "mozzarella ball", "quantity": "8", "unit": "ounces", "base_quantity": "8", "base_unit": "ounces", "recipe_qty": "8"}
          ],
          "equipment": [],
          "instructions": [
            {"step_number": 1, "instruction": "Fill the pasta with tomatoes, mozzarella, basil, and marinara, then bake until hot.", "equipment_used": []}
          ],
          "nutrition": {"other": []}
        }
        """,
    ]

    def fake_audio_image_openai(prompt, image_urls):
        responses.append(prompt)
        return api_responses.pop(0)

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
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda url, data: saved.update({"url": url, "data": data}),
    )

    result = recipe_extract_service.extract_recipe_from_social_video_audio_images(recipe_url)

    assert result["ok"] is True
    assert len(responses) == 2
    assert "some ingredient quantities are still blank" in responses[1]
    assert result["raw"]["ingredients"][0]["quantity"] == "1"
    assert result["raw"]["ingredients"][0]["unit"] == "cup"
    assert result["raw"]["ingredients"][1]["quantity"] == "8"
    assert result["raw"]["ingredients"][1]["unit"] == "ounces"
    assert saved["data"]["ingredients"][0]["base_quantity"] == "1"


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
        "extract_recipe_from_social_video_audio_images",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_video_recipe_pdf_data_with_openai",
        lambda url, text, progress_callback=None: {
            "source_url": url,
            "display_name": "Simple Pasta",
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
    assert result["display_name"] == "Simple Pasta"
    assert result["servings"] == "2 servings"
    assert result["level"] == "Easy"
    assert result["nutrition"]["serving_basis"] == "per serving (estimated)"
    assert saved["data"]["cover_image"] == cover_image
    assert archived["kwargs"]["structured_recipe_data"]["servings"] == "2 servings"
    assert archived["kwargs"]["prefer_openai"] is False


def test_social_video_text_openai_result_uses_audio_images_when_editor_fields_are_thin(monkeypatch):
    recipe_url = "https://www.youtube.com/shorts/thinRecipe"
    page_text = "Title: New way to make dinner\n\nDescription: Watch this."
    audio_image_called = {}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        recipe_extract_service,
        "fetch_social_video_text",
        lambda url, progress_callback=None: ("<html></html>", page_text),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_recipe_cover_image_from_html",
        lambda html_text, url: {},
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "has_meaningful_social_video_text",
        lambda text: True,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_recipe_from_social_video_text",
        lambda url, text: None,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "send_prompt_to_openai",
        lambda prompt: """
        {
          "source_url": "https://www.youtube.com/shorts/thinRecipe",
          "recipe_title": "New way to make dinner",
          "ingredients": [
            {"original_text": "ground beef sauce", "ingredient": "ground beef sauce", "quantity": null, "unit": null},
            {"original_text": "heavy cream", "ingredient": "heavy cream", "quantity": null, "unit": null}
          ],
          "equipment": [],
          "instructions": [
            {"step_number": 1, "instruction": "Add ingredients.", "equipment_used": []}
          ],
          "nutrition": {"other": []}
        }
        """,
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "save_json_response",
        lambda url, response_text, html_text=None: (True, recipe_extract_service.json.loads(response_text)),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "archive_social_video_text_pdf",
        lambda *args, **kwargs: None,
    )

    def fake_audio_image(url, page_text="", cover_image=None, progress_callback=None):
        audio_image_called["page_text"] = page_text
        return {
            "ok": True,
            "source_url": url,
            "display_name": "Creamy Beef Pasta Bake",
            "recipe_title": "Creamy Beef Pasta Bake",
            "servings": "4 servings",
            "level": "Easy",
            "total_time": "1 hr",
            "prep_time": "15 min",
            "inactive_time": "0 min",
            "cook_time": "45 min",
            "ingredients": ["ground beef", "heavy cream"],
            "raw": {},
            "extraction_method": "social_video_audio_image",
        }

    monkeypatch.setattr(
        recipe_extract_service,
        "extract_recipe_from_social_video_audio_images",
        fake_audio_image,
    )

    result = recipe_extract_service.extract_recipe_from_social_video_url(recipe_url)

    assert result["extraction_method"] == "social_video_audio_image"
    assert result["display_name"] == "Creamy Beef Pasta Bake"
    assert audio_image_called["page_text"] == page_text


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
    assert "Do not leave quantity blank" in prompt
    assert "Fill display_name with a short, card-friendly recipe name" in prompt
    assert "create the likely missing steps" in prompt


def test_video_text_pdf_includes_title_image_and_estimated_recipe_metadata():
    pdf_html = recipe_extract_service.build_video_text_pdf_html(
        "https://www.youtube.com/shorts/Xao87NNSfiM",
        "",
        recipe_data={
            "recipe_title": "Video Lasagna",
            "display_name": "Video Lasagna",
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
    assert result["display_name"] == "Quick Dinner"
    assert result["level"] == "Easy"
    assert result["total_time"] == "30 min"
    assert result["prep_time"] == "10 min"
    assert result["inactive_time"] == "0 min"
    assert result["cook_time"] == "20 min"


def test_recipe_info_defaults_fill_editor_metadata_fields():
    recipe_data = {
        "recipe_title": "Pan Dinner",
        "ingredients": [
            {
                "original_text": "1 cup rice",
                "ingredient": "rice",
                "quantity": "1",
                "unit": "cup",
            }
        ],
        "instructions": [{"step_number": 1, "instruction": "Cook the rice and serve."}],
    }

    recipe_extract_service.apply_recipe_info_metadata(recipe_data)
    recipe_extract_service.apply_recipe_scaling_metadata(recipe_data)

    assert recipe_data["servings"] == "4 servings"
    assert recipe_data["level"] == "Easy"
    assert recipe_data["total_time"] == "45 min"
    assert recipe_data["prep_time"] == "15 min"
    assert recipe_data["inactive_time"] == "0 min"
    assert recipe_data["cook_time"] == "30 min"
    assert recipe_data["scaling"]["base_servings"] == "4 servings"


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
