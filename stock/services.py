"""Domain servisleri ve stok hareket mantığı."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from .models import (
    Product,
    StockAdjustment,
    StockEntry,
    StockMovement,
    StockRequest,
)


class InsufficientStockError(Exception):
    """Stok yetersiz olduğunda fırlatılan hata."""


@dataclass
class StockIssueResult:
    movements: List[StockMovement]
    total_cost: Decimal


@transaction.atomic
def record_stock_entry(
    *,
    product: Product,
    warehouse,
    supplier,
    invoice_number: str,
    quantity: int,
    unit_cost: Decimal,
    received_at=None,
    created_by=None,
    notes: str = "",
) -> StockEntry:
    entry = StockEntry.objects.create(
        product=product,
        warehouse=warehouse,
        supplier=supplier,
        invoice_number=invoice_number,
        quantity=quantity,
        unit_cost=unit_cost,
        created_by=created_by,
        received_at=received_at or timezone.now(),
        notes=notes,
    )
    StockMovement.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_cost=unit_cost,
        movement_type=StockMovement.MOVEMENT_IN,
        source_entry=entry,
        performed_by=created_by,
        note=notes,
    )
    return entry


@transaction.atomic
def issue_stock(
    *,
    product: Product,
    warehouse,
    quantity: int,
    performed_by=None,
    project=None,
    request: Optional[StockRequest] = None,
    note: str = "",
    movement_type: str = StockMovement.MOVEMENT_OUT,
) -> StockIssueResult:
    if quantity <= 0:
        raise ValueError("Çıkış miktarı pozitif olmalıdır.")

    remaining = quantity
    movements: List[StockMovement] = []
    total_cost = Decimal("0")

    entries = (
        StockEntry.objects.select_for_update()
        .filter(product=product, warehouse=warehouse, remaining_quantity__gt=0)
        .order_by("received_at", "id")
    )

    for entry in entries:
        if remaining <= 0:
            break
        consumable = min(entry.remaining_quantity, remaining)
        entry.remaining_quantity -= consumable
        entry.save(update_fields=["remaining_quantity", "updated_at"])
        cost = entry.unit_cost * Decimal(consumable)
        movement = StockMovement.objects.create(
            product=product,
            warehouse=warehouse,
            project=project,
            quantity=-consumable,
            unit_cost=entry.unit_cost,
            movement_type=movement_type,
            source_entry=entry,
            request=request,
            performed_by=performed_by,
            note=note,
        )
        movements.append(movement)
        total_cost += cost
        remaining -= consumable

    if remaining > 0:
        raise InsufficientStockError("Yeterli stok bulunamadı.")

    if request and movement_type == StockMovement.MOVEMENT_OUT:
        request.status = StockRequest.STATUS_FULFILLED
        request.fulfilled_at = timezone.now()
        request.save(update_fields=["status", "fulfilled_at", "updated_at"])

    return StockIssueResult(movements=movements, total_cost=total_cost)


@transaction.atomic
def adjust_stock(
    *,
    product: Product,
    warehouse,
    quantity_change: int,
    reason: str,
    performed_by=None,
    project=None,
    note: str = "",
) -> StockAdjustment:
    if quantity_change == 0:
        raise ValueError("Düzeltme miktarı sıfır olamaz.")

    adjustment = StockAdjustment.objects.create(
        product=product,
        warehouse=warehouse,
        quantity_change=quantity_change,
        reason=reason,
        performed_by=performed_by,
    )

    if quantity_change > 0:
        entry = StockEntry.objects.create(
            product=product,
            warehouse=warehouse,
            supplier=None,
            invoice_number=f"ADJ-{adjustment.pk}",
            quantity=quantity_change,
            unit_cost=Decimal("0.00"),
            created_by=performed_by,
            received_at=timezone.now(),
            notes=f"Manuel düzeltme: {reason}",
        )
        StockMovement.objects.create(
            product=product,
            warehouse=warehouse,
            quantity=quantity_change,
            movement_type=StockMovement.MOVEMENT_ADJUSTMENT,
            source_entry=entry,
            adjustment=adjustment,
            performed_by=performed_by,
            note=note or reason,
        )
    else:
        issue_result = issue_stock(
            product=product,
            warehouse=warehouse,
            quantity=abs(quantity_change),
            performed_by=performed_by,
            project=project,
            note=note or reason,
            movement_type=StockMovement.MOVEMENT_ADJUSTMENT,
        )
        for movement in issue_result.movements:
            movement.adjustment = adjustment
            movement.save(update_fields=["adjustment"])

    return adjustment


def calculate_average_cost(product: Product) -> Optional[Decimal]:
    entries = product.stock_entries.all()
    total_quantity = sum(entry.quantity for entry in entries)
    if total_quantity == 0:
        return None
    total_cost = sum(entry.quantity * entry.unit_cost for entry in entries)
    return total_cost / Decimal(total_quantity)
