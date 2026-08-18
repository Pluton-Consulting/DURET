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
import base64
import io
import json
import os
import time

import httpx

import wconfig
import db
import credentials
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
def build_tools(job_id: str, user_id: str, readonly: bool = True):
    from browser_use import Tools, ActionResult

    # LECTURE SEULE (défaut) = VERROU RÉEL : on retire TOUTES les actions d'interaction /
    # mutation du registre (clic, saisie, sélection, upload, glisser-déposer). L'agent ne
    # peut donc PAS cliquer/soumettre/écrire — uniquement naviguer par URL, scroller, lire,
    # extraire. Le bypass HITL n'existe pas dans ce mode (aucune action modifiante à contourner).
    # ⚠ MODE ÉCRITURE (readonly=False) : ces actions redeviennent disponibles et le gate
    # d'approbation redevient best-effort. À réserver à un usage supervisé — le verrou réel
    # (redesign plan→approuver→exécuter) n'est pas encore implémenté (voir README §Sécurité).
    _MUTATING = [
        "click_element_by_index", "input_text", "send_keys",
        "select_dropdown_option", "upload_file", "drag_drop", "clear_text",
    ]
    exclude = _MUTATING if readonly else []
    try:
        tools = Tools(exclude_actions=exclude) if exclude else Tools()
    except TypeError:
        tools = Tools()  # API browser-use différente : fallback (voir limites README)

    @tools.action(description=(
        "OBLIGATOIRE avant TOUTE action modifiante (soumettre un formulaire, "
        "envoyer, acheter, écrire, supprimer, confirmer). Demande l'approbation "
        "d'un humain avec un résumé clair de l'action et l'URL. N'exécute l'action "
        "réelle QUE si la réponse commence par APPROVED ; si REJECTED, n'exécute "
        "PAS l'action et termine la tâche."))
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
    if not wconfig.INGESTION_WEBHOOK_SECRET:
        return
    text = final_text or (json.dumps(structured, ensure_ascii=False) if structured else "")
    if not text.strip():
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{wconfig.BACKEND_URL}/api/ingestion/webhook",
                headers={"X-Ingestion-Secret": wconfig.INGESTION_WEBHOOK_SECRET},
                json={
                    "source_type": "web_extraction",
                    "source_id": job_id,
                    "filename": f"browser-{job_id}",
                    "text": text,
                    "anonymize": True,
                },
            )
    except Exception:
        pass


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
        tools = build_tools(job_id, user_id, readonly=readonly)
        sensitive = credentials.build_sensitive_data(allowed_domains)

        # garde-fou domaines : hôtes EXACTS uniquement (pas de wildcard *.{d} qui
        # exposerait les identifiants sur un sous-domaine tiers / repris).
        allow = list(allowed_domains)

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
            include_tool_call_examples=True,
            # Garde-fous anti-flail : stoppe après N échecs consécutifs, détecte les boucles
            # (mêmes actions/objectifs répétés), et laisse plus de temps au LLM lent (LongCat)
            # que les 75 s par défaut qui provoquaient des « LLM call timed out ».
            max_failures=4,
            loop_detection_enabled=True,
            llm_timeout=120,
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

        # Fallback : si l'agent n'a pas rédigé de résumé, on remonte le contenu extrait.
        if not final_text.strip() and extracted:
            final_text = "\n\n".join(str(e) for e in extracted if e)[:3000]

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
