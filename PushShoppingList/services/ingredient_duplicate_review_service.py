import json
import os
import re
from difflib import SequenceMatcher

from openai import OpenAI

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services.ingredient_unit_service import misplaced_unit_ingredient_details
from PushShoppingList.services.openai_model_service import supports_custom_temperature
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_usage_service import record_openai_usage


MODEL = os.getenv(
    "OPENAI_INGREDIENT_REVIEW_MODEL",
    os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini"),
)
MAX_SCAN_RECORDS = 500
MAX_AI_CANDIDATES = 40
VALID_CLASSIFICATIONS = {"duplicate", "related", "different"}
DECISION_STATUSES = {"dismissed", "related", "merged"}
IRREGULAR_SINGULARS = {
    "leaves": "leaf",
    "loaves": "loaf",
    "potatoes": "potato",
    "tomatoes": "tomato",
}
client = None


def get_openai_client():
    global client
    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45)
    return client


def singular_token(value):
    token = master_data.normalized_master_name(value)
    if token in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[token]
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith(("ches", "shes", "sses", "xes", "zes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def singular_name(value):
    normalized = master_data.normalized_master_name(value)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return " ".join(singular_token(token) for token in tokens)


def ingredient_pair_signals(left, right):
    left_name = master_data.normalized_master_name(left.get("normalized_name") or left.get("name"))
    right_name = master_data.normalized_master_name(right.get("normalized_name") or right.get("name"))
    left_singular = singular_name(left_name)
    right_singular = singular_name(right_name)
    left_tokens = set(left_singular.split())
    right_tokens = set(right_singular.split())
    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    token_similarity = len(intersection) / len(union) if union else 0.0
    spelling_similarity = SequenceMatcher(None, left_name, right_name).ratio()
    singular_exact = bool(left_singular and left_singular == right_singular)
    token_subset = bool(intersection and (left_tokens <= right_tokens or right_tokens <= left_tokens))
    left_aliases = {
        singular_name(alias)
        for alias in left.get("aliases", [])
        if singular_name(alias)
    }
    right_aliases = {
        singular_name(alias)
        for alias in right.get("aliases", [])
        if singular_name(alias)
    }
    alias_match = bool(
        left_singular in right_aliases
        or right_singular in left_aliases
        or left_aliases & right_aliases
    )
    same_store_section = (
        master_data.clean_ingredient_store_section(left.get("store_section"))
        == master_data.clean_ingredient_store_section(right.get("store_section"))
    )

    score = 0.0
    if singular_exact:
        score = 0.99
    elif alias_match:
        score = 0.98
    else:
        if token_subset:
            score = max(score, 0.76)
        if token_similarity >= 0.5:
            score = max(score, 0.58 + (0.24 * token_similarity))
        if spelling_similarity >= 0.72:
            score = max(score, 0.48 + (0.42 * spelling_similarity))
        if same_store_section and score:
            score = min(0.97, score + 0.03)

    return {
        "singular_exact": singular_exact,
        "alias_match": alias_match,
        "token_subset": token_subset,
        "same_store_section": same_store_section,
        "token_similarity": round(token_similarity, 3),
        "spelling_similarity": round(spelling_similarity, 3),
        "candidate_score": round(score, 3),
    }


def local_candidate_classification(candidate):
    signals = candidate["signals"]
    if signals.get("singular_exact") or signals.get("alias_match"):
        return {
            "classification": "duplicate",
            "confidence": max(0.94, signals.get("candidate_score", 0)),
            "reason": "The names resolve to the same singular ingredient name.",
        }
    if signals.get("token_subset"):
        return {
            "classification": "related",
            "confidence": max(0.64, signals.get("candidate_score", 0)),
            "reason": "The names share a base ingredient, but one has extra variant or preparation detail.",
        }
    return {
        "classification": "duplicate",
        "confidence": max(0.55, signals.get("candidate_score", 0)),
        "reason": "The names have similar spelling or ingredient tokens and should be reviewed.",
    }


def candidate_ingredient_pairs(rows, excluded_pairs=None, limit=MAX_AI_CANDIDATES):
    excluded_pairs = set(excluded_pairs or set())
    candidates = []
    rows = [dict(row) for row in rows if isinstance(row, dict)]
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1:]:
            pair_left = left
            pair_right = right
            left_id = int(pair_left.get("id") or 0)
            right_id = int(pair_right.get("id") or 0)
            if left_id <= 0 or right_id <= 0:
                continue
            if left_id > right_id:
                pair_left, pair_right = pair_right, pair_left
                left_id, right_id = right_id, left_id
            pair = (left_id, right_id)
            if pair in excluded_pairs:
                continue
            signals = ingredient_pair_signals(pair_left, pair_right)
            if signals["candidate_score"] < 0.60:
                continue
            candidate = {
                "pair_key": f"{left_id}:{right_id}",
                "left": pair_left,
                "right": pair_right,
                "signals": signals,
            }
            candidate.update(local_candidate_classification(candidate))
            candidates.append(candidate)
    candidates.sort(
        key=lambda row: (
            -float(row["signals"].get("candidate_score") or 0),
            -int(row["left"].get("usage_count") or 0) - int(row["right"].get("usage_count") or 0),
            row["pair_key"],
        )
    )
    return candidates[:max(1, min(int(limit or MAX_AI_CANDIDATES), MAX_AI_CANDIDATES))]


def ai_candidate_payload(candidate):
    def record_payload(row):
        return {
            "ingredient_id": int(row.get("id") or 0),
            "name": master_data.clean_text(row.get("name")),
            "normalized_name": master_data.normalized_master_name(
                row.get("normalized_name") or row.get("name")
            ),
            "aliases": [master_data.clean_text(value) for value in row.get("aliases", [])],
            "store_section": master_data.clean_ingredient_store_section(row.get("store_section")),
            "usage_count": int(row.get("usage_count") or 0),
        }

    return {
        "pair_key": candidate["pair_key"],
        "left": record_payload(candidate["left"]),
        "right": record_payload(candidate["right"]),
        "signals": candidate["signals"],
    }


def build_duplicate_review_prompt(candidates):
    return f"""
Classify each candidate pair of grocery ingredient master records.

Candidate pairs:
{json.dumps([ai_candidate_payload(candidate) for candidate in candidates], ensure_ascii=False)}

Use exactly one classification for every pair:
- duplicate: the same grocery ingredient identity, including singular/plural, spelling, or harmless formatting differences;
- related: the same base ingredient but a meaningful subtype, preparation, form, or variant should be preserved;
- different: distinct grocery ingredients that must remain separate.

Examples:
- potato / potatoes = duplicate
- inca pepper / yellow inca peppers = related unless the names clearly refer to the same market item
- corn / cooked corn kernels = related
- sweet potato / potato = different

Store section is supporting context, never proof by itself. Be conservative about duplicate because a person may use the recommendation to merge records. The application will require human approval and will never merge automatically.

Return ONLY valid JSON with this shape:
{{
  "reviews": [
    {{
      "pair_key": "12:34",
      "classification": "duplicate",
      "confidence": 0.97,
      "reason": "Short, specific explanation.",
      "suggested_target_id": 12
    }}
  ]
}}
"""


def clean_json_response(value):
    text = str(value or "").strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    return re.sub(r"```$", "", text).strip()


def request_ai_classifications(candidates):
    request_payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You classify possible duplicate grocery ingredient records. Return only valid JSON.",
            },
            {"role": "user", "content": build_duplicate_review_prompt(candidates)},
        ],
        "response_format": {"type": "json_object"},
    }
    if supports_custom_temperature(MODEL):
        request_payload["temperature"] = 0
    response = throttled_chat_completion(
        get_openai_client(),
        request_payload,
        action_name="ingredient-duplicate-review",
        model=MODEL,
    )
    record_openai_usage(response, "ingredient-duplicate-review", model=MODEL)
    data = json.loads(clean_json_response(response.choices[0].message.content))
    return data.get("reviews", []) if isinstance(data, dict) else []


