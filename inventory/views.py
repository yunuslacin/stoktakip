from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    ProjectForm,
    StockAdjustmentForm,
    StockEntryForm,
    StockRequestForm,
    SupplierForm,
    UserProfileForm,
    WarehouseForm,
)
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
from .services import (
    InsufficientStockError,
    apply_stock_adjustment,
    approve_stock_request,
    log_activity,
    record_stock_entry,
    reject_stock_request,
)


def is_manager(user: User) -> bool:
    return user.is_staff or user.is_superuser


def can_manage_request(user: User, request_obj: StockRequest) -> bool:
    if is_manager(user):
        return True
    manager = None
    if hasattr(request_obj.requested_by, "profile"):
        manager = request_obj.requested_by.profile.manager
    return manager == user


@login_required
def dashboard(request):
    low_stock_products = [p for p in Product.objects.all() if p.is_below_reorder]

    recent_movements = StockMovement.objects.select_related("product", "warehouse", "project")[:10]
    if is_manager(request.user):
        pending_requests = StockRequest.objects.filter(status=StockRequest.STATUS_PENDING)
    else:
        pending_requests = StockRequest.objects.filter(
            status=StockRequest.STATUS_PENDING, requested_by=request.user
        )

    total_stock_value = (
        StockEntry.objects.aggregate(
            total=Sum(F("remaining_quantity") * F("unit_cost"))
        )["total"]
        or 0
    )

    context = {
        "low_stock_products": low_stock_products,
        "recent_movements": recent_movements,
        "pending_requests": pending_requests,
        "total_stock_value": total_stock_value,
    }
    return render(request, "inventory/dashboard.html", context)


@login_required
def stock_entry_create(request):
    if request.method == "POST":
        form = StockEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            record_stock_entry(entry, request.user)
            messages.success(request, "Stok girişi başarıyla kaydedildi.")
            return redirect("stock-entry-create")
    else:
        form = StockEntryForm()
    return render(request, "inventory/stock_entry_form.html", {"form": form})


@login_required
def stock_request_create(request):
    if request.method == "POST":
        form = StockRequestForm(request.POST)
        if form.is_valid():
            stock_request = form.save(commit=False)
            stock_request.requested_by = request.user
            stock_request.status = StockRequest.STATUS_PENDING
            stock_request.save()
            log_activity(
                request.user,
                action="Stok Talebi",
                description=f"{stock_request.product} için {stock_request.quantity} adet talep oluşturdu.",
                metadata={"request": stock_request.pk},
            )
            messages.success(request, "Stok talebi oluşturuldu.")
            return redirect("stock-request-list")
    else:
        form = StockRequestForm()
    return render(request, "inventory/stock_request_form.html", {"form": form})


@login_required
def stock_request_list(request):
    if is_manager(request.user):
        requests_qs = StockRequest.objects.select_related(
            "product", "project", "warehouse", "requested_by", "approver"
        )
    else:
        requests_qs = StockRequest.objects.filter(requested_by=request.user).select_related(
            "product", "project", "warehouse", "requested_by", "approver"
        )
    return render(request, "inventory/stock_request_list.html", {"requests": requests_qs})


