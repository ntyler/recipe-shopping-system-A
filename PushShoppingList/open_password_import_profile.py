import subprocess
import time
from pathlib import Path

import pyautogui
import pyperclip

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


PROFILE_DIR = Path(
    r"D:\GitHub\recipe-shopping-system\chrome_worker_profiles\profile_stores_common_ID_01"
)

CSV_FILE = Path(
    r"D:\GitHub\recipe-shopping-system\PushShoppingList\password_manager_import_template.csv"
)

CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

if not CHROME_EXE.exists():
    CHROME_EXE = Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")

if not CHROME_EXE.exists():
    raise FileNotFoundError("Google Chrome executable was not found.")

if not CSV_FILE.exists():
    raise FileNotFoundError(f"CSV password file not found:\n{CSV_FILE}")

PROFILE_DIR.mkdir(parents=True, exist_ok=True)

CSV_FOLDER = CSV_FILE.parent
CSV_NAME = CSV_FILE.name

print(f"Using Chrome profile:\n{PROFILE_DIR}")
print(f"Found password CSV:\n{CSV_FILE}")

print("\nClosing existing Chrome windows...")
subprocess.run(
    ["taskkill", "/F", "/IM", "chrome.exe"],
    capture_output=True,
    text=True,
)

time.sleep(2)

options = Options()
options.binary_location = str(CHROME_EXE)
options.add_argument(f"--user-data-dir={PROFILE_DIR}")
options.add_argument("--profile-directory=Default")
options.add_argument("--no-first-run")
options.add_argument("--no-default-browser-check")
options.add_argument("--disable-popup-blocking")
options.add_argument("--disable-notifications")
options.add_argument("--start-maximized")
options.add_argument("--enable-features=PasswordImport")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options,
)

wait = WebDriverWait(driver, 45)


def find_select_file_button():
    return driver.execute_script(
        """
        function textOf(el) {
            return (
                el.innerText ||
                el.textContent ||
                el.getAttribute("aria-label") ||
                el.getAttribute("title") ||
                ""
            ).trim().toLowerCase();
        }

        function deepFind(root) {
            if (!root) return null;

            const candidates = root.querySelectorAll
                ? root.querySelectorAll('button, cr-button, div[role="button"]')
                : [];

            for (const el of candidates) {
                const txt = textOf(el);
                if (
                    txt.includes("select file") ||
                    txt.includes("import passwords") ||
                    txt.includes("import")
                ) {
                    return el;
                }
            }

            const all = root.querySelectorAll ? root.querySelectorAll("*") : [];

            for (const el of all) {
                if (el.shadowRoot) {
                    const found = deepFind(el.shadowRoot);
                    if (found) return found;
                }
            }

            return null;
        }

        return deepFind(document);
        """
    )


def paste_text(text):
    pyperclip.copy(str(text))
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.5)


try:
    print("\nOpening Chrome Password Manager settings...")
    driver.get("chrome://password-manager/settings")

    print("\nWaiting for Password Manager UI...")
    time.sleep(7)

    print("\nLooking for Select file button inside Shadow DOM...")
    select_button = wait.until(lambda d: find_select_file_button())

    print("Found Select file button.")
    print("Clicking Select file...")

    driver.execute_script(
        """
        arguments[0].scrollIntoView({block: "center"});
        arguments[0].click();
        """,
        select_button,
    )

    print("\nWaiting for Windows file picker...")
    time.sleep(4)

    print(f"Navigating to folder:\n{CSV_FOLDER}")

    # Move focus to file dialog address bar
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)

    # Paste folder path
    paste_text(CSV_FOLDER)

    # Navigate to folder
    pyautogui.press("enter")
    time.sleep(2)

    print(f"Selecting CSV file:\n{CSV_NAME}")

    # Move focus to File name box
    pyautogui.hotkey("alt", "n")
    time.sleep(0.5)

    # Paste filename
    paste_text(CSV_NAME)

    # Click Open / press Enter
    pyautogui.press("enter")

    print("CSV file selected.")
    print("Waiting for Chrome import...")

    time.sleep(10)

    print("Looking for success dialog Close button...")

    time.sleep(3)

    close_clicked = driver.execute_script(
        """
        function textOf(el) {
            return (
                el.innerText ||
                el.textContent ||
                el.getAttribute("aria-label") ||
                ""
            ).trim().toLowerCase();
        }

        function deepFind(root) {
            if (!root) return null;

            const buttons = root.querySelectorAll
                ? root.querySelectorAll('button, cr-button')
                : [];

            for (const btn of buttons) {
                const txt = textOf(btn);

                if (txt === "close") {
                    return btn;
                }
            }

            const all = root.querySelectorAll
                ? root.querySelectorAll("*")
                : [];

            for (const el of all) {
                if (el.shadowRoot) {
                    const found = deepFind(el.shadowRoot);
                    if (found) return found;
                }
            }

            return null;
        }

        const btn = deepFind(document);

        if (!btn) {
            return false;
        }

        btn.click();

        return true;
        """
    )

    if close_clicked:
        print("Close button clicked.")
    else:
        print("Could not find Close button.")

    input("\nPress ENTER to close browser...\n")

finally:
    driver.quit()
