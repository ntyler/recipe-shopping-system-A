from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SHOPPING_LIST_FILE = BASE_DIR / "shopping_list.txt"


def load_items():
    if not SHOPPING_LIST_FILE.exists():
        return []

    return [
        line.strip()
        for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def save_items(items):
    SHOPPING_LIST_FILE.write_text(
        "\n".join(items) + ("\n" if items else ""),
        encoding="utf-8",
    )


def add_items(new_items):
    items = load_items()

    for item in new_items:
        item = str(item).strip()

        if item and item not in items:
            items.append(item)

    save_items(items)