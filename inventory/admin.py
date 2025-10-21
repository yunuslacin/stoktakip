from django.contrib import admin

from .models import (
    PriceHistory,
    Product,
    Project,
    StockAdjustment,
    StockEntry,
    StockMovement,
    StockRequest,
    Supplier,
    UserActivityLog,
    UserProfile,
    Warehouse,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "unit", "reorder_level", "total_stock")
    search_fields = ("name", "sku")


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "warehouse",
        "quantity",
        "remaining_quantity",
        "unit_cost",
        "supplier",
        "invoice_number",
        "received_at",
    )
    list_filter = ("warehouse", "product")
    search_fields = ("invoice_number",)


@admin.register(StockRequest)
class StockRequestAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "project",
        "warehouse",
        "quantity",
        "status",
        "requested_by",
        "approver",
        "created_at",
    )
    list_filter = ("status", "project", "warehouse")
    search_fields = ("product__name",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "movement_type",
        "warehouse",
        "project",
        "quantity",
        "unit_cost",
        "created_at",
    )
    list_filter = ("movement_type", "warehouse", "project")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "email", "phone")
    search_fields = ("name", "contact")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "location")


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("product", "warehouse", "quantity_change", "reason", "created_at")


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "unit_cost", "source", "created_at")
    list_filter = ("product",)


@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "created_at")
    search_fields = ("action", "description")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "manager")
    autocomplete_fields = ("manager",)
