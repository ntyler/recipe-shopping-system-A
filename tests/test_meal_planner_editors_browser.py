"""Chromium exercises the production dialog/template/CSS against isolated real APIs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

from flask import Response, render_template_string, send_from_directory
import pytest
from werkzeug.serving import make_server

from PushShoppingList.routes import main_routes
from test_meal_prep_batches import scoped_client, sign_in


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script', ['meal_planner_editors.cjs', 'meal_calendar_drag.cjs', 'meal_planner_yield_split.cjs', 'meal_planner_shared_portions.cjs', 'meal_planner_recipe_portions.cjs', 'meal_planner_yield_coverage.cjs'])
def test_simultaneous_meal_editors_in_chromium(scoped_client, monkeypatch, script):
    node = shutil.which('node')
    module = os.environ.get('AI_PANTRY_PLAYWRIGHT_MODULE', 'playwright')
    if not node or subprocess.run([node, '-e', 'require.resolve(process.argv[1])', module], capture_output=True).returncode:
        pytest.skip('Set AI_PANTRY_PLAYWRIGHT_MODULE to an installed Playwright module')
    recipes = [dict(url=f'recipe://{name.lower()}', name=name, default_servings=servings, yield_servings=servings,
                    yield_label=f'{servings} servings', ingredient_requirements=[{
                        'id': 'oil', 'label': 'Oil', 'default_option_id': 'olive',
                        'options': [{'id': 'olive', 'label': 'Olive', 'items': []},
                                    {'id': 'sunflower', 'label': 'Sunflower', 'items': []}],
                    }]) for name, servings in [('Bread', 8), ('Soup', 4), ('Rice', 6)]]
    monkeypatch.setattr(main_routes, 'meal_plan_recipe_option_rows', lambda rows: recipes)
    app = scoped_client.application
    source = (ROOT / 'PushShoppingList/static/js/app.js').read_text(encoding='utf-8')
    workspace = (ROOT / 'PushShoppingList/templates/sections/app_workspaces.html').read_text(encoding='utf-8')
    dialog = workspace[workspace.index('<dialog id="mealPlannerDialog"'):workspace.index('<dialog id="mealPlannerDeleteDialog"')]

    @app.get('/editor-qa')
    def editor_page():
        return render_template_string('''<!doctype html><html data-public-auth-theme="dark"><head>
            <meta name="viewport" content="width=device-width, initial-scale=1"><title>AI Pantry — Meal Planner</title><link rel="icon" href="data:,">
            <link rel="stylesheet" href="/qa-static/css/app.css"><link rel="stylesheet" href="/qa-static/css/recipe-preview.css">
            </head><body style="background:var(--app-bg);color:var(--app-text);padding:24px">
            <main id="mealPlannerPage"><h1>Meal Planner</h1><button onclick="openMealPlannerDialog('2026-10-05','dinner')">Add Meals</button>
            <p data-meal-planner-refresh-status hidden></p><div id="plannerMealsPanel"></div>'''
            + dialog + '''</main><script src="/qa-static/js/meal-plan-schedule.js"></script>
            <script src="/qa-static/js/meal-plan-panel.js"></script><script src="/editor-controller.js"></script>
            <script>async function refreshMealPlannerWorkspace(){return true;}</script></body></html>''',
            meal_plan_recipe_options=recipes)

    @app.get('/qa-static/<path:name>')
    def assets(name):
        return send_from_directory(ROOT / 'PushShoppingList/static', name)

    @app.get('/editor-controller.js')
    def controller():
        status = source[source.index('function setMealPlannerStatus('):source.index('async function toggleMealPlannerPrepStep(')]
        scheduling = source[source.index('function formatMealPlannerServingNumber'):source.index('function openMealPlannerDeleteDialog')]
        return Response(status + scheduling, mimetype='text/javascript')

    sign_in(scoped_client, 'editor-qa')
    cookie = scoped_client.get_cookie(app.config['SESSION_COOKIE_NAME'])
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [node, str(ROOT / 'tests/browser' / script), module, f'http://127.0.0.1:{server.server_port}'],
            input=json.dumps({'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'}),
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
