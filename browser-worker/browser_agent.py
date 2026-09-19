"""
Exécution d'une tâche de navigation agentique via browser-use.

- Boucle observe→décide→agit pilotée par le LLM (natif browser-use).
- Toute action modifiante DOIT passer par l'action custom `request_human_approval`
  (gate HITL) : insertion d'une ligne `validations` + attente de la décision humaine.
- Identifiants injectés via `sensitive_data` (jamais vus du LLM) + `allowed_domains`.
- Session connectée persistée via `storage_state` par domaine.
- Extraction structurée optionnelle → réinjection RAG via le webhook d'ingestion.
"""
import asyncio
import logging

logger = logging.getLogger("browser-worker.agent")
import base64
import io
import json
import os
import re
import time

import httpx

import wconfig
import db
import credentials
import lecture_sure
import llm_factory
import site_login


# ── Capture d'écran (best-effort, tolérant aux variantes d'API) ───────────
def _downscale_b64(b64: str) -> str:
    try:
        from PIL import Image
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.width > wconfig.SCREENSHOT_MAX_WIDTH:
            ratio = wconfig.SCREENSHOT_MAX_WIDTH / img.width
            img = img.resize((wconfig.SCREENSHOT_MAX_WIDTH, int(img.height * ratio)))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=50)
        return base64.b64encode(out.getvalue()).decode()
    except Exception:
        return b64


async def _capture_screenshot(browser_session) -> str | None:
    if browser_session is None:
        return None
    raw = None
    try:
        shot = await browser_session.take_screenshot()      # certaines versions : base64
        if isinstance(shot, str):
            return _downscale_b64(shot)
        if isinstance(shot, (bytes, bytearray)):
            raw = bytes(shot)
    except Exception:
        raw = None
    if raw is None:
        try:
            page = await browser_session.get_current_page()
            raw = await page.screenshot(type="jpeg", quality=50)
        except Exception:
            return None
    try:
        return _downscale_b64(base64.b64encode(raw).decode())
    except Exception:
        return None


async def _wait_for_decision(validation_id: str) -> str:
    deadline = time.monotonic() + wconfig.APPROVAL_TIMEOUT_S
    while time.monotonic() < deadline:
        st = await db.poll_validation_status(validation_id)
        if st in ("approved", "rejected"):
            return st
        await asyncio.sleep(2)
    return "timeout"


# ── Jeu d'outils : action d'approbation humaine ───────────────────────────
def _extrait_de_recherche(contenu: str, requete: str, longueur: int = 600) -> str:
    """Le passage d'une page qui porte les mots cherchés, pas son menu."""
    texte = re.sub(r"\s+", " ", str(contenu or "")).strip()
    bas = texte.lower()
    mots = [m for m in re.findall(r"\w{4,}", str(requete or "").lower()) if not m.startswith("site")]
    positions = [bas.find(m) for m in mots if bas.find(m) >= 0]
    debut = max(0, min(positions) - 120) if positions else 0
    return texte[debut:debut + longueur]


