import json
from pathlib import Path
import shutil
import subprocess

import pytest

from PushShoppingList.services import currency_catalog_service
from PushShoppingList.services import recipe_edit_service


ROOT = Path(__file__).resolve().parents[1]


def test_python_numeric_currency_lookup_preserves_three_digit_codes():
    expected = {
        "840": ("USD", "$", 2),
        "978": ("EUR", "€", 2),
        "392": ("JPY", "¥", 0),
        "356": ("INR", "₹", 2),
        "008": ("ALL", "L", 2),
    }

    for numeric_code, (code, symbol, minor_unit) in expected.items():
        currency = currency_catalog_service.get_currency_by_numeric_code(numeric_code)
        assert currency["code"] == code
        assert currency["symbol"] == symbol
        assert currency["numeric_code"] == numeric_code
        assert currency["minor_unit"] == minor_unit

    albanian_lek = currency_catalog_service.get_currency_by_numeric_code(8)
    assert albanian_lek["code"] == "ALL"
    assert albanian_lek["numeric_code"] == "008"


@pytest.mark.parametrize("invalid", [None, "", "8.0", "0008", -1, 1000, object()])
def test_python_numeric_currency_lookup_returns_none_for_invalid_codes(invalid):
    assert currency_catalog_service.get_currency_by_numeric_code(invalid) is None


def test_backend_resolves_api_numeric_currency_identity_to_alphabetic_code():
    assert recipe_edit_service.clean_menu_price_currency("978") == "EUR"
    assert recipe_edit_service.clean_menu_price_currency(8) == "ALL"


def test_browser_currency_catalog_lookup_and_search_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the browser currency catalog regression")

    currency_script = ROOT / "PushShoppingList" / "static" / "js" / "currency-data.js"
    harness = f"""
const catalog = require({json.dumps(str(currency_script))});
const compact = currency => currency && ({{
    code: currency.code,
    name: currency.name,
    symbol: currency.symbol,
    numericCode: currency.numericCode,
    minorUnit: currency.minorUnit,
}});
const codes = query => catalog.searchCurrencies(query).map(currency => currency.code);
const usd = catalog.getCurrencyByNumericCode("840");
const cad = catalog.getCurrencyByAlphabeticCode("CAD");
process.stdout.write(JSON.stringify({{
    lookups: {{
        usd: compact(usd),
        eur: compact(catalog.getCurrencyByNumericCode("978")),
        jpy: compact(catalog.getCurrencyByNumericCode("392")),
        inr: compact(catalog.getCurrencyByNumericCode("356")),
        allString: compact(catalog.getCurrencyByNumericCode("008")),
        allNumber: compact(catalog.getCurrencyByNumericCode(8)),
    }},
    shared: {{
        usdSymbol: usd.symbol,
        cadSymbol: cad.symbol,
        usdIsShared: catalog.isCurrencySymbolShared("USD"),
        cadIsShared: catalog.isCurrencySymbolShared("CAD"),
    }},
    searches: {{
        name: codes("Indian Rupee"),
        alphabetic: codes("cad"),
        numeric: codes("008"),
        symbol: codes("₹"),
        territory: codes("Albania"),
    }},
    invalid: [
        catalog.getCurrencyByNumericCode(""),
        catalog.getCurrencyByNumericCode("not-a-code"),
        catalog.getCurrencyByNumericCode("0008"),
        catalog.getCurrencyByNumericCode(-1),
        catalog.getCurrencyByNumericCode(1000),
    ],
    spendableCount: catalog.spendableCurrencies.length,
    normalListCodes: catalog.spendableCurrencies.map(currency => currency.code),
}}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)

    assert result["lookups"] == {
        "usd": {"code": "USD", "name": "US Dollar", "symbol": "$", "numericCode": "840", "minorUnit": 2},
        "eur": {"code": "EUR", "name": "Euro", "symbol": "€", "numericCode": "978", "minorUnit": 2},
        "jpy": {"code": "JPY", "name": "Yen", "symbol": "¥", "numericCode": "392", "minorUnit": 0},
        "inr": {"code": "INR", "name": "Indian Rupee", "symbol": "₹", "numericCode": "356", "minorUnit": 2},
        "allString": {"code": "ALL", "name": "Lek", "symbol": "L", "numericCode": "008", "minorUnit": 2},
        "allNumber": {"code": "ALL", "name": "Lek", "symbol": "L", "numericCode": "008", "minorUnit": 2},
    }
    assert result["shared"] == {
        "usdSymbol": "$",
        "cadSymbol": "$",
        "usdIsShared": True,
        "cadIsShared": True,
    }
    assert "INR" in result["searches"]["name"]
    assert "CAD" in result["searches"]["alphabetic"]
    assert result["searches"]["numeric"] == ["ALL"]
    assert "INR" in result["searches"]["symbol"]
    assert "ALL" in result["searches"]["territory"]
    assert result["invalid"] == [None, None, None, None, None]
    assert result["spendableCount"] == 155
    assert not {"XAU", "XTS", "XXX"} & set(result["normalListCodes"])
