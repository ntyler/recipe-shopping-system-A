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
          "servings": null,
          "ingredients": [
            {"original_text": "green enchilada sauce", "ingredient": "green enchilada sauce", "quantity": null, "unit": null},
            {"original_text": "tortillas", "ingredient": "tortillas", "quantity": null, "unit": null}
          ],
          "equipment": [],
          "instructions": [
            {"step_number": 1, "instruction": "Fill tortillas and bake until bubbly.", "equipment_used": []}
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

    result = recipe_extract_service.extract_recipe_from_social_video_url(recipe_url)

    assert result["ok"] is True
    assert result["extraction_method"] == "social_video_audio_image"
    assert result["ingredients"] == ["green enchilada sauce", "tortillas"]
    assert "Audio transcript" in calls["prompt"]
    assert "jackfruit" in calls["prompt"]
    assert calls["image_urls"]


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
