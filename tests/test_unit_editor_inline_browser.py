"""Real Chromium coverage for click-activated inline editing; opt in with an installed Playwright module."""
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from test_unit_registry_management import unit_registry_app, sign_in
from test_unit_edit_usage_flow import seed_usage, reference_measurements


@pytest.mark.parametrize('script', ['units_inline.cjs', 'unit_categories.cjs', 'units_alias_popover.cjs', 'units_alias_controls.cjs', 'units_new_draft.cjs', 'units_save_actions.cjs'])
def test_unit_cells_activate_real_controls_on_click(unit_registry_app, script):
    node = shutil.which('node')
    module = os.environ.get('AI_PANTRY_PLAYWRIGHT_MODULE', 'playwright')
    if not node or subprocess.run([node, '-e', 'require.resolve(process.argv[1])', module], capture_output=True).returncode:
        pytest.skip('Install Playwright for Node or set AI_PANTRY_PLAYWRIGHT_MODULE to run Chromium coverage')
    seed_usage()
    before = reference_measurements()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        cookie = client.get_cookie(unit_registry_app.config['SESSION_COOKIE_NAME'])
        browser_cookie = {'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'}
    server = make_server('127.0.0.1', 0, unit_registry_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [node, str(Path(__file__).parent / 'browser' / script), module, f'http://127.0.0.1:{server.server_port}'],
            input=json.dumps(browser_cookie), capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    after = reference_measurements()
    for table, rows in before.items():
        assert len(rows) == len(after[table])
        for old, new in zip(rows, after[table]):
            assert {k: v for k, v in old.items() if k != 'unit'} == {k: v for k, v in new.items() if k != 'unit'}
