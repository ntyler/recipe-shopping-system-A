import json
from pathlib import Path

from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import scoped_extractor_data_path


BASE_DIR = Path(__file__).resolve().parent
HOME_ADDRESS_FILE = scoped_extractor_data_path("home_address.json")

DEFAULT_HOME_ADDRESS = {
    "street": "5905 Arlo Drive",
    "apartment": "Apt 2213",
    "city": "Indianapolis",
    "county": "Marion County",
    "state": "IN",
    "zip": "46237",
    "country": "United States",
}
EMPTY_HOME_ADDRESS = {
    "street": "",
    "apartment": "",
    "city": "",
    "county": "",
    "state": "",
    "zip": "",
    "country": "",
}

HOME_ADDRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_home_address():
    data = (EMPTY_HOME_ADDRESS if active_user_id() else DEFAULT_HOME_ADDRESS).copy()

    if HOME_ADDRESS_FILE.exists():
        try:
            saved = json.loads(HOME_ADDRESS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update({
                    key: str(saved.get(key, data[key]) or "").strip()
                    for key in DEFAULT_HOME_ADDRESS
                })
        except Exception:
            pass

    data["full_address"] = build_full_address(data)
    return data


def save_home_address(form_data):
    data = {
        "street": str(form_data.get("address_street", "") or "").strip(),
        "apartment": str(form_data.get("address_apartment", "") or "").strip(),
        "city": str(form_data.get("address_city", "") or "").strip(),
        "county": str(form_data.get("address_county", "") or "").strip(),
        "state": str(form_data.get("address_state", "") or "").strip(),
        "zip": str(form_data.get("address_zip", "") or "").strip(),
        "country": str(form_data.get("address_country", "") or "").strip(),
    }

    HOME_ADDRESS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    data["full_address"] = build_full_address(data)
    return data


def build_full_address(data):
    street_line = " ".join(
        part
        for part in [data.get("street", ""), data.get("apartment", "")]
        if str(part or "").strip()
    )
    city_line = ", ".join(
        part
        for part in [
            str(data.get("city", "") or "").strip(),
            str(data.get("county", "") or "").strip(),
            " ".join(
                part
                for part in [
                    str(data.get("state", "") or "").strip(),
                    str(data.get("zip", "") or "").strip(),
                ]
                if part
            ),
        ]
        if part
    )

    return ", ".join(
        part
        for part in [
            street_line,
            city_line,
            str(data.get("country", "") or "").strip(),
        ]
        if part
    )