@login_required
def stock_request_detail(request, pk):
    stock_request = get_object_or_404(StockRequest, pk=pk)
    if not (can_manage_request(request.user, stock_request) or request.user == stock_request.requested_by):
        messages.error(request, "Bu talebi görüntüleme yetkiniz yok.")
        return redirect("stock-request-list")
    allocations = []
    if request.method == "POST" and "action" in request.POST:
        action = request.POST.get("action")
        reason = request.POST.get("reason", "")
        if action == "approve":
            if not can_manage_request(request.user, stock_request):
                messages.error(request, "Talep onaylamak için yetkiniz yok.")
                return redirect("stock-request-detail", pk=stock_request.pk)
            try:
                allocations = approve_stock_request(stock_request, request.user)
                messages.success(request, "Talep onaylandı ve stok düşüldü.")
            except InsufficientStockError as exc:
                messages.error(request, str(exc))
        elif action == "reject":
            if not can_manage_request(request.user, stock_request):
                messages.error(request, "Talep reddetmek için yetkiniz yok.")
                return redirect("stock-request-detail", pk=stock_request.pk)
            reject_stock_request(stock_request, request.user, reason)
            messages.info(request, "Talep reddedildi.")
        return redirect("stock-request-detail", pk=stock_request.pk)

    if stock_request.status == StockRequest.STATUS_COMPLETED:
        allocations = StockMovement.objects.filter(
            reference=f"Talep #{stock_request.pk}",
            movement_type=StockMovement.OUTBOUND,
        ).select_related("source_entry")

    return render(
        request,
        "inventory/stock_request_detail.html",
        {
            "stock_request": stock_request,
            "allocations": allocations,
            "can_manage": can_manage_request(request.user, stock_request),
        },
    )


@login_required
def stock_adjustment_create(request):
    if request.method == "POST":
        form = StockAdjustmentForm(request.POST)
        if form.is_valid():
            adjustment = form.save(commit=False)
            try:
                apply_stock_adjustment(adjustment, request.user)
                messages.success(request, "Stok düzeltmesi uygulandı.")
                return redirect("stock-adjustment-create")
            except InsufficientStockError as exc:
                messages.error(request, str(exc))
    else:
        form = StockAdjustmentForm()
    return render(request, "inventory/stock_adjustment_form.html", {"form": form})


@login_required
def stock_status_report(request):
    products = Product.objects.all().prefetch_related("stock_entries")
    return render(request, "inventory/stock_status_report.html", {"products": products})


@login_required
def stock_movement_history(request):
    movements = StockMovement.objects.select_related("product", "warehouse", "project", "performed_by")
    return render(request, "inventory/stock_movement_history.html", {"movements": movements})


@login_required
def price_history_view(request):
    history = PriceHistory.objects.select_related("product")[:100]
    return render(request, "inventory/price_history.html", {"history": history})


@login_required
@user_passes_test(is_manager)
def supplier_list(request):
    suppliers = Supplier.objects.all()
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Tedarikçi kaydedildi.")
            return redirect("supplier-list")
    else:
        form = SupplierForm()
    return render(request, "inventory/supplier_list.html", {"suppliers": suppliers, "form": form})


@login_required
@user_passes_test(is_manager)
def warehouse_list(request):
    warehouses = Warehouse.objects.all()
    if request.method == "POST":
        form = WarehouseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Depo kaydedildi.")
            return redirect("warehouse-list")
    else:
        form = WarehouseForm()
    return render(request, "inventory/warehouse_list.html", {"warehouses": warehouses, "form": form})


@login_required
@user_passes_test(is_manager)
def project_list(request):
    projects = Project.objects.all()
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Proje kaydedildi.")
            return redirect("project-list")
    else:
        form = ProjectForm()
    return render(request, "inventory/project_list.html", {"projects": projects, "form": form})


@login_required
@user_passes_test(is_manager)
def user_management(request):
    users = User.objects.all().select_related("profile")
    user_forms = [(user, UserProfileForm(instance=user.profile)) for user in users]
    if request.method == "POST":
        user_id = request.POST.get("user_id")
        user_obj = get_object_or_404(User, pk=user_id)
        form = UserProfileForm(request.POST, instance=user_obj.profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Kullanıcı güncellendi.")
            return redirect("user-management")
        user_forms = [
            (user, form if user.pk == user_obj.pk else UserProfileForm(instance=user.profile))
            for user in users
        ]
    return render(
        request,
        "inventory/user_management.html",
        {"user_forms": user_forms},
    )


@login_required
@user_passes_test(is_manager)
def activity_logs(request):
    logs = UserActivityLog.objects.select_related("user")[:100]
    return render(request, "inventory/activity_logs.html", {"logs": logs})
