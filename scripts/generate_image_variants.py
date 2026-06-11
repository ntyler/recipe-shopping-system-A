from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PushShoppingList.services.image_variant_service import IMAGE_VARIANTS
from PushShoppingList.services.image_variant_service import STATIC_DIR
from PushShoppingList.services.image_variant_service import ensure_webp_variants


SUPPORTED_EXTENSIONS = {".avif", ".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def source_images(root):
    for path in root.rglob("*"):
        if not path.is_file():
            continue

        lower_name = path.name.lower()
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if any(lower_name.endswith(f"__{variant}.webp") for variant in IMAGE_VARIANTS):
            continue

        yield path


def main():
    root = STATIC_DIR / "generated"
    count = 0
    variants = 0

    for image_path in source_images(root):
        count += 1
        variants += len(ensure_webp_variants(image_path))

    print(f"images={count} variants_ready={variants} root={root}")


if __name__ == "__main__":
    main()
