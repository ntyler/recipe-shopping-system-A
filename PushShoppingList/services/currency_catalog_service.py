"""ISO 4217 currency lookup backed by the bundled 2026-01-01 dataset.

Numeric codes are normalized to three-character strings. Public lookup helpers
return ``None`` for malformed or unknown identities.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
import re


CURRENCY_DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "iso_4217_currency_symbols_2026-01-01.csv"
)


def normalize_numeric_currency_code(input_value):
    """Return a zero-padded ISO numeric code, or ``None`` when invalid."""

    if isinstance(input_value, bool):
        return None
    if isinstance(input_value, int):
        return f"{input_value:03d}" if 0 <= input_value <= 999 else None
    if not isinstance(input_value, str):
        return None
    value = input_value.strip()
    return value.zfill(3) if re.fullmatch(r"\d{1,3}", value) else None


@lru_cache(maxsize=1)
def currency_catalog():
    """Load every ISO row; the selector filters normal spendable currencies."""

    currencies = []
    with CURRENCY_DATASET_PATH.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            minor_unit_text = str(row.get("minor_unit") or "").strip()
            currencies.append({
                "code": str(row.get("ISO_4217_alpha") or "").strip().upper(),
                "numeric_code": str(row.get("ISO_4217_numeric") or "").strip().zfill(3),
                "name": str(row.get("currency_or_fund_name") or "").strip(),
                "symbol": str(row.get("display_symbol") or "").strip(),
                "minor_unit": int(minor_unit_text) if minor_unit_text.isdigit() else None,
                "classification": str(row.get("classification") or "").strip(),
                "territories": tuple(
                    territory.strip()
                    for territory in str(row.get("entities_or_territories") or "").split(";")
                    if territory.strip()
                ),
            })
    return tuple(currencies)


@lru_cache(maxsize=1)
def _currencies_by_numeric_code():
    return {currency["numeric_code"]: currency for currency in currency_catalog()}


@lru_cache(maxsize=1)
def _currencies_by_alphabetic_code():
    return {currency["code"]: currency for currency in currency_catalog()}


@lru_cache(maxsize=1)
def _spendable_currencies_by_symbol():
    by_symbol = {}
    for currency in currency_catalog():
        if currency["classification"] != "Currency":
            continue
        by_symbol.setdefault(currency["symbol"], []).append(currency)
    return {symbol: tuple(currencies) for symbol, currencies in by_symbol.items()}


def get_currency_by_numeric_code(input_value):
    """Resolve a numeric ISO identity, returning a currency record or ``None``."""

    numeric_code = normalize_numeric_currency_code(input_value)
    return _currencies_by_numeric_code().get(numeric_code) if numeric_code else None


def get_currency_by_alphabetic_code(input_value):
    code = str(input_value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        return None
    return _currencies_by_alphabetic_code().get(code)


def resolve_currency_code(input_value):
    """Resolve numeric, alphabetic, or unambiguous symbol input to an ISO code.

    Unknown three-letter alphabetic values are preserved for compatibility with
    existing saved recipes. The shared ``$`` legacy symbol resolves to USD.
    """

    numeric_match = get_currency_by_numeric_code(input_value)
    if numeric_match:
        return numeric_match["code"]

    value = str(input_value or "").strip()
    alphabetic = value.upper()
    if re.fullmatch(r"[A-Z]{3}", alphabetic):
        return alphabetic

    symbol_matches = _spendable_currencies_by_symbol().get(value, ())
    if len(symbol_matches) == 1:
        return symbol_matches[0]["code"]
    if value == "$":
        return "USD"
    return None


def infer_currency_code_from_price(input_value):
    """Infer a legacy formatted price prefix without changing its stored text."""

    value = str(input_value or "").strip()
    if not value:
        return None
    code_match = re.match(r"^([A-Za-z]{3})(?:\s|(?=\d))", value)
    if code_match:
        return resolve_currency_code(code_match.group(1))
    for symbol in sorted(_spendable_currencies_by_symbol(), key=len, reverse=True):
        if value.startswith(symbol):
            return resolve_currency_code(symbol)
    return None
