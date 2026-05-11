# login_meijer_profile.py

from __future__ import annotations

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
        "sign out" in text
        or "my account" in text
        or "account settings" in text
        or "hi," in text
        or "hi, " in text
    )


def detect_meijer_mfa_screen(driver) -> bool:
    text = page_text(driver)
    return (
        "how do you want to verify" in text
        or "send email" in text
        or "send text" in text
        or "verification" in text
        or "verify by email" in text
        or "enter code" in text
        or "get a verification email" in text
        or "verify by email" in text
        or "get a verification email" in text
    )


def wait_for_mfa_or_login_or_password(driver, seconds: int = 20) -> str:
    for _ in range(seconds):
        if already_logged_in(driver):
            return "logged_in"

        if detect_meijer_mfa_screen(driver):
            return "mfa"

        password_box = find_css(
            driver,
            [
                "input[name='credentials.passcode']",
                "input[type='password']",
                "input[id*='password']",
                "input[name*='password']",
                "input[autocomplete='current-password']",
            ],
        )
        if password_box:
            return "password"

        time.sleep(1)

    return "unknown"


def click_send_me_an_email_if_present(driver) -> bool:
    text = page_text(driver)

    if "send me an email" not in text and "get a verification email" not in text:
        return True

    print("📨 Clicking Send Me an Email")

    clicked = click_xpath(
        driver,
        [
            "//button[contains(normalize-space(.), 'Send Me an Email')]",
            "//*[contains(normalize-space(.), 'Send Me an Email')]",
            "//input[@type='submit' and contains(@value, 'Send Me an Email')]",
            "//button[contains(normalize-space(.), 'Send')]",
        ],
        wait=5,
    )

    if not clicked:
        print("❌ Could not click Send Me an Email")
        return False

    time.sleep(4)
    return True


def wait_for_code_entry_screen(driver, seconds: int = 20) -> bool:
    for _ in range(seconds):
        text = page_text(driver)

        if (
            "enter code" in text
            or "verify by email" in text
            or "a code was sent" in text
            or "code below" in text
        ):
            return True

        time.sleep(1)

    return False


def prompt_for_code_or_send_again(driver) -> bool:
    while True:
        print("")
        print("===================================================")
        print("📬 VERIFICATION OPTIONS")
        print("===================================================")
        print("")
        print("1 = Send Again")
        print("2 = Enter Code")
        print("")

        verify_choice = input("Choose option: ").strip()

        if verify_choice == "1":
            print("")
            print("📨 Sending verification again...")
            print("")

            clicked_again = click_xpath(
                driver,
                [
                    "//a[contains(normalize-space(.), 'Send again')]",
                    "//button[contains(normalize-space(.), 'Send again')]",
                    "//*[contains(normalize-space(.), 'Send again')]",
                    "//a[contains(normalize-space(.), 'Resend')]",
                    "//button[contains(normalize-space(.), 'Resend')]",
                    "//*[contains(normalize-space(.), 'Resend')]",
                ],
                wait=5,
            )

            if clicked_again:
                print("✅ Verification resent")
            else:
                print("⚠️ Could not find Send again button")

            time.sleep(3)

            continue

        elif verify_choice == "2":
            verification_code = input("Enter Code: ").strip()

            if not verification_code:
                print("❌ No code entered")
                continue

            code_box = find_css(
                driver,
                [
                    "input[name='credentials.passcode']",
                    "input[autocomplete='one-time-code']",
                    "input[inputmode='numeric']",
                    "input[id*='code']",
                    "input[name*='code']",
                    "input[type='tel']",
                    "input[type='text']",
                ],
            )

            if not code_box:
                print("❌ Could not find verification code field")
                return False

            print("")
            print(f"🔢 Entering Code: {verification_code}")
            print("")

            type_box(code_box, verification_code)

            clicked_submit = click_xpath(
                driver,
                [
                    "//button[contains(normalize-space(.), 'Submit')]",
                    "//button[contains(normalize-space(.), 'Verify')]",
                    "//button[contains(normalize-space(.), 'Continue')]",
                    "//input[@type='submit']",
                    "//button[@type='submit']",
                ],
                wait=5,
            )

            if not clicked_submit:
                print("❌ Verification submit button not found")
                return False

            time.sleep(8)

            print("")
            print("✅ Verification submitted")
            print("")

            return True

        else:
            print("❌ Invalid option")


