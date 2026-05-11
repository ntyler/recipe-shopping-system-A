# login_target_profile.py

from __future__ import annotations

import time

from store_profile_common import (
    STORES,
    PROFILE_ROOT,
    build_driver,
)


def login_target(driver, store):
    print("🌐 Opening Target")

    driver.get("https://www.target.com/")

    time.sleep(10)

    print("")
    print("🛑 Manually log into Target")
    print("🛑 Session will persist")
    print("")

    print(PROFILE_ROOT / "profile_target")

    return True


def main():
    store = STORES.get("target", {})

    driver = build_driver("profile_target")

    try:
        login_target(driver, store)

        input("Press ENTER to close browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