def classify_candidate_pairs(candidates):
    results = {}
    for candidate in candidates:
        local_result = dict(local_candidate_classification(candidate))
        local_result.update({"analysis_source": "local", "model": ""})
        results[candidate["pair_key"]] = local_result
    source = "local"
    warning = ""
    if not candidates:
        return {"results": results, "source": source, "model": "", "warning": warning}
    if not os.getenv("OPENAI_API_KEY"):
        warning = "OpenAI is not configured, so these suggestions use local similarity checks."
        return {"results": results, "source": source, "model": "", "warning": warning}

    try:
        raw_reviews = request_ai_classifications(candidates)
        valid_pair_ids = {
            candidate["pair_key"]: {
                int(candidate["left"].get("id") or 0),
                int(candidate["right"].get("id") or 0),
            }
            for candidate in candidates
        }
        for review in raw_reviews if isinstance(raw_reviews, list) else []:
            if not isinstance(review, dict):
                continue
            pair_key = master_data.clean_text(review.get("pair_key"))
            classification = master_data.clean_text(review.get("classification")).lower()
            if pair_key not in results or classification not in VALID_CLASSIFICATIONS:
                continue
            candidate = next(
                (item for item in candidates if item["pair_key"] == pair_key),
                None,
            )
            if candidate and (
                candidate["signals"].get("singular_exact")
                or candidate["signals"].get("alias_match")
            ):
                continue
            try:
                confidence = float(review.get("confidence"))
            except (TypeError, ValueError):
                confidence = results[pair_key]["confidence"]
            try:
                suggested_target_id = int(review.get("suggested_target_id") or 0)
            except (TypeError, ValueError):
                suggested_target_id = 0
            if suggested_target_id not in valid_pair_ids[pair_key]:
                suggested_target_id = 0
            results[pair_key] = {
                "classification": classification,
                "confidence": max(0.0, min(1.0, confidence)),
                "reason": master_data.clean_text(review.get("reason"))
                or results[pair_key]["reason"],
                "suggested_target_id": suggested_target_id or None,
                "analysis_source": "ai",
                "model": MODEL,
            }
        source = "ai"
    except Exception:
        warning = "AI classification was unavailable, so these suggestions use local similarity checks."
    return {"results": results, "source": source, "model": MODEL if source == "ai" else "", "warning": warning}


