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
import hashlib
import hmac
import json as _json
import logging
import time

from database.connection import get_db
from sandbox.daytona_client import sandbox_client
from security.audit import log_action

logger = logging.getLogger("duret.skills")

# Statuts d'un skill réellement invocable par les agents en production.
RUNNABLE_STATUSES = ("validated", "stable")


# Réexporté depuis `skills.erreurs` : les skills doivent pouvoir lever sans
# importer la base de données. `from skills.executor import SkillError` reste
# valide partout, et la classe reste unique.
from skills.erreurs import SkillError  # noqa: E402,F401


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


def hash_payload(name: str, data: dict) -> str:
    """Empreinte du couple (skill, arguments), sous forme canonique.

    Elle lie une approbation humaine au payload EXACT qui lui a été présenté :
    approuver « envoyer à Dupont » ne peut pas servir à exécuter « envoyer à
    quelqu'un d'autre ».
    """
    canon = _json.dumps({"skill": name, "args": data or {}},
                        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                        default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def effet_du_skill(name: str, ligne=None) -> str:
    """Effet d'un skill. FAIL-CLOSED : non déclaré = `externe`, donc verrouillé."""
    from mail.skills import EFFETS_NATIFS
    if name in EFFETS_NATIFS:
        return EFFETS_NATIFS[name]
    # Skills déclarés au REGISTRE (propres au projet) : l'effet vit dans la
    # déclaration, à côté de la fonction — plus de table à tenir ici. Le défaut
    # du registre est « externe », comme celui de cette fonction : un oubli
    # verrouille, il n'ouvre jamais.
    from skills.registre import effet as effet_declare
    declare = effet_declare(name)
    if declare:
        return declare
    try:
        valeur = ligne["effect"] if ligne is not None else None
    except (KeyError, TypeError):
        valeur = None
    return valeur or "externe"


def _verifier_effet(name: str, data: dict, ligne, approbation: dict | None) -> str:
    """Verrou structurel des actions à effet externe.

    Placé dans l'exécuteur, c'est-à-dire dans le goulot que TOUS les chemins
    empruntent (chat, API, tâche planifiée, webhook). Un modèle de langage ne
    contourne pas un `if` : aucune formulation, aucune injection de prompt cachée
    dans un document ingéré ne peut faire exécuter une action externe sans une
    approbation humaine liée au payload exact.
    """
    effet = effet_du_skill(name, ligne)
    if effet != "externe":
        return effet
    attendu = hash_payload(name, data or {})
    fourni = (approbation or {}).get("payload_hash") or ""
    if not hmac.compare_digest(fourni, attendu):
        raise SkillError(
            f"skill '{name}' : action à effet externe, une validation humaine est "
            "requise avant exécution.")
    return effet


async def execute_skill(name: str, data: dict, user_id: str | None = None,
                        allow_draft: bool = False, user=None,
                        approbation: dict | None = None,
                        trigger: dict | None = None) -> dict:
    """Exécute un skill par nom avec `data`. Journalise, incrémente usage_count.

    Deux familles de skills :
      * NATIFS (mail…) : fonctions Python du backend. Elles ont besoin du LLM, de
        la base documentaire et surtout de l'IDENTITÉ de l'appelant pour vérifier
        ses droits sur une boîte mail — inaccessibles depuis un bac à sable isolé.
      * GÉNÉRÉS : code exécuté en bac à sable, sans accès au reste du système.

    Renvoie : {skill, status, ok, output, error, execution_time_ms, sandbox_type}.
    Lève SkillError si le skill est introuvable ou non exécutable.
    """
    from mail.skills import SKILLS_NATIFS
    from skills.registre import fonction as fonction_declaree

    # Registre d'abord ? Non : les NATIFS gardent la priorité, leur signature
    # est déclarée dans le code du socle. Un module de projet ne peut pas
    # masquer un skill du socle en réutilisant son nom.
    executable = SKILLS_NATIFS.get(name) or fonction_declaree(name)
    if executable is not None:
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

        _verifier_effet(name, data, ref, approbation)

        start = time.monotonic()
        sortie = await executable(data or {}, user)
        duree = int((time.monotonic() - start) * 1000)
        try:
            async with get_db() as conn:
                await conn.execute(
                    "UPDATE skills SET usage_count = usage_count + 1, updated_at = NOW() "
                    "WHERE name = $1", name)
        except Exception:
            pass

        # Les skills natifs échappaient à l'audit (seuls ceux du bac à sable y
        # passaient). Indispensable pour répondre à « qui a déclenché quoi, au nom
        # de qui » dès que des tâches autonomes exécuteront ces mêmes skills.
        try:
            await log_action(
                action="skill_executed", user_id=str(user.id),
                on_behalf_of=str(user.id), duration_ms=duree,
                trigger_type=(trigger or {}).get("type", "chat"),
                trigger_id=(trigger or {}).get("id"),
                metadata={"skill": name, "effet": effet_du_skill(name, ref),
                          "mailbox": (sortie or {}).get("mailbox")},
            )
        except Exception:
            pass

        return {"skill": name, "status": "native", "ok": True, "output": sortie,
                "error": None, "execution_time_ms": duree, "sandbox_type": "natif"}

    async with get_db() as conn:
        row = await conn.fetchrow("SELECT code, status, enabled FROM skills WHERE name = $1", name)
    if not row:
        raise SkillError(f"skill introuvable : {name}")

    status = row["status"]
    # Même garde que le catalogue, au goulot que TOUS les chemins empruntent :
    # une coquille validée par erreur ne s'exécute pas non plus. Le message
    # nomme la vraie capacité, pour que le modèle se rattrape dans le même tour.
    if "Squelette g" in (row["code"] or ""):
        raise SkillError(
            f"skill '{name}' : squelette non implémenté, pas une capacité. "
            "Pour une recherche dans la mémoire d'entreprise, utilise "
            "`rechercher_documents`.")
    if not allow_draft:
        if status not in RUNNABLE_STATUSES:
            raise SkillError(
                f"skill '{name}' non exécutable (statut '{status}') : validation requise"
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
