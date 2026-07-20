"""
Login DÉTERMINISTE pour les sites configurés.

Au lieu de laisser le LLM deviner la mécanique d'un formulaire de connexion
(source d'échecs : hallucination de « shadow DOM », boucles, tentatives répétées
qui peuvent verrouiller le compte), le worker remplit lui-même les champs via CDP
— exactement comme un humain — puis soumet. Fiable, rapide, une seule tentative.

Sécurité : les identifiants sont lus du fichier monté :ro et injectés directement
dans le DOM via CDP. Ils ne transitent JAMAIS par le LLM (aucun placeholder à
deviner, aucune valeur dans le prompt). Scopé à l'hôte exact (allowed_domains).

Pour ajouter un site : renseigner ses sélecteurs dans LOGIN_CONFIGS.
"""
import asyncio
import json

import credentials


# Sélecteurs de formulaire par domaine (hôte exact). Vérifiés sur le DOM réel.
LOGIN_CONFIGS: dict[str, dict] = {
    # Appli PRO Extrabat (pas exemple.fr, qui est l'espace client final).
    # Sélecteurs par `name` (robustes) : sur exemple le champ mot de passe n'a pas d'id.
    "exemple.fr": {
        "login_url": "https://exemple.fr/authentification",
        "user_sel": "input[name=user_login]",
        "pass_sel": "input[name=user_pwd]",
        "submit_sel": "input[type=submit],button[type=submit]",
        # Succès si l'URL quitte la page d'auth ET aucun mot-clé d'erreur affiché.
        "success_url_excludes": "/authentification",
        "error_keywords": ["incorrect", "erreur", "invalide", "identifiant ou mot de passe"],
    },
}


def has_config(domain: str) -> bool:
    return domain in LOGIN_CONFIGS


async def _eval(browser, expr: str):
    s = await browser.get_or_create_cdp_session()
    r = await s.cdp_client.send.Runtime.evaluate(
        params={"expression": expr, "returnByValue": True, "awaitPromise": True},
        session_id=s.session_id,
    )
    return r.get("result", {}).get("value")


async def try_login(browser, domain: str) -> dict:
    """
    Tente un login déterministe sur `domain`. Renvoie un dict :
      {attempted: bool, ok: bool, reason?: str, url_left_auth?: bool, error_shown?: bool}
    Ne lève jamais (toute erreur technique → attempted=True, ok=False, reason).
    """
    cfg = LOGIN_CONFIGS.get(domain)
    if not cfg:
        return {"attempted": False}
    creds = credentials.load_site_credentials().get(domain) or {}
    user, pwd = creds.get("x_user", ""), creds.get("x_pass", "")
    if not user or not pwd:
        return {"attempted": False, "reason": "no_creds"}

    try:
        await browser.navigate_to(cfg["login_url"])
        await asyncio.sleep(5)  # laisse le formulaire se rendre / la redirection se faire

        # Déjà authentifié ? Une session `storage_state` valide fait rediriger la page d'auth
        # vers le dashboard : le formulaire n'est plus présent. Ce n'est PAS un échec — succès.
        url_now = (await _eval(browser, "location.href")) or ""
        if cfg["success_url_excludes"] not in url_now:
            return {"attempted": True, "ok": True, "already_logged_in": True}

        fill = (
            "(function(){"
            "var lg=document.querySelector(%s),pw=document.querySelector(%s);"
            "if(!lg||!pw)return 'missing';"
            "var d=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
            "d.call(lg,%s);d.call(pw,%s);"
            "[lg,pw].forEach(function(e){e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));});"
            "return 'ok';})()"
        ) % (json.dumps(cfg["user_sel"]), json.dumps(cfg["pass_sel"]),
             json.dumps(user), json.dumps(pwd))
        filled = await _eval(browser, fill)
        if filled != "ok":
            # Champ absent : soit une redirection tardive (déjà connecté), soit un vrai souci.
            url_now = (await _eval(browser, "location.href")) or ""
            if cfg["success_url_excludes"] not in url_now:
                return {"attempted": True, "ok": True, "already_logged_in": True}
            return {"attempted": True, "ok": False, "reason": "form_not_found"}

        # Soumission fidèle (clic sur le bouton → embarque le token CSRF caché).
        await _eval(
            browser,
            "(function(){var b=document.querySelector(%s);if(b){b.click();return 1;}"
            "var f=document.querySelector('form');if(f){f.submit();return 1;}return 0;})()"
            % json.dumps(cfg["submit_sel"]),
        )
        await asyncio.sleep(6)  # laisse la redirection / le rechargement se faire

        url = (await _eval(browser, "location.href")) or ""
        body = (await _eval(browser, "document.body?document.body.innerText.toLowerCase():''")) or ""
        error_shown = any(k in body for k in cfg["error_keywords"])
        url_left_auth = cfg["success_url_excludes"] not in url
        ok = url_left_auth and not error_shown
        return {"attempted": True, "ok": ok,
                "url_left_auth": url_left_auth, "error_shown": error_shown}
    except Exception as e:
        return {"attempted": True, "ok": False, "reason": type(e).__name__}