async def _rechercher(requete: str, domaines: list[str]):
    """L'action `search` de l'agent, servie par le lecteur rapide du conteneur.

    Celle de browser-use OUVRE Google, Bing ou DuckDuckGo dans l'onglet de l'agent :
    hors des domaines autorisés, c'est bloqué (« blocked by security policy », 19/09) ;
    sans domaines, c'est un captcha une fois sur deux. Le lecteur rapide passe par ses
    moteurs à lui, lit les premières pages et rend adresses + extraits. Les résultats
    hors des sites autorisés sont écartés : la tâche reste où la personne l'a mise.
    """
    from browser_use import ActionResult
    import rapide

    q = str(requete or "").strip()
    if not q:
        return ActionResult(error="Recherche vide : dis ce que tu cherches.")
    bases = [d for d in domaines or [] if not d.startswith("*.")]
    if len(bases) == 1 and "site:" not in q.lower():
        q = f"{q} site:{bases[0]}"
    try:
        # UNE page à la fois : le Chromium de l'agent tourne déjà dans ce conteneur.
        res = await rapide.chercher(q, 4, 12000, concurrence=1)
    except Exception as e:  # noqa: BLE001 — une recherche qui échoue se dit, elle ne tue pas la tâche
        return ActionResult(error=f"La recherche web n'a pas répondu ({type(e).__name__}). "
                                  "Explore le site par ses menus et ses liens.")
    lignes, adresses = [], []
    for r in res.get("results") or []:
        u = str(r.get("url") or "")
        if not u or (domaines and not lecture_sure.hote_autorise(u, domaines)):
            continue
        adresses.append(u)
        extrait = _extrait_de_recherche(r.get("contenu"), requete) or "(page sans texte lisible)"
        lignes.append(f"- {r.get('titre') or u}\n  {u}\n  {extrait}")
    if not lignes:
        ou = f" sur {', '.join(bases)}" if bases else ""
        return ActionResult(
            extracted_content=(f"Aucun résultat pour « {q} »{ou}. Explore le site par ses menus, "
                               "ses liens et son moteur de recherche interne."),
            long_term_memory=f"Recherche « {q} » : aucun résultat")
    return ActionResult(
        extracted_content=f"Résultats pour « {q} » :\n" + "\n".join(lignes),
        long_term_memory=f"Recherche « {q} » : " + ", ".join(adresses),
        include_extracted_content_only_once=True)


