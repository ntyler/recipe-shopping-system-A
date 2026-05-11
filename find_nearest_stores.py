import json
import math
import os
import re
import time
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from openai import OpenAI


# =========================================================
# CONFIG
# =========================================================

HEADLESS = True

SCRIPT_DIR = Path(__file__).resolve().parent
STORES_FILE = SCRIPT_DIR / "PushShoppingList" / "shopping_stores.json"
OUTPUT_FILE = SCRIPT_DIR / "PushShoppingList" / "shopping_stores_Results.json"

MAX_WORKER_LIMIT = 8

ADDRESS_STREET = "5905 Arlo Drive"
ADDRESS_APARTMENT = "Apt 2213"
ADDRESS_CITY = "Indianapolis"
ADDRESS_STATE = "IN"
ADDRESS_ZIP = "46237"

FULL_ADDRESS = (
    f"{ADDRESS_STREET} {ADDRESS_APARTMENT}, "
    f"{ADDRESS_CITY}, {ADDRESS_STATE} {ADDRESS_ZIP}"
)

OPENAI_MODEL = "gpt-4o-mini"


# =========================================================
# STORE CONFIG
# =========================================================

def load_stores():
    if not STORES_FILE.exists():
        raise FileNotFoundError(f"Missing file: {STORES_FILE}")

    data = json.loads(STORES_FILE.read_text(encoding="utf-8"))

    stores = {}

    for key, value in data.items():
        stores[key] = {
            "label": value.get("label", key),
            "url": value.get("url"),
        }

    return stores


# =========================================================
# DRIVER
# =========================================================

def build_driver(headless=HEADLESS):
    options = uc.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")

    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    driver = uc.Chrome(
        options=options,
        headless=headless,
        use_subprocess=True,
    )

    driver.set_page_load_timeout(60)
    return driver


# =========================================================
# HELPERS
# =========================================================

def clean_text(value):
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


def maps_search_url(query):
    return f"https://www.google.com/maps/search/{urllib.parse.quote_plus(query)}"


def build_product_search_url(template, query):
    if not template:
        return None
    return template + urllib.parse.quote_plus(query)


def extract_lat_lng_from_url(url):
    patterns = [
        r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return {
                "lat": float(match.group(1)),
                "lng": float(match.group(2)),
            }

    return None


def haversine_miles(lat1, lng1, lat2, lng2):
    radius = 3958.8

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )

    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def safe_text(driver, xpath):
    try:
        return clean_text(driver.find_element(By.XPATH, xpath).text)
    except Exception:
        return None


def safe_attr(driver, xpath, attr):
    try:
        return driver.find_element(By.XPATH, xpath).get_attribute(attr)
    except Exception:
        return None


def safe_json_loads(text):
    if not text:
        raise ValueError("Empty AI response")

    text = text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    return json.loads(text)


# =========================================================
# GOOGLE MAPS
# =========================================================

def get_home_coordinates():
    driver = build_driver()

    try:
        print(f"\n🏠 Getting home coordinates for: {FULL_ADDRESS}")

        driver.get(maps_search_url(FULL_ADDRESS))
        time.sleep(6)

        coords = extract_lat_lng_from_url(driver.current_url)

        if not coords:
            time.sleep(4)
            coords = extract_lat_lng_from_url(driver.current_url)

        if not coords:
            raise RuntimeError("Failed to get home coordinates from Google Maps URL.")

        print(f"✅ Home coordinates: {coords}")
        return coords

    finally:
        driver.quit()


def collect_place_links(driver):
    links = []
    seen = set()

    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/']")

    for anchor in anchors:
        href = anchor.get_attribute("href")

        if href and href not in seen:
            seen.add(href)
            links.append({"place_url": href})

    return links


def extract_place(driver, store_name):
    url = driver.current_url
    coords = extract_lat_lng_from_url(url)

    return {
        "name": safe_text(driver, "//h1") or store_name,
        "exact_address": safe_text(
            driver,
            "//button[contains(@aria-label,'Address') or contains(@data-item-id,'address')]"
        ),
        "lat": coords["lat"] if coords else None,
        "lng": coords["lng"] if coords else None,
        "website": safe_attr(
            driver,
            "//a[contains(@aria-label,'Website') or contains(@data-item-id,'authority')]",
            "href",
        ),
        "place_url": url,
        "phone": safe_text(
            driver,
            "//button[contains(@aria-label,'Phone') or contains(@data-item-id,'phone')]"
        ),
    }


def search_store_candidates(store_name, home_coords, max_candidates=5):
    driver = build_driver()

    try:
        query = f"{store_name} near {FULL_ADDRESS}"
        print(f"\n🔎 Searching Google Maps: {query}")

        driver.get(maps_search_url(query))
        time.sleep(7)

        links = collect_place_links(driver)

        if not links:
            links = [{"place_url": driver.current_url}]

        candidates = []

        for link in links[:max_candidates]:
            try:
                driver.get(link["place_url"])
                time.sleep(4)

                candidate = extract_place(driver, store_name)

                if candidate.get("lat") and candidate.get("lng"):
                    candidate["distance_miles"] = round(
                        haversine_miles(
                            home_coords["lat"],
                            home_coords["lng"],
                            candidate["lat"],
                            candidate["lng"],
                        ),
                        2,
                    )
                else:
                    candidate["distance_miles"] = None

                candidates.append(candidate)

            except Exception as e:
                print(f"⚠️ Failed candidate for {store_name}: {e}")

        return candidates

    finally:
        driver.quit()


