from PushShoppingList.services import recipe_url_service


def test_recipe_url_rows_reads_recipe_metadata_once(monkeypatch):
    urls = [
        "https://example.com/black-bean-tacos",
        "https://example.com/green-curry",
        "manual://family-soup",
    ]
    metadata_calls = []
    metadata = {
        recipe_url_service.normalize_recipe_url_key(urls[0]): {
            "name": "Black Bean Tacos",
            "quantity": "2",
        },
        recipe_url_service.normalize_recipe_url_key(urls[1]): {
            "name": "Green Curry",
            "quantity": "1/2",
        },
    }

    def load_recipe_url_meta_once():
        metadata_calls.append(True)
        return metadata

    monkeypatch.setattr(recipe_url_service, "load_recipe_urls", lambda: urls)
    monkeypatch.setattr(recipe_url_service, "load_recipe_url_meta", load_recipe_url_meta_once)

    rows = recipe_url_service.recipe_url_rows()

    assert len(metadata_calls) == 1
    assert [row["name"] for row in rows] == [
        "Black Bean Tacos",
        "Green Curry",
        "Family Soup",
    ]
    assert [row["quantity"] for row in rows] == [2, 0.5, 1]
