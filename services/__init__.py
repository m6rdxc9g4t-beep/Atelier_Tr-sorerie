"""Couche métier : chaque module reçoit une connexion SQLite et ne dépend pas de Flask."""
from .validation import ConflictError, NotFoundError, ServiceError, ValidationError

__all__ = ["ConflictError", "NotFoundError", "ServiceError", "ValidationError"]
