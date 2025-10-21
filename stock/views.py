from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import FormMixin, FormView

from . import services
from .forms import (
    ProductForm,
    StockAdjustmentForm,
    StockApprovalForm,
    StockEntryForm,
    StockIssueForm,
    StockRequestForm,
    SupplierForm,
    UserProfileForm,
    WarehouseForm,
)
from .models import (
    Product,
    StockAdjustment,
    StockEntry,
    StockMovement,
    StockRequest,
    Supplier,
    UserProfile,
    Warehouse,
)
from .services import InsufficientStockError
from .utils import log_user_activity

User = get_user_model()


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "stock/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product_stock = (
            Product.objects.annotate(
                on_hand=Coalesce(Sum("stock_entries__remaining_quantity"), 0),
            )
            .order_by("name")
            .select_related()
        )
        low_stock = [p for p in product_stock if p.reorder_level and p.on_hand <= p.reorder_level]
        pending_queryset = StockRequest.objects.select_related(
            "product", "requested_by", "project"
        ).filter(status=StockRequest.STATUS_PENDING)
        if not self.request.user.is_staff:
            pending_queryset = pending_queryset.filter(approver=self.request.user)
        pending_requests = pending_queryset.order_by("-created_at")[:10]
        awaiting_user_requests = (
            StockRequest.objects.filter(Q(requested_by=self.request.user) | Q(approver=self.request.user))
            .order_by("-created_at")[:10]
        )
        recent_movements = (
            StockMovement.objects.select_related("product", "warehouse", "project")
            .order_by("-created_at")[:10]
        )
        inventory_value = (
            StockEntry.objects.aggregate(
                total=Coalesce(
                    Sum(
                        F("remaining_quantity") * F("unit_cost"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    ),
                    Decimal("0"),
                )
            )["total"]
            or Decimal("0")
        )
        context.update(
            {
                "product_stock": product_stock,
                "low_stock_products": low_stock,
                "pending_requests": pending_requests,
                "awaiting_user_requests": awaiting_user_requests,
                "recent_movements": recent_movements,
                "inventory_value": inventory_value,
            }
        )
        return context


class StockEntryCreateView(LoginRequiredMixin, FormView):
    form_class = StockEntryForm
    template_name = "stock/stock_entry_form.html"
    success_url = reverse_lazy("stock-entry-list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        data = form.cleaned_data
        services.record_stock_entry(
            product=data["product"],
            warehouse=data["warehouse"],
            supplier=data.get("supplier"),
            invoice_number=data.get("invoice_number", ""),
            quantity=data["quantity"],
            unit_cost=data["unit_cost"],
            received_at=data.get("received_at"),
            created_by=self.request.user,
            notes=data.get("notes", ""),
        )
        messages.success(self.request, "Stok girişi başarıyla kaydedildi.")
        log_user_activity(
            user=self.request.user,
            action="Stok girişi oluşturdu",
            request=self.request,
            extra={"product": data["product"].pk, "quantity": data["quantity"]},
        )
        return super().form_valid(form)


class StockEntryListView(LoginRequiredMixin, ListView):
    model = StockEntry
    template_name = "stock/stock_entry_list.html"
    paginate_by = 20

    def get_queryset(self):
        return (
            StockEntry.objects.select_related("product", "warehouse", "supplier", "created_by")
            .order_by("-received_at")
        )


class StockIssueView(LoginRequiredMixin, FormView):
    form_class = StockIssueForm
    template_name = "stock/stock_issue_form.html"
    success_url = reverse_lazy("stock-movement-list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        request_id = self.request.GET.get("request")
        if request_id:
            try:
                request_obj = StockRequest.objects.get(pk=request_id)
            except StockRequest.DoesNotExist:
                pass
            else:
                initial.update(
                    {
                        "request": request_obj,
                        "product": request_obj.product,
                        "warehouse": request_obj.warehouse,
                        "project": request_obj.project,
                        "quantity": request_obj.quantity,
                    }
                )
        return initial

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            result = services.issue_stock(
                product=data["product"],
                warehouse=data["warehouse"],
                project=data["project"],
                quantity=data["quantity"],
                performed_by=self.request.user,
                request=data.get("request"),
                note=data.get("note", ""),
            )
        except InsufficientStockError as exc:
            form.add_error("quantity", str(exc))
            return self.form_invalid(form)

        request_info = ""
        if data.get("request"):
            request_info = f" (Talep #{data['request'].pk})"
        messages.success(
            self.request,
            f"{data['quantity']} {data['product']} projesine çıkıldı{request_info}. Toplam maliyet {result.total_cost:.2f} ₺",
        )
        extra = {"product": data["product"].pk, "quantity": data["quantity"]}
        if data.get("request"):
            extra["request"] = data["request"].pk
        log_user_activity(
            user=self.request.user,
            action="Stok çıkışı gerçekleştirdi",
            request=self.request,
            extra=extra,
        )
        return super().form_valid(form)


class StockMovementListView(LoginRequiredMixin, ListView):
    model = StockMovement
    template_name = "stock/stock_movement_list.html"
    paginate_by = 25

    def get_queryset(self):
        queryset = (
            StockMovement.objects.select_related("product", "warehouse", "project", "performed_by")
            .order_by("-created_at")
        )
        movement_type = self.request.GET.get("type")
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)
        return queryset


class StockRequestListView(LoginRequiredMixin, ListView):
    model = StockRequest
    template_name = "stock/stock_request_list.html"
    paginate_by = 20

    def get_queryset(self):
        queryset = StockRequest.objects.select_related(
            "product", "warehouse", "project", "requested_by", "approver"
        ).order_by("-created_at")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(Q(requested_by=self.request.user) | Q(approver=self.request.user))


class StockRequestCreateView(LoginRequiredMixin, FormView):
    form_class = StockRequestForm
    template_name = "stock/stock_request_form.html"
    success_url = reverse_lazy("stock-request-list")

    def form_valid(self, form):
        stock_request = form.save(commit=False)
        stock_request.requested_by = self.request.user
        profile = getattr(self.request.user, "userprofile", None)
        if profile and profile.manager:
            stock_request.approver = profile.manager
        else:
            stock_request.approver = (
                User.objects.filter(is_staff=True).exclude(pk=self.request.user.pk).first()
            )
        stock_request.status = StockRequest.STATUS_PENDING
        stock_request.save()
        form.save_m2m()
        messages.success(self.request, "Stok talebi oluşturuldu.")
        log_user_activity(
            user=self.request.user,
            action="Stok talebi oluşturdu",
            request=self.request,
            extra={"request_id": stock_request.pk},
        )
        return super().form_valid(form)


class StockRequestDetailView(LoginRequiredMixin, FormMixin, DetailView):
    model = StockRequest
    form_class = StockApprovalForm
    context_object_name = "request_obj"
    template_name = "stock/stock_request_detail.html"

    def get_queryset(self):
        queryset = StockRequest.objects.select_related(
            "product", "warehouse", "project", "requested_by", "approver"
        )
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(
            Q(requested_by=self.request.user) | Q(approver=self.request.user)
        )

    def get_success_url(self):
        return reverse("stock-request-detail", args=[self.object.pk])

    def can_approve(self, request_obj: StockRequest) -> bool:
        return (
            request_obj.status == StockRequest.STATUS_PENDING
            and (self.request.user == request_obj.approver or self.request.user.is_staff)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        can_approve = self.can_approve(self.object)
        context["can_approve"] = can_approve
        if can_approve:
            context["approval_form"] = self.get_form()
        context["movements"] = self.object.movements.select_related("product", "warehouse", "project")
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not self.can_approve(self.object):
            return HttpResponseForbidden("Onay yetkiniz yok.")
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.object
        return kwargs

    def form_valid(self, form):
        status = form.cleaned_data["status"]
        decision_reason = form.cleaned_data.get("decision_reason", "")
        self.object.status = status
        self.object.decision_reason = decision_reason
        self.object.approver = self.request.user
        if status == StockRequest.STATUS_APPROVED:
            self.object.approved_at = timezone.now()
        else:
            self.object.approved_at = None
            if status != StockRequest.STATUS_FULFILLED:
                self.object.fulfilled_at = None
        self.object.save(update_fields=[
            "status",
            "decision_reason",
            "approver",
            "approved_at",
            "fulfilled_at",
            "updated_at",
        ])
        self.object.approvals.create(
            approver=self.request.user,
            status=status,
            comments=decision_reason,
        )
        messages.success(self.request, "Talep güncellendi.")
        log_user_activity(
            user=self.request.user,
            action=f"Stok talebi {status} olarak güncellendi",
            request=self.request,
            extra={"request_id": self.object.pk},
        )
        return super().form_valid(form)


class StockAdjustmentCreateView(LoginRequiredMixin, FormView):
    form_class = StockAdjustmentForm
    template_name = "stock/stock_adjustment_form.html"
    success_url = reverse_lazy("stock-movement-list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            adjustment = services.adjust_stock(
                product=data["product"],
                warehouse=data["warehouse"],
                quantity_change=data["quantity_change"],
                reason=data["reason"],
                performed_by=self.request.user,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Stok düzeltmesi uygulandı.")
        log_user_activity(
            user=self.request.user,
            action="Stok düzeltmesi yaptı",
            request=self.request,
            extra={"product": adjustment.product.pk, "quantity_change": adjustment.quantity_change},
        )
        return super().form_valid(form)


class InventoryReportView(LoginRequiredMixin, TemplateView):
    template_name = "stock/inventory_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product_stock = (
            Product.objects.annotate(
                on_hand=Coalesce(Sum("stock_entries__remaining_quantity"), 0),
                total_value=Coalesce(
                    Sum(
                        F("stock_entries__remaining_quantity") * F("stock_entries__unit_cost"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    ),
                    Decimal("0"),
                ),
            )
            .order_by("name")
        )
        context["product_stock"] = product_stock
        context["movements"] = (
            StockMovement.objects.select_related("product", "warehouse", "project")
            .order_by("-created_at")[:50]
        )
        return context


class PriceHistoryView(LoginRequiredMixin, ListView):
    model = StockEntry
    template_name = "stock/price_history.html"
    paginate_by = 25

    def get_queryset(self):
        return (
            StockEntry.objects.select_related("product", "supplier", "warehouse")
            .order_by("-received_at")
        )


class UserManagementView(LoginRequiredMixin, TemplateView):
    template_name = "stock/user_management.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["users"] = User.objects.select_related("userprofile").all()
        context["profiles"] = UserProfile.objects.select_related("user", "manager")
        return context


class SupplierListView(LoginRequiredMixin, ListView):
    model = Supplier
    template_name = "stock/supplier_list.html"
    paginate_by = 20

    def get_queryset(self):
        return Supplier.objects.order_by("name")


class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = "stock/product_list.html"
    paginate_by = 20

    def get_queryset(self):
        return (
            Product.objects.annotate(on_hand=Coalesce(Sum("stock_entries__remaining_quantity"), 0))
            .order_by("name")
        )


class WarehouseListView(LoginRequiredMixin, ListView):
    model = Warehouse
    template_name = "stock/warehouse_list.html"
    paginate_by = 20

    def get_queryset(self):
        return Warehouse.objects.order_by("name")


@login_required
def profile_update(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profiliniz güncellendi.")
            log_user_activity(user=request.user, action="Profilini güncelledi", request=request)
            return redirect("profile")
    else:
        form = UserProfileForm(instance=profile)
    return render(request, "stock/profile.html", {"form": form})


class SupplierCreateView(LoginRequiredMixin, FormView):
    form_class = SupplierForm
    template_name = "stock/supplier_form.html"
    success_url = reverse_lazy("supplier-list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        supplier = form.save()
        messages.success(self.request, "Tedarikçi kaydedildi.")
        log_user_activity(
            user=self.request.user,
            action="Tedarikçi oluşturdu",
            request=self.request,
            extra={"supplier": supplier.pk},
        )
        return super().form_valid(form)


class ProductCreateView(LoginRequiredMixin, FormView):
    form_class = ProductForm
    template_name = "stock/product_form.html"
    success_url = reverse_lazy("product-list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        product = form.save()
        messages.success(self.request, "Ürün kaydedildi.")
        log_user_activity(
            user=self.request.user,
            action="Ürün oluşturdu",
            request=self.request,
            extra={"product": product.pk},
        )
        return super().form_valid(form)


class WarehouseCreateView(LoginRequiredMixin, FormView):
    form_class = WarehouseForm
    template_name = "stock/warehouse_form.html"
    success_url = reverse_lazy("warehouse-list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Yetkiniz yok.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        warehouse = form.save()
        messages.success(self.request, "Depo kaydedildi.")
        log_user_activity(
            user=self.request.user,
            action="Depo oluşturdu",
            request=self.request,
            extra={"warehouse": warehouse.pk},
        )
        return super().form_valid(form)
