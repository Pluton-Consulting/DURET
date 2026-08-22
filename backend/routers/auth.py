import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from database.connection import get_db
from auth.jwt_handler import create_access_token, decode_access_token
from auth.dependencies import get_current_user
from database.models import User
from security.audit import log_action
from emails.envoi import envoyer
from emails.gabarit import mail_connexion
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
    """Envoie le lien de connexion. En debug, l'affiche AUSSI en console.

    Le contenu a quitté ce fichier : il vit dans `emails/`, gabarit commun aux
    deux clients et marque isolée dans un seul module. Ce routeur ne connaît
    plus ni HTML ni Resend — c'est ce qui garantit qu'une correction de mise en
    page se pose des deux côtés d'un seul geste.
    """
    if settings.debug:
        print(f"\nMAGIC LINK (dev) → {magic_link}\n")
        # Pas de return : l'email part quand même en mode debug.

    objet, _apercu, html = mail_connexion(magic_link, MAGIC_LINK_EXPIRE_MINUTES)
    await envoyer(to_email, objet, html)


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
