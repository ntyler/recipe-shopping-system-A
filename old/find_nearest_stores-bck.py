"""
find_nearest_stores.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import tkinter as tk
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

import undetected_chromedriver as uc
from bs4 import BeautifulSoup


# =========================================================
# ADDRESS CONFIG
# =========================================================

address_street = "5905 Arlo Drive"
address_appartment = "Apt 2213"
address_city = "Indianapolis"
address_state = "IN"
address_zip = "46237"

full_address = f"{address_street}, {address_appartment}, {address_city}, {address_state} {address_zip}"


# =========================================================
# CONFIG
# =========================================================

CHROME_VERSION_MAIN = 147

SCRIPT_DIR = Path(__file__).resolve().parent
SHOPPING_STORES_FILE = SCRIPT_DIR / "PushShoppingList" / "shopping_stores.json"
AI_PROMPT_DIR = SCRIPT_DIR / "nearest_store_ai_prompts"
HTML_DIR = SCRIPT_DIR / "nearest_store_html"

DEFAULT_LOCATORS = {
    "meijer": "https://www.meijer.com/shopping/store-finder.html",
    "aldi": "https://info.aldi.us/stores",
    "kroger": "https://www.kroger.com/stores/search",
    "walmart": "https://www.walmart.com/store-finder",
    "target": "https://www.target.com/store-locator/find-stores",
    "costco": "https://www.costco.com/warehouse-locations",
}


# =========================================================
# DRIVER HELPERS
# =========================================================

def get_chrome_major_version() -> int:
    try:
        result = subprocess.check_output(
            r'reg query "HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon" /v version',
            shell=True,
        ).decode(errors="ignore")

        version_match = re.search(r"\d+\.\d+\.\d+\.\d+", result)
        if version_match:
            return int(version_match.group(0).split(".")[0])
    except Exception:
        pass

    return CHROME_VERSION_MAIN


def get_screen_size() -> tuple[int, int]:
    try:
        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return width, height
    except Exception:
        return 1600, 900


def build_driver(headless: bool = False):
    options = uc.ChromeOptions()

    primary_profile = r"C:\Users\Tyler\AppData\Local\Google\Chrome\User Data\Default"
##    fallback_profile = r"C:\ChromeProfiles\automation-profile"

    try:
        # ✅ Try using real Chrome profile first
        options.add_argument(f"--user-data-dir={primary_profile}")
##        options.add_argument("--profile-directory=Default")

        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")

        driver = uc.Chrome(
            options=options,
            headless=False,
            use_subprocess=True,
            version_main=get_chrome_major_version(),
        )

        print("✅ Using DEFAULT Chrome profile")
        return driver

    except Exception as e:
        print("⚠️ Default profile failed, switching to automation profile...")
        print(f"Reason: {e}")

        options = uc.ChromeOptions()

        # ✅ Fallback safe profile
        options.add_argument(f"--user-data-dir={fallback_profile}")

        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")

        driver = uc.Chrome(
            options=options,
            headless=False,
            use_subprocess=True,
            version_main=get_chrome_major_version(),
        )

        print("✅ Using FALLBACK automation profile")
        return driver


# =========================================================
# FILE HELPERS
# =========================================================

def load_stores() -> dict[str, Any]:
    if not SHOPPING_STORES_FILE.exists():
        raise FileNotFoundError(f"Could not find {SHOPPING_STORES_FILE}")

    data = json.loads(SHOPPING_STORES_FILE.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("shopping_stores.json must contain a JSON object.")

    return data


def save_stores(stores: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(
        json.dumps(stores, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def safe_filename(value: str) -> str:
    value = clean_text(value or "store")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = value.strip("_")
    return value or "store"


def save_full_html(driver, store_key: str) -> Path:
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    html_file = HTML_DIR / f"{safe_filename(store_key)}_locator_page.html"
    html_file.write_text(driver.page_source, encoding="utf-8")

    print(f"[{store_key}] Full HTML saved: {html_file}")
    return html_file


def save_visible_text(driver, store_key: str) -> Path:
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    text_file = HTML_DIR / f"{safe_filename(store_key)}_visible_text.txt"
    text_file.write_text(page_text(driver), encoding="utf-8")

    print(f"[{store_key}] Visible text saved: {text_file}")
    return text_file


def save_html_analysis_prompt(
    store_key: str,
    search_value: str,
    locator_results_url: str,
    html_file: Path,
    text_file: Path,
    candidates: list[dict[str, Any]],
) -> Path:
    AI_PROMPT_DIR.mkdir(parents=True, exist_ok=True)

    html = html_file.read_text(encoding="utf-8", errors="ignore")

    max_html_chars = 180000
    if len(html) > max_html_chars:
        html_for_prompt = html[:max_html_chars]
        html_note = f"HTML was truncated to first {max_html_chars} characters."
    else:
        html_for_prompt = html
        html_note = "HTML was not truncated."

    candidates_json = json.dumps(candidates[:50], indent=2, ensure_ascii=False)

    prompt = f"""
