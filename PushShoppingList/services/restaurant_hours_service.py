"""Canonical conversion helpers for normalized restaurant weekly hours."""

from __future__ import annotations

import json
import re


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_LABELS = {day: day.title() for day in WEEKDAYS}
DAY_ALIASES = {
    "mo": "monday", "mon": "monday", "monday": "monday",
    "tu": "tuesday", "tue": "tuesday", "tues": "tuesday", "tuesday": "tuesday",
    "we": "wednesday", "wed": "wednesday", "wednesday": "wednesday",
    "th": "thursday", "thu": "thursday", "thur": "thursday", "thurs": "thursday", "thursday": "thursday",
    "fr": "friday", "fri": "friday", "friday": "friday",
    "sa": "saturday", "sat": "saturday", "saturday": "saturday",
    "su": "sunday", "sun": "sunday", "sunday": "sunday",
}


def _clean(value):
    return " ".join(str(value or "").strip().split())


def _day_key(value):
    return DAY_ALIASES.get(_clean(value).casefold(), "")


def normalize_hours_time(value, *, closing=False):
    text = _clean(value).replace(".", "")
    if closing and re.fullmatch(r"24:00(?::00)?", text):
        return "24:00"
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap]m)?", text, re.I)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").casefold()
    if meridiem:
        if not 1 <= hour <= 12:
            return ""
        hour = (hour % 12) + (12 if meridiem == "pm" else 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def normalize_weekly_hours(value):
    """Return the single persisted weekly-hours shape used by scan and editor code."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                value = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                value = None
        else:
            value = parse_weekly_hours_text(text)[0]
    if not isinstance(value, dict):
        return {}

    normalized = {}
    for raw_day, raw_entry in value.items():
        day = _day_key(raw_day)
        if not day:
            continue
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        closed = entry.get("closed") is True or _clean(entry.get("status")).casefold() == "closed"
        open_24_hours = entry.get("open_24_hours") is True or _clean(entry.get("status")).casefold() in {
            "open_24_hours", "open 24 hours", "24_hours",
        }
        ranges = []
        raw_ranges = entry.get("ranges") if isinstance(entry.get("ranges"), list) else []
        for raw_range in raw_ranges[:2]:
            if not isinstance(raw_range, dict):
                continue
            opens = normalize_hours_time(raw_range.get("opens"))
            closes = normalize_hours_time(raw_range.get("closes"), closing=True)
            if not opens or not closes:
                continue
            candidate = {"opens": opens, "closes": closes}
            if candidate not in ranges:
                ranges.append(candidate)
            if opens == "00:00" and closes in {"23:59", "24:00"}:
                open_24_hours = True
        if closed:
            normalized[day] = {"closed": True, "ranges": []}
        elif open_24_hours:
            normalized[day] = {
                "closed": False,
                "open_24_hours": True,
                "ranges": [{"opens": "00:00", "closes": "24:00"}],
            }
        else:
            normalized[day] = {"closed": False, "ranges": ranges}
    return {day: normalized[day] for day in WEEKDAYS if day in normalized}


def parse_weekly_hours_text(value):
    weekly = {}
    notes = ""
    for raw_line in str(value or "").splitlines():
        label, separator, detail = raw_line.partition(":")
        if not separator:
            continue
        key = _clean(label).casefold()
        detail = _clean(detail)
        if key == "notes":
            notes = detail
            continue
        day = _day_key(key)
        if not day:
            continue
        if detail.casefold() == "closed":
            weekly[day] = {"closed": True, "ranges": []}
            continue
        if detail.casefold() in {"open 24 hours", "open 24 hrs", "24 hours"}:
            weekly[day] = {"closed": False, "open_24_hours": True, "ranges": []}
            continue
        ranges = []
        for match in re.finditer(r"(\d{1,2}(?::\d{2})?\s*(?:[ap]m)?)\s*-\s*(\d{1,2}(?::\d{2})?\s*(?:[ap]m)?)", detail, re.I):
            opens = normalize_hours_time(match.group(1))
            closes = normalize_hours_time(match.group(2), closing=True)
            if opens and closes:
                ranges.append({"opens": opens, "closes": closes})
        weekly[day] = {"closed": False, "ranges": ranges[:2]}
    return normalize_weekly_hours(weekly), notes


def weekly_hours_to_text(value, notes=""):
    weekly = normalize_weekly_hours(value)
    lines = []
    for day in WEEKDAYS:
        entry = weekly.get(day)
        if not entry:
            continue
        if entry.get("closed"):
            detail = "Closed"
        elif entry.get("open_24_hours"):
            detail = "00:00-24:00"
        else:
            ranges = [
                f"{item['opens']}-{item['closes']}"
                for item in entry.get("ranges", [])
                if item.get("opens") and item.get("closes")
            ]
            detail = ", ".join(ranges) or "Open"
        lines.append(f"{DAY_LABELS[day]}: {detail}")
    if _clean(notes):
        lines.append(f"Notes: {_clean(notes)}")
    return "\n".join(lines)
