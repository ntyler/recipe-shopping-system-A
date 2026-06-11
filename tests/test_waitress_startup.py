from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_py_uses_waitress_by_default_with_flask_dev_escape_hatch():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")

    assert 'os.getenv("SHOPPING_APP_SERVER", "waitress")' in app_py
    assert "from waitress import serve" in app_py
    assert "run_waitress_server()" in app_py
    assert "SHOPPING_APP_SERVER=flask-dev" in app_py


def test_requirements_include_waitress():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "waitress>=3.0" in requirements