You are analyzing a grocery store locator HTML page.

GOAL:
Find the embedded store-detail hyperlink associated with the closest matching store result.

STORE:
{store_key}

SEARCH ADDRESS:
{search_value}

FULL ADDRESS TO COMPARE AGAINST:
{full_address}

LOCATOR RESULTS URL:
{locator_results_url}

LOCAL FULL HTML FILE:
{html_file}

LOCAL VISIBLE TEXT FILE:
{text_file}

HTML NOTE:
{html_note}

STRUCTURED CANDIDATES FOUND BY SCRIPT:
{candidates_json}

AI RULES:
- Return ONLY valid JSON.
- Do not include markdown.
- Use only the HTML, visible text, and structured candidates.
- Compare every candidate address found by AI/script against FULL ADDRESS TO COMPARE AGAINST.
- Pick the closest store result to FULL ADDRESS TO COMPARE AGAINST.
- Prefer the smallest displayed numeric distance in miles.
- If distance is missing, prefer the candidate matching the same ZIP, city, and state as FULL ADDRESS TO COMPARE AGAINST.
- closest_address must be the exact candidate address selected.
- The embedded hyperlink must be from the same card/container as closest_address.
- Do not return a hyperlink connected to a different address.
- Prefer links inside the same parent/card/container as the store name and address.
- Do not return search-page URLs unless no store-detail URL exists.
- If href is relative, resolve it using the locator website domain.
- If there are multiple links in the same store card, prefer:
  1. store detail link
  2. store name link
  3. view store details link
  4. directions link
- If a value is missing, use null.

EXPECTED JSON FORMAT:
{{
  "store": "{store_key}",
  "closest_store_name": null,
  "closest_address": null,
  "closest_distance": null,
  "closest_phone": null,
  "embedded_store_url": null,
  "link_text": null,
  "html_reason": null
}}