def build_tools(job_id: str, user_id: str, readonly: bool = True, domaines: list[str] | None = None):
    from browser_use import Tools, ActionResult
    from pydantic import BaseModel, Field

    # LECTURE (défaut) : on lit un site comme une personne — liens, menus, onglets,
    # bannières, moteur de recherche du site — mais rien de ce qui ENVOIE (formulaire
    # posté, commande, inscription, suppression) : `lecture_sure` juge chaque
    # interaction sur l'élément visé, au moment de l'exécuter (19/09 ; avant, la lecture
    # retirait tout clic et l'agent ne pouvait qu'inventer des adresses).
    # ⚠ MODE ÉCRITURE (readonly=False) : ce qui n'est pas une interaction de lecture
    # passe par l'accord humain ; le gate d'approbation reste best-effort — le verrou
    # réel (plan→approuver→exécuter) n'est pas encore implémenté (voir README §Sécurité).
    try:
        tools = Tools()
    except TypeError as e:
        raise RuntimeError("API des outils navigateur incompatible ; navigation arrêtée avant toute action.") from e

    class RechercheWeb(BaseModel):
        query: str
        engine: str = Field(default="duckduckgo", description="sans effet : un seul moteur, celui du conteneur")

    @tools.registry.action(
        "Cherche sur le web et rend les adresses trouvées avec un extrait de chaque page "
        "(limité aux sites autorisés quand la tâche en fixe). Ouvre ensuite l'adresse choisie avec navigate.",
        param_model=RechercheWeb)
    async def search(params: RechercheWeb):
        return await _rechercher(params.query, domaines or [])

    async def request_human_approval(summary: str, target_url: str, browser_session=None):
        screenshot_b64 = await _capture_screenshot(browser_session)
        payload = {"job_id": job_id, "url": target_url, "summary": summary}
        if screenshot_b64:
            payload["screenshot"] = screenshot_b64

        vid = await db.insert_validation(
            thread_id=job_id, user_id=user_id, reason="browser_action",
            payload=payload, draft=summary,
        )
        await db.update_status(job_id, "awaiting_approval")
        await db.log_audit("browser_action_requested", user_id,
                           metadata={"job_id": job_id, "url": target_url})

        decision = "timeout"
        try:
            decision = await _wait_for_decision(vid)
        finally:
            # Purge la capture (PII) + repasse en cours QUOI QU'IL ARRIVE (exception/annulation).
            await db.purge_validation_screenshot(vid)
            await db.update_status(job_id, "running")
        await db.log_audit(f"browser_action_{decision}", user_id,
                           metadata={"job_id": job_id, "url": target_url})

        if decision == "approved":
            return ActionResult(
                extracted_content="APPROVED : l'humain a validé. Tu peux exécuter l'action maintenant."
            )
        return ActionResult(
            extracted_content=(f"REJECTED ({decision}) : NE PAS exécuter l'action. "
                               "Termine la tâche proprement sans la réaliser.")
        )

    # Le contrôle s'exécute au goulot réel, y compris si browser-use ajoute
    # un outil dynamiquement après la construction du registre.
    import copy
    lectures = {"search", "navigate", "go_back", "wait", "switch", "close", "extract",
                "search_page", "find_elements", "scroll", "find_text", "screenshot", "dropdown_options", "done"}
    # Jugées à l'élément visé : permises sans accord quand elles ne font que MONTRER.
    interactions = {"click", "input", "send_keys", "select_dropdown",
                    "click_element_by_index", "input_text", "select_dropdown_option"}
    modifications = {"click", "input", "send_keys", "select_dropdown", "upload_file",
                     "click_element_by_index", "input_text", "select_dropdown_option", "drag_drop", "clear_text"}
    original = tools.registry.execute_action
    async def execute_avec_accord(action_name, params, *args, **kwargs):
        if action_name not in lectures:
            session = kwargs.get("browser_session")
            if action_name in interactions:
                noeud, index = None, (params or {}).get("index")
                if index is not None and session is not None:
                    try:
                        noeud = await session.get_element_by_index(int(index))
                    except Exception:  # noqa: BLE001 — élément disparu : refusé plus bas, avec sa raison
                        noeud = None
                permis, raison = lecture_sure.interaction_permise(action_name, params or {}, noeud)
                if permis:
                    return await original(action_name, params, *args, **kwargs)
                if readonly:
                    return ActionResult(error=raison)
            if readonly or action_name not in modifications:
                raise RuntimeError("Cette action n'est pas autorisée dans cette navigation.")
            charge = copy.deepcopy(params)
            url = await session.get_current_page_url() if session else ""
            decision = await request_human_approval(
                action_name + " : " + json.dumps(charge, ensure_ascii=False, default=str), url, session)
            if not str(getattr(decision,"extracted_content","")).startswith("APPROVED"):
                raise RuntimeError("Action non approuvée ; aucune interaction exécutée.")
            params = charge
        return await original(action_name, params, *args, **kwargs)
    tools.registry.execute_action = execute_avec_accord
    # Ne pas annoncer les actions interdites au modèle. Le verrou d'exécution
    # ci-dessus reste déterminant même si une nouvelle version les réintroduit.
    for nom in list(tools.registry.registry.actions):
        if nom not in lectures and nom not in interactions and (readonly or nom not in modifications):
            tools.exclude_action(nom)
    return tools


def _build_output_model(output_schema):
    """output_schema = {champ: 'str'|'int'|'float'|'bool'} → modèle pydantic simple."""
    if not output_schema or not isinstance(output_schema, dict):
        return None
    try:
        from pydantic import create_model
        type_map = {"str": str, "int": int, "float": float, "bool": bool}
        fields = {name: (type_map.get(str(t).lower(), str), None)
                  for name, t in output_schema.items()}
        return create_model("BrowserExtraction", **fields)
    except Exception:
        return None


async def _post_to_rag(job_id: str, structured: dict | None, final_text: str) -> None:
    # Le backend reprend le résultat déjà enregistré pour CE job ; le worker
    # ne détient plus le secret d'ingestion générale.
    resultat = await db._dire("POST", "/tache/" + job_id + "/indexer", {})
    if not resultat or not resultat.get("ok"):
        logger.warning("Navigation terminée ; indexation non confirmée pour %s", job_id)


_AGENT_UTILISATEUR: str | None = None
_CREDIT_EPUISE = re.compile(r"\b402\b|more credits|insufficient[_ ](?:credits|quota|balance)", re.I)


