from PushShoppingList.services import ingredient_duplicate_review_service as duplicate_reviews
from PushShoppingList.services import recipe_master_data_service as master_data


def configure_master_db(monkeypatch, tmp_path):
    db_path = tmp_path / "recipe_master.sqlite3"
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return db_path


def ingredient_row(ingredient_id, name, usage_count=1):
    return {
        "id": ingredient_id,
        "name": name,
        "normalized_name": name.lower(),
        "store_section": "PRODUCE",
        "usage_count": usage_count,
        "aliases": [],
    }


def seed_pair(user_id="user-a"):
    master_data.sync_recipe_master_records(
        "https://example.com/potato",
        recipe_data={"ingredients": [{"ingredient": "Potato", "store_section": "Produce"}]},
        user_id=user_id,
    )
    master_data.sync_recipe_master_records(
        "https://example.com/potatoes",
        recipe_data={"ingredients": [{"ingredient": "Potatoes", "store_section": "Produce"}]},
        user_id=user_id,
    )


def test_candidate_generation_finds_plural_spelling_and_related_names():
    rows = [
        ingredient_row(1, "potato", 8),
        ingredient_row(2, "potatoes", 2),
        ingredient_row(3, "sweet potato", 3),
        ingredient_row(4, "inca pepper", 2),
        ingredient_row(5, "yellow inca peppers"),
        ingredient_row(6, "corn", 4),
        ingredient_row(7, "cooked corn kernels"),
    ]

    candidates = duplicate_reviews.candidate_ingredient_pairs(rows)
    by_pair = {candidate["pair_key"]: candidate for candidate in candidates}

    assert by_pair["1:2"]["classification"] == "duplicate"
    assert by_pair["1:2"]["signals"]["singular_exact"] is True
    assert by_pair["4:5"]["signals"]["token_subset"] is True
    assert by_pair["6:7"]["classification"] == "related"
    assert by_pair["1:3"]["classification"] == "related"


def test_scan_persists_reviews_and_rejected_pairs_do_not_return(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()

    first_scan = duplicate_reviews.scan_potential_duplicates("user-a")

    assert first_scan["ok"] is True
    assert first_scan["analysis_source"] == "local"
    assert first_scan["review_count"] == 1
    assert first_scan["reviews"][0]["classification"] == "duplicate"
    review_id = first_scan["reviews"][0]["review_id"]

    decision = duplicate_reviews.decide_duplicate_review(
        review_id,
        "not_duplicate",
        user_id="user-a",
    )
    second_scan = duplicate_reviews.scan_potential_duplicates("user-a")

    assert decision == {
        "ok": True,
        "action": "not_duplicate",
        "review_id": review_id,
        "status": "dismissed",
    }
    assert second_scan["review_count"] == 0
    assert duplicate_reviews.list_duplicate_reviews("user-a") == []
    with master_data.recipe_master_connection() as connection:
        row = connection.execute(
            "SELECT status, classification FROM ingredient_duplicate_reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
    assert row["status"] == "dismissed"
    assert row["classification"] == "different"


def test_related_decision_is_durable(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    review = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"][0]

    decision = duplicate_reviews.decide_duplicate_review(
        review["review_id"],
        "related",
        user_id="user-a",
    )

    assert decision["status"] == "related"
    assert duplicate_reviews.scan_potential_duplicates("user-a")["review_count"] == 0


def test_approved_merge_relinks_usage_and_preserves_alias(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    scan = duplicate_reviews.scan_potential_duplicates("user-a")
    review = scan["reviews"][0]
    potato = master_data.master_record_for_name("ingredients", "user-a", "potato")

    result = duplicate_reviews.decide_duplicate_review(
        review["review_id"],
        "merge",
        target_ingredient_id=potato["id"],
        user_id="user-a",
    )

    assert result["ok"] is True
    assert result["merge"]["combined_usage_count"] == 2
    assert master_data.master_record_for_name("ingredients", "user-a", "potatoes") is None
    matches = master_data.list_ingredients(user_id="user-a", search="potatoes")
    assert len(matches) == 1
    assert matches[0]["id"] == potato["id"]
    assert matches[0]["aliases"] == ["Potatoes"]


def test_ai_classifications_are_validated_and_do_not_merge(monkeypatch):
    candidates = duplicate_reviews.candidate_ingredient_pairs([
        ingredient_row(1, "potato", 8),
        ingredient_row(2, "sweet potato", 2),
    ])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        duplicate_reviews,
        "request_ai_classifications",
        lambda _candidates: [{
            "pair_key": "1:2",
            "classification": "different",
            "confidence": 0.91,
            "reason": "Sweet potato is a distinct ingredient.",
            "suggested_target_id": 1,
        }],
    )

    result = duplicate_reviews.classify_candidate_pairs(candidates)

    assert result["source"] == "ai"
    assert result["results"]["1:2"] == {
        "classification": "different",
        "confidence": 0.91,
        "reason": "Sweet potato is a distinct ingredient.",
        "suggested_target_id": 1,
        "analysis_source": "ai",
        "model": duplicate_reviews.MODEL,
    }


def test_ai_cannot_downgrade_exact_singular_plural_guardrail(monkeypatch):
    candidates = duplicate_reviews.candidate_ingredient_pairs([
        ingredient_row(1, "large onion", 8),
        ingredient_row(2, "large onions", 2),
    ])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        duplicate_reviews,
        "request_ai_classifications",
        lambda _candidates: [{
            "pair_key": "1:2",
            "classification": "different",
            "confidence": 0.99,
            "reason": "Incorrect model response.",
            "suggested_target_id": 1,
        }],
    )

    result = duplicate_reviews.classify_candidate_pairs(candidates)

    assert result["source"] == "ai"
    assert result["results"]["1:2"]["classification"] == "duplicate"
    assert result["results"]["1:2"]["analysis_source"] == "local"


def test_decision_cannot_cross_workspaces(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair(user_id="user-b")
    review = duplicate_reviews.scan_potential_duplicates("user-b")["reviews"][0]

    result = duplicate_reviews.decide_duplicate_review(
        review["review_id"],
        "not_duplicate",
        user_id="user-a",
    )

    assert result["ok"] is False
    assert result["status"] == 404
