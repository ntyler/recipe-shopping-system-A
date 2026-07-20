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
    assert first_scan["scan"]["review_count"] == 1
    assert first_scan["scan"]["scanned_at"]
    assert duplicate_reviews.duplicate_scan_summary("user-a") == first_scan["scan"]
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


def test_suspicious_unit_as_ingredient_reference_blocks_merge(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/teaspoon",
        recipe_data={"ingredients": [{"ingredient": "Teaspoon", "original_text": "teaspoon"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/teaspoons",
        recipe_data={"ingredients": [{"ingredient": "Teaspoons", "original_text": "teaspoons"}]},
        user_id="user-a",
    )
    teaspoon = master_data.master_record_for_name("ingredients", "user-a", "teaspoon")
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE recipe_ingredients
               SET original_recipe_text = 'soy sauce', unit = '', unit_id = NULL
             WHERE user_id = ? AND ingredient_id = ?
            """,
            ("user-a", teaspoon["id"]),
        )

    review = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"][0]

    assert review["merge_blocked"] is True
    assert review["left"]["data_quality_issue_count"] + review["right"]["data_quality_issue_count"] == 1
    assert review["data_quality_issues"][0]["source_text"] == "soy sauce"
    result = duplicate_reviews.decide_duplicate_review(
        review["review_id"],
        "merge",
        target_ingredient_id=review["suggested_target_id"],
        user_id="user-a",
    )
    assert result["ok"] is False
    assert result["status"] == 409
    assert result["merge_blocked"] is True


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


def test_ai_second_opinion_uses_raw_records_and_warns_when_usage_is_missing():
    candidate = duplicate_reviews.candidate_ingredient_pairs([
        ingredient_row(1, "bell pepper", 0),
        ingredient_row(2, "bell peppers", 0),
    ])[0]
    payload = duplicate_reviews.second_opinion_candidate_payload(candidate)
    opinion = duplicate_reviews.validate_ai_second_opinion(
        {
            "pair_key": candidate["pair_key"],
            "verdict": "merge",
            "confidence": 0.93,
            "suggested_target_id": 1,
            "evidence": ["The names differ only by pluralization."],
            "warnings": [],
        },
        candidate,
    )

    assert set(payload) == {"pair_key", "left", "right"}
    assert "signals" not in payload
    assert "classification" not in payload
    assert opinion["status"] == "ready"
    assert opinion["verdict"] == "merge"
    assert "Neither record has recipe usage" in opinion["warnings"][0]


def test_scan_generates_and_caches_independent_ai_second_opinions(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(duplicate_reviews, "request_ai_classifications", lambda _candidates: [])
    opinion_calls = []

    def fake_second_opinions(candidates, user_id=None):
        opinion_calls.append((len(candidates), user_id))
        return [{
            "pair_key": candidates[0]["pair_key"],
            "verdict": "merge",
            "confidence": 0.97,
            "suggested_target_id": int(candidates[0]["left"]["id"]),
            "evidence": ["Both recipe contexts use the same base ingredient."],
            "warnings": [],
        }]

    monkeypatch.setattr(duplicate_reviews, "request_ai_second_opinions", fake_second_opinions)

    first_scan = duplicate_reviews.scan_potential_duplicates("user-a")
    second_scan = duplicate_reviews.scan_potential_duplicates("user-a")
    opinion = second_scan["reviews"][0]["ai_second_opinion"]

    assert first_scan["reviews"][0]["ai_second_opinion"]["status"] == "ready"
    assert opinion["verdict"] == "merge"
    assert opinion["agreement"] == "agree"
    assert opinion["evidence"] == ["Both recipe contexts use the same base ingredient."]
    assert opinion_calls == [(1, "user-a")]


def test_ai_second_opinion_can_be_generated_on_demand_and_reuses_cache(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    review = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"][0]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []

    def fake_second_opinions(candidates, user_id=None):
        calls.append(candidates[0]["pair_key"])
        return [{
            "pair_key": candidates[0]["pair_key"],
            "verdict": "merge",
            "confidence": 0.95,
            "suggested_target_id": int(candidates[0]["left"]["id"]),
            "evidence": ["The records are singular and plural forms of one ingredient."],
            "warnings": [],
        }]

    monkeypatch.setattr(duplicate_reviews, "request_ai_second_opinions", fake_second_opinions)

    generated = duplicate_reviews.generate_ai_second_opinion(
        review["review_id"],
        user_id="user-a",
    )
    cached = duplicate_reviews.generate_ai_second_opinion(
        review["review_id"],
        user_id="user-a",
    )

    assert generated["ok"] is True
    assert generated["cache_hit"] is False
    assert generated["ai_second_opinion"]["agreement"] == "agree"
    assert cached["ok"] is True
    assert cached["cache_hit"] is True
    assert calls == [f"{review['left']['ingredient_id']}:{review['right']['ingredient_id']}"]


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


def test_bulk_decisions_apply_multiple_review_choices(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    master_data.sync_recipe_master_records(
        "https://example.com/tomato",
        recipe_data={"ingredients": [{"ingredient": "Tomato", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/tomatoes",
        recipe_data={"ingredients": [{"ingredient": "Tomatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    reviews = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"]

    result = duplicate_reviews.decide_duplicate_reviews(
        [
            {"review_id": review["review_id"], "action": "related"}
            for review in reviews
        ],
        user_id="user-a",
    )

    assert result["ok"] is True
    assert result["complete"] is True
    assert result["requested_count"] == len(reviews)
    assert result["succeeded_count"] == len(reviews)
    assert result["failed_count"] == 0
    assert result["merged_count"] == 0
    assert duplicate_reviews.list_duplicate_reviews("user-a") == []


def test_bulk_merge_uses_each_suggested_survivor(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    master_data.sync_recipe_master_records(
        "https://example.com/tomato",
        recipe_data={"ingredients": [{"ingredient": "Tomato", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/tomatoes",
        recipe_data={"ingredients": [{"ingredient": "Tomatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    reviews = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"]
    exact_reviews = [review for review in reviews if review["signals"].get("singular_exact")]

    result = duplicate_reviews.decide_duplicate_reviews(
        [
            {
                "review_id": review["review_id"],
                "action": "merge",
                "target_ingredient_id": review["suggested_target_id"],
            }
            for review in exact_reviews
        ],
        user_id="user-a",
    )

    assert result["complete"] is True
    assert result["merged_count"] == 2
    assert len(master_data.list_ingredients(user_id="user-a", search="potatoes")) == 1
    assert len(master_data.list_ingredients(user_id="user-a", search="tomatoes")) == 1


def test_undo_merge_restores_duplicate_review_to_pending(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    review = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"][0]

    merge_result = duplicate_reviews.decide_duplicate_review(
        review["review_id"],
        "merge",
        target_ingredient_id=review["suggested_target_id"],
        user_id="user-a",
    )
    undo_result = master_data.undo_last_ingredient_master_merge("user-a")
    restored_reviews = duplicate_reviews.list_duplicate_reviews("user-a")

    assert merge_result["ok"] is True
    assert undo_result["ok"] is True
    assert [item["review_id"] for item in restored_reviews] == [review["review_id"]]
    assert restored_reviews[0]["status"] == "pending"


def test_bulk_merge_rejects_lower_confidence_spelling_candidates(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/potatoes",
        recipe_data={"ingredients": [{"ingredient": "Potatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/tomatoes",
        recipe_data={"ingredients": [{"ingredient": "Tomatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    review = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"][0]

    result = duplicate_reviews.decide_duplicate_reviews(
        [{
            "review_id": review["review_id"],
            "action": "merge",
            "target_ingredient_id": review["suggested_target_id"],
        }],
        user_id="user-a",
    )

    assert result["complete"] is False
    assert result["succeeded_count"] == 0
    assert result["failed_count"] == 1
    assert "high-confidence" in result["results"][0]["error"]
    assert master_data.count_ingredients(user_id="user-a") == 2


def test_bulk_decisions_report_item_failures_without_rolling_back_success(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    seed_pair()
    review = duplicate_reviews.scan_potential_duplicates("user-a")["reviews"][0]

    result = duplicate_reviews.decide_duplicate_reviews(
        [
            {"review_id": review["review_id"], "action": "not_duplicate"},
            {"review_id": 999999, "action": "not_duplicate"},
        ],
        user_id="user-a",
    )

    assert result["ok"] is True
    assert result["complete"] is False
    assert result["succeeded_count"] == 1
    assert result["failed_count"] == 1
    assert result["results"][1]["status"] == 404