FULL HTML:
{html_for_prompt}
""".strip()

    prompt_file = AI_PROMPT_DIR / f"{safe_filename(store_key)}_html_analysis_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    print(f"[{store_key}] Full HTML AI analysis prompt saved: {prompt_file}")
    return prompt_file


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def page_text(driver) -> str:
    soup = BeautifulSoup(driver.page_source, "html.parser")
    return clean_text(soup.get_text(" ", strip=True))


def extract_distance(text: str) -> str | None:
    match = re.search(r"\b\d+(?:\.\d+)?\s*(?:mi|mile|miles)\b", text or "", flags=re.I)
    return match.group(0) if match else None


def distance_number(distance: str | None) -> float:
    if not distance:
        return 999999.0

    match = re.search(r"\d+(?:\.\d+)?", distance)
    if not match:
        return 999999.0

    try:
        return float(match.group(0))
    except Exception:
        return 999999.0


def extract_phone(text: str) -> str | None:
    match = re.search(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", text or "")
    return match.group(0) if match else None


def extract_address(text: str) -> str | None:
    patterns = [
        r"\d{1,6}\s+[A-Za-z0-9 .#'-]+,\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}",
        r"\d{1,6}\s+[A-Za-z0-9 .#'-]+\s+[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return clean_text(match.group(0))

    return None


def normalize_address(value: str | None) -> str:
    value = clean_text(value or "").lower()
    value = value.replace(".", "")
    value = value.replace(",", "")
    value = value.replace("#", " ")
    value = re.sub(r"\bapt\b", "apartment", value)
    value = re.sub(r"\bste\b", "suite", value)
    value = re.sub(r"\bst\b", "street", value)
    value = re.sub(r"\brd\b", "road", value)
    value = re.sub(r"\bdr\b", "drive", value)
    value = re.sub(r"\save\b", "avenue", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def address_similarity_score(candidate_address: str | None, target_address: str) -> int:
    candidate = normalize_address(candidate_address)
    target = normalize_address(target_address)

    if not candidate:
        return 9999

    score = 0

    target_zip = re.search(r"\b\d{5}\b", target)
    candidate_zip = re.search(r"\b\d{5}\b", candidate)

    if target_zip and candidate_zip and target_zip.group(0) != candidate_zip.group(0):
        score += 200
    elif target_zip and candidate_zip and target_zip.group(0) == candidate_zip.group(0):
        score -= 50

    if address_city.lower() not in candidate:
        score += 100
    else:
        score -= 25

    if address_state.lower() not in candidate:
        score += 50
    else:
        score -= 10

    target_words = set(target.split())
    candidate_words = set(candidate.split())

    shared = target_words & candidate_words
    missing = target_words - candidate_words

    score -= len(shared) * 5
    score += len(missing) * 2

    return score


def candidate_sort_key(item: dict[str, Any]) -> tuple[float, int, str]:
    return (
        distance_number(item.get("distance")),
        address_similarity_score(item.get("address"), full_address),
        normalize_address(item.get("address")),
    )


def sort_candidates_by_closest_address(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []

    for item in candidates:
        copied = dict(item)
        copied["address_compare_full_address"] = full_address
        copied["address_compare_distance_number"] = distance_number(copied.get("distance"))
        copied["address_compare_score"] = address_similarity_score(
            copied.get("address"),
            full_address,
        )
        enriched.append(copied)

    return sorted(enriched, key=candidate_sort_key)


def guess_store_name(store_key: str, text: str) -> str:
    store_labels = {
        "meijer": "Meijer",
        "aldi": "ALDI",
        "kroger": "Kroger",
        "walmart": "Walmart",
        "target": "Target",
        "costco": "Costco",
    }

    if store_key == "aldi":
        match = re.search(r"\bALDI\s+\d{1,6}\s+[A-Za-z0-9 .#'-]+", text or "", flags=re.I)
        if match:
            return clean_text(match.group(0))

    if store_key == "kroger":
        patterns = [
            r"Kroger\s+[A-Za-z0-9 &'#.-]+",
            r"Claybrooke Commons",
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "", flags=re.I)
            if match:
                return clean_text(match.group(0))

    if store_key == "walmart":
        match = re.search(
            r"(Walmart\s+(?:Supercenter|Neighborhood Market).*?)(?:\d{1,6}\s+)",
            text or "",
            flags=re.I,
        )
        if match:
            return clean_text(match.group(1))

    if store_key == "costco":
        return "Costco Wholesale"

    return store_labels.get(store_key, store_key.title())


# =========================================================
# DEBUG HELPERS
# =========================================================

def debug_page(driver, store_key: str) -> None:
    print(f"\n[{store_key}] Browser title: {driver.title}")
    print(f"[{store_key}] Current URL: {driver.current_url}")


def pause_for_review(enabled: bool, message: str) -> None:
    if enabled:
        input(f"\n{message}\nPress ENTER to continue...")


# =========================================================
# STORE LINK EXTRACTION
# =========================================================

def is_good_store_href(href: str, store_key: str) -> bool:
    href = str(href or "").strip()

    if not href:
        return False

    href_lower = href.lower()

    if href_lower.startswith("#"):
        return False

    if href_lower.startswith("javascript:"):
        return False

    if "mailto:" in href_lower or "tel:" in href_lower:
        return False

    if store_key == "aldi":
        return "/stores/" in href_lower

    if store_key == "kroger":
        return "/stores/details/" in href_lower

    if store_key == "meijer":
        return "store-finder" in href_lower or "/shopping/store/" in href_lower

    return True


def score_link_for_store(a, parent_text: str, store_key: str) -> int:
    href = str(a.get("href") or "")
    link_text = clean_text(a.get_text(" ", strip=True)).lower()
    href_lower = href.lower()
    parent_lower = parent_text.lower()

    score = 0

    if not is_good_store_href(href, store_key):
        return -999

    if store_key == "aldi":
        if "/stores/" in href_lower:
            score += 100
        if "/-/" in href_lower:
            score += 50
        if "directions" in link_text:
            score += 40
        if "aldi" in link_text:
            score += 30
        if "indianapolis" in href_lower:
            score += 20
        if "emerson" in href_lower:
            score += 20

    if store_key == "kroger":
        if "/stores/details/" in href_lower:
            score += 120
        if "view store details" in link_text:
            score += 80
        if "claybrooke" in link_text:
            score += 60
        if "kroger" in link_text:
            score += 30
        if "details" in href_lower:
            score += 30

    if "directions" in link_text:
        score += 25

    if "details" in link_text:
        score += 25

    if extract_address(parent_text):
        score += 20

    if "closed now" in parent_lower or "open" in parent_lower:
        score += 10

    return score


def find_best_embedded_link(parent, store_key: str, base_url: str) -> tuple[str | None, str | None]:
    parent_text = clean_text(parent.get_text(" ", strip=True))

    links = []

    for a in parent.find_all("a", href=True):
        href = str(a.get("href") or "").strip()

        if not is_good_store_href(href, store_key):
            continue

        score = score_link_for_store(a, parent_text, store_key)

        links.append(
            {
                "score": score,
                "href": href,
                "text": clean_text(a.get_text(" ", strip=True)),
            }
        )

    if not links:
        return None, None

    links = sorted(links, key=lambda item: item["score"], reverse=True)
    best = links[0]

    return urljoin(base_url, best["href"]), best["text"]


def find_store_card_parent(tag):
    parent = tag

    for _ in range(14):
        if parent is None:
            break

        parent_text = clean_text(parent.get_text(" ", strip=True))

        has_address = bool(extract_address(parent_text))
        has_link = bool(parent.find("a", href=True))
        has_store_signals = any(
            signal in parent_text.lower()
            for signal in [
                "directions",
                "closed now",
                "open now",
                "opens at",
                "store hours",
                "view store details",
                "open until",
                "miles",
            ]
        )

        if has_address and has_link and has_store_signals:
            return parent

        parent = parent.parent

    return tag.parent if tag else None


def extract_store_links_with_context(driver, store_key: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(driver.page_source, "html.parser")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    address_tags = []

    for tag in soup.find_all(True):
        tag_text = clean_text(tag.get_text(" ", strip=True))

        if extract_address(tag_text):
            address_tags.append(tag)

    for tag in address_tags:
        try:
            address = extract_address(clean_text(tag.get_text(" ", strip=True)))

            if not address:
                continue

            parent = find_store_card_parent(tag)

            if not parent:
                continue

            context = clean_text(parent.get_text(" ", strip=True))
            distance = extract_distance(context)
            phone = extract_phone(context)

            url, link_text = find_best_embedded_link(
                parent=parent,
                store_key=store_key,
                base_url=base_url,
            )

            key = f"{normalize_address(address)}|{distance}|{url}"

            if key in seen:
                continue

            seen.add(key)

            candidates.append(
                {
                    "store": store_key,
                    "store_name_guess": guess_store_name(store_key, context),
                    "address": address,
                    "distance": distance,
                    "phone": phone,
                    "url": url,
                    "link_text": link_text,
                    "context": context[:1500],
                }
            )

        except Exception:
            continue

    return sort_candidates_by_closest_address(candidates)


def extract_direct_store_links(driver, store_key: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(driver.page_source, "html.parser")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()

        if not is_good_store_href(href, store_key):
            continue

        parent = a

        for _ in range(14):
            if parent is None:
                break

            parent_text = clean_text(parent.get_text(" ", strip=True))

            if extract_address(parent_text):
                break

            parent = parent.parent

        if not parent:
            continue

        context = clean_text(parent.get_text(" ", strip=True))
        address = extract_address(context)

        if not address:
            continue

        url = urljoin(base_url, href)

        key = f"{normalize_address(address)}|{url}"

        if key in seen:
            continue

        seen.add(key)

        candidates.append(
            {
                "store": store_key,
                "store_name_guess": guess_store_name(store_key, context),
                "address": address,
                "distance": extract_distance(context),
                "phone": extract_phone(context),
                "url": url,
                "link_text": clean_text(a.get_text(" ", strip=True)),
                "context": context[:1500],
            }
        )

    return sort_candidates_by_closest_address(candidates)


def merge_candidates(*candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for group in candidate_groups:
        for item in group:
            key = f"{normalize_address(item.get('address'))}|{item.get('url')}"

            if key in seen:
                continue

            seen.add(key)
            merged.append(item)

    return sort_candidates_by_closest_address(merged)


def extract_nearest_from_candidates(
    store_key: str,
    candidates: list[dict[str, Any]],
    fallback_text: str,
    current_url: str,
) -> dict[str, Any]:
    candidates = sort_candidates_by_closest_address(candidates)

    if candidates:
        best = candidates[0]

        return {
            "pickup_store_name": best.get("store_name_guess") or guess_store_name(store_key, best.get("context", "")),
            "pickup_address": best.get("address"),
            "pickup_distance": best.get("distance"),
            "pickup_phone": best.get("phone"),
            "pickup_store_url": best.get("url"),
            "pickup_store_context": best.get("context"),
            "pickup_address_compare_full_address": full_address,
            "pickup_address_compare_score": best.get("address_compare_score"),
            "pickup_address_compare_distance_number": best.get("address_compare_distance_number"),
            "locator_results_url": current_url,
            "store_candidates": candidates,
        }

    return {
        "pickup_store_name": guess_store_name(store_key, fallback_text),
        "pickup_address": extract_address(fallback_text),
        "pickup_distance": extract_distance(fallback_text),
        "pickup_phone": extract_phone(fallback_text),
        "pickup_store_url": None,
        "pickup_store_context": fallback_text[:1500],
        "pickup_address_compare_full_address": full_address,
        "pickup_address_compare_score": address_similarity_score(extract_address(fallback_text), full_address),
        "pickup_address_compare_distance_number": distance_number(extract_distance(fallback_text)),
        "locator_results_url": current_url,
        "store_candidates": [],
    }


# =========================================================
# AI PROMPT HELPERS
# =========================================================

def build_closest_store_ai_prompt(
    store_key: str,
    search_value: str,
    locator_url: str,
    webpage_text: str,
    candidates: list[dict[str, Any]],
    html_file: Path | None = None,
    text_file: Path | None = None,
) -> str:
    webpage_text = clean_text(webpage_text)

    if len(webpage_text) > 12000:
        webpage_text = webpage_text[:12000]

    candidates = sort_candidates_by_closest_address(candidates)
    candidates_json = json.dumps(candidates[:50], indent=2, ensure_ascii=False)

    return f"""
