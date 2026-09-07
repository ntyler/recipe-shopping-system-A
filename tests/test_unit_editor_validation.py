"""Exercise the browser's draft validation against realistic registry conflicts."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_unit_editor_validation_and_change_detection():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise browser validation")
    script = Path("PushShoppingList/static/js/units.js").read_text(encoding="utf-8")
    helpers = script[script.index("    function cleanText"):script.index("    function parseRegistry")]
    assertions = r'''
const assert = require('node:assert/strict');
const registry = {
    categories: [{key: 'volume'}, {key: 'weight'}],
    units: [
        {id:'teaspoon', name:'teaspoon', seeded:true, aliases:['tsp', 'teaspoons']},
        {id:'tablespoon', name:'tablespoon', aliases:['tbsp', 'table-spoons']},
    ],
};
const original = {canonical_name:'teaspoon', category:'volume', aliases:['tsp', 'teaspoons']};
const validate = draft => validateUnitDraft({...original, ...draft}, registry, 'teaspoon');
assert.deepEqual(validate({}), {aliases:{}});
assert.deepEqual(validate({canonical_name:'tea measure', category:'weight'}), {aliases:{}});
assert.match(validate({canonical_name:' tAbLeSpOoN '}).canonical_name, /already accepted by tablespoon/);
assert.deepEqual(validate({aliases:['  scoops  ']}), {aliases:{}});
assert.match(validate({aliases:['tsp', ' TSP ']}).aliases[1], /already in this unit/);
assert.match(validate({aliases:['T.S.P.', 'tsp']}).aliases[1], /already in this unit/);
assert.match(validate({aliases:['ＴＳＰ', 'tsp']}).aliases[1], /already in this unit/);
assert.match(validate({aliases:[' TABLESPOON ']}).aliases[0], /already accepted by tablespoon/);
assert.match(validate({aliases:[' TBSP ']}).aliases[0], /already accepted by tablespoon/);
assert.match(validate({aliases:['table_spoons']}).aliases[0], /already accepted by tablespoon/);
assert.match(validate({aliases:[' TEASPOON ']}).aliases[0], /canonical name/);
assert.match(validate({canonical_name:'TBSP'}).canonical_name, /already accepted by tablespoon/);
assert.match(validate({canonical_name:'', category:'unknown'}).canonical_name, /Enter/);
assert.match(validate({category:'unknown'}).category, /Choose/);
assert.match(validate({aliases:['.', 'a'.repeat(61)]}).aliases[0], /Enter/);
assert.match(validate({aliases:['.', 'a'.repeat(61)]}).aliases[1], /60/);
assert.match(validate({canonical_name:'a'.repeat(61)}).canonical_name, /60/);
assert.match(validateUnitDraft(original, registry).canonical_name, /already accepted/);
const signature = unitDraftSignature(original);
assert.equal(unitDraftSignature({...original, canonical_name:'  teaspoon  ', aliases:['teaspoons','tsp']}), signature);
assert.notEqual(unitDraftSignature({...original, category:'weight'}), signature);
assert.notEqual(unitDraftSignature({...original, aliases:['tsp']}), signature);
assert.notEqual(unitDraftSignature({...original, canonical_name:'tea measure'}), signature);
assert.deepEqual(original.aliases, ['tsp', 'teaspoons']);
'''
    subprocess.run([node, "-e", helpers + assertions], check=True, capture_output=True, text=True)
