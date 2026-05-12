import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "downloaded_recipe_html"
OUTPUT_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_filename(url):
    name = re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_")
    return name[:120] or "recipe"


def download_recipe_html(recipe_url):
    response = requests.get(
        recipe_url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        },
    )
    response.raise_for_status()

    html = response.text

    html_path = OUTPUT_DIR / f"{safe_filename(recipe_url)}.html"
    html_path.write_text(html, encoding="utf-8")

    return html, html_path


def html_to_page_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "svg", "noscript", "iframe"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text[:40000]


def extract_json(text):
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("ChatGPT did not return JSON.")

    return json.loads(text[start:end + 1])


def ask_chatgpt_to_extract(recipe_url, page_text):
    prompt = f"""
Extract recipe ingredients from this webpage text.

Return STRICT JSON only.

Format:
{{
  "recipe_title": "",
  "source_url": "{recipe_url}",
  "ingredients": [
    {{
      "quantity": "",
      "unit": "",
      "ingredient": "",
      "preparation": "",
      "original_text": "",
      "store_section": ""
    }}
  ]
}}

WEBPAGE TEXT:
{page_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        timeout=60,
    )

    return extract_json(response.choices[0].message.content)


def extract_recipe_from_url(recipe_url):
    recipe_url = clean_text(recipe_url)

    if not recipe_url:
        return {"ok": False, "error": "Missing recipe URL.", "ingredients": []}

    try:
        html, html_path = download_recipe_html(recipe_url)
        page_text = html_to_page_text(html)
        data = ask_chatgpt_to_extract(recipe_url, page_text)

        ingredients = []
        for item in data.get("ingredients", []):
            if isinstance(item, dict):
                ingredients.append(
                    clean_text(item.get("original_text") or item.get("ingredient"))
                )

        ingredients = [x for x in ingredients if x]

        return {
            "ok": True,
            "source_url": recipe_url,
            "html_file": str(html_path),
            "recipe_title": data.get("recipe_title", ""),
            "ingredients": ingredients,
            "raw": data,
        }

    except Exception as exc:
        return {
            "ok": False,
            "source_url": recipe_url,
            "error": str(exc),
            "ingredients": [],
        }