def handle_meijer_mfa(driver) -> bool:
    if not detect_meijer_mfa_screen(driver):
        return True

    print("")
    print("===================================================")
    print("⚠️ MEIJER MFA REQUIRED")
    print("===================================================")
    print("")
    print("1 = Send Email")
    print("2 = Send Text")
    print("")

    choice = input("Choose verification method (1 or 2): ").strip()

    if choice == "1":
        print("")
        print("📧 Selecting Send Email")
        print("")

        clicked = click_xpath(
            driver,
            [
                "//*[contains(normalize-space(.), 'Send Email')]",
                "//button[contains(normalize-space(.), 'Send Email')]",
                "//div[contains(normalize-space(.), 'Send Email')]",
                "//*[contains(normalize-space(.), 'Email')]",
            ],
            wait=3,
        )

        if not clicked:
            print("❌ Could not click Send Email")
            return False

        time.sleep(3)

        if not click_send_me_an_email_if_present(driver):
            return False

        if not wait_for_code_entry_screen(driver):
            print("⚠️ Code entry screen was not detected, but continuing")
            time.sleep(2)

        return prompt_for_code_or_send_again(driver)

    elif choice == "2":
        print("")
        print("📱 Selecting Send Text")
        print("")

        clicked = click_xpath(
            driver,
            [
                "//*[contains(normalize-space(.), 'Send Text')]",
                "//button[contains(normalize-space(.), 'Send Text')]",
                "//div[contains(normalize-space(.), 'Send Text')]",
                "//*[contains(normalize-space(.), 'Text')]",
            ],
            wait=3,
        )

        if not clicked:
            print("❌ Could not click Send Text")
            return False

        time.sleep(3)

        print("📨 Clicking Receive a Code Via Text")

        clicked_receive_text = click_xpath(
            driver,
            [
                "//button[contains(normalize-space(.), 'Receive a Code Via Text')]",
                "//*[contains(normalize-space(.), 'Receive a Code Via Text')]",
                "//button[contains(normalize-space(.), 'Receive Code')]",
                "//button[contains(normalize-space(.), 'Via Text')]",
                "//*[contains(normalize-space(.), 'Via Text')]",
            ],
            wait=5,
        )

        if not clicked_receive_text:
            print("❌ Could not click Receive a Code Via Text")
            return False

        time.sleep(5)

        if not wait_for_code_entry_screen(driver):
            print("⚠️ Code entry screen was not detected, but continuing")
            time.sleep(2)

        return prompt_for_code_or_send_again(driver)

    else:
        print("❌ Invalid MFA choice")
        return False


def login_meijer(driver, store) -> bool:
    username = str(store.get("username", "")).strip()
    password = str(store.get("password", "")).strip()

    if not username or not password:
        print("❌ Missing Meijer username/password in shopping_stores.json")
        return False

    print("🌐 Opening Meijer")
    driver.get("https://www.meijer.com/")
    time.sleep(5)

    if already_logged_in(driver):
        print("✅ Meijer already appears logged in")
        return True

    print("🔐 Clicking header Sign in")

    clicked_header = click_xpath(
        driver,
        [
            "//button[contains(normalize-space(.), 'Sign in')]",
            "//a[contains(normalize-space(.), 'Sign in')]",
            "//*[@role='button' and contains(normalize-space(.), 'Sign in')]",
            "//*[contains(@aria-label, 'Sign in')]",
            "//*[contains(@aria-label, 'Account')]",
        ],
        wait=3,
    )

    if not clicked_header:
        print("❌ Header Sign in was not clicked")
        return False

    time.sleep(2)

    print("🔐 Clicking drawer Sign in")

    clicked_drawer = click_xpath(
        driver,
        [
            "//button[normalize-space(.)='Sign in']",
            "//a[normalize-space(.)='Sign in']",
            "//button[contains(normalize-space(.), 'Sign in')]",
            "//a[contains(normalize-space(.), 'Sign in')]",
            "//aside//button[contains(normalize-space(.), 'Sign in')]",
            "//div[contains(@class,'drawer')]//button[contains(normalize-space(.), 'Sign in')]",
        ],
        wait=4,
    )

    if not clicked_drawer:
        print("❌ Drawer Sign in was not clicked")
        return False

    time.sleep(4)

    print("📧 Finding email field")

    email_box = find_css(
        driver,
        [
            "input[name='identifier']",
            "input[type='email']",
            "input[id*='identifier']",
            "input[id*='email']",
            "input[autocomplete='username']",
        ],
    )

    if not email_box:
        print("❌ Could not find email field")
        return False

    print("🧹 Clearing email field and entering username")
    type_box(email_box, username)

    print("➡️ Clicking Next")

    clicked_next = click_xpath(
        driver,
        [
            "//input[@type='submit']",
            "//button[@type='submit']",
            "//button[contains(normalize-space(.), 'Next')]",
            "//button[contains(normalize-space(.), 'Continue')]",
        ],
        wait=4,
    )

    if not clicked_next:
        print("❌ Next button was not clicked")
        return False

    status = wait_for_mfa_or_login_or_password(driver, seconds=20)

    if status == "mfa":
        if not handle_meijer_mfa(driver):
            return False

    if already_logged_in(driver):
        print("✅ Meijer logged in")
        return True

    print("🔑 Finding password field")

    password_box = find_css(
        driver,
        [
            "input[name='credentials.passcode']",
            "input[type='password']",
            "input[id*='password']",
            "input[name*='password']",
            "input[autocomplete='current-password']",
        ],
    )

    if not password_box:
        print("❌ Could not find password field")
        return False

    print("🔑 Entering password")
    type_box(password_box, password)

    print("✅ Clicking Submit")

    clicked_submit = click_xpath(
        driver,
        [
            "//input[@type='submit']",
            "//button[@type='submit']",
            "//button[contains(normalize-space(.), 'Submit')]",
            "//button[contains(normalize-space(.), 'Sign In')]",
            "//button[contains(normalize-space(.), 'Sign in')]",
            "//button[contains(normalize-space(.), 'Log in')]",
            "//button[contains(normalize-space(.), 'Continue')]",
        ],
        wait=5,
    )

    if not clicked_submit:
        print("❌ Submit button was not clicked")
        return False

    status = wait_for_mfa_or_login_or_password(driver, seconds=25)

    if status == "mfa":
        if not handle_meijer_mfa(driver):
            return False

    time.sleep(5)

    if not already_logged_in(driver):
        print("⚠️ Login submitted, but Meijer login was not confirmed")
        return False

    print("")
    print("✅ MEIJER LOGIN COMPLETE")
    print("✅ PROFILE SAVED TO:")
    print(PROFILE_ROOT / COMMON_PROFILE_NAME)
    print("")

    return True


