from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    # Farmers
    path('farmers/', views.farmer_list, name='farmer_list'),
    path('farmers/new/', views.farmer_create, name='farmer_create'),
    path('farmers/<int:pk>/', views.farmer_detail, name='farmer_detail'),
    path('farmers/<int:pk>/edit/', views.farmer_edit, name='farmer_edit'),
    # Inventory
    path('inventory/', views.inventory_list, name='inventory_list'),
    path('inventory/new/', views.inventory_create, name='inventory_create'),
    # Allocations
    path('allocations/', views.allocation_list, name='allocation_list'),
    path('allocations/new/', views.allocation_create, name='allocation_create'),
    path('allocations/<int:pk>/', views.allocation_detail, name='allocation_detail'),
    # Distribution
    path('distributions/', views.distribution_list, name='distribution_list'),
    path('distributions/record/<int:allocation_pk>/', views.distribution_record, name='distribution_record'),
    # Reports
    path('reports/', views.reports, name='reports'),
    path('reports/export/farmers/', views.export_farmers_csv, name='export_farmers_csv'),
    path('reports/export/allocations/', views.export_allocations_csv, name='export_allocations_csv'),
    # Users
    path('users/', views.user_list, name='user_list'),
    path('users/new/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    # Settings
    path('settings/seeds/', views.seed_type_list, name='seed_type_list'),
    path('settings/seeds/new/', views.seed_type_create, name='seed_type_create'),
    path('settings/seasons/', views.season_list, name='season_list'),
    path('settings/seasons/new/', views.season_create, name='season_create'),
    path('settings/locations/', views.location_manage, name='location_manage'),
    # Stock transfers
    path('stock/', views.stock_list, name='stock_list'),
    path('stock/distribute/', views.stock_distribute, name='stock_distribute'),
    path('stock/request/', views.stock_request_create, name='stock_request_create'),
    path('stock/requests/<int:pk>/respond/', views.stock_request_respond, name='stock_request_respond'),
    # Logs
    path('sms-logs/', views.sms_logs, name='sms_logs'),
    path('activity-logs/', views.activity_logs, name='activity_logs'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
