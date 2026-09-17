"""Conversation de l’action, transmise par le serveur et isolée par tâche asyncio."""
from contextvars import ContextVar
fil_courant = ContextVar("fil_action_documentaire", default=None)
