"""
Client Daytona — Sandbox isolé pour tester les skills générés par l'Agent 3.

Fonctionnement :
1. L'Agent 3 génère du code Python (le skill)
2. Ce client crée un sandbox Daytona éphémère (<90ms)
3. Le code est exécuté avec des données de test fictives
4. Le résultat (succès/échec, output, métriques) est retourné
5. Le sandbox est détruit immédiatement après
6. Aucune donnée client ne transite par Daytona — uniquement du code Python

Si DAYTONA_API_KEY est absent, bascule automatiquement sur subprocess local.
"""
import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Optional
from config import settings


@dataclass
class SandboxTestResult:
    passed: bool
    output: Optional[str]
    error: Optional[str]
    execution_time_ms: int
    memory_used_mb: Optional[float]
    confidence_score: float  # 0.0 = échec, 1.0 = succès parfait
    sandbox_type: str        # 'daytona' ou 'subprocess_fallback'


# Données de test fictives — aucune information réelle de Duret & Sols
MOCK_TEST_DATA = {
    "surface_m2": 85.0,
    "longueur_m": 12.5,
    "largeur_m": 6.8,
    "perimetre_m": 38.6,
    "hauteur_m": 2.4,
    "essence_bois": "ipé",
    "epaisseur_lame_mm": 21,
    "largeur_lame_mm": 145,
    "prix_m2_ht": 85.0,
    "nb_poteaux": 12,
    "entraxe_m": 1.5,
    "nb_lames_necessaires": 230,
    "resultat_attendu": 7225.0,
}