# =========================================================
# FALLBACK SELECTION
# =========================================================

def fallback_choose_closest(store_key, store, candidates):
    store_name = store["label"]

    if not candidates:
        return {
            "store_key": store_key,
            "store_name": store_name,
            "selected_name": None,
            "exact_address": None,
            "lat": None,
            "lng": None,
            "website": None,
            "place_url": None,
            "phone": None,
            "distance_miles": None,
            "search_url_template": store.get("url"),
            "ai_reason": "No candidates found.",
            "fallback_used": True,
        }

    valid = []

    for candidate in candidates:
        name = (candidate.get("name") or "").lower()
        distance = candidate.get("distance_miles")
        candidate["_name_match"] = store_name.lower() in name

        if distance is not None:
            valid.append(candidate)

    if valid:
        valid.sort(
            key=lambda x: (
                not x.get("_name_match", False),
                x.get("distance_miles", 999999),
            )
        )
        best = valid[0]
    else:
        best = candidates[0]

    return {
        "store_key": store_key,
        "store_name": store_name,
        "selected_name": best.get("name"),
        "exact_address": best.get("exact_address"),
        "lat": best.get("lat"),
        "lng": best.get("lng"),
        "website": best.get("website"),
        "place_url": best.get("place_url"),
        "phone": best.get("phone"),
        "distance_miles": best.get("distance_miles"),
        "search_url_template": store.get("url"),
        "ai_reason": "Fallback selected closest/name-matching Google Maps candidate.",
        "fallback_used": True,
    }


# =========================================================
# AI
# =========================================================

def ai_choose_best(store_key, store, candidates):
    store_name = store["label"]
    search_url_template = store.get("url")

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            'OPENAI_API_KEY is missing. Run: setx OPENAI_API_KEY "your_real_api_key_here" '
            "then close and reopen your terminal."
        )

    client = OpenAI(api_key=api_key)

    prompt = f"""
You are selecting the best grocery store location from Google Maps results.

Target home address:
{FULL_ADDRESS}

Requested store:
{store_name}

Store search URL template:
{search_url_template}

Candidate stores:
{json.dumps(candidates, indent=2)}

Rules:
- Pick the candidate that is actually the requested store.
- Prefer the closest candidate by distance_miles.
- If names are wrong, reject them.
- Do not invent missing information.
- Keep the original Google Maps place_url.
- Keep the original website URL if available.
- Return null for unknown values.
- Return valid JSON only.

Return this exact JSON schema:
{{
  "store_key": "{store_key}",
  "store_name": "{store_name}",
  "selected_name": null,
  "exact_address": null,
  "lat": null,
  "lng": null,
  "website": null,
  "place_url": null,
  "phone": null,
  "distance_miles": null,
  "search_url_template": "{search_url_template}",
  "ai_reason": ""
}}
"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You return only valid JSON. No markdown. No explanations.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        data = safe_json_loads(raw)

        required_keys = {
            "store_key",
            "store_name",
            "selected_name",
            "exact_address",
            "lat",
            "lng",
            "website",
            "place_url",
            "phone",
            "distance_miles",
            "search_url_template",
            "ai_reason",
        }

        for key in required_keys:
            data.setdefault(key, None)

        data["store_key"] = store_key
        data["store_name"] = store_name
        data["search_url_template"] = search_url_template
        data["fallback_used"] = False

        return data

    except Exception as e:
        print(f"⚠️ AI failed for {store_name}: {e}")
        return fallback_choose_closest(store_key, store, candidates)


# =========================================================
# WORKER
# =========================================================

def process_store(store_key, store, home_coords):
    store_name = store["label"]

    print(f"\n🚀 Processing {store_name}")

    try:
        candidates = search_store_candidates(store_name, home_coords)

        best = ai_choose_best(
            store_key=store_key,
            store=store,
            candidates=candidates,
        )

        best["candidates"] = candidates
        best["selection_method"] = "parallel_google_maps_chatgpt_api"

        return store_key, best

    except Exception as e:
        print(f"❌ Failed processing {store_name}: {e}")

        return store_key, {
            "store_key": store_key,
            "store_name": store_name,
            "selected_name": None,
            "exact_address": None,
            "lat": None,
            "lng": None,
            "website": None,
            "place_url": None,
            "phone": None,
            "distance_miles": None,
            "search_url_template": store.get("url"),
            "ai_reason": f"Store processing failed: {e}",
            "fallback_used": True,
            "candidates": [],
            "selection_method": "failed",
        }


# =========================================================
# MAIN
# =========================================================

def main():
    stores = load_stores()
    max_workers = min(MAX_WORKER_LIMIT, len(stores))

    print(f"🏬 Loaded stores: {list(stores.keys())}")
    print(f"⚙️ Using workers: {max_workers}")

    home_coords = get_home_coordinates()

    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_store, key, store, home_coords)
            for key, store in stores.items()
        ]

        for future in as_completed(futures):
            key, result = future.result()
            results[key] = result

    payload = {
        "home_address": {
            "street": ADDRESS_STREET,
            "apartment": ADDRESS_APARTMENT,
            "city": ADDRESS_CITY,
            "state": ADDRESS_STATE,
            "zip": ADDRESS_ZIP,
            "full_address": FULL_ADDRESS,
            "lat": home_coords["lat"],
            "lng": home_coords["lng"],
        },
        "stores": results,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n✅ DONE")
    print(f"✅ Saved results to: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
