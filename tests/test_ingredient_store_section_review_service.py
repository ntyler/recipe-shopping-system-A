from PushShoppingList.services import ingredient_store_section_review_service as review_service


def candidate(deterministic_section="SPICES & SEASONINGS"):
    return {
        "ingredient_id": 12,
        "ingredient": "Ground ginger",
        "normalized_name": "ground ginger",
        "canonical_ingredient": "ginger",
        "form": "ground",
        "image_url": "/static/generated/ingredients/ground-ginger.png",
        "recipe_context": [{"source_text": "1 tsp ground ginger"}],
        "deterministic": (
            {
                "store_section": deterministic_section,
                "confidence": 1.0,
                "reason": "Known mapping.",
            }
            if deterministic_section
            else None
        ),
    }


def test_ai_store_section_prompt_is_independent_and_requires_structured_categories():
    prompt = review_service.build_ai_store_section_review_prompt([candidate()])

    assert "deliberately NOT being shown another classifier's recommendation" in prompt
    assert '"raw_name": "Ground ginger"' in prompt
    assert '"form": "ground"' in prompt
    assert "SPICES & SEASONINGS" not in prompt
    assert "Canned Goods" in prompt
    assert '"store_section": "Spices"' in prompt
    assert '"confidence": 0.97' in prompt


def test_validate_ai_store_section_opinion_reports_agreement_and_disagreement():
    agrees = review_service.validate_ai_store_section_opinion(
        {
            "ingredient_id": 12,
            "store_section": "Spices",
            "confidence": 0.98,
            "reason": "Ground ginger is a dried seasoning.",
            "normalized_name": "ground ginger",
        },
        candidate(),
    )
    disagrees = review_service.validate_ai_store_section_opinion(
        {
            "ingredient_id": 12,
            "store_section": "Produce",
            "confidence": 0.62,
            "reason": "The form was interpreted as fresh.",
            "normalized_name": "ground ginger",
        },
        candidate(),
    )
    invalid = review_service.validate_ai_store_section_opinion(
        {"ingredient_id": 12, "store_section": "Hardware"},
        candidate(),
    )

    assert agrees["store_section"] == "SPICES & SEASONINGS"
    assert agrees["agreement"] == "agree"
    assert agrees["image_url"] == "/static/generated/ingredients/ground-ginger.png"
    assert disagrees["store_section"] == "PRODUCE"
    assert disagrees["agreement"] == "disagree"
    assert invalid is None


def test_ai_review_uses_user_scoped_candidates_and_validates_results(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        review_service.master_data,
        "misc_ingredient_store_section_review_candidates",
        lambda **kwargs: {
            "ok": True,
            "user_id": kwargs.get("user_id"),
            "scope": kwargs.get("scope"),
            "candidates": [candidate()],
        },
    )

    def fake_request(candidates, user_id=None):
        calls.append({"candidates": candidates, "user_id": user_id})
        return [{
            "ingredient_id": 12,
            "store_section": "Spices",
            "confidence": 0.97,
            "reason": "Ground ginger is a dried powdered seasoning.",
            "normalized_name": "ground ginger",
        }]

    monkeypatch.setattr(review_service, "request_ai_store_section_opinions", fake_request)
    result = review_service.review_misc_ingredient_store_sections_with_ai(
        user_id="user-a",
        scope="suggested",
        ingredient_ids=[12],
    )

    assert result["ok"] is True
    assert result["opinion_count"] == 1
    assert result["opinions"][0]["agreement"] == "agree"
    assert calls[0]["user_id"] == "user-a"
