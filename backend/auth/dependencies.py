from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import PyJWTError
from uuid import UUID
from auth.jwt_handler import decode_access_token
from database.connection import get_db
from database.models import User

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")
    except PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")

    async with get_db() as conn:
        # Vérifie si le token a été révoqué (logout)
        if jti:
            revoked = await conn.fetchval(
                "SELECT 1 FROM revoked_tokens WHERE jti = $1",
                UUID(jti),
            )
            if revoked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session révoquée : reconnectez-vous",
                )

        row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1 AND actif = true",
            UUID(user_id),
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Utilisateur non trouvé ou désactivé",
            )
        return User(**dict(row))