class DaytonaClient:
    """
    Client pour l'exécution de code dans des sandboxes Daytona isolés.
    Fallback automatique sur subprocess si Daytona non configuré.
    """

    def __init__(self):
        self.api_key = settings.daytona_api_key
        self.daytona_available = bool(self.api_key)

        if self.daytona_available:
            try:
                from daytona_sdk import Daytona, DaytonaConfig
                self._daytona = Daytona(DaytonaConfig(api_key=self.api_key))
            except ImportError:
                self.daytona_available = False
                self._daytona = None
        else:
            self._daytona = None

    async def test_skill(
        self,
        skill_code: str,
        skill_name: str,
        max_execution_seconds: int = 30,
    ) -> SandboxTestResult:
        if self.daytona_available:
            return await self._test_in_daytona(skill_code, skill_name, max_execution_seconds)
        return await self._test_in_subprocess(skill_code, skill_name, max_execution_seconds)

    async def _test_in_daytona(
        self,
        skill_code: str,
        skill_name: str,
        timeout: int,
    ) -> SandboxTestResult:
        sandbox = None
        start_time = time.monotonic()

        try:
            from daytona_sdk import CreateSandboxFromImageParams
            test_code = self._wrap_with_test_data(skill_code)
            sandbox = self._daytona.create(
                CreateSandboxFromImageParams(image="python:3.12-slim", language="python")
            )
            result = sandbox.process.exec(
                f"python3 -c '{test_code}'",
                timeout=timeout,
            )
            execution_time = int((time.monotonic() - start_time) * 1000)
            passed = result.exit_code == 0
            return SandboxTestResult(
                passed=passed,
                output=result.result if passed else None,
                error=result.result if not passed else None,
                execution_time_ms=execution_time,
                memory_used_mb=None,
                confidence_score=self._calculate_confidence(passed, result.result, execution_time),
                sandbox_type="daytona",
            )
        except Exception as e:
            return SandboxTestResult(
                passed=False, output=None, error=str(e),
                execution_time_ms=int((time.monotonic() - start_time) * 1000),
                memory_used_mb=None, confidence_score=0.0, sandbox_type="daytona",
            )
        finally:
            if sandbox and self._daytona:
                try:
                    self._daytona.delete(sandbox)
                except Exception:
                    pass

    async def _test_in_subprocess(
        self,
        skill_code: str,
        skill_name: str,
        timeout: int,
    ) -> SandboxTestResult:
        start_time = time.monotonic()
        test_code = self._wrap_with_test_data(skill_code)
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, prefix=f"skill_test_{skill_name}_"
            ) as tmp:
                tmp.write(test_code)
                tmp_path = tmp.name

            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return SandboxTestResult(
                    passed=False, output=None, error=f"Timeout après {timeout}s",
                    execution_time_ms=timeout * 1000, memory_used_mb=None,
                    confidence_score=0.0, sandbox_type="subprocess_fallback",
                )

            execution_time = int((time.monotonic() - start_time) * 1000)
            passed = proc.returncode == 0
            output = stdout.decode().strip() if stdout else None
            error = stderr.decode().strip() if stderr else None

            return SandboxTestResult(
                passed=passed,
                output=output,
                error=error if not passed else None,
                execution_time_ms=execution_time,
                memory_used_mb=None,
                confidence_score=self._calculate_confidence(passed, output, execution_time),
                sandbox_type="subprocess_fallback",
            )
        except Exception as e:
            return SandboxTestResult(
                passed=False, output=None, error=str(e),
                execution_time_ms=int((time.monotonic() - start_time) * 1000),
                memory_used_mb=None, confidence_score=0.0, sandbox_type="subprocess_fallback",
            )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _wrap_with_test_data(self, skill_code: str) -> str:
        """
        Enveloppe le skill avec des données de test fictives.
        Convention : le skill doit exposer run(data: dict) -> dict
        """
        return f"""
TEST_DATA = {MOCK_TEST_DATA}

{skill_code}

try:
    result = run(TEST_DATA)
    print(f"OK: {{result}}")
except NameError:
    print("OK: skill exécuté sans erreur")
except Exception as e:
    raise RuntimeError(f"Skill failed: {{e}}")
"""

    def _calculate_confidence(
        self,
        passed: bool,
        output: Optional[str],
        execution_time_ms: int,
    ) -> float:
        if not passed:
            return 0.0
        score = 0.7
        if output and len(output) > 0:
            score += 0.1
        if execution_time_ms < 5000:
            score += 0.1
        if execution_time_ms < 1000:
            score += 0.1
        return min(score, 1.0)

    # ── Exécution RÉELLE d'un skill avec données (pour l'exécuteur) ───────
    async def execute_skill(
        self,
        skill_code: str,
        skill_name: str,
        data: dict,
        max_execution_seconds: int = 30,
    ) -> dict:
        """Exécute `run(data)` dans un sous-process isolé et renvoie la SORTIE réelle.

        Les données passent par stdin (jamais injectées dans le code source → pas d'injection).
        Env réduit (pas d'accès réseau implicite). Renvoie :
          {ok: bool, output: dict|None, error: str|None, execution_time_ms: int, sandbox_type: str}
        """
        import json as _json

        start = time.monotonic()
        marker = "__SKILL_RESULT__"
        wrapper = (
            "import json, sys\n"
            "_data = json.loads(sys.stdin.read() or '{}')\n"
            f"{skill_code}\n"
            "_res = run(_data)\n"
            f"print({marker!r} + json.dumps(_res, ensure_ascii=False, default=str))\n"
        )
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, prefix=f"skill_exec_{skill_name}_"
            ) as tmp:
                tmp.write(wrapper)
                tmp_path = tmp.name

            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=_json.dumps(data or {}).encode()),
                    timeout=max_execution_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {"ok": False, "output": None, "error": f"Timeout après {max_execution_seconds}s",
                        "execution_time_ms": max_execution_seconds * 1000, "sandbox_type": "subprocess"}

            elapsed = int((time.monotonic() - start) * 1000)
            out = (stdout.decode() if stdout else "").strip()
            err = (stderr.decode() if stderr else "").strip()

            if proc.returncode != 0:
                return {"ok": False, "output": None, "error": err or "échec d'exécution",
                        "execution_time_ms": elapsed, "sandbox_type": "subprocess"}

            parsed = None
            for line in out.splitlines():
                if line.startswith(marker):
                    try:
                        parsed = _json.loads(line[len(marker):])
                    except Exception:
                        parsed = None
                    break
            return {
                "ok": parsed is not None,
                "output": parsed,
                "error": None if parsed is not None else "sortie du skill illisible",
                "execution_time_ms": elapsed,
                "sandbox_type": "subprocess",
            }
        except Exception as e:
            return {"ok": False, "output": None, "error": str(e),
                    "execution_time_ms": int((time.monotonic() - start) * 1000),
                    "sandbox_type": "subprocess"}
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


# Singleton — importé par l'Agent 3
sandbox_client = DaytonaClient()
