from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScreenshotResult:
    path: str
    width: int
    height: int
    content_digest: str
    page_title: str = ""
    url: str = ""


@dataclass(frozen=True)
class DomExtract:
    url: str
    html_content: str
    title: str = ""
    meta_description: str = ""


@dataclass
class BrowserExecutor:
    output_dir: Path = field(default_factory=lambda: Path(".run-logs/browser"))
    playwright_script_dir: Path = field(default_factory=lambda: Path("scripts"))
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def screenshot(
        self,
        url: str,
        filename: str | None = None,
        viewport_width: int = 1280,
        viewport_height: int = 720,
    ) -> ScreenshotResult:
        if filename is None:
            filename = f"screenshot_{hashlib.md5(url.encode()).hexdigest()[:8]}.png"
        output_path = self.output_dir / filename

        script = self._build_screenshot_script(
            url=url,
            output_path=output_path,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        script_path = self._write_temp_script(script)

        try:
            self._run_playwright(script_path)
            content = output_path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            return ScreenshotResult(
                path=str(output_path),
                width=viewport_width,
                height=viewport_height,
                content_digest=digest,
                url=url,
            )
        finally:
            script_path.unlink(missing_ok=True)

    def get_dom(self, url: str) -> DomExtract:
        script = self._build_dom_script(url)
        script_path = self._write_temp_script(script)

        try:
            self._run_playwright(script_path)
            result_path = self.output_dir / "dom_extract.json"
            if result_path.exists():
                import json

                data = json.loads(result_path.read_text())
                return DomExtract(
                    url=url,
                    html_content=data.get("html", ""),
                    title=data.get("title", ""),
                    meta_description=data.get("meta_description", ""),
                )
        finally:
            script_path.unlink(missing_ok=True)

        return DomExtract(url=url, html_content="")

    def run_playwright_script(self, script_path: Path) -> subprocess.CompletedProcess:
        return self._run_playwright(script_path)

    def _build_screenshot_script(
        self,
        url: str,
        output_path: Path,
        viewport_width: int,
        viewport_height: int,
    ) -> str:
        return f"""
const {{ chromium }} = require('playwright');
(async () => {{
  const browser = await chromium.launch();
  const page = await browser.newPage({{ viewport: {{ width: {viewport_width}, height: {viewport_height} }} }});
  await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: {self.timeout_seconds * 1000} }});
  await page.screenshot({{ path: '{output_path}' }});
  await browser.close();
}})();
"""

    def _build_dom_script(self, url: str) -> str:
        output_path = self.output_dir / "dom_extract.json"
        return f"""
const {{ chromium }} = require('playwright');
const fs = require('fs');
(async () => {{
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: {self.timeout_seconds * 1000} }});
  const html = await page.content();
  const title = await page.title();
  const metaDescription = await page.locator('meta[name="description"]').getAttribute('content').catch(() => '');
  fs.writeFileSync('{output_path}', JSON.stringify({{ html, title, meta_description: metaDescription }}));
  await browser.close();
}})();
"""

    def _write_temp_script(self, content: str) -> Path:
        script_path = (
            self.output_dir / f"_tmp_{hashlib.md5(content.encode()).hexdigest()[:8]}.js"
        )
        script_path.write_text(content)
        return script_path

    def _run_playwright(self, script_path: Path) -> subprocess.CompletedProcess:
        node_path = _find_node()
        return subprocess.run(
            [node_path, str(script_path)],
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=True,
        )


def _find_node() -> str:
    node = os.environ.get("NODE_PATH", "node")
    return node