def main():
    meijer = STORES.get("meijer")

    if not meijer:
        print("❌ No Meijer config found in shopping_stores.json")
        return

    driver = build_driver(COMMON_PROFILE_NAME)

    try:
        ok = login_meijer(driver, meijer)

        if ok:
            results_path = (
                PROFILE_ROOT.parent / "PushShoppingList" / "shopping_stores_Results.json"
            )

            meijer_store_address = ""

            try:
                import json

                with open(results_path, "r", encoding="utf-8") as f:
                    results_data = json.load(f)

                stores = results_data.get("stores", {})
                meijer_store = stores.get("meijer", {})

                # USE THE EXACT STORE ADDRESS
                meijer_store_address = str(
                    meijer_store.get("exact_address", "")
                ).strip()

                # FALLBACK
                if not meijer_store_address:
                    meijer_store_address = str(
                        meijer_store.get("selected_address", "")
                    ).strip()

            except Exception as exc:
                print("")
                print("❌ Failed to load shopping_stores_Results.json")
                print(exc)
                print("")

            if meijer_store_address:
                print("")
                print("🏬 Loaded Meijer Store Address:")
                print(meijer_store_address)
                print("")

                update_meijer_store(driver, meijer_store_address)

            else:
                print("⚠️ Could not determine Meijer store address")

        print("")
        if ok:
            print("✅ Browser profile is now saved/authenticated here:")
        else:
            print("⚠️ Login did not fully complete, but profile is still saved here:")

        print(PROFILE_ROOT / COMMON_PROFILE_NAME)
        print("")

        input("Press ENTER to close browser...")

    finally:
        driver.quit()


def update_meijer_store(driver, full_address: str) -> bool:
    print("")
    print("===================================================")
    print("🛒 UPDATING MEIJER STORE")
    print("===================================================")
    print("")

    driver.get("https://www.meijer.com/")
    time.sleep(6)

    print("📍 Opening pickup/store selector")

    clicked_pickup = click_xpath(
        driver,
        [
            "//button[contains(., 'Pickup')]",
            "//*[contains(@aria-label, 'Pickup')]",
            "//*[contains(normalize-space(.), 'Pickup')]",
            "//*[@role='button' and contains(normalize-space(.), 'Pickup')]",
        ],
        wait=4,
    )

    if not clicked_pickup:
        print("❌ Could not open Pickup selector")
        return False

    time.sleep(3)

    print("📍 Finding address input")

    address_box = find_css(
        driver,
        [
            "input[placeholder*='ZIP']",
            "input[placeholder*='Zip']",
            "input[placeholder*='zip']",
            "input[placeholder*='Address']",
            "input[placeholder*='address']",
            "input[aria-label*='ZIP']",
            "input[aria-label*='Zip']",
            "input[aria-label*='address']",
            "input[type='text']",
        ],
    )

    if not address_box:
        print("❌ Could not find store address field")
        return False

    print(f"🏬 Entering Meijer store address: {full_address}")

    type_box(address_box, full_address)
    time.sleep(1)

    address_box.send_keys("\ue007")
    time.sleep(5)

    print("🏬 Selecting store radio button")

    clicked_radio = click_xpath(
        driver,
        [
            "//input[@type='radio']",
            "//*[@role='radio']",
            "//label[contains(., 'Southport Rd')]",
            "//*[contains(normalize-space(.), 'Southport Rd')]",
        ],
        wait=3,
    )

    if not clicked_radio:
        print("⚠️ Could not click store radio button")

    time.sleep(2)

    print("✅ Clicking Continue shopping")

    clicked_continue = click_xpath(
        driver,
        [
            "//button[contains(normalize-space(.), 'Continue shopping')]",
            "//*[contains(normalize-space(.), 'Continue shopping')]",
            "//button[contains(normalize-space(.), 'Start shopping')]",
            "//button[contains(normalize-space(.), 'Save')]",
            "//button[contains(normalize-space(.), 'Use this store')]",
        ],
        wait=5,
    )

    if not clicked_continue:
        print("❌ Could not click Continue shopping")
        return False

    time.sleep(5)

    print("")
    print("✅ MEIJER STORE UPDATED")
    print("")

    return True


if __name__ == "__main__":
    main()
