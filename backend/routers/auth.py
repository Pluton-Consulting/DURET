import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import httpx
from database.connection import get_db
from auth.jwt_handler import create_access_token, decode_access_token
from auth.dependencies import get_current_user
from database.models import User
from security.audit import log_action
from config import settings

_bearer = HTTPBearer()

router = APIRouter()

MAGIC_LINK_EXPIRE_MINUTES = 15


class MagicLinkRequest(BaseModel):
    email: str


class VerifyTokenRequest(BaseModel):
    token: str
    email: str


async def _send_magic_link_email(to_email: str, magic_link: str) -> None:
    """Envoie le lien de connexion via l'API Resend. En debug, affiche AUSSI le lien en console."""
    if settings.debug:
        print(f"\nMAGIC LINK (dev) → {magic_link}\n")
        # Pas de return : l'email est envoyé via Resend même en mode debug.

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F1F5FA;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F1F5FA;padding:40px 0">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.08)">

        <!-- En-tête -->
        <tr>
          <td style="background:#16283F;padding:32px 40px">
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="background:#2E6BB0;width:36px;height:36px;border-radius:9px;text-align:center;vertical-align:middle">
                  <span style="color:white;font-size:15px;font-weight:800;letter-spacing:-0.5px">D</span>
                </td>
                <td style="padding-left:12px;vertical-align:middle">
                  <div style="color:#ffffff;font-size:18px;font-weight:800;letter-spacing:-0.3px;line-height:1">Duret & Sols</div>
                  <div style="color:#AECBE8;font-size:11px;font-weight:500;margin-top:3px">Assistant IA interne</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Corps -->
        <tr>
          <td style="padding:40px 40px 24px">
            <h1 style="margin:0 0 12px;font-size:22px;font-weight:700;color:#16283F;letter-spacing:-0.4px">
              Votre lien de connexion
            </h1>
            <p style="margin:0 0 32px;font-size:15px;color:#33424F;line-height:1.6">
              Bonjour,<br><br>
              Vous avez demandé à vous connecter à <strong>Duret & Sols</strong>.<br>
              Cliquez sur le bouton ci-dessous — ce lien est à usage unique et expire dans <strong>{MAGIC_LINK_EXPIRE_MINUTES}&nbsp;minutes</strong>.
            </p>

            <!-- CTA -->
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-radius:10px;background:#2E6BB0">
                  <a href="{magic_link}"
                     style="display:inline-block;padding:14px 32px;color:#ffffff;font-size:15px;
                            font-weight:600;text-decoration:none;letter-spacing:-0.2px">
                    Se connecter à Duret & Sols →
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Lien de secours -->
        <tr>
          <td style="padding:0 40px 32px">
            <p style="margin:24px 0 0;font-size:12px;color:#78899B;line-height:1.6">
              Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :<br>
              <a href="{magic_link}" style="color:#2E6BB0;word-break:break-all;font-size:11px">{magic_link}</a>
            </p>
          </td>
        </tr>

        <!-- Séparateur -->
        <tr><td style="border-top:1px solid #DCE4EE"></td></tr>

        <!-- Pied de page -->
        <tr>
          <td style="padding:20px 40px;background:#F1F5FA">
            <p style="margin:0;font-size:12px;color:#78899B;line-height:1.6">
              Si vous n'avez pas demandé ce lien, ignorez simplement cet email.<br>
              Ce message est envoyé automatiquement — ne pas y répondre.
            </p>
            <p style="margin:12px 0 0;font-size:11px;color:#8AA0BA">
              Duret & Sols · Assistant IA interne
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "User-Agent": "python-httpx/0.27.0",
                },
                json={
                    "from": settings.resend_from_email,
                    "to": to_email,
                    "subject": "Votre lien de connexion Duret & Sols",
                    "html": html,
                },
                timeout=10.0,
            )
            res.raise_for_status()
        logging.getLogger("duret.auth").info("Email de connexion envoyé via Resend à %s", to_email)
    except Exception as e:
        # Ne pas casser la connexion : le token est déjà créé (lien console dispo en debug).
        detail = getattr(getattr(e, "response", None), "text", "")
        logging.getLogger("duret.auth").warning("Échec envoi Resend à %s : %s %s", to_email, e, detail)


@router.post("/magic-link/request")
async def request_magic_link(body: MagicLinkRequest):
    """
    Génère un token et envoie un lien de connexion par email.
    Retourne toujours le même message pour ne pas révéler si l'email existe.
    """
    async with get_db() as conn:
        user = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1 AND actif = true",
            body.email,
        )

    if not user:
        await log_action(
            action="login_attempt_unknown",
            success=False,
            error_message="Email non enregistré",
        )
        # Réponse UNIFORME (anti-énumération de comptes) — voir aussi le chemin "connu".
        return {"ok": True}

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_EXPIRE_MINUTES)

    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO verification_tokens (email, token, expires_at) VALUES ($1, $2, $3)",
            body.email, token, expires_at,
        )

    magic_link = f"{settings.app_url}/verify?token={token}&email={body.email}"
    await _send_magic_link_email(body.email, magic_link)
    return {"ok": True}


@router.post("/magic-link/verify")
async def verify_magic_link(body: VerifyTokenRequest):
    """Vérifie le token, le consomme et retourne un JWT backend."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM verification_tokens WHERE token = $1 AND email = $2",
            body.token, body.email,
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien invalide")
    if row["used"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien déjà utilisé")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien expiré")

    async with get_db() as conn:
        await conn.execute(
            "UPDATE verification_tokens SET used = true WHERE token = $1",
            body.token,
        )
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE email = $1 AND actif = true",
            body.email,
        )

    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès non autorisé")

    async with get_db() as conn:
        await conn.execute(
            "UPDATE users SET last_login = $1 WHERE id = $2",
            datetime.now(timezone.utc), user["id"],
        )

    await log_action(action="login", user_id=str(user["id"]))

    access_token = create_access_token({"sub": str(user["id"]), "role": user["role"]})
    return {"access_token": access_token, "token_type": "bearer", "role": user["role"]}


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    current_user: User = Depends(get_current_user),
):
    """Révoque le JWT actuel — inscrit le jti en blacklist jusqu'à expiration."""
    try:
        payload = decode_access_token(credentials.credentials)
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO revoked_tokens (jti, user_id, expires_at)
                       VALUES ($1, $2, to_timestamp($3))
                       ON CONFLICT DO NOTHING""",
                    UUID(jti), current_user.id, float(exp),
                )
    except Exception:
        pass  # Toujours renvoyer OK même si l'inscription blacklist échoue

    await log_action(action="logout", user_id=str(current_user.id))
    return {"ok": True}
