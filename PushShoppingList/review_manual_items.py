import json
import re
import time
import subprocess
from pathlib import Path

import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =========================================================
# CLEANUP
# =========================================================
# Do NOT kill chrome.exe because that closes your normal browser.
subprocess.run("taskkill /F /IM chromedriver.exe /T", shell=True, check=False)


# =========================================================
# PATHS
# =========================================================
BASE_DIR = Path(__file__).resolve().parent

SHOPPING_LIST_FILE = BASE_DIR / "shopping_list.txt"
ITEM_SOURCES_FILE = BASE_DIR / "shopping_item_sources.json"
LOG_FOLDER = BASE_DIR / "data" / "logs"

LOG_FOLDER.mkdir(parents=True, exist_ok=True)


# =========================================================
# CONFIG
# =========================================================
MODEL_URL = "https://chatgpt.com/?model=gpt-4o"
CHROME_PROFILE_PATH = r"C:\Users\Tyler\AppData\Local\Google\Chrome\User Data\ChatGPTBot"
#CHROME_PROFILE_PATH = r"C:\Users\Tyler\AppData\Local\Google\Chrome\User Data\Default"
CHROME_VERSION_MAIN = 147

SECTION_ORDER = {
    "PRODUCE": 1,
    "DAIRY": 2,
    "DRY GOODS": 3,
    "CANNED": 4,
    "BEVERAGES": 5,
    "SPICES": 6,
    "OILS": 7,
    "BAKERY": 8,
    "MISC": 9,
}


# =========================================================
# HELPERS
# =========================================================
def normalize(text):
    return " ".join(text.strip().lower().split())


def is_section_header(text):
    text = text.strip()
    return text.startswith("===") and text.endswith("===")


def load_items():
    if not SHOPPING_LIST_FILE.exists():
        return []

    return [
        line.strip()
        for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not is_section_header(line)
    ]


