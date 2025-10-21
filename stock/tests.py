from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase

from . import services
from .models import (
    Product,
    Project,
    StockAdjustment,
    StockEntry,
    StockRequest,
    Supplier,
    Warehouse,
)

User = get_user_model()


class StockServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="warehouse", password="test123", is_staff=True
        )
        self.product = Product.objects.create(name="Vida", sku="SKU-1", reorder_level=5)
        self.supplier = Supplier.objects.create(name="Tedarikçi A")
        self.warehouse = Warehouse.objects.create(name="Merkez")
        self.project = Project.objects.create(name="Şantiye", code="PRJ-1")

    def test_issue_stock_fifo(self):
        services.record_stock_entry(
            product=self.product,
            warehouse=self.warehouse,
            supplier=self.supplier,
            invoice_number="FTR-1",
            quantity=5,
            unit_cost=Decimal("10.00"),
            created_by=self.user,
        )
        services.record_stock_entry(
            product=self.product,
            warehouse=self.warehouse,
            supplier=self.supplier,
            invoice_number="FTR-2",
            quantity=10,
            unit_cost=Decimal("20.00"),
            created_by=self.user,
        )

        result = services.issue_stock(
            product=self.product,
            warehouse=self.warehouse,
            quantity=12,
            performed_by=self.user,
        )

        first_entry, second_entry = StockEntry.objects.order_by("received_at")
        self.assertEqual(first_entry.remaining_quantity, 0)
        self.assertEqual(second_entry.remaining_quantity, 3)
        self.assertEqual(len(result.movements), 2)
        self.assertEqual(result.total_cost, Decimal("190.00"))

    def test_issue_stock_insufficient_raises(self):
        with self.assertRaises(services.InsufficientStockError):
            services.issue_stock(
                product=self.product,
                warehouse=self.warehouse,
                quantity=1,
                performed_by=self.user,
            )

    def test_request_fulfillment_marks_status(self):
        request = StockRequest.objects.create(
            product=self.product,
            quantity=2,
            warehouse=self.warehouse,
            project=self.project,
            requested_by=self.user,
            approver=self.user,
            status=StockRequest.STATUS_APPROVED,
        )
        services.record_stock_entry(
            product=self.product,
            warehouse=self.warehouse,
            supplier=self.supplier,
            invoice_number="FTR-3",
            quantity=2,
            unit_cost=Decimal("5.00"),
            created_by=self.user,
        )

        services.issue_stock(
            product=self.product,
            warehouse=self.warehouse,
            quantity=2,
            performed_by=self.user,
            request=request,
        )

        request.refresh_from_db()
        self.assertEqual(request.status, StockRequest.STATUS_FULFILLED)
        self.assertIsNotNone(request.fulfilled_at)

    def test_manual_adjustment_positive_and_negative(self):
        adjustment_increase = services.adjust_stock(
            product=self.product,
            warehouse=self.warehouse,
            quantity_change=4,
            reason="Sayım fazlası",
            performed_by=self.user,
        )
        self.assertTrue(
            StockEntry.objects.filter(product=self.product, warehouse=self.warehouse).exists()
        )
        self.assertEqual(adjustment_increase.quantity_change, 4)

        result = services.issue_stock(
            product=self.product,
            warehouse=self.warehouse,
            quantity=2,
            performed_by=self.user,
        )
        self.assertEqual(len(result.movements), 1)

        adjustment_decrease = services.adjust_stock(
            product=self.product,
            warehouse=self.warehouse,
            quantity_change=-1,
            reason="Kayıp",
            performed_by=self.user,
        )
        self.assertIsInstance(adjustment_decrease, StockAdjustment)
        remaining = self.product.stock_entries.aggregate(total=models.Sum("remaining_quantity"))["total"]
        self.assertEqual(remaining, 1)
