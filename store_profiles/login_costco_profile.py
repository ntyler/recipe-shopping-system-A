# login_costco_profile.py
from __future__ import annotations

import time

from store_profile_common import (
    STORES,
    PROFILE_ROOT,
    build_driver,
)


def login_costco(driver, store):
    print("🌐 Opening Costco")

    driver.get("https://www.costco.com/")

    time.sleep(10)

    print("")
    print("🛑 Manually log into Costco")
    print("🛑 Session will persist")
    print("")

    print(PROFILE_ROOT / "profile_costco")

    return True


def main():
    store = STORES.get("costco", {})

    driver = build_driver("profile_costco")

    try:
        login_costco(driver, store)

        input("Press ENTER to close browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