def load_item_sources():
    if not ITEM_SOURCES_FILE.exists():
        return {}

    try:
        return json.loads(ITEM_SOURCES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_item_sources(sources):
    ITEM_SOURCES_FILE.write_text(
        json.dumps(sources, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def find_manual_items(items, item_sources):
    manual_items = []

    for item in items:
        key = normalize(item)

        if key not in item_sources:
            manual_items.append(item)

    return manual_items


def build_prompt(manual_items):
    items_json = json.dumps(manual_items, indent=2, ensure_ascii=False)

    return f"""
Classify these manually entered grocery shopping items.

Return ONLY valid JSON.
Do not include markdown.
Do not include explanations.

Use ONLY these exact store_section values:
PRODUCE, DAIRY, DRY GOODS, CANNED, BEVERAGES, SPICES, OILS, BAKERY, MISC

Use this exact store_section_order:
PRODUCE = 1
DAIRY = 2
DRY GOODS = 3
CANNED = 4
BEVERAGES = 5
SPICES = 6
OILS = 7
BAKERY = 8
MISC = 9

Rules:
- Preserve the exact item text.
- Do not rename items.
- Do not remove items.
- Do not add items.
- Prepared baked goods such as donuts, bread, rolls, muffins, bagels, and buns should be BAKERY.
- If unsure, use MISC.

ITEMS:
{items_json}

FINAL OUTPUT FORMAT:
{{
  "items": [
    {{
      "item": "Donuts",
      "store_section": "BAKERY",
      "store_section_order": 8
    }}
  ]
}}
"""


def clean_json_response(text):
    text = text.strip()
    text = text.replace("```json", "")
    text = text.replace("```", "")
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = text.replace("\r\n", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    return text.strip()


# =========================================================
# CHATGPT SELENIUM
# =========================================================
def wait_for_chatgpt_ready(driver):
    selectors = [
        (By.CSS_SELECTOR, "#prompt-textarea"),
        (By.ID, "prompt-textarea"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
        (By.CSS_SELECTOR, "textarea"),
    ]

    for by, selector in selectors:
        try:
            return WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((by, selector))
            )
        except Exception:
            pass

    driver.save_screenshot(str(LOG_FOLDER / "manual_classifier_input_not_found.png"))
    return None


def send_prompt_to_chatgpt(driver, prompt_text):
    input_box = wait_for_chatgpt_ready(driver)

    if input_box is None:
        return False

    try:
        driver.execute_script(
            """
            const el = arguments[0];
            const text = arguments[1];

            el.focus();

            const clipboardData = new DataTransfer();
            clipboardData.setData('text/plain', text);

            const pasteEvent = new ClipboardEvent('paste', {
                bubbles: true,
                cancelable: true,
                clipboardData: clipboardData
            });

            el.dispatchEvent(pasteEvent);
            el.innerText = text;

            el.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'insertText',
                data: text
            }));
            """,
            input_box,
            prompt_text
        )

        time.sleep(2)

        send_buttons = driver.find_elements(
            By.XPATH,
            "//button[@data-testid='send-button']"
        )

        if send_buttons:
            send_buttons[-1].click()
            return True

        ActionChains(driver).send_keys(Keys.ENTER).perform()
        return True

    except Exception as e:
        print(f"Failed to send prompt: {e}")
        driver.save_screenshot(str(LOG_FOLDER / "manual_classifier_send_failed.png"))
        return False


def extract_response_text(driver):
    try:
        assistant_messages = driver.find_elements(
            By.XPATH,
            "//div[@data-message-author-role='assistant']"
        )

        if not assistant_messages:
            return ""

        last_message = assistant_messages[-1]

        code_blocks = last_message.find_elements(
            By.XPATH,
            ".//pre//code | .//pre | .//code"
        )

        for block in reversed(code_blocks):
            text = block.text.strip()
            if text:
                return text

        return last_message.text.replace("Copy code", "").strip()

    except Exception as e:
        print(f"Could not extract response: {e}")
        return ""


def wait_until_done(driver, max_wait_seconds=180):
    start_time = time.time()
    last_text = ""
    stable_count = 0

    while time.time() - start_time < max_wait_seconds:
        stop_buttons = driver.find_elements(
            By.XPATH,
            "//button[@data-testid='stop-button']"
        )

        if stop_buttons:
            stable_count = 0
            last_text = ""
            time.sleep(2)
            continue

        current_text = extract_response_text(driver)

        if not current_text:
            time.sleep(2)
            continue

        if current_text == last_text:
            stable_count += 1
        else:
            stable_count = 0
            last_text = current_text

        if stable_count >= 4:
            return True

        time.sleep(2)

    return False


def classify_manual_items_with_chatgpt(manual_items):
    subprocess.run(
        "taskkill /F /IM chromedriver.exe /T",
        shell=True,
        check=False
    )

    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,900")

    driver = uc.Chrome(
        version_main=CHROME_VERSION_MAIN,
        headless=False,
        use_subprocess=True,
        options=options
    )

    try:
        driver.set_page_load_timeout(120)
        driver.get(MODEL_URL)
        time.sleep(5)

        prompt = build_prompt(manual_items)

        sent = send_prompt_to_chatgpt(driver, prompt)

        if not sent:
            print("Could not send prompt to ChatGPT.")
            return []

        wait_until_done(driver)

        response_text = extract_response_text(driver)
        cleaned = clean_json_response(response_text)

        data = json.loads(cleaned)

        return data.get("items", [])

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def update_item_sources_with_manual_classifications(classified_items):
    sources = load_item_sources()

    for entry in classified_items:
        item = entry.get("item")
        section = str(entry.get("store_section", "")).strip().upper()

        if not item:
            continue

        if section not in SECTION_ORDER:
            section = "MISC"

        key = normalize(item)

        sources[key] = [
            {
                "url": None,
                "quantity": None,
                "unit": None,
                "original_text": item,
                "source_type": "manual",
                "store_section": section,
                "store_section_order": SECTION_ORDER[section]
            }
        ]

    save_item_sources(sources)


def main():
    items = load_items()
    item_sources = load_item_sources()

    manual_items = find_manual_items(items, item_sources)

    if not manual_items:
        print("No manual items found.")
        return

    print("Manual items found:")
    for item in manual_items:
        print(f"- {item}")

    classified_items = classify_manual_items_with_chatgpt(manual_items)

    if not classified_items:
        print("No classifications returned.")
        return

    update_item_sources_with_manual_classifications(classified_items)

    print("\nSaved manual item classifications:")
    for item in classified_items:
        print(
            f"- {item.get('item')} -> "
            f"{item.get('store_section')} "
            f"({item.get('store_section_order')})"
        )


if __name__ == "__main__":
    main()
