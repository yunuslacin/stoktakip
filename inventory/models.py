from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="team_members",
        null=True,
        blank=True,
        help_text="Talep onayları için hiyerarşik yönetici",
    )

    def __str__(self) -> str:
        return f"{self.user.get_full_name() or self.user.username} profili"


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=255)
    contact = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)

    def __str__(self) -> str:
        return self.name


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return self.name


class Project(TimeStampedModel):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=32, default="adet")
    reorder_level = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    @property
    def total_stock(self) -> int:
        return (
            self.stock_entries.aggregate(total=models.Sum("remaining_quantity"))["total"]
            or 0
        )

    @property
    def is_below_reorder(self) -> bool:
        return self.reorder_level > 0 and self.total_stock <= self.reorder_level


class PriceHistory(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_history")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.product} - {self.unit_cost}"


class StockEntry(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_entries")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="stock_entries"
    )
    quantity = models.PositiveIntegerField()
    remaining_quantity = models.PositiveIntegerField(editable=False)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, related_name="stock_entries", null=True, blank=True
    )
    invoice_number = models.CharField(max_length=128, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_stock_entries"
    )

    class Meta:
        ordering = ["received_at", "id"]

    def __str__(self) -> str:
        return f"{self.product} - {self.quantity}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity
        if self.remaining_quantity < 0:
            raise ValueError("Kalan miktar negatif olamaz.")
        super().save(*args, **kwargs)
        if is_new:
            PriceHistory.objects.create(
                product=self.product,
                unit_cost=self.unit_cost,
                source=f"Giriş #{self.pk}",
            )


class StockMovement(TimeStampedModel):
    INBOUND = "IN"
    OUTBOUND = "OUT"
    ADJUSTMENT = "ADJ"

    MOVEMENT_TYPES = [
        (INBOUND, "Giriş"),
        (OUTBOUND, "Çıkış"),
        (ADJUSTMENT, "Düzeltme"),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="movements")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, related_name="movements", null=True, blank=True
    )
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, related_name="movements", null=True, blank=True
    )
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    movement_type = models.CharField(max_length=3, choices=MOVEMENT_TYPES)
    reference = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, related_name="movements", null=True, blank=True
    )
    invoice_number = models.CharField(max_length=128, blank=True)
    source_entry = models.ForeignKey(
        "inventory.StockEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movements",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} - {self.product} ({self.quantity})"


class StockRequest(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Beklemede"),
        (STATUS_APPROVED, "Onaylandı"),
        (STATUS_REJECTED, "Reddedildi"),
        (STATUS_COMPLETED, "Tamamlandı"),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="requests")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="requests")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="requests", help_text="Sevk edilecek depo"
    )
    quantity = models.PositiveIntegerField()
    requested_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="stock_requests"
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_requests"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.product} talebi ({self.quantity})"


class StockAdjustment(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="adjustments")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="adjustments"
    )
    quantity_change = models.IntegerField()
    reason = models.CharField(max_length=255)
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="stock_adjustments", null=True, blank=True
    )

    def __str__(self) -> str:
        return f"{self.product} düzeltme {self.quantity_change}"


class UserActivityLog(TimeStampedModel):
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="activity_logs", null=True, blank=True
    )
    action = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} - {self.action}"
