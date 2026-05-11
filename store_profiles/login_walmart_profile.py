# login_walmart_profile.py

from __future__ import annotations

import time

from store_profile_common import (
    STORES,
    PROFILE_ROOT,
    build_driver,
)


def login_walmart(driver, store):
    print("🌐 Opening Walmart")

    driver.get("https://www.walmart.com/")

    time.sleep(10)

    print("")
    print("🛑 Manually log into Walmart")
    print("🛑 Session will persist")
    print("")

    print(PROFILE_ROOT / "profile_walmart")

    return True


def main():
    store = STORES.get("walmart", {})

    driver = build_driver("profile_walmart")

    try:
        login_walmart(driver, store)

        input("Press ENTER to close browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
