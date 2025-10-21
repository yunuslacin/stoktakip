"""Uygulama genelinde kullanılan yardımcı fonksiyonlar."""
from __future__ import annotations

from typing import Any, Dict, Optional

from django.http import HttpRequest

from .models import UserActivityLog


def log_user_activity(
    *, user, action: str, request: Optional[HttpRequest] = None, extra: Optional[Dict[str, Any]] = None
) -> None:
    UserActivityLog.objects.create(
        user=user if user.is_authenticated else None,
        action=action,
        ip_address=request.META.get("REMOTE_ADDR") if request else None,
        extra_data=extra or {},
    )
