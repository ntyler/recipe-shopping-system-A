import argparse
import json
import os
import sys
from pathlib import Path

import openai


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from PushShoppingList.services.recipe_extract_service import build_vision_debug
from PushShoppingList.services.recipe_extract_service import call_openai_vision_image
from PushShoppingList.services.recipe_extract_service import normalize_image_bytes_for_openai


def main():
    parser = argparse.ArgumentParser(description="Test the app OpenAI Vision image path.")
    parser.add_argument("--image", required=True, help="Path to a local image file.")
    parser.add_argument("--model", default="", help="Optional model override, for example gpt-5.5.")
    parser.add_argument(
        "--prompt",
        default="Describe this food image briefly.",
        help="Prompt to send with the image.",
    )
    args = parser.parse_args()

    image_path = Path(args.image).expanduser()
    print(f"sys.executable = {sys.executable}")
    print(f"openai.__version__ = {getattr(openai, '__version__', '')}")
    print(f"openai.__file__ = {getattr(openai, '__file__', '')}")
    print(f"OPENAI_API_KEY present = {'yes' if bool(os.getenv('OPENAI_API_KEY')) else 'no'}")

    debug = build_vision_debug(uploaded_file_path=str(image_path), filename=image_path.name)
    try:
        image_bytes, output_mime, details = normalize_image_bytes_for_openai(image_path, debug=debug)
        print(
            "normalized_image = "
            + json.dumps(
                {
                    **details,
                    "output_mime": output_mime,
                    "output_bytes": len(image_bytes),
                },
                indent=2,
            )
        )
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error_code": "IMAGE_NORMALIZATION_FAILED",
            "error_message": "Image decode/conversion failure.",
            "technical_message": str(exc),
            "exception_type": type(exc).__name__,
        }, indent=2))
        return 1

    result = call_openai_vision_image(
        str(image_path),
        args.prompt,
        "debug_script_vision_image",
        preferred_model=args.model or None,
        debug=debug,
    )
    if result.ok:
        print(json.dumps({
            "ok": True,
            "model_used": result.model_used,
            "model_source": result.model_source,
            "fallback_used": result.fallback_used,
            "response_preview": result.text[:1200],
        }, indent=2))
        return 0

    print(json.dumps(result.to_dict(), indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
