from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "start_app.bat"


def test_launcher_can_skip_only_automatic_browser_opening():
    script = LAUNCHER.read_text(encoding="utf-8")
    normalized = script.replace("\r\n", "\n")

    load_setting = "call :load_user_env SHOPPING_APP_OPEN_BROWSER"
    load_local_env = "if exist local_env.bat call local_env.bat"
    false_guard = 'if /I "%SHOPPING_APP_OPEN_BROWSER%"=="false" goto :skip_open_browser'
    browser_command = "start http://127.0.0.1:%SHOPPING_APP_PORT%"
    skip_label = ":skip_open_browser"
    python_check = 'if not exist "%SHOPPING_APP_PYTHON_EXE%" ('
    python_start = '"%SHOPPING_APP_PYTHON_EXE%" app.py'

    assert normalized.count(browser_command) == 1
    assert normalized.count(false_guard) == 1
    assert normalized.count(skip_label) == 2  # guard target plus label definition
    assert normalized.index(load_setting) < normalized.index(load_local_env)
    assert normalized.index(load_local_env) < normalized.index(false_guard)
    assert normalized.index(false_guard) < normalized.index(browser_command)
    assert normalized.index(browser_command) < normalized.index("\n:skip_open_browser\n")
    assert normalized.index("\n:skip_open_browser\n") < normalized.index(python_check)
    assert normalized.index(python_check) < normalized.index(python_start)


def test_launcher_preserves_default_browser_and_python_start_paths():
    lines = [line.strip() for line in LAUNCHER.read_text(encoding="utf-8").splitlines()]

    guard_index = lines.index(
        'if /I "%SHOPPING_APP_OPEN_BROWSER%"=="false" goto :skip_open_browser'
    )
    browser_index = lines.index("start http://127.0.0.1:%SHOPPING_APP_PORT%")
    skip_index = lines.index(":skip_open_browser")
    python_index = lines.index('"%SHOPPING_APP_PYTHON_EXE%" app.py')

    # With the setting absent (the default), the exact-false jump is not taken,
    # so the existing browser command remains on the path to the Python start.
    assert guard_index + 1 == browser_index
    assert browser_index + 1 == skip_index
    assert skip_index < python_index
