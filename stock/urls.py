from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="stock/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("entries/", views.StockEntryListView.as_view(), name="stock-entry-list"),
    path("entries/new/", views.StockEntryCreateView.as_view(), name="stock-entry-create"),
    path("issues/new/", views.StockIssueView.as_view(), name="stock-issue"),
    path("adjustments/new/", views.StockAdjustmentCreateView.as_view(), name="stock-adjustment"),
    path("movements/", views.StockMovementListView.as_view(), name="stock-movement-list"),
    path("requests/", views.StockRequestListView.as_view(), name="stock-request-list"),
    path("requests/new/", views.StockRequestCreateView.as_view(), name="stock-request-create"),
    path("requests/<int:pk>/", views.StockRequestDetailView.as_view(), name="stock-request-detail"),
    path("reports/inventory/", views.InventoryReportView.as_view(), name="inventory-report"),
    path("reports/price-history/", views.PriceHistoryView.as_view(), name="price-history"),
    path("users/", views.UserManagementView.as_view(), name="user-management"),
    path("profile/", views.profile_update, name="profile"),
    path("suppliers/", views.SupplierListView.as_view(), name="supplier-list"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier-create"),
    path("products/", views.ProductListView.as_view(), name="product-list"),
    path("products/new/", views.ProductCreateView.as_view(), name="product-create"),
    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse-list"),
    path("warehouses/new/", views.WarehouseCreateView.as_view(), name="warehouse-create"),
]
