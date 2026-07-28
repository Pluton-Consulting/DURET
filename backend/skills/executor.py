"""
Exécuteur de skills — LE chaînon entre la table `skills` et les agents.

- Registre : liste / charge les skills depuis la base (filtrage par agent, par statut).
- Exécution : lance `run(data)` en sous-process isolé (sandbox_client), journalise l'usage.
- Sélection : propose les skills pertinentes pour une requête (par agent), pour que
  l'Agent 1 puisse en invoquer une.

Garde-fou : seules les skills 'validated' / 'stable' sont exécutables par défaut. Les
'draft' ne tournent qu'en mode test explicite (`allow_draft=True`), réservé aux admins.
Aucune donnée client ne sort de l'infra : le code s'exécute en local, isolé.
"""
import logging
import time

from database.connection import get_db
from sandbox.daytona_client import sandbox_client
from security.audit import log_action

logger = logging.getLogger("duret.skills")

# Statuts d'un skill réellement invocable par les agents en production.
RUNNABLE_STATUSES = ("validated", "stable")


class SkillError(Exception):
    """Skill introuvable ou non exécutable (statut insuffisant)."""


async def list_skills(agent: str | None = None, statuses: tuple | None = None,
                      include_code: bool = False) -> list[dict]:
    cols = ("name, description, status, agent, category, enabled, "
            "confidence_score, usage_count, updated_at")
    if include_code:
        cols += ", code, prompt_template"
    clauses: list[str] = []
    args: list = []
    if agent:
        args.append(agent)
        clauses.append(f"agent = ${len(args)}")
    if statuses:
        args.append(list(statuses))
        clauses.append(f"status = ANY(${len(args)})")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT {cols} FROM skills{where} ORDER BY agent, category, name", *args
        )
    return [dict(r) for r in rows]


async def get_skill(name: str) -> dict | None:
    from mail.skills import SKILLS_NATIFS

    if name in SKILLS_NATIFS:
        if user is None:
            # Sans identité, impossible de vérifier les droits sur une boîte :
            # on refuse plutôt que d'exécuter avec des droits indéterminés.
            raise SkillError(f"skill '{name}' : identité de l'appelant requise")

        # Un skill natif reste pilotable depuis l'interface : s'il est référencé
        # en base et désactivé, on le refuse. Sans ligne en base, on l'autorise
        # (le code est livré avec l'application, contrairement au code généré).
        async with get_db() as conn:
            ref = await conn.fetchrow("SELECT enabled FROM skills WHERE name = $1", name)
        if ref is not None and not ref["enabled"]:
            raise SkillError(f"skill '{name}' désactivé")

        start = time.monotonic()
        sortie = await SKILLS_NATIFS[name](data or {}, user)
        duree = int((time.monotonic() - start) * 1000)
        try:
            async with get_db() as conn:
                await conn.execute(
                    "UPDATE skills SET usage_count = usage_count + 1, updated_at = NOW() "
                    "WHERE name = $1", name)
        except Exception:
            pass
        return {"skill": name, "status": "native", "ok": True, "output": sortie,
                "error": None, "execution_time_ms": duree, "sandbox_type": "natif"}

    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT name, description, status, agent, category, code, prompt_template, "
            "confidence_score, usage_count, version, updated_at "
            "FROM skills WHERE name = $1",
            name,
        )
    return dict(row) if row else None


async def available_for_agent(agent: str) -> list[dict]:
    """Skills invocables (validated/stable) pour un agent — utilisé par la boucle agent."""
    return await list_skills(agent=agent, statuses=RUNNABLE_STATUSES, include_code=False)


async def execute_skill(name: str, data: dict, user_id: str | None = None,
                        allow_draft: bool = False, user=None) -> dict:
    """Exécute un skill par nom avec `data`. Journalise, incrémente usage_count.

    Renvoie : {skill, status, ok, output, error, execution_time_ms, sandbox_type}.
    Lève SkillError si le skill est introuvable ou non exécutable.
    """
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT code, status, enabled FROM skills WHERE name = $1", name)
    if not row:
        raise SkillError(f"skill introuvable : {name}")

    status = row["status"]
    if not allow_draft:
        if status not in RUNNABLE_STATUSES:
            raise SkillError(
                f"skill '{name}' non exécutable (statut '{status}') — validation requise"
            )
        if not row["enabled"]:
            raise SkillError(f"skill '{name}' désactivé")

    result = await sandbox_client.execute_skill(row["code"], name, data or {})

    # Compteur d'usage + audit (best-effort : ne bloque jamais l'exécution).
    try:
        async with get_db() as conn:
            await conn.execute(
                "UPDATE skills SET usage_count = usage_count + 1, updated_at = NOW() WHERE name = $1",
                name,
            )
    except Exception:
        pass
    try:
        await log_action(
            action="skill_executed", user_id=user_id,
            success=bool(result.get("ok")),
            duration_ms=result.get("execution_time_ms"),
            metadata={"skill": name, "status": status, "sandbox": result.get("sandbox_type")},
        )
    except Exception:
        pass

    return {"skill": name, "status": status, **result}
