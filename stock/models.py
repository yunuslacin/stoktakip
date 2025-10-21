from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Project(TimeStampedModel):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Product(TimeStampedModel):
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=50, default="adet")
    reorder_level = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    @property
    def total_on_hand(self) -> int:
        return (
            self.stock_entries.aggregate(total=models.Sum("remaining_quantity"))[
                "total"
            ]
            or 0
        )

    @property
    def is_below_reorder(self) -> bool:
        return self.reorder_level > 0 and self.total_on_hand <= self.reorder_level


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_members",
    )
    department = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "Kullanıcı Profili"
        verbose_name_plural = "Kullanıcı Profilleri"

    def __str__(self) -> str:
        return self.user.get_full_name() or self.user.get_username()


class StockEntry(TimeStampedModel):
    product = models.ForeignKey(
        Product, related_name="stock_entries", on_delete=models.PROTECT
    )
    warehouse = models.ForeignKey(
        Warehouse, related_name="stock_entries", on_delete=models.PROTECT
    )
    supplier = models.ForeignKey(
        Supplier,
        related_name="stock_entries",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    invoice_number = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField()
    remaining_quantity = models.PositiveIntegerField(editable=False)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    received_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_stock_entries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["received_at"]

    def __str__(self) -> str:
        return f"{self.product} - {self.quantity}"

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.remaining_quantity = self.quantity
        super().save(*args, **kwargs)


class StockRequest(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_FULFILLED = "fulfilled"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Beklemede"),
        (STATUS_APPROVED, "Onaylandı"),
        (STATUS_REJECTED, "Reddedildi"),
        (STATUS_FULFILLED, "Karşılandı"),
        (STATUS_CANCELLED, "İptal edildi"),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="stock_requests",
        on_delete=models.CASCADE,
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="approved_stock_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    approved_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    need_by_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.product} - {self.quantity} ({self.get_status_display()})"


class StockApproval(TimeStampedModel):
    STATUS_CHOICES = [
        (StockRequest.STATUS_APPROVED, "Onaylandı"),
        (StockRequest.STATUS_REJECTED, "Reddedildi"),
    ]

    request = models.ForeignKey(
        StockRequest, related_name="approvals", on_delete=models.CASCADE
    )
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    comments = models.TextField(blank=True)
    decided_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-decided_at"]


class StockMovement(TimeStampedModel):
    MOVEMENT_IN = "in"
    MOVEMENT_OUT = "out"
    MOVEMENT_ADJUSTMENT = "adjustment"
    MOVEMENT_CHOICES = [
        (MOVEMENT_IN, "Giriş"),
        (MOVEMENT_OUT, "Çıkış"),
        (MOVEMENT_ADJUSTMENT, "Düzeltme"),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES)
    source_entry = models.ForeignKey(
        StockEntry, related_name="movements", on_delete=models.SET_NULL, null=True, blank=True
    )
    request = models.ForeignKey(
        StockRequest, related_name="movements", on_delete=models.SET_NULL, null=True, blank=True
    )
    adjustment = models.ForeignKey(
        "StockAdjustment",
        related_name="movements",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="stock_movements",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class StockAdjustment(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity_change = models.IntegerField()
    reason = models.CharField(max_length=255)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="stock_adjustments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    class Meta:
        ordering = ["-created_at"]


class UserActivityLog(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra_data = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        username = self.user.get_username() if self.user else "Bilinmiyor"
        return f"{username} - {self.action}"
