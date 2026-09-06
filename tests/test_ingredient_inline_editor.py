from io import BytesIO
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from PushShoppingList.services import recipe_master_data_service as md
from PushShoppingList.services import recipe_master_image_service as images
from test_recipe_master_data_routes import configure_master_data_app, seed_master_records, sign_in


@pytest.fixture
def editor_app(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    md.sync_recipe_master_records('https://example.com/editor-carrot',
        recipe_data={'ingredients': [{'ingredient': 'Carrot', 'store_section': 'Produce'}]}, user_id='user-a')
    monkeypatch.setattr(images, 'STEP_IMAGE_FOLDER', tmp_path / 'images')
    monkeypatch.setattr(images, 'ensure_webp_variants', lambda *args, **kwargs: None)
    return app


def image_file():
    output = BytesIO()
    Image.new('RGB', (24, 24), '#b95b32').save(output, format='PNG')
    output.seek(0)
    return output


def tomato():
    return md.master_record_for_name('ingredients', 'user-a', 'tomato')


def save_payload(record, **changes):
    return {'name': record['name'], 'normalized_name': record['normalized_name'],
            'store_section': record['store_section'], **changes}


def test_editor_uses_shared_alias_component_and_real_scoped_context(editor_app):
    record = tomato()
    with editor_app.test_client() as client:
        sign_in(client, 'user-a')
        html = client.get('/admin/master-data/ingredients?search=Tomato').data
        soup = BeautifulSoup(html, 'html.parser')
        assert len(soup.select('[data-ingredient-editor-form]')) == 1
        form = soup.select_one('[data-ingredient-editor-form]')
        assert form.has_attr('hidden') and form['aria-labelledby'] == 'ingredientEditorTitle'
        assert form.select_one('[data-ingredient-editor-save]').has_attr('disabled')
        assert form.select_one('.unit-master-alias-editor [data-ingredient-editor-alias-input]')['maxlength'] == '160'
        assert form.select_one('[data-ingredient-editor-feedback]')['role'] == 'status'
        assert form.select_one('[data-ingredient-editor-image-replace]')
        assert form.select_one('[data-ingredient-editor-image-generate]')
        assert form.select_one('[data-ingredient-editor-image-remove]')
        assert not form.select('[data-unit-master-ai-suggest]')
        row = soup.select_one('[data-ingredient-master-row]')
        assert row.select_one('[data-ingredient-row-edit]')['aria-controls'] == form['id']
        assert not row.select_one('[popover]').select('[data-ingredient-row-edit]')
        assert not row.select('input[type="text"]')
        assert row.select_one('[data-master-merge-open]')
        context = client.get(f'/api/master-data/ingredients/{record["id"]}/editor').json
        assert context['record']['name'] == record['name']
        assert context['record']['source_label'] == 'User-created'
        assert context['record']['section_editable'] is True
        assert context['record']['usage_count'] == md.list_master_record_recipe_references('ingredients', record['id'], user_id='user-a')['total']
        assert len(context['registry']) > len(soup.select('[data-ingredient-master-row]'))
        assert all('user_id' not in item and 'image_path' not in item for item in context['registry'])
        expected_sections = md.ingredient_store_section_details(user_id='user-a')
        assert [item['section_key'] for item in context['sections']] == [item['section_key'] for item in expected_sections]
        assert all(item['icon'] for item in context['sections'])
        sign_in(client, 'user-b')
        assert client.get(f'/api/master-data/ingredients/{record["id"]}/editor').status_code == 404
        assert client.post(f'/api/master-data/ingredients/{record["id"]}/image-preview', data={'image': (image_file(), 'a.png')}).status_code == 404


def test_image_preview_does_not_save_and_can_only_be_applied_to_its_owner(editor_app):
    record = tomato()
    with editor_app.test_client() as client:
        sign_in(client, 'user-a')
        preview = client.post(f'/api/master-data/ingredients/{record["id"]}/image-preview', data={'image': (image_file(), 'a.png')})
        assert preview.status_code == 200
        assert tomato() == record  # Cancel needs no database rollback.
        change = {'action': 'replace', 'token': preview.json['token']}
        saved = client.post(f'/admin/master-data/ingredients/{record["id"]}', json=save_payload(record, image=change))
        assert saved.status_code == 200 and saved.json['result']['changed']
        assert tomato()['image_url'] == preview.json['image_url']
        assert Path(tomato()['image_path']).is_file()
        other = next(item for item in md.list_ingredients(user_id='user-a') if item['id'] != record['id'])
        rejected = client.post(f'/admin/master-data/ingredients/{other["id"]}', json=save_payload(other, image=change))
        assert rejected.status_code == 400 and rejected.json['result']['errors']['image']
        rejected = client.post(f'/admin/master-data/ingredients/{record["id"]}', json=save_payload(record, image={'action': 'replace', 'token': 'forged'}))
        assert rejected.status_code == 400
        removed = client.post(f'/admin/master-data/ingredients/{record["id"]}', json=save_payload(record, image={'action': 'remove'}))
        assert removed.status_code == 200
        assert tomato()['image_url'] == tomato()['image_path'] == ''
        assert client.delete(f'/admin/master-data/ingredients/{record["id"]}').status_code == 405


def test_image_and_section_changes_roll_back_on_alias_conflict(editor_app):
    record = tomato()
    other = next(item for item in md.list_ingredients(user_id='user-a') if item['id'] != record['id'])
    with editor_app.test_client() as client:
        sign_in(client, 'user-a')
        preview = client.post(f'/api/master-data/ingredients/{record["id"]}/image-preview', data={'image': (image_file(), 'a.png')}).json
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}', json=save_payload(
            record, name='Roma tomato', normalized_name='roma tomato', store_section='DAIRY & EGGS',
            aliases=[other['normalized_name']], image={'action': 'replace', 'token': preview['token']},
        ))
        assert response.status_code == 409 and response.json['result']['errors']['aliases']
        assert tomato() == record


def test_generation_reuses_existing_service_without_attaching_image(editor_app, monkeypatch):
    record = tomato()
    calls = []
    def generate(prompt, row):
        calls.append((prompt, row['id']))
        return image_file().getvalue()
    monkeypatch.setattr(images, 'request_master_ingredient_image_bytes', generate)
    with editor_app.test_client() as client:
        sign_in(client, 'user-a')
        result = client.post(f'/api/master-data/ingredients/{record["id"]}/image-preview', json={'action': 'generate', 'name': 'Roma tomato'})
    assert result.status_code == 200 and result.json['token']
    assert calls and calls[0][1] == record['id'] and 'Roma tomato' in calls[0][0]
    assert tomato() == record


@pytest.mark.parametrize('content', [b'not an image', b'x' * (10 * 1024 * 1024 + 1)], ids=['invalid', 'oversized'])
def test_invalid_upload_never_changes_ingredient(editor_app, content):
    record = tomato()
    with editor_app.test_client() as client:
        sign_in(client, 'user-a')
        response = client.post(f'/api/master-data/ingredients/{record["id"]}/image-preview', data={'image': (BytesIO(content), 'bad.png')})
    assert response.status_code == 400
    assert tomato() == record
