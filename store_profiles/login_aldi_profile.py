# login_aldi_profile.py

from __future__ import annotations

import json
import time

from store_profile_common import (
    STORES,
    PROFILE_ROOT,
    build_driver,
    click_xpath,
    find_css,
    type_box,
)


COMMON_PROFILE_NAME = "profile_stores_common"


def page_text(driver) -> str:
    try:
        return driver.find_element("tag name", "body").text.lower()
    except Exception:
        return ""


def already_logged_in(driver) -> bool:
    text = page_text(driver)

    return (
        "my account" in text
        or "sign out" in text
        or "logout" in text
        or "account settings" in text
        or "hi," in text
    )


def wait_for_css(driver, selectors, seconds=30):
    for _ in range(seconds):
        element = find_css(driver, selectors)
        if element:
            return element
        time.sleep(1)
    return None


def find_aldi_input_by_name(driver, name: str):
    script = """
    const targetName = arguments[0];

    function search(root) {
        const inputs = root.querySelectorAll('input');

        for (const input of inputs) {
            if (
                input.name === targetName ||
                input.id === targetName ||
                input.placeholder?.toLowerCase().includes(targetName.toLowerCase())
            ) {
                return input;
            }
        }

        const all = root.querySelectorAll('*');

        for (const el of all) {
            if (el.shadowRoot) {
                const found = search(el.shadowRoot);
                if (found) return found;
            }
        }

        return null;
    }

    return search(document);
    """

    try:
        return driver.execute_script(script, name)
    except Exception:
        return None


