from django.contrib import admin

from . import models


@admin.register(models.Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email")
    search_fields = ("name", "contact_name", "tax_number")


@admin.register(models.Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "location")
    search_fields = ("name", "location")


@admin.register(models.Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "unit_of_measure", "reorder_level")
    search_fields = ("sku", "name")
    list_filter = ("unit_of_measure",)


@admin.register(models.StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "warehouse",
        "supplier",
        "invoice_number",
        "quantity",
        "remaining_quantity",
        "unit_cost",
        "received_at",
    )
    list_filter = ("warehouse", "supplier", "received_at")
    search_fields = ("product__name", "invoice_number")


@admin.register(models.StockRequest)
class StockRequestAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "quantity",
        "project",
        "requested_by",
        "status",
        "created_at",
    )
    list_filter = ("status", "project", "warehouse")
    search_fields = ("product__name", "requested_by__username")


@admin.register(models.StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "movement_type",
        "quantity",
        "warehouse",
        "project",
        "created_at",
    )
    list_filter = ("movement_type", "warehouse", "project")
    search_fields = ("product__name", "note")


@admin.register(models.StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "warehouse",
        "quantity_change",
        "reason",
        "created_at",
    )
    list_filter = ("warehouse",)
    search_fields = ("product__name", "reason")


@admin.register(models.UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "manager", "department")
    search_fields = ("user__username", "department")


@admin.register(models.StockApproval)
class StockApprovalAdmin(admin.ModelAdmin):
    list_display = ("request", "approver", "status", "decided_at")
    list_filter = ("status",)


@admin.register(models.UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "action")
