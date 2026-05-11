# login_kroger_profile.py

from __future__ import annotations

import time

from store_profile_common import (
    STORES,
    PROFILE_ROOT,
    build_driver,
)


def login_kroger(driver, store):
    print("🌐 Opening Kroger")

    driver.get("https://www.kroger.com/")

    time.sleep(10)

    print("")
    print("🛑 Manually log into Kroger")
    print("🛑 Session will persist")
    print("")

    print(PROFILE_ROOT / "profile_kroger")

    return True


def main():
    store = STORES.get("kroger", {})

    driver = build_driver("profile_kroger")

    try:
        login_kroger(driver, store)

        input("Press ENTER to close browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