def _resolved_target_id(candidate, classification):
    requested = classification.get("suggested_target_id")
    pair_ids = {
        int(candidate["left"].get("id") or 0),
        int(candidate["right"].get("id") or 0),
    }
    if requested in pair_ids:
        return requested
    rows = [candidate["left"], candidate["right"]]
    rows.sort(key=lambda row: (-int(row.get("usage_count") or 0), int(row.get("id") or 0)))
    return int(rows[0].get("id") or 0)


def _manual_decision_pairs(connection, user_id):
    rows = connection.execute(
        """
        SELECT left_ingredient_id, right_ingredient_id
          FROM ingredient_duplicate_reviews
         WHERE user_id = ?
           AND status IN ('dismissed', 'related', 'merged')
        """,
        (user_id,),
    ).fetchall()
    return {(int(row["left_ingredient_id"]), int(row["right_ingredient_id"])) for row in rows}


def _ingredient_reference_quality_issues(connection, user_id, ingredient_names):
    ingredient_names = {
        int(ingredient_id): master_data.clean_text(name)
        for ingredient_id, name in (ingredient_names or {}).items()
        if int(ingredient_id or 0) > 0
    }
    if not ingredient_names:
        return {}

    placeholders = ", ".join("?" for _ingredient_id in ingredient_names)
    rows = connection.execute(
        f"""
        SELECT ingredient_id, recipe_id, unit, original_recipe_text
          FROM recipe_ingredients
         WHERE user_id = ?
           AND ingredient_id IN ({placeholders})
         ORDER BY ingredient_id ASC, LOWER(recipe_id) ASC, sort_order ASC, id ASC
        """,
        (user_id, *ingredient_names),
    ).fetchall()
    issues = {}
    for row in rows:
        ingredient_id = int(row["ingredient_id"])
        ingredient_name = ingredient_names.get(ingredient_id, "")
        mismatch = misplaced_unit_ingredient_details(
            ingredient_name,
            row["original_recipe_text"],
            row["unit"],
        )
        if not mismatch:
            continue
        issues.setdefault(ingredient_id, []).append({
            "ingredient_id": ingredient_id,
            "ingredient_name": ingredient_name,
            "recipe_id": master_data.clean_text(row["recipe_id"]),
            "source_text": master_data.clean_text(row["original_recipe_text"]),
            "misplaced_unit": mismatch["unit"],
            "message": (
                f"{ingredient_name} appears to be a misplaced unit for "
                f"{master_data.clean_text(row['original_recipe_text'])}."
            ),
        })
    return issues


