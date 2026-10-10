from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field

from .base import Tool, ToolError


class NavigateArgs(BaseModel):
    url: str = Field(description="Absolute http:// or https:// URL")


class ClickArgs(BaseModel):
    selector: str = Field(min_length=1, description="Selector returned in visible interactive elements")


class FillFormArgs(BaseModel):
    fields: dict[str, str] = Field(description="Mapping of visible selectors to values")


class EmptyArgs(BaseModel):
    """Schema for browser actions that take no arguments."""

    pass


class BrowserTool:
    """Async Playwright browser tool returning visible text and interactive controls."""

    def __init__(self, browser: Browser, runs_dir: str | Path = "runs"):
        self.browser = browser
        self.page: Page | None = None
        self.step_count = 0
        self.runs_dir = Path(runs_dir)

    async def _ensure_page(self) -> Page:
        if self.page is None or self.page.is_closed():
            self.page = await self.browser.new_page()
        return self.page

    async def navigate(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            raise ToolError("invalid_request", "Only http:// and https:// URLs are allowed.")
        page = await self._ensure_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            # A partially loaded page may still be usable.
            if not page.url:
                raise ToolError("timeout", f"Navigation timed out: {exc}", retryable=True) from exc
        self.step_count += 1
        return await self.extract_page_text()

    async def click(self, selector: str) -> str:
        page = await self._require_page()
        try:
            await page.locator(selector).first.click(timeout=10_000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=3_000)
            except PlaywrightTimeoutError:
                pass
        except Exception as exc:
            raise ToolError("browser", f"Could not click selector {selector!r}: {exc}", retryable=True) from exc
        self.step_count += 1
        return await self.extract_page_text()

    async def fill_form(self, fields: dict[str, Any]) -> str:
        page = await self._require_page()
        for selector, value in fields.items():
            try:
                await page.locator(selector).first.fill(str(value), timeout=10_000)
            except Exception as exc:
                raise ToolError("browser", f"Could not fill selector {selector!r}: {exc}") from exc
        self.step_count += 1
        return await self.extract_page_text()

    async def extract_page_text(self) -> str:
        """Extract rendered visible text and visible interactive elements, never raw HTML."""
        page = await self._require_page()
        try:
            payload = await page.evaluate("""() => {
              const visible = (el) => {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s && s.visibility !== 'hidden' && s.display !== 'none' &&
                       Number(s.opacity || 1) > 0 && r.width > 0 && r.height > 0;
              };
              const clean = (s) => (s || '').replace(/\\\\s+/g, ' ').trim();
              const elements = Array.from(document.querySelectorAll(
                'button, a, input, textarea, select, [role="button"], [role="link"]'
              )).filter(visible).slice(0, 100);
              const interactive = elements.map((el, i) => {
                const id = 'agent-control-' + i;
                el.setAttribute('data-agent-control', id);
                return {
                  selector: '[data-agent-control="' + id + '"]',
                  tag: el.tagName.toLowerCase(),
                  role: el.getAttribute('role') || '',
                  text: clean(el.innerText || el.value || el.getAttribute('aria-label') ||
                               el.getAttribute('placeholder') || el.title),
                  type: el.getAttribute('type') || '',
                  placeholder: el.getAttribute('placeholder') || '',
                  href: el.tagName.toLowerCase() === 'a' ? el.href : ''
                };
              });
              const bodyText = document.body ? clean(document.body.innerText) : '';
              return { text: bodyText.slice(0, 12000), interactive };
            }""")
        except Exception as exc:
            raise ToolError("browser", f"Could not extract visible page content: {exc}") from exc
        controls = "\n".join(
            f"- {item['tag']} {item['role']} text={item['text']!r} "
            f"type={item['type']!r} placeholder={item['placeholder']!r} "
            f"selector={item['selector']}"
            + (f" href={item['href']}" if item["href"] else "")
            for item in payload["interactive"]
        )
        return f"VISIBLE PAGE TEXT:\n{payload['text']}\n\nVISIBLE INTERACTIVE ELEMENTS:\n{controls}"

    async def screenshot(self) -> str:
        page = await self._require_page()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"step_{self.step_count:04d}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def close(self) -> None:
        if self.page is not None and not self.page.is_closed():
            await self.page.close()
        self.page = None

    async def _require_page(self) -> Page:
        if self.page is None or self.page.is_closed():
            raise ToolError("invalid_request", "No active page. Call navigate(url) first.")
        return self.page


def build_browser_tools(browser: BrowserTool) -> list[Tool]:
    """Return registry-compatible wrappers for the stateful browser capability."""
    return [
        Tool("browser_navigate", "Navigate and return visible page text and controls.", NavigateArgs, browser.navigate),
        Tool("browser_click", "Click a visible control using its returned selector.", ClickArgs, browser.click, risky=True),
        Tool("browser_fill_form", "Fill visible form fields by selector.", FillFormArgs, browser.fill_form),
        Tool("browser_screenshot", "Save a screenshot of the current page.", EmptyArgs, browser.screenshot),
    ]
