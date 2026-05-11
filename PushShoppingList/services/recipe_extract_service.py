import json
import os
import re

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


def clean_text(value):
    return re.sub(r"\\s+", " ", str(value or "")).strip()


def fetch_recipe_page_html(recipe_url):
    response = requests.get(
        recipe_url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            )
        },
    )

    response.raise_for_status()

    return response.text


def simplify_html(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup([
        "script",
        "style",
        "svg",
        "noscript",
        "iframe",
    ]):
        tag.decompose()

    text = soup.get_text("\n")

    text = re.sub(r"\\s+", " ", text)

    return text[:40000]


def extract_json(text):
    text = text.strip()

    text = (
        text
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )

    start = text.find("{")
    end = text.rfind("}")

    return json.loads(text[start:end + 1])


def ask_chatgpt_to_extract(recipe_url, html_text):
    prompt = f"""
Extract recipe ingredients from webpage text.

Return strict JSON only.

WEBPAGE TEXT:
{html_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        timeout=60,
    )

    text = response.choices[0].message.content

    return extract_json(text)


def extract_recipe_from_url(recipe_url):
    html = fetch_recipe_page_html(recipe_url)

    cleaned_text = simplify_html(html)

    return ask_chatgpt_to_extract(
        recipe_url,
        cleaned_text,
    )
