from django.urls import path, include
from reviews.views import vehicle_list, booking_list, account_profile
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('accounts/login/', auth_views.LoginView.as_view(template_name='reviews/login.html'), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('profile/', account_profile, name='account_profile'),

    # TỔNG QUAN
    path('', views.tong_quan, name="tong_quan"),

    # Khách hàng
    path('khach-hang/', views.khach_hang_list, name='khach_hang_list'),
    path('khach-hang/them/', views.khach_hang_create, name='khach_hang_create'),
    path('khach-hang/<str:pk>/sua/', views.khach_hang_update, name='khach_hang_update'),
    path('khach-hang/<str:pk>/lich-su/', views.khach_hang_history, name='khach_hang_history'),

    # Hợp đồng
    path('hop-dong/', views.hop_dong_list, name='hop_dong_list'),
    path('hop-dong/lap-moi/', views.hop_dong_create, name='hop_dong_create'),
    path('hop-dong/<str:pk>/gia-han/', views.hop_dong_gia_han, name='hop_dong_gia_han'),
    path('hop-dong/<str:pk>/in/', views.hop_dong_print_view, name='hop_dong_print'),

    # BIÊN BẢN BÀN GIAO
    path('hop-dong/<str:hop_dong_id>/xuat-bai/', views.bien_ban_xuat_bai, name='bien_ban_xuat_bai'),
    path('hop-dong/<str:hop_dong_id>/thu-hoi/', views.bien_ban_tra_xe, name='bien_ban_tra_xe'),
    path('bien-ban/<str:pk>/', views.bien_ban_detail, name='bien_ban_detail'),
    path('bien-ban/tra-cuu/<str:token>/', views.bien_ban_public_view, name='bien_ban_public'),

    # QUẢN LÝ XE
    path('quan-ly-xe/', vehicle_list, name='vehicle_list'),

    # ĐẶT XE
    path('bookings/', booking_list, name='booking_list'),
    path('bookings/create/', views.booking_create, name='booking_create'),

    # BÁO CÁO THỐNG KÊ
    path("bao-cao/", views.bao_cao, name="bao_cao"),

    # API hỗ trợ lấy giá xe tự động
    path('api/xe/<str:bien_so>/pricing/', views.api_get_vehicle_pricing, name='api_vehicle_pricing'),
    path("api/tong-quan/", views.api_tong_quan, name="api_tong_quan"),
    path("api/bao-cao/", views.api_bao_cao,name="api_bao_cao"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)