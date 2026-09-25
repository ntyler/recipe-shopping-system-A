"""Exercise saved groups through the actual scheduling model and meal APIs."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_family_members import scoped_client, sign_in


MODEL = Path(__file__).resolve().parents[1] / "PushShoppingList/static/js/meal-plan-schedule.js"


def schedule_payload(registry, group_ids, *, customize=False, dates=("2026-10-05", "2026-10-07")):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for the shared scheduling model")
    script = r"""
const fs = require('node:fs');
require(process.argv[1]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const M = globalThis.MealPlanSchedule;
const draft = M.create({today:'2026-10-05', members:input.registry.members, groups:input.registry.groups});
M.setDates(draft, input.dates);
M.setMeals(draft, ['breakfast','dinner']);
M.setPortionMode(draft, 'family');
M.selectGroupMembers(draft, input.group_ids);
if (input.customize) {
    const child = draft.members.find(member => member.name === 'Ava');
    M.setDayFamily(draft, '2026-10-07', child.id, 'dinner', {servings:0.25});
}
draft.notes = 'Pack individual portions';
process.stdout.write(JSON.stringify(M.payload(draft)));
"""
    result = subprocess.run(
        [node, "-e", script, str(MODEL)],
        input=json.dumps({"registry": registry, "group_ids": group_ids, "customize": customize, "dates": dates}),
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {"recipe_url": "recipe://soup", **json.loads(result.stdout)}


def test_groups_bulk_people_schedule_and_historical_meals_stay_synchronized(scoped_client):
    client = scoped_client
    sign_in(client, "family-owner")
    family = client.post("/api/meal-plan/groups", json={"name": "Tyler Family"}).json["group"]
    work = client.post("/api/meal-plan/groups", json={"name": "Work Lunch"}).json["group"]
    groups = [family["id"], work["id"]]
    nate = client.post("/api/meal-plan/members", json={
        "name": "Nate", "first_name": "Nathaniel", "last_name": "Tyler",
        "default_portion": 1.5, "group_ids": groups,
    }).json["member"]
    bulk = client.post("/api/meal-plan/members/bulk", json={
        "members": [{"name": "Ava", "last_name": "Different", "default_portion": 0.5}, {"name": "Archived person"}],
        "group_ids": [family["id"]],
    })
    assert bulk.status_code == 201
    ava, archived = bulk.json["members"]
    jordan = client.post("/api/meal-plan/members", json={"name": "Jordan", "group_ids": [work["id"]]}).json["member"]
    client.post("/api/meal-plan/members", json={"name": "Someone else", "last_name": "Tyler"})
    client.patch(f"/api/meal-plan/members/{archived['id']}", json={"archived": True})

    registry = client.get("/api/meal-plan/members").json
    assert next(member for member in registry["members"] if member["id"] == nate["id"])["name"] == "Nate"
    payload = schedule_payload(registry, groups, customize=True)
    expected_ids = {nate["id"], ava["id"], jordan["id"]}
    assert len(payload["allocations"]) == 4
    for allocation in payload["allocations"]:
        ids = [portion["member_id"] for portion in allocation["member_portions"]]
        assert len(ids) == 3 and set(ids) == expected_ids
    created = client.post("/api/meal-plan/batches", json=payload)
    assert created.status_code == 201, created.get_data(as_text=True)
    before = client.get("/api/meal-plan?recipe_url=recipe://soup").json
    assert sum(meal["planned_servings"] for meal in before["meals"]) == 11.75
    assert before["batches"][0]["prep_notes"] == "Pack individual portions"
    assert all(member["meal_count"] == 4 for member in client.get("/api/meal-plan/members").json["members"] if member["id"] in expected_ids)

    # Membership and portion defaults affect subsequent selections, not saved meals.
    assert client.patch(f"/api/meal-plan/members/{nate['id']}", json={"default_portion": 3, "group_ids": []}).status_code == 200
    assert client.patch(f"/api/meal-plan/groups/{work['id']}", json={"archived": True}).status_code == 200
    assert client.get("/api/meal-plan?recipe_url=recipe://soup").json == before
    next_registry = client.get("/api/meal-plan/members").json
    next_payload = schedule_payload(next_registry, groups, dates=("2026-10-12", "2026-10-14"))
    assert all(allocation["member_portions"] == [{"member_id": ava["id"], "servings": 0.5}] for allocation in next_payload["allocations"])
    next_saved = client.post("/api/meal-plan/batches", json=next_payload)
    assert next_saved.status_code == 201, next_saved.get_data(as_text=True)
    assert len(client.get("/api/meal-plan?recipe_url=recipe://soup").json["meals"]) == 8
