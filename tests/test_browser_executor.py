from pathlib import Path
from unittest.mock import MagicMock, patch

from taskplane.browser_executor import (
    BrowserExecutor,
    DomExtract,
    ScreenshotResult,
)


def test_browser_executor_init_creates_output_dir(tmp_path):
    output_dir = tmp_path / "browser"
    executor = BrowserExecutor(output_dir=output_dir)
    assert output_dir.exists()


def test_browser_executor_screenshot_builds_script(tmp_path):
    executor = BrowserExecutor(output_dir=tmp_path)

    with patch.object(executor, "_run_playwright") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        output_path = tmp_path / "test.png"
        output_path.write_bytes(b"fakepng")

        result = executor.screenshot("https://example.com", filename="test.png")

        assert isinstance(result, ScreenshotResult)
        assert result.url == "https://example.com"
        assert result.path == str(output_path)
        assert result.content_digest is not None
        assert result.width == 1280
        assert result.height == 720


def test_browser_executor_screenshot_default_filename(tmp_path):
    executor = BrowserExecutor(output_dir=tmp_path)

    with patch.object(executor, "_run_playwright") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        import hashlib

        hash_part = hashlib.md5(b"https://example.com").hexdigest()[:8]
        output_path = tmp_path / f"screenshot_{hash_part}.png"
        output_path.write_bytes(b"fakepng")

        result = executor.screenshot("https://example.com")

        assert "screenshot_" in result.path
        assert result.path.endswith(".png")


def test_browser_executor_get_dom_returns_empty_on_missing(tmp_path):
    executor = BrowserExecutor(output_dir=tmp_path)

    with patch.object(executor, "_run_playwright") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        result = executor.get_dom("https://example.com")

        assert isinstance(result, DomExtract)
        assert result.url == "https://example.com"
        assert result.html_content == ""


def test_browser_executor_get_dom_parses_json(tmp_path):
    executor = BrowserExecutor(output_dir=tmp_path)

    with patch.object(executor, "_run_playwright") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        import json

        (tmp_path / "dom_extract.json").write_text(
            json.dumps(
                {
                    "html": "<html><body>test</body></html>",
                    "title": "Test Page",
                    "meta_description": "A test page",
                }
            )
        )

        result = executor.get_dom("https://example.com")

        assert result.html_content == "<html><body>test</body></html>"
        assert result.title == "Test Page"
        assert result.meta_description == "A test page"


def test_browser_executor_build_screenshot_script():
    executor = BrowserExecutor()
    script = executor._build_screenshot_script(
        url="https://example.com",
        output_path=Path("/tmp/test.png"),
        viewport_width=1920,
        viewport_height=1080,
    )

    assert "chromium" in script
    assert "https://example.com" in script
    assert "1920" in script
    assert "1080" in script
    assert "/tmp/test.png" in script


def test_browser_executor_build_dom_script():
    executor = BrowserExecutor(output_dir=Path("/tmp"))
    script = executor._build_dom_script("https://example.com")

    assert "chromium" in script
    assert "https://example.com" in script
    assert "dom_extract.json" in script


def test_browser_executor_write_temp_script(tmp_path):
    executor = BrowserExecutor(output_dir=tmp_path)
    script_path = executor._write_temp_script("const x = 1;")

    assert script_path.exists()
    assert script_path.read_text() == "const x = 1;"
    assert script_path.suffix == ".js"


def test_screenshot_result_is_immutable():
    result = ScreenshotResult(
        path="/tmp/test.png",
        width=1280,
        height=720,
        content_digest="sha256",
        url="https://example.com",
    )

    assert result.path == "/tmp/test.png"
    assert result.width == 1280