def type_aldi_shadow_input(driver, name: str, value: str) -> bool:
    element = find_aldi_input_by_name(driver, name)

    if not element:
        return False

    driver.execute_script(
        """
        const input = arguments[0];
        const value = arguments[1];

        input.focus();

        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));

        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        element,
        value,
    )

    time.sleep(1)
    return True


def click_aldi_login_button(driver) -> bool:
    script = """
    function isVisible(el) {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function search(root) {
        const candidates = root.querySelectorAll(
            'button, input[type="submit"], lightning-button'
        );

        for (const el of candidates) {
            const text = (
                el.innerText ||
                el.textContent ||
                el.value ||
                ''
            ).trim().toLowerCase();

            if (
                text === 'log in' ||
                text === 'login' ||
                text.includes('log in') ||
                text.includes('login')
            ) {
                if (isVisible(el)) {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return true;
                }
            }
        }

        const all = root.querySelectorAll('*');

        for (const el of all) {
            if (el.shadowRoot) {
                const found = search(el.shadowRoot);
                if (found) return true;
            }
        }

        return false;
    }

    return search(document);
    """

    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def load_aldi_store_address() -> str:
    results_path = (
        PROFILE_ROOT.parent / "PushShoppingList" / "shopping_stores_Results.json"
    )

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            results_data = json.load(f)

        stores = results_data.get("stores", {})
        aldi_store = stores.get("aldi", {})

        address = str(aldi_store.get("exact_address", "")).strip()

        if not address:
            address = str(aldi_store.get("selected_address", "")).strip()

        return address

    except Exception as exc:
        print("❌ Failed to load Aldi store address")
        print(exc)
        return ""


def click_aldi_change_store(driver) -> bool:
    script = """
    function visible(el) {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function clickIt(el) {
        el.scrollIntoView({block: 'center', inline: 'center'});
        el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
        el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
        el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        return true;
    }

    function allText(el) {
        return (el.innerText || el.textContent || '').trim().toLowerCase();
    }

    // STEP 1: open top pickup dropdown
    const all = [...document.querySelectorAll('*')];

    for (const el of all) {
        const text = allText(el);

        if (
            visible(el) &&
            text.includes('pickup') &&
            text.includes('aldi -') &&
            (el.tagName.toLowerCase() === 'button' || el.getAttribute('role') === 'button')
        ) {
            clickIt(el);
            break;
        }
    }

    // STEP 2 happens after dropdown opens
    setTimeout(() => {}, 500);

    // STEP 2: click Change store inside Pickup row
    const candidates = [...document.querySelectorAll('button, a, div, span')];

    for (const el of candidates) {
        const text = allText(el);

        if (!visible(el)) continue;

        if (text === 'change store' || text.includes('change store')) {
            let container = el.closest('button') || el.closest('[role="button"]') || el;

            const parentText = allText(
                el.closest('div[class]') ||
                el.parentElement ||
                el
            );

            // Prefer the Pickup row, not Delivery/In-Store
            if (
                parentText.includes('pickup') ||
                parentText.includes('aldi -') ||
                parentText.includes('change store')
            ) {
                return clickIt(container);
            }
        }
    }

    return false;
    """

    try:
        return bool(driver.execute_script(script))
    except Exception as exc:
        print(f"❌ Change store JS click failed: {exc}")
        return False
    

def update_aldi_store(driver) -> bool:
    print("")
    print("===================================================")
    print("🛒 UPDATING ALDI STORE")
    print("===================================================")
    print("")

    aldi_store_address = load_aldi_store_address()

    if not aldi_store_address:
        print("❌ Could not determine Aldi store address")
        return False

    print(f"🏬 Aldi Store Address: {aldi_store_address}")

    driver.get("https://new.aldi.us/")
    time.sleep(8)

    print("📍 Clicking Pickup Change store")

    clicked_change_store = click_aldi_change_store(driver)

    if not clicked_change_store:
        print("❌ Could not click Pickup Change store")
        return False

    print("✅ Pickup Change store clicked")
    time.sleep(5)

    print("📍 Entering Aldi store address")

    entered_address = type_aldi_shadow_input(
        driver,
        "address",
        aldi_store_address,
    )

    if not entered_address:
        entered_address = type_aldi_shadow_input(
            driver,
            "store",
            aldi_store_address,
        )

    if not entered_address:
        address_box = find_css(
            driver,
            [
                "input[placeholder*='address']",
                "input[placeholder*='Address']",
                "input[placeholder*='ZIP']",
                "input[placeholder*='Zip']",
                "input[type='text']",
            ],
        )

        if address_box:
            type_box(address_box, aldi_store_address)
            address_box.send_keys("\ue007")
            entered_address = True

    if not entered_address:
        print("❌ Could not enter Aldi address")
        return False

    print("✅ Aldi address entered")

    time.sleep(6)

    print("🏬 Selecting Aldi store")

    clicked_store = click_xpath(
        driver,
        [
            "//button[contains(normalize-space(.), 'Select Store')]",
            "//button[contains(normalize-space(.), 'Select')]",
            "//button[contains(normalize-space(.), 'Choose Store')]",
            "//button[contains(normalize-space(.), 'Choose')]",
            "//button[contains(normalize-space(.), 'Shop This Store')]",
        ],
        wait=5,
    )

    if not clicked_store:
        print("⚠️ Could not automatically select Aldi store")
        return False

    time.sleep(5)

    print("")
    print("✅ ALDI STORE UPDATED")
    print("")

    return True


def login_aldi(driver, store) -> bool:
    username = str(store.get("username", "")).strip()
    password = str(store.get("password", "")).strip()

    print("🌐 Opening Aldi")

    driver.get("https://new.aldi.us/")
    time.sleep(8)

    # =====================================================
    # SKIP LOGIN IF ALREADY LOGGED IN
    # =====================================================

    if already_logged_in(driver):
        print("✅ Aldi already logged in")
        return True

    print("🔐 Opening Aldi login page")

    clicked_sign_in = click_xpath(
        driver,
        [
            "//button[contains(normalize-space(.), 'Sign In')]",
            "//a[contains(normalize-space(.), 'Sign In')]",
            "//button[contains(normalize-space(.), 'Log In')]",
            "//a[contains(normalize-space(.), 'Log In')]",
            "//*[contains(normalize-space(.), 'Account')]",
        ],
        wait=6,
    )

    if clicked_sign_in:
        time.sleep(8)

    print("📧 Entering Aldi email")

    entered_email = type_aldi_shadow_input(
        driver,
        "emailAddress",
        username,
    )

    if not entered_email:
        entered_email = type_aldi_shadow_input(
            driver,
            "email",
            username,
        )

    if not entered_email:
        print("❌ Could not enter Aldi email")
        return False

    print("🔑 Entering Aldi password")

    entered_password = type_aldi_shadow_input(
        driver,
        "password",
        password,
    )

    if not entered_password:
        print("❌ Could not enter Aldi password")
        return False

    print("")
    print("===================================================")
    print("🤖 WAITING FOR FRIENDLY CAPTCHA")
    print("===================================================")
    print("")

    captcha_verified = False

    while not captcha_verified:
        page = page_text(driver)

        if (
            "i am human" in page
            or "you are human" in page
        ):
            print("✅ CAPTCHA verified")
            captcha_verified = True
            break

        print("⏳ Waiting for captcha to finish...")
        time.sleep(1)

    print("✅ Continuing Aldi login")

    time.sleep(2)

    print("✅ Clicking Aldi Log In")

    clicked_login = click_aldi_login_button(driver)
    time.sleep(8)

    if not clicked_login:
        print("❌ Could not click Aldi Log In")
        return False

    time.sleep(10)

    print("")
    print("✅ ALDI LOGIN COMPLETE")
    print("")

    return True


def main():
    store = STORES.get("aldi", {})

    driver = build_driver(COMMON_PROFILE_NAME)

    try:
        ok = login_aldi(driver, store)

        if ok:
            print("✅ Aldi login/session confirmed")
        else:
            print("⚠️ Aldi login was not confirmed")
            print("➡️ Trying Aldi store update anyway")

        update_aldi_store(driver)

        print("")
        print("✅ Shared profile saved to:")
        print(PROFILE_ROOT / COMMON_PROFILE_NAME)
        print("")

        input("Press ENTER to close browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
