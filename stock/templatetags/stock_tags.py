from django import template

from ..models import StockRequest

register = template.Library()


@register.filter
def status_badge_class(status: str) -> str:
    return {
        StockRequest.STATUS_PENDING: "warning text-dark",
        StockRequest.STATUS_APPROVED: "success",
        StockRequest.STATUS_FULFILLED: "primary",
        StockRequest.STATUS_REJECTED: "danger",
        StockRequest.STATUS_CANCELLED: "secondary",
    }.get(status, "secondary")
