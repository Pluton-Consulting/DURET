"""
Client browser qui délègue toute navigation web à un sandbox Daytona éphémère.

Architecture :
  Backend → DaytonaBrowserClient.run_search() → Daytona sandbox
                                                   └── Script Python autonome
                                                         └── Playwright + Chromium
                                                               └── DuckDuckGo / URL cible
                                                   └── JSON résultat sur stdout
  Backend ← JSON parsé ← Daytona sandbox détruite

Le backend ne touche jamais à Playwright.
Si le sandbox plante, le backend est inchangé.
"""

import json
import time
import logging
from dataclasses import dataclass
from typing import Optional
from browser.scripts import SEARCH_SCRIPT, FETCH_SCRIPT
from browser.sandbox_filter import SandboxFilter
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class BrowserResult:
    success: bool
    results: list[dict]
    error: Optional[str]
    execution_time_ms: int
    was_filtered: bool = False
    sandbox_type: str = "daytona"


class DaytonaBrowserClient:
    """
    Exécute Playwright dans un sandbox Daytona isolé.
    Si Daytona non configuré, retourne un résultat vide explicatif —
    pas de Playwright local en fallback (contrairement au DaytonaClient
    des skills, le browser n'a pas de fallback subprocess car trop risqué
    sans isolation).
    """

    def __init__(self):
        self.api_key = settings.daytona_api_key
        self.enabled = settings.browser_enabled
        self.filter = SandboxFilter()

        if self.api_key:
            try:
                from daytona_sdk import Daytona, DaytonaConfig
                self._daytona = Daytona(DaytonaConfig(api_key=self.api_key))
                self._available = True
            except ImportError:
                self._daytona = None
                self._available = False
                logger.warning("Daytona SDK absent — browser agent désactivé")
        else:
            self._daytona = None
            self._available = False
            logger.info("DAYTONA_API_KEY absent — browser agent désactivé")

    def _is_ready(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "Browser agent désactivé (BROWSER_ENABLED=false)"
        if not self._available:
            return False, "Daytona non configuré : DAYTONA_API_KEY requis pour le browser"
        return True, ""

    async def run_search(self, query: str, max_results: int = 3) -> BrowserResult:
        """Recherche web via DuckDuckGo dans un sandbox Daytona."""
        ready, reason = self._is_ready()
        if not ready:
            return BrowserResult(
                success=False, results=[], error=reason,
                execution_time_ms=0, sandbox_type="disabled",
            )

        max_results = min(max(1, max_results), 5)
        script = SEARCH_SCRIPT.format(
            query=query.replace('"', '\\"'),
            max_results=max_results,
            timeout_ms=settings.browser_timeout_ms,
        )
        return await self._run_in_sandbox(script)

    async def run_fetch(self, url: str) -> BrowserResult:
        """Récupère le contenu d'une URL spécifique dans un sandbox Daytona."""
        blocked, reason = self.filter.is_blocked(url)
        if blocked:
            return BrowserResult(
                success=False, results=[], error=f"URL bloquée : {reason}",
                execution_time_ms=0, was_filtered=True,
            )

        ready, reason = self._is_ready()
        if not ready:
            return BrowserResult(
                success=False, results=[], error=reason,
                execution_time_ms=0, sandbox_type="disabled",
            )

        script = FETCH_SCRIPT.format(
            url=url.replace('"', '\\"'),
            timeout_ms=settings.browser_timeout_ms,
        )
        return await self._run_in_sandbox(script)

    async def _run_in_sandbox(self, script: str) -> BrowserResult:
        """Crée sandbox → exécute script → parse JSON → détruit sandbox."""
        sandbox = None
        start_time = time.monotonic()

        try:
            from daytona_sdk import CreateSandboxFromImageParams
            sandbox = self._daytona.create(
                CreateSandboxFromImageParams(image="python:3.12-slim", language="python")
            )
            result = sandbox.process.exec(
                f"python3 -c '{script}'",
                timeout=int(settings.browser_timeout_ms / 1000) + 30,
            )
            elapsed = int((time.monotonic() - start_time) * 1000)

            if result.exit_code != 0:
                return BrowserResult(
                    success=False, results=[],
                    error=f"Script exit code {result.exit_code}: {result.result[:200]}",
                    execution_time_ms=elapsed,
                )

            try:
                data = json.loads(result.result)
                return BrowserResult(
                    success=data.get("success", False),
                    results=data.get("results", []),
                    error=data.get("error"),
                    execution_time_ms=elapsed,
                )
            except json.JSONDecodeError as e:
                return BrowserResult(
                    success=False, results=[],
                    error=f"JSON parse error: {e}. Output: {result.result[:100]}",
                    execution_time_ms=elapsed,
                )

        except Exception as e:
            elapsed = int((time.monotonic() - start_time) * 1000)
            logger.error(f"Daytona browser error: {e}")
            return BrowserResult(
                success=False, results=[], error=str(e), execution_time_ms=elapsed,
            )

        finally:
            # Destruction du sandbox dans TOUS les cas
            if sandbox and self._daytona:
                try:
                    self._daytona.delete(sandbox)
                    logger.debug("Browser sandbox détruite")
                except Exception as e:
                    logger.warning(f"Sandbox destruction failed: {e}")


daytona_browser = DaytonaBrowserClient()