You are helping choose the closest pickup store.

STORE:
{store_key}

SEARCH ADDRESS OR ZIP:
{search_value}

FULL ADDRESS TO COMPARE AGAINST:
{full_address}

LOCATOR RESULTS URL:
{locator_url}

LOCAL FULL HTML FILE:
{html_file}

LOCAL VISIBLE TEXT FILE:
{text_file}

STRUCTURED STORE CANDIDATES:
{candidates_json}

WEBPAGE RESULTS TEXT:
{webpage_text}

Return ONLY valid JSON.

Pick the closest store from the webpage results.

Required JSON format:
{{
  "store": "{store_key}",
  "closest_store_name": null,
  "closest_address": null,
  "closest_distance": null,
  "closest_phone": null,
  "closest_store_url": null,
  "reason": null
}}

Rules:
- Use only information from the structured candidates, webpage results text, and saved HTML.
- Compare every candidate address against FULL ADDRESS TO COMPARE AGAINST.
- Prefer STRUCTURED STORE CANDIDATES when available.
- If multiple stores are listed, choose the one with the smallest displayed numeric distance in miles.
- If distance is missing or tied, choose the address that best matches the same ZIP, city, and state as FULL ADDRESS TO COMPARE AGAINST.
- closest_address must be the exact candidate address chosen.
- closest_store_url must be the embedded candidate URL associated with the chosen address.
- The embedded URL must come from the same card/container as the selected address.
- Do not return a store URL connected to a different address.
- If a value is missing, use null.
- Return only valid JSON.
""".strip()


def save_ai_prompt(store_key: str, prompt: str) -> Path:
    AI_PROMPT_DIR.mkdir(parents=True, exist_ok=True)

    prompt_file = AI_PROMPT_DIR / f"{safe_filename(store_key)}_nearest_store_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    return prompt_file


# =========================================================
# LOCATOR URL BUILDING
# =========================================================

def get_locator_search_value(store_key: str, stores: dict[str, Any]) -> tuple[str, str]:
    locator_search_by = (
        stores.get(store_key, {}).get("locator_search_by")
        or "Zip Code"
    )

    if locator_search_by == "Full Address":
        return locator_search_by, full_address

    if locator_search_by == "Zip Code":
        return locator_search_by, address_zip

    return locator_search_by, address_zip


def build_locator_results_url(store_key: str, locator_url: str, search_value: str) -> str:
    if store_key == "kroger":
        return f"{locator_url}?searchText={quote_plus(search_value)}"

    if store_key == "aldi":
        return f"{locator_url}/?q={quote_plus(search_value)}"

    return f"{locator_url}/{quote_plus(search_value)}"


# =========================================================
# MAIN LOCATOR LOGIC
# =========================================================

def search_locator(
    driver,
    store_key: str,
    stores: dict[str, Any],
    debug: bool = False,
    pause: bool = False,
    wait_seconds: float = 12.0,
) -> dict[str, Any]:
    locator_url = (
        stores.get(store_key, {}).get("locator_url")
        or DEFAULT_LOCATORS.get(store_key)
    )

    if not locator_url:
        return {
            "ok": False,
            "error": f"No locator URL configured for {store_key}",
        }

    locator_search_by, search_value = get_locator_search_value(store_key, stores)
    locator_results_url = build_locator_results_url(store_key, locator_url, search_value)

    print(f"\n[{store_key}] Opening locator results: {locator_results_url}")
    print(f"[{store_key}] Searching by {locator_search_by}: {search_value}")
    print(f"[{store_key}] Comparing candidate addresses against: {full_address}")

    driver.get(locator_results_url)
    time.sleep(wait_seconds)

    debug_page(driver, store_key)

    html_file = save_full_html(driver, store_key)
    text_file = save_visible_text(driver, store_key)

    pause_for_review(
        pause,
        f"[{store_key}] Page loaded. Review the browser before extraction.",
    )

    text = page_text(driver)

    candidates = extract_store_links_with_context(
        driver=driver,
        store_key=store_key,
        base_url=locator_url,
    )

    direct_candidates = extract_direct_store_links(
        driver=driver,
        store_key=store_key,
        base_url=locator_url,
    )

    candidates = merge_candidates(candidates, direct_candidates)

    html_analysis_prompt_file = save_html_analysis_prompt(
        store_key=store_key,
        search_value=search_value,
        locator_results_url=locator_results_url,
        html_file=html_file,
        text_file=text_file,
        candidates=candidates,
    )

    prompt = build_closest_store_ai_prompt(
        store_key=store_key,
        search_value=search_value,
        locator_url=locator_results_url,
        webpage_text=text,
        candidates=candidates,
        html_file=html_file,
        text_file=text_file,
    )

    prompt_file = save_ai_prompt(store_key, prompt)

    print(f"[{store_key}] AI prompt saved: {prompt_file}")
    print(f"[{store_key}] HTML AI analysis prompt saved: {html_analysis_prompt_file}")
    print(f"[{store_key}] Candidate store links found: {len(candidates)}")

    if debug:
        print(f"[{store_key}] Candidates sorted by closest address/distance:")
        print(json.dumps(candidates[:20], indent=2, ensure_ascii=False))

    nearest = extract_nearest_from_candidates(
        store_key=store_key,
        candidates=candidates,
        fallback_text=text,
        current_url=driver.current_url,
    )

    ok = bool(
        nearest.get("pickup_address")
        or nearest.get("pickup_distance")
        or nearest.get("pickup_store_url")
    )

    return {
        "ok": ok,
        "locator_search_by": locator_search_by,
        "locator_search_value": search_value,
        "locator_base_url": locator_url,
        "locator_results_url": locator_results_url,
        "html_file": str(html_file),
        "visible_text_file": str(text_file),
        "ai_prompt_file": str(prompt_file),
        "html_analysis_prompt_file": str(html_analysis_prompt_file),
        **nearest,
    }


def update_store_record(
    stores: dict[str, Any],
    store_key: str,
    nearest: dict[str, Any],
) -> None:
    store = stores.setdefault(store_key, {})

    store["pickup_zip"] = address_zip
    store["pickup_full_address"] = full_address

    fields = [
        "locator_search_by",
        "locator_search_value",
        "locator_base_url",
        "locator_results_url",
        "html_file",
        "visible_text_file",
        "ai_prompt_file",
        "html_analysis_prompt_file",
        "pickup_store_name",
        "pickup_address",
        "pickup_distance",
        "pickup_phone",
        "pickup_store_url",
        "pickup_store_context",
        "pickup_address_compare_full_address",
        "pickup_address_compare_score",
        "pickup_address_compare_distance_number",
        "store_candidates",
    ]

    for field in fields:
        if nearest.get(field) is not None:
            target_field = "locator_url" if field == "locator_base_url" else field
            store[target_field] = nearest[field]

    store["nearest_lookup_ok"] = bool(nearest.get("ok"))
    store["nearest_lookup_error"] = nearest.get("error")


# =========================================================
# MAIN
# =========================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find nearest pickup stores and update shopping_stores.json."
    )

    parser.add_argument(
        "--stores",
        nargs="*",
        help="Optional store keys to update, like meijer aldi walmart.",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chrome window.",
    )

    parser.add_argument(
        "--pause",
        action="store_true",
        help="Pause after each locator page loads so you can inspect the browser.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print detected candidate store cards.",
    )

    parser.add_argument(
        "--wait",
        type=float,
        default=12.0,
        help="Seconds to wait after opening each locator page.",
    )

    parser.add_argument(
        "--output",
        default=str(SHOPPING_STORES_FILE),
        help="Output JSON file.",
    )

    args = parser.parse_args()

    print(f"Full address: {full_address}")

    stores = load_stores()

    selected_store_keys = args.stores or list(stores.keys())
    selected_store_keys = [
        str(store).strip().lower()
        for store in selected_store_keys
        if str(store).strip().lower() in stores
    ]

    if not selected_store_keys:
        print("No matching stores found in shopping_stores.json.")
        return 1

    driver = build_driver(headless=False)

    try:
        for store_key in selected_store_keys:
            try:
                nearest = search_locator(
                    driver=driver,
                    store_key=store_key,
                    stores=stores,
                    debug=args.debug,
                    pause=args.pause,
                    wait_seconds=args.wait,
                )

                update_store_record(
                    stores=stores,
                    store_key=store_key,
                    nearest=nearest,
                )

                status = "✅" if nearest.get("ok") else "⚠️"
                print(f"{status} {store_key}:")
                print(json.dumps(nearest, indent=2, ensure_ascii=False))

                pause_for_review(
                    args.pause,
                    f"[{store_key}] Extraction complete. Review before moving to the next store.",
                )

            except Exception as exc:
                print(f"❌ {store_key}: {exc}")

                update_store_record(
                    stores=stores,
                    store_key=store_key,
                    nearest={
                        "ok": False,
                        "error": str(exc),
                    },
                )

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    output_path = Path(args.output)
    save_stores(stores, output_path)

    print(f"\nUpdated: {output_path}")
    print(f"HTML saved in: {HTML_DIR}")
    print(f"AI prompts saved in: {AI_PROMPT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
