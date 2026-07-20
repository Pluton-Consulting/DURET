from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class User(BaseModel):
    id: UUID
    email: str
    name: Optional[str] = None
    role: str
    actif: bool
    quota_mensuel: Optional[int] = None
    bypass_schedule: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
