from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_webdrivers.ps1"


def test_sync_webdrivers_script_uses_official_driver_sources():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json" in script
    assert "googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" in script
    assert "https://msedgedriver.microsoft.com/$BrowserVersion/edgedriver_$Platform.zip" in script


def test_sync_webdrivers_script_has_safe_install_controls():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "SupportsShouldProcess = $true" in script
    assert "[switch]$PlanOnly" in script
    assert "Copy-Item -LiteralPath $destination -Destination $backupPath -Force" in script
    assert "webdriver-sync-" in script
    assert "Remove-Item -LiteralPath $resolvedPath -Recurse -Force" in script
    assert "StartsWith($tempBase" in script
    assert 'return "C:\\Python39Drivers"' in script