def duplicate_scan_summary(user_id=None):
    scoped_user_id = master_data.scoped_recipe_user_id(user_id)
    with master_data.existing_recipe_master_connection() as connection:
        if connection is None:
            return {}
        row = connection.execute(
            """
            SELECT scanned_at, scanned_count, candidate_count, review_count
              FROM ingredient_duplicate_scans
             WHERE user_id = ?
            """,
            (scoped_user_id,),
        ).fetchone()
        if not row:
            row = connection.execute(
                """
                SELECT MAX(updated_at) AS scanned_at,
                       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS review_count,
                       (SELECT COUNT(*) FROM ingredients WHERE user_id = ?) AS scanned_count
                  FROM ingredient_duplicate_reviews
                 WHERE user_id = ?
                """,
                (scoped_user_id, scoped_user_id),
            ).fetchone()
            if not row or not master_data.clean_text(row["scanned_at"]):
                return {}
            review_count = int(row["review_count"] or 0)
            return {
                "scanned_at": master_data.clean_text(row["scanned_at"]),
                "scanned_count": int(row["scanned_count"] or 0),
                "candidate_count": review_count,
                "review_count": review_count,
                "inferred_from_reviews": True,
            }
    return {
        "scanned_at": master_data.clean_text(row["scanned_at"]),
        "scanned_count": int(row["scanned_count"] or 0),
        "candidate_count": int(row["candidate_count"] or 0),
        "review_count": int(row["review_count"] or 0),
    }


def scan_potential_duplicates(user_id=None):
    scoped_user_id = master_data.scoped_recipe_user_id(user_id)
    rows = master_data.list_ingredients(
        user_id=scoped_user_id,
        limit=MAX_SCAN_RECORDS,
        sort="name_asc",
    )
    with master_data.recipe_master_connection() as connection:
        excluded_pairs = _manual_decision_pairs(connection, scoped_user_id)
    candidates = candidate_ingredient_pairs(rows, excluded_pairs=excluded_pairs)
    classifications = classify_candidate_pairs(candidates)
    now = master_data.utc_now_iso()

    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE ingredient_duplicate_reviews
               SET status = 'stale', updated_at = ?
             WHERE user_id = ? AND status = 'pending'
            """,
            (now, scoped_user_id),
        )
        for candidate in candidates:
            left = candidate["left"]
            right = candidate["right"]
            result = classifications["results"].get(candidate["pair_key"], local_candidate_classification(candidate))
            connection.execute(
                """
                INSERT INTO ingredient_duplicate_reviews (
                    user_id, left_ingredient_id, right_ingredient_id,
                    left_name, right_name, left_normalized_name, right_normalized_name,
                    classification, status, confidence, reason, suggested_target_id,
                    signals_json, model, analysis_source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, left_ingredient_id, right_ingredient_id) DO UPDATE SET
                    left_name = excluded.left_name,
                    right_name = excluded.right_name,
                    left_normalized_name = excluded.left_normalized_name,
                    right_normalized_name = excluded.right_normalized_name,
                    classification = excluded.classification,
                    status = CASE
                        WHEN ingredient_duplicate_reviews.status IN ('dismissed', 'related', 'merged')
                            THEN ingredient_duplicate_reviews.status
                        ELSE 'pending'
                    END,
                    confidence = excluded.confidence,
                    reason = excluded.reason,
                    suggested_target_id = excluded.suggested_target_id,
                    signals_json = excluded.signals_json,
                    model = excluded.model,
                    analysis_source = excluded.analysis_source,
                    updated_at = excluded.updated_at
                """,
                (
                    scoped_user_id,
                    int(left["id"]),
                    int(right["id"]),
                    master_data.clean_text(left.get("name")),
                    master_data.clean_text(right.get("name")),
                    master_data.normalized_master_name(left.get("normalized_name") or left.get("name")),
                    master_data.normalized_master_name(right.get("normalized_name") or right.get("name")),
                    result["classification"],
                    float(result.get("confidence") or 0),
                    master_data.clean_text(result.get("reason")),
                    _resolved_target_id(candidate, result),
                    json.dumps(candidate["signals"], sort_keys=True),
                    master_data.clean_text(result.get("model")),
                    master_data.clean_text(result.get("analysis_source")) or "local",
                    now,
                    now,
                ),
            )

    reviews = list_duplicate_reviews(scoped_user_id)
    scan = {
        "scanned_at": now,
        "scanned_count": len(rows),
        "candidate_count": len(candidates),
        "review_count": len(reviews),
    }
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            INSERT INTO ingredient_duplicate_scans (
                user_id, scanned_at, scanned_count, candidate_count, review_count
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                scanned_at = excluded.scanned_at,
                scanned_count = excluded.scanned_count,
                candidate_count = excluded.candidate_count,
                review_count = excluded.review_count
            """,
            (
                scoped_user_id,
                scan["scanned_at"],
                scan["scanned_count"],
                scan["candidate_count"],
                scan["review_count"],
            ),
        )
    return {
        "ok": True,
        "user_id": scoped_user_id,
        "review_count": len(reviews),
        "reviews": reviews,
        "analysis_source": classifications["source"],
        "model": classifications["model"],
        "warning": classifications["warning"],
        "candidate_count": len(candidates),
        "scanned_count": len(rows),
        "scan_limited": len(rows) >= MAX_SCAN_RECORDS,
        "scan": scan,
    }


