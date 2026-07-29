from selenium.common.exceptions import SessionNotCreatedException

from PushShoppingList.services import recipe_extract_service


DRIVER_MISMATCH_MESSAGE = (
    "Message: session not created: This version of ChromeDriver only supports "
    "Chrome version 149 Current browser version is 151.0.7922.71"
)


def test_chromedriver_mismatch_detection_is_specific():
    assert recipe_extract_service.is_chrome_driver_version_mismatch(
        SessionNotCreatedException(DRIVER_MISMATCH_MESSAGE)
    )
    assert not recipe_extract_service.is_chrome_driver_version_mismatch(
        RuntimeError("Chrome failed to start because the profile is locked.")
    )


def test_selenium_manager_ignores_path_driver_and_can_refresh_metadata(monkeypatch):
    calls = []

    def fake_binary_paths(self, args):
        calls.append(list(args))
        return {"driver_path": r"C:\managed\chromedriver.exe"}

    monkeypatch.setattr(
        "selenium.webdriver.common.selenium_manager.SeleniumManager.binary_paths",
        fake_binary_paths,
    )

    initial = recipe_extract_service.selenium_managed_chrome_service()
    refreshed = recipe_extract_service.selenium_managed_chrome_service(
        force_refresh=True
    )

    assert initial.path == r"C:\managed\chromedriver.exe"
    assert refreshed.path == r"C:\managed\chromedriver.exe"
    assert calls == [
        ["--browser", "chrome", "--skip-driver-in-path"],
        [
            "--browser",
            "chrome",
            "--skip-driver-in-path",
            "--clear-metadata",
        ],
    ]


def test_selenium_driver_refreshes_and_retries_once_on_version_mismatch(
    monkeypatch,
):
    services = []
    webdriver_calls = []
    expected_driver = object()

    def fake_service(force_refresh=False):
        service = object()
        services.append((force_refresh, service))
        return service

    def fake_chrome(*, service, options):
        webdriver_calls.append((service, options))
        if len(webdriver_calls) == 1:
            raise SessionNotCreatedException(DRIVER_MISMATCH_MESSAGE)
        return expected_driver

    monkeypatch.setattr(
        recipe_extract_service,
        "selenium_managed_chrome_service",
        fake_service,
    )
    monkeypatch.setattr("selenium.webdriver.Chrome", fake_chrome)

    options = object()
    result = recipe_extract_service.create_selenium_managed_chrome_driver(options)

    assert result is expected_driver
    assert [force_refresh for force_refresh, _service in services] == [False, True]
    assert [options_arg for _service, options_arg in webdriver_calls] == [
        options,
        options,
    ]


def test_selenium_driver_does_not_retry_unrelated_startup_errors(monkeypatch):
    service_calls = []
    chrome_calls = []

    def fake_service(force_refresh=False):
        service_calls.append(force_refresh)
        return object()

    def fake_chrome(*, service, options):
        chrome_calls.append((service, options))
        raise RuntimeError("Chrome profile is locked.")

    monkeypatch.setattr(
        recipe_extract_service,
        "selenium_managed_chrome_service",
        fake_service,
    )
    monkeypatch.setattr("selenium.webdriver.Chrome", fake_chrome)

    try:
        recipe_extract_service.create_selenium_managed_chrome_driver(object())
    except RuntimeError as exc:
        assert str(exc) == "Chrome profile is locked."
    else:
        raise AssertionError("Expected the unrelated startup error to be raised.")

    assert service_calls == [False]
    assert len(chrome_calls) == 1