async def _agent_utilisateur() -> str:
    """L'identité d'un Chrome ordinaire à la version du Chromium de l'image (lue une fois)."""
    global _AGENT_UTILISATEUR
    if _AGENT_UTILISATEUR is None:
        import subprocess
        import rapide
        try:
            sortie = (await asyncio.to_thread(subprocess.run, [rapide.CHROMIUM, "--version"],
                                              capture_output=True, text=True, timeout=15)).stdout
        except Exception:  # noqa: BLE001 — sans version lisible, une version récente plausible
            sortie = ""
        _AGENT_UTILISATEUR = lecture_sure.agent_utilisateur(sortie)
    return _AGENT_UTILISATEUR


# ── Point d'entrée : exécuter une tâche complète ──────────────────────────
async def run_task(job_id: str, task_prompt: str, allowed_domains: list[str],
                   user_id: str, ingest: bool = False, readonly: bool = True,
                   output_schema=None, max_steps: int | None = None) -> None:
    from browser_use import Agent, Browser

    await db.update_status(job_id, "running")
    await db.log_audit("browser_task_running", user_id,
                       metadata={"job_id": job_id, "domains": allowed_domains})

    browser = None
    step_state = {"n": 0}   # défini avant le try : lisible même si l'échec survient au démarrage
    try:
        llm = llm_factory.build_llm()
        # garde-fou domaines. En ÉCRITURE : hôtes EXACTS (pas de wildcard *.{d} qui
        # exposerait les identifiants sur un sous-domaine tiers / repris). En LECTURE :
        # aucun identifiant n'est injecté, le site nommé s'ouvre avec ses sous-domaines
        # (www., cdn. — c'est là que vivent ses fiches techniques).
        allow = lecture_sure.domaines_de_lecture(allowed_domains) if readonly else list(allowed_domains)
        tools = build_tools(job_id, user_id, readonly=readonly, domaines=allow)
        sensitive = {} if readonly else credentials.build_sensitive_data(allowed_domains)

        # session persistée sur le domaine principal
        os.makedirs(wconfig.SESSIONS_DIR, exist_ok=True)
        primary = allowed_domains[0] if allowed_domains else "default"
        storage_path = os.path.join(wconfig.SESSIONS_DIR, f"{primary}.json")

        # Flags de stabilité Chromium en conteneur : pas de sandbox utilisateur possible
        # (non-root), /dev/shm potentiellement insuffisant sous pression mémoire (WSL),
        # pas de GPU. Sans ces flags, le lancement peut boucler puis timeouter au cold start.
        chromium_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            # Empreinte mémoire minimale (PC 7 Go, WSL ~3.3 Go) : Chromium en UN seul process
            # au lieu de ~5. Sans ça, la cible CDP initiale se fait tuer sous pression mémoire
            # (« Target ... may have detached »). OK pour nos tâches mono-page (login/lecture).
            "--single-process",
            "--no-zygote",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-features=TranslateUI",
            "--mute-audio",
            "--no-first-run",
        ]
        browser_kwargs = {
            "headless": True,
            # L'IDENTITÉ D'UN CHROME ORDINAIRE : « HeadlessChrome » suffisait à Akamai pour
            # répondre « Access Denied » (gerflor.fr, 19/09) alors que la même page s'ouvrait
            # avec un Chrome ordinaire. Même version majeure que le binaire.
            "user_agent": await _agent_utilisateur(),
            "allowed_domains": allow,
            "storage_state": storage_path,
            "args": chromium_args,
            "chromium_sandbox": False,
            # Temps d'attente RAPIDES (défauts browser-use) : réactivité proche d'un site classique.
            # Les tests réussis tournaient à ces valeurs ; les gonfler donnait une impression de bug.
            "minimum_wait_page_load_time": 0.25,
            "wait_for_network_idle_page_load_time": 0.5,
            "wait_between_actions": 0.1,
        }
        try:
            browser = Browser(**browser_kwargs)
        except Exception:
            browser_kwargs.pop("storage_state", None)
            browser = Browser(**browser_kwargs)

        # ── Login DÉTERMINISTE préalable (domaines configurés, mode écriture) ──
        # Évite que le LLM se batte avec le formulaire de connexion (hallucinations type
        # « shadow DOM », boucles, tentatives répétées qui verrouillent le compte). Le worker
        # remplit et soumet lui-même via CDP, puis l'agent démarre DÉJÀ authentifié.
        # Nécessite le mode écriture : soumettre un formulaire est une action modifiante.
        effective_task = task_prompt
        if not readonly and site_login.has_config(primary):
            try:
                await browser.start()
                login_info = await site_login.try_login(browser, primary)
            except Exception as e:
                login_info = {"attempted": True, "ok": False, "reason": type(e).__name__}
            await db.log_audit(
                "browser_login_ok" if login_info.get("ok") else "browser_login_failed",
                user_id, success=bool(login_info.get("ok")),
                metadata={"job_id": job_id, "domain": primary,
                          **{k: v for k, v in login_info.items() if k != "attempted"}},
            )
            if login_info.get("attempted") and not login_info.get("ok"):
                # Login refusé (mot de passe erroné ou compte verrouillé) → inutile de lancer
                # l'agent : échec précoce avec message clair (économie de temps/tokens).
                await db.set_result(
                    job_id, "failed",
                    result={"summary": "Échec du login : le site a refusé les identifiants "
                                       "(mot de passe erroné, ou compte temporairement verrouillé "
                                       "après des tentatives répétées). L'agent n'a pas été lancé.",
                            "steps": 0, "step_log": [], "login": login_info},
                    steps=0,
                )
                await db.set_error(job_id, "login_refused")
                return
            if login_info.get("ok"):
                effective_task = ("Tu es DÉJÀ connecté au site (connexion déjà effectuée). "
                                  "Ne cherche pas à te reconnecter. " + task_prompt)

        output_model = _build_output_model(output_schema)

        agent_kwargs = dict(
            task=effective_task, llm=llm, browser=browser, tools=tools,
            use_vision=wconfig.USE_VISION,
            # LongCat 2.0 / modèles raisonnants : simplifier le schéma d'action et fournir
            # des exemples de format aident browser-use à parser la sortie structurée.
            use_thinking=False,
            # MODE RAPIDE, SANS JUGE (19/09, mesuré sur la même tâche Gerflor) : les champs de
            # réflexion et le juge final doublaient les appels — 16 étapes en 9 min, coupées ;
            # sans eux, 17 étapes en 3 min 38 et la liste complète des produits, source citée.
            flash_mode=True,
            use_judge=False,
            include_tool_call_examples=True,
            # Garde-fous anti-flail : stoppe après N échecs consécutifs, détecte les boucles
            # (mêmes actions/objectifs répétés), et laisse plus de temps au LLM lent (LongCat)
            # que les 75 s par défaut qui provoquaient des « LLM call timed out ».
            max_failures=4,
            loop_detection_enabled=True,
            llm_timeout=120,
            # SA SITUATION, dite en plus des règles de browser-use : explorer au lieu de
            # deviner des adresses, ce que la lecture permet, les sites autorisés.
            extend_system_message=lecture_sure.consigne_de_navigation(allow, readonly),
        )
        if sensitive:
            agent_kwargs["sensitive_data"] = sensitive
        if output_model is not None:
            agent_kwargs["output_model_schema"] = output_model

        agent = Agent(**agent_kwargs)

        async def on_step_end(a):
            step_state["n"] += 1
            try:
                await db.set_steps(job_id, step_state["n"])
            except Exception:
                pass

        # LE PLAFOND VIENT DE L'APPELANT QUAND IL EN POSE UN.
        # Une tache lancee depuis l'ecran peut prendre son temps : personne
        # n'attend devant. Une tache lancee depuis le chat se deroule DANS un
        # tour de conversation : au-dela de quelques minutes, l'utilisateur
        # n'a plus rien, et l'agent est coupe en pleine phrase. Mieux vaut
        # qu'il s'arrete de lui-meme et redige ce qu'il a vu.
        history = await agent.run(max_steps=max_steps or wconfig.MAX_STEPS,
                                  on_step_end=on_step_end)

        final_text = ""
        try:
            final_text = history.final_result() or ""
        except Exception:
            final_text = ""

        # Journal des étapes (défensif : les méthodes de l'historique varient selon la version).
        def _safe(name):
            try:
                fn = getattr(history, name, None)
                v = fn() if callable(fn) else None
                return list(v) if v else []
            except Exception:
                return []

        urls = _safe("urls")
        actions = _safe("action_names")
        extracted = _safe("extracted_content")
        n = max(len(urls), len(actions), step_state["n"])
        step_log = [
            {
                "n": i + 1,
                "url": urls[i] if i < len(urls) else None,
                "action": actions[i] if i < len(actions) else None,
            }
            for i in range(n)
        ]

        try:
            fini = bool(history.is_done())
        except Exception:  # noqa: BLE001 — selon la version, l'historique ne le dit pas
            fini = bool(final_text.strip())

        # LE CRÉDIT ÉPUISÉ SE DIT. Relevé le 19/09 : OpenRouter répondait 402 (« requires more
        # credits ») ; l'agent échouait cinq fois, puis la tâche finissait « terminée » avec,
        # en guise de résumé, le collage de ses messages d'action. Personne ne pouvait
        # deviner qu'il suffisait de recharger un compte.
        erreurs = [str(e) for e in _safe("errors") if e]
        if not fini and any(_CREDIT_EPUISE.search(e) for e in erreurs):
            await db.set_error(job_id, (
                "Le modèle qui conduit le navigateur a refusé la demande faute de crédit chez son "
                "fournisseur : la navigation s'est arrêtée. Recharger ce crédit (ou changer de modèle) "
                "la rétablira ; la recherche web et l'ouverture d'une page marchent sans lui."))
            await db.log_audit("browser_task_failed", user_id, success=False,
                               metadata={"job_id": job_id, "error_type": "credit_epuise",
                                         "steps_reached": step_state["n"], "readonly": readonly})
            return

        # Fallback : si l'agent n'a pas rédigé de résumé, on remonte ce qu'il a LU (les
        # extraits longs), pas ses messages d'action ; et une navigation coupée par le
        # plafond d'étapes le dit en tête.
        if not final_text.strip() and extracted:
            lus = [str(e) for e in extracted if e and len(str(e)) > 150] or [str(e) for e in extracted if e]
            entete = "" if fini else ("NAVIGATION INACHEVÉE (plafond d'étapes atteint avant la fin) — "
                                      "ce qui a été lu en chemin :\n\n")
            final_text = (entete + "\n\n".join(lus))[:3000]

        structured = None
        if output_model is not None:
            try:
                so = history.structured_output
                structured = so.model_dump() if so is not None else None
            except Exception:
                structured = None

        await db.set_result(
            job_id, "completed",
            result={"summary": final_text, "steps": step_state["n"], "step_log": step_log},
            structured=structured, steps=step_state["n"],
        )
        await db.log_audit("browser_task_completed", user_id,
                           metadata={"job_id": job_id, "steps": step_state["n"]})

        if ingest:
            await _post_to_rag(job_id, structured, final_text)

    except Exception as e:
        # LA TRACE COMPLÈTE VA AU JOURNAL DU CONTENEUR, et seulement là. Le nom
        # du type suffisait à dire « ça a cassé », jamais OÙ : le diagnostic de
        # l'AttributeError de `log_audit` a demandé une relecture de tout le
        # module au lieu d'une ligne de log. Le journal est interne — rien de
        # tout cela n'atteint le modèle ni l'écran.
        logger.exception("Tâche %s tombée (%s)", job_id, type(e).__name__)
        await db.set_error(job_id, type(e).__name__)  # message générique (pas de fuite d'URL/hôte)
        await db.log_audit("browser_task_failed", user_id, success=False,
                           metadata={"job_id": job_id, "error_type": type(e).__name__,
                                     "steps_reached": step_state["n"], "readonly": readonly})
    finally:
        if browser is not None:
            try:
                await browser.stop()   # sauvegarde storage_state
            except Exception:
                pass