def _decode_signals(value):
    try:
        signals = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        signals = {}
    return signals if isinstance(signals, dict) else {}


def list_duplicate_reviews(user_id=None, status="pending"):
    scoped_user_id = master_data.scoped_recipe_user_id(user_id)
    status = master_data.clean_text(status).lower() or "pending"
    with master_data.existing_recipe_master_connection() as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT r.*,
                   left_item.name AS current_left_name,
                   left_item.normalized_name AS current_left_normalized_name,
                   left_item.store_section AS left_store_section,
                   left_item.image_url AS left_image_url,
                   right_item.name AS current_right_name,
                   right_item.normalized_name AS current_right_normalized_name,
                   right_item.store_section AS right_store_section,
                   right_item.image_url AS right_image_url,
                   (SELECT COUNT(*) FROM recipe_ingredients usage
                     WHERE usage.user_id = r.user_id AND usage.ingredient_id = r.left_ingredient_id) AS left_usage_count,
                   (SELECT COUNT(*) FROM recipe_ingredients usage
                     WHERE usage.user_id = r.user_id AND usage.ingredient_id = r.right_ingredient_id) AS right_usage_count,
                   COALESCE((SELECT GROUP_CONCAT(a.alias_name, CHAR(31)) FROM ingredient_aliases a
                     WHERE a.user_id = r.user_id AND a.ingredient_id = r.left_ingredient_id), '') AS left_aliases,
                   COALESCE((SELECT GROUP_CONCAT(a.alias_name, CHAR(31)) FROM ingredient_aliases a
                     WHERE a.user_id = r.user_id AND a.ingredient_id = r.right_ingredient_id), '') AS right_aliases
              FROM ingredient_duplicate_reviews r
              LEFT JOIN ingredients left_item
                ON left_item.id = r.left_ingredient_id AND left_item.user_id = r.user_id
              LEFT JOIN ingredients right_item
                ON right_item.id = r.right_ingredient_id AND right_item.user_id = r.user_id
             WHERE r.user_id = ? AND r.status = ?
               AND left_item.id IS NOT NULL AND right_item.id IS NOT NULL
             ORDER BY r.confidence DESC, r.updated_at DESC, r.id DESC
            """,
            (scoped_user_id, status),
        ).fetchall()
        ingredient_names = {}
        for row in rows:
            ingredient_names[int(row["left_ingredient_id"])] = master_data.clean_text(
                row["current_left_name"] or row["left_name"]
            )
            ingredient_names[int(row["right_ingredient_id"])] = master_data.clean_text(
                row["current_right_name"] or row["right_name"]
            )
        quality_issues = _ingredient_reference_quality_issues(
            connection,
            scoped_user_id,
            ingredient_names,
        )

    reviews = []
    for row in rows:
        item = dict(row)
        left_quality_issues = quality_issues.get(int(item["left_ingredient_id"]), [])
        right_quality_issues = quality_issues.get(int(item["right_ingredient_id"]), [])
        data_quality_issues = [*left_quality_issues, *right_quality_issues]
        review = {
            "review_id": int(item["id"]),
            "classification": item["classification"],
            "status": item["status"],
            "confidence": max(0.0, min(1.0, float(item["confidence"] or 0))),
            "reason": master_data.clean_text(item["reason"]),
            "suggested_target_id": int(item["suggested_target_id"] or 0) or None,
            "signals": _decode_signals(item["signals_json"]),
            "analysis_source": item["analysis_source"],
            "model": item["model"],
            "merge_blocked": bool(data_quality_issues),
            "data_quality_issues": data_quality_issues,
            "left": {
                "ingredient_id": int(item["left_ingredient_id"]),
                "name": master_data.clean_text(item["current_left_name"] or item["left_name"]),
                "normalized_name": master_data.normalized_master_name(
                    item["current_left_normalized_name"] or item["left_normalized_name"]
                ),
                "store_section": master_data.clean_ingredient_store_section(item["left_store_section"]),
                "image_url": master_data.clean_text(item["left_image_url"]),
                "usage_count": int(item["left_usage_count"] or 0),
                "aliases": [value for value in master_data.clean_text(item["left_aliases"]).split(chr(31)) if value],
                "data_quality_issue_count": len(left_quality_issues),
            },
            "right": {
                "ingredient_id": int(item["right_ingredient_id"]),
                "name": master_data.clean_text(item["current_right_name"] or item["right_name"]),
                "normalized_name": master_data.normalized_master_name(
                    item["current_right_normalized_name"] or item["right_normalized_name"]
                ),
                "store_section": master_data.clean_ingredient_store_section(item["right_store_section"]),
                "image_url": master_data.clean_text(item["right_image_url"]),
                "usage_count": int(item["right_usage_count"] or 0),
                "aliases": [value for value in master_data.clean_text(item["right_aliases"]).split(chr(31)) if value],
                "data_quality_issue_count": len(right_quality_issues),
            },
        }
        reviews.append(review)
    return reviews


def decide_duplicate_review(review_id, action, target_ingredient_id=None, user_id=None, allow_other_users=False):
    try:
        review_id = int(review_id or 0)
    except (TypeError, ValueError):
        review_id = 0
    action = master_data.clean_text(action).lower().replace("-", "_")
    if review_id <= 0 or action not in {"merge", "not_duplicate", "related"}:
        return {"ok": False, "status": 400, "error": "Choose a valid review action."}

    scoped_user_id = master_data.scoped_recipe_user_id(user_id)
    with master_data.existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "Duplicate review was not found."}
        review = connection.execute(
            "SELECT * FROM ingredient_duplicate_reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not review or (not allow_other_users and review["user_id"] != scoped_user_id):
            return {"ok": False, "status": 404, "error": "Duplicate review was not found."}
        if review["status"] != "pending":
            return {"ok": False, "status": 409, "error": "That pair has already been reviewed."}
        review_user_id = review["user_id"]
        left_id = int(review["left_ingredient_id"])
        right_id = int(review["right_ingredient_id"])

        if action == "merge":
            quality_issues = _ingredient_reference_quality_issues(
                connection,
                review_user_id,
                {
                    left_id: review["left_name"],
                    right_id: review["right_name"],
                },
            )
            if quality_issues:
                return {
                    "ok": False,
                    "status": 409,
                    "error": (
                        "Repair the suspicious recipe references before merging this ingredient pair."
                    ),
                    "merge_blocked": True,
                }

    now = master_data.utc_now_iso()
    if action == "merge":
        try:
            target_id = int(target_ingredient_id or 0)
        except (TypeError, ValueError):
            target_id = 0
        if target_id not in {left_id, right_id}:
            return {"ok": False, "status": 400, "error": "Choose which ingredient should survive the merge."}
        source_id = right_id if target_id == left_id else left_id
        merge_result = master_data.merge_ingredient_master_records(
            source_id,
            target_id,
            user_id=review_user_id,
            allow_other_users=allow_other_users,
        )
        if not merge_result.get("ok"):
            return merge_result
        with master_data.recipe_master_connection() as connection:
            connection.execute(
                """
                UPDATE ingredient_duplicate_reviews
                   SET status = 'merged', classification = 'duplicate',
                       suggested_target_id = ?, updated_at = ?
                 WHERE id = ?
                """,
                (target_id, now, review_id),
            )
            connection.execute(
                """
                UPDATE ingredient_duplicate_reviews
                   SET status = 'stale', updated_at = ?
                 WHERE user_id = ? AND status = 'pending' AND id != ?
                   AND (left_ingredient_id = ? OR right_ingredient_id = ?)
                """,
                (now, review_user_id, review_id, source_id, source_id),
            )
        return {"ok": True, "action": action, "review_id": review_id, "merge": merge_result}

    status = "related" if action == "related" else "dismissed"
    classification = "related" if action == "related" else "different"
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE ingredient_duplicate_reviews
               SET status = ?, classification = ?, updated_at = ?
             WHERE id = ? AND user_id = ? AND status = 'pending'
            """,
            (status, classification, now, review_id, review_user_id),
        )
    return {"ok": True, "action": action, "review_id": review_id, "status": status}


