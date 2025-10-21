from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("stok-giris/", views.stock_entry_create, name="stock-entry-create"),
    path("stok-talep/", views.stock_request_create, name="stock-request-create"),
    path("stok-talep-listesi/", views.stock_request_list, name="stock-request-list"),
    path("stok-talep/<int:pk>/", views.stock_request_detail, name="stock-request-detail"),
    path("stok-duzeltme/", views.stock_adjustment_create, name="stock-adjustment-create"),
    path("raporlar/stok-durumu/", views.stock_status_report, name="stock-status-report"),
    path("hareket-gecmisi/", views.stock_movement_history, name="stock-movement-history"),
    path("fiyat-gecmisi/", views.price_history_view, name="price-history"),
    path("yonetim/tedarikciler/", views.supplier_list, name="supplier-list"),
    path("yonetim/depolar/", views.warehouse_list, name="warehouse-list"),
    path("yonetim/projeler/", views.project_list, name="project-list"),
    path("yonetim/kullanicilar/", views.user_management, name="user-management"),
    path("aktivite-loglari/", views.activity_logs, name="activity-logs"),
]
