from pathlib import Path

from PIL import Image

from PushShoppingList.services import image_variant_service


def test_local_static_image_variants_create_webp_files(monkeypatch, tmp_path):
    static_dir = tmp_path / "static"
    image_dir = static_dir / "generated" / "recipe_steps"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "demo.png"
    Image.new("RGB", (1200, 800), color=(30, 120, 200)).save(image_path)

    monkeypatch.setattr(image_variant_service, "STATIC_DIR", static_dir)

    variants = image_variant_service.local_static_image_variants(
        "/static/generated/recipe_steps/demo.png"
    )

    assert variants["thumb_url"] == "/static/generated/recipe_steps/demo__thumb.webp"
    assert variants["card_url"] == "/static/generated/recipe_steps/demo__card.webp"
    assert variants["detail_url"] == "/static/generated/recipe_steps/demo__detail.webp"
    assert "240w" in variants["srcset"]
    assert "640w" in variants["srcset"]
    assert image_path.exists()
    assert (image_dir / "demo__thumb.webp").is_file()
    assert (image_dir / "demo__card.webp").is_file()
    assert (image_dir / "demo__detail.webp").is_file()


def test_local_static_image_variants_ignore_non_static_urls(monkeypatch, tmp_path):
    monkeypatch.setattr(image_variant_service, "STATIC_DIR", tmp_path / "static")

    assert image_variant_service.local_static_image_variants("https://example.com/photo.jpg") == {}
    assert image_variant_service.local_static_image_variants("/not-static/photo.jpg") == {}