def decide_duplicate_reviews(decisions, user_id=None, allow_other_users=False, limit=100):
    if not isinstance(decisions, list) or not decisions:
        return {
            "ok": False,
            "status": 400,
            "error": "Choose at least one duplicate review.",
        }

    try:
        limit = max(1, min(int(limit or 100), 100))
    except (TypeError, ValueError):
        limit = 100

    results = []
    seen_review_ids = set()
    for raw_decision in decisions[:limit]:
        if not isinstance(raw_decision, dict):
            results.append({
                "ok": False,
                "review_id": 0,
                "error": "Invalid duplicate review decision.",
            })
            continue
        try:
            review_id = int(raw_decision.get("review_id") or 0)
        except (TypeError, ValueError):
            review_id = 0
        if review_id <= 0 or review_id in seen_review_ids:
            results.append({
                "ok": False,
                "review_id": review_id,
                "error": "Invalid or repeated duplicate review.",
            })
            continue
        seen_review_ids.add(review_id)
        action = master_data.clean_text(raw_decision.get("action")).lower().replace("-", "_")
        if action == "merge":
            scoped_user_id = master_data.scoped_recipe_user_id(user_id)
            with master_data.existing_recipe_master_connection() as connection:
                review = connection.execute(
                    "SELECT user_id, classification, confidence, signals_json "
                    "FROM ingredient_duplicate_reviews WHERE id = ?",
                    (review_id,),
                ).fetchone() if connection is not None else None
            if review and (allow_other_users or review["user_id"] == scoped_user_id):
                signals = _decode_signals(review["signals_json"])
                high_confidence_duplicate = (
                    review["classification"] == "duplicate"
                    and float(review["confidence"] or 0) >= 0.98
                    and bool(signals.get("singular_exact") or signals.get("alias_match"))
                )
                if not high_confidence_duplicate:
                    results.append({
                        "ok": False,
                        "status": 400,
                        "review_id": review_id,
                        "error": (
                            "Bulk merge is limited to high-confidence singular/plural or alias matches."
                        ),
                    })
                    continue
        result = decide_duplicate_review(
            review_id,
            action,
            target_ingredient_id=raw_decision.get("target_ingredient_id"),
            user_id=user_id,
            allow_other_users=allow_other_users,
        )
        results.append(result)

    succeeded_count = sum(1 for result in results if result.get("ok"))
    failed_count = len(results) - succeeded_count
    merged_count = sum(
        1
        for result in results
        if result.get("ok") and result.get("action") == "merge"
    )
    return {
        "ok": True,
        "complete": failed_count == 0,
        "requested_count": min(len(decisions), limit),
        "succeeded_count": succeeded_count,
        "failed_count": failed_count,
        "merged_count": merged_count,
        "results": results,
    }
