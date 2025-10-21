"""Domain servisleri ve stok hesaplamaları."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List

from django.db import transaction
from django.utils import timezone

from .models import (
    StockAdjustment,
    StockEntry,
    StockMovement,
    StockRequest,
    UserActivityLog,
)


@dataclass
class AllocationResult:
    entry: StockEntry
    quantity: int


class InsufficientStockError(Exception):
    """Yeterli stok olmadığında fırlatılır."""


def log_activity(user, action: str, description: str = "", metadata=None) -> None:
    """Kullanıcı aktivite logu oluştur."""
    UserActivityLog.objects.create(
        user=user,
        action=action,
        description=description,
        metadata=metadata or {},
    )


@transaction.atomic
def record_stock_entry(entry: StockEntry, performed_by) -> StockEntry:
    """Yeni stok girişini kaydeder ve hareket kaydı oluşturur."""
    is_new = entry.pk is None
    entry.created_by = performed_by
    entry.save()
    if is_new:
        StockMovement.objects.create(
            product=entry.product,
            warehouse=entry.warehouse,
            quantity=entry.quantity,
            unit_cost=entry.unit_cost,
            movement_type=StockMovement.INBOUND,
            reference=f"Giriş #{entry.pk}",
            performed_by=performed_by,
            supplier=entry.supplier,
            invoice_number=entry.invoice_number,
            source_entry=entry,
        )
        log_activity(
            performed_by,
            action="Stok Girişi",
            description=f"{entry.product} için {entry.quantity} adet stok girişi yapıldı.",
            metadata={
                "product": entry.product.pk,
                "warehouse": entry.warehouse.pk,
                "quantity": entry.quantity,
            },
        )
    return entry


@transaction.atomic
def approve_stock_request(request_obj: StockRequest, approver) -> List[AllocationResult]:
    """FIFO yöntemini kullanarak stok talebini onaylar."""
    if request_obj.status not in {StockRequest.STATUS_PENDING, StockRequest.STATUS_APPROVED}:
        raise ValueError("Yalnızca beklemede olan talepler onaylanabilir.")

    remaining = request_obj.quantity
    allocations: List[AllocationResult] = []

    entries = (
        StockEntry.objects.select_for_update()
        .filter(
            product=request_obj.product,
            warehouse=request_obj.warehouse,
            remaining_quantity__gt=0,
        )
        .order_by("received_at", "id")
    )

    for entry in entries:
        if remaining <= 0:
            break
        take = min(entry.remaining_quantity, remaining)
        entry.remaining_quantity -= take
        entry.save(update_fields=["remaining_quantity", "updated_at"])
        allocations.append(AllocationResult(entry=entry, quantity=take))
        remaining -= take
        StockMovement.objects.create(
            product=request_obj.product,
            warehouse=request_obj.warehouse,
            project=request_obj.project,
            quantity=-take,
            unit_cost=entry.unit_cost,
            movement_type=StockMovement.OUTBOUND,
            reference=f"Talep #{request_obj.pk}",
            performed_by=approver,
            supplier=entry.supplier,
            invoice_number=entry.invoice_number,
            source_entry=entry,
        )

    if remaining > 0:
        raise InsufficientStockError("Yeterli stok bulunamadı.")

    request_obj.status = StockRequest.STATUS_COMPLETED
    request_obj.approver = approver
    request_obj.approved_at = timezone.now()
    request_obj.save(update_fields=["status", "approver", "approved_at", "updated_at"])

    log_activity(
        approver,
        action="Stok Talebi Onayı",
        description=f"{request_obj.product} için {request_obj.quantity} adet talep onaylandı.",
        metadata={
            "request": request_obj.pk,
            "project": request_obj.project.pk,
            "warehouse": request_obj.warehouse.pk,
        },
    )
    return allocations


@transaction.atomic
def reject_stock_request(request_obj: StockRequest, approver, reason: str = "") -> StockRequest:
    request_obj.status = StockRequest.STATUS_REJECTED
    request_obj.approver = approver
    request_obj.approved_at = timezone.now()
    request_obj.notes = reason
    request_obj.save(update_fields=["status", "approver", "approved_at", "notes", "updated_at"])
    log_activity(
        approver,
        action="Stok Talebi Reddedildi",
        description=f"{request_obj.product} talebi reddedildi.",
        metadata={"request": request_obj.pk, "reason": reason},
    )
    return request_obj


@transaction.atomic
def apply_stock_adjustment(adjustment: StockAdjustment, performed_by):
    adjustment.performed_by = performed_by
    adjustment.save()

    remaining_change = adjustment.quantity_change
    if remaining_change == 0:
        return adjustment

    StockMovement.objects.create(
        product=adjustment.product,
        warehouse=adjustment.warehouse,
        quantity=remaining_change,
        movement_type=StockMovement.ADJUSTMENT,
        reference=f"Düzeltme #{adjustment.pk}",
        performed_by=performed_by,
    )

    # Düzeltme miktarına göre stok girişlerini güncelle
    if remaining_change > 0:
        entry = StockEntry.objects.create(
            product=adjustment.product,
            warehouse=adjustment.warehouse,
            quantity=remaining_change,
            remaining_quantity=remaining_change,
            unit_cost=Decimal("0"),
            created_by=performed_by,
        )
        entry.invoice_number = "DÜZELTME"
        entry.save(update_fields=["invoice_number", "updated_at"])
        StockMovement.objects.filter(reference=f"Düzeltme #{adjustment.pk}").update(source_entry=entry)
    else:
        required = -remaining_change
        entries = (
            StockEntry.objects.select_for_update()
            .filter(
                product=adjustment.product,
                warehouse=adjustment.warehouse,
                remaining_quantity__gt=0,
            )
            .order_by("received_at", "id")
        )
        for entry in entries:
            if required <= 0:
                break
            take = min(entry.remaining_quantity, required)
            entry.remaining_quantity -= take
            entry.save(update_fields=["remaining_quantity", "updated_at"])
            required -= take
        if required > 0:
            raise InsufficientStockError("Düşürülecek yeterli stok bulunamadı.")

    log_activity(
        performed_by,
        action="Stok Düzeltmesi",
        description=f"{adjustment.product} için {adjustment.quantity_change} düzeltme yapıldı.",
        metadata={
            "product": adjustment.product.pk,
            "warehouse": adjustment.warehouse.pk,
            "quantity_change": adjustment.quantity_change,
        },
    )
    return adjustment
