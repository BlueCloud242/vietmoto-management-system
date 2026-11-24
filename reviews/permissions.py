from functools import wraps
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import NhanVien


def resolve_nhan_vien(user):
    """
    Lấy bản ghi NhanVien gắn với tài khoản Django User đang đăng nhập.
    Không tự tạo mới để tránh tạo nhầm quyền khi kiểm tra read-only.
    """
    if not user or not user.is_authenticated:
        return None

    nv = getattr(user, 'nhanvien', None)
    if nv:
        return nv

    return NhanVien.objects.filter(ten_dang_nhap=user.username).first()


def get_role_flags(user):
    """
    Trả về dictionary các cờ phân quyền chuẩn hóa cho cả View (Python) và Template (HTML).
    """
    flags = {
        'nhan_vien_obj': None,
        'role_code': None,
        'role_label': 'Chưa phân quyền',
        'is_active_staff': False,
        'is_manager': False,
        'is_quay': False,
        'is_ky_thuat': False,
        # Quyền theo từng phân hệ
        'can_manage_customers': False,     # Thêm/sửa khách hàng
        'can_manage_bookings': False,      # Tạo/sửa/hủy đơn đặt trước
        'can_manage_contracts': False,     # Lập HĐ, gia hạn HĐ
        'can_manage_handover': False,      # Lập biên bản xuất bãi & thu hồi xe
        'can_manage_fleet': False,         # Toàn quyền đội xe (Thêm/sửa/xóa xe & dòng xe, điều phối)
        'can_ready_vehicle': False,        # Xác nhận rửa xe / sạc pin & báo hỏng vào xưởng
        'can_manage_maintenance': False,   # Lập & hoàn tất phiếu bảo dưỡng kỹ thuật
        'can_view_reports': False,         # Truy cập trang Báo cáo thống kê
        'can_view_profit': False,          # Xem KPI Lợi nhuận ròng & Chi phí bảo dưỡng (chỉ Quản lý)
    }

    if not user or not user.is_authenticated:
        return flags

    nv = resolve_nhan_vien(user)
    flags['nhan_vien_obj'] = nv

    # Nếu nhân viên đã bị đánh dấu NGHỈ VIỆC -> thu hồi toàn bộ quyền thao tác
    if nv and nv.trang_thai == 'NGHI_VIEC' and not user.is_superuser:
        flags['role_code'] = 'NGHI_VIEC'
        flags['role_label'] = 'Đã nghỉ việc'
        return flags

    if user.is_superuser or (nv and nv.vai_tro in ('ADMIN', 'QUAN_LY')):
        role_code = 'ADMIN' if (user.is_superuser or (nv and nv.vai_tro == 'ADMIN')) else 'QUAN_LY'
        role_label = nv.get_vai_tro_display() if nv else 'Quản trị viên'
        flags.update({
            'role_code': role_code,
            'role_label': role_label,
            'is_active_staff': True,
            'is_manager': True,
            'can_manage_customers': True,
            'can_manage_bookings': True,
            'can_manage_contracts': True,
            'can_manage_handover': True,
            'can_manage_fleet': True,
            'can_ready_vehicle': True,
            'can_manage_maintenance': True,
            'can_view_reports': True,
            'can_view_profit': True,
        })
        return flags

    if nv and nv.vai_tro == 'QUAY':
        flags.update({
            'role_code': 'QUAY',
            'role_label': nv.get_vai_tro_display(),
            'is_active_staff': True,
            'is_quay': True,
            # Nhân viên quầy: Toàn quyền Khách hàng, Đặt xe, Hợp đồng, Quản lý đội xe
            'can_manage_customers': True,
            'can_manage_bookings': True,
            'can_manage_contracts': True,
            'can_manage_fleet': True,
            'can_ready_vehicle': True,
            # Báo cáo: Được xem vận hành & đối soát thu/cọc, ẨN lợi nhuận & chi phí vốn
            'can_view_reports': True,
            'can_view_profit': False,
            # Chỉ xem (không thao tác) Biên bản bàn giao & Phiếu bảo dưỡng kỹ thuật
            'can_manage_handover': False,
            'can_manage_maintenance': False,
        })
        return flags

    if nv and nv.vai_tro == 'KY_THUAT':
        flags.update({
            'role_code': 'KY_THUAT',
            'role_label': nv.get_vai_tro_display(),
            'is_active_staff': True,
            'is_ky_thuat': True,
            # Kỹ thuật viên: Toàn quyền Biên bản bàn giao, Bảo dưỡng & thao tác rửa xe/báo hỏng
            'can_manage_handover': True,
            'can_manage_maintenance': True,
            'can_ready_vehicle': True,
            # Các phân hệ quầy & báo cáo: Chỉ xem hoặc ẩn
            'can_manage_customers': False,
            'can_manage_bookings': False,
            'can_manage_contracts': False,
            'can_manage_fleet': False,
            'can_view_reports': False,
            'can_view_profit': False,
        })
        return flags

    return flags


def vietmoto_permissions(request):
    """Context processor tự động truyền biến `perms_vm` vào mọi template HTML."""
    return {
        'perms_vm': get_role_flags(getattr(request, 'user', None))
    }


def has_permission(user, permission_key):
    """Kiểm tra nhanh 1 quyền cụ thể trong views.py (dùng cho các nhánh POST action)."""
    flags = get_role_flags(user)
    return bool(flags.get(permission_key, False))


def permission_required_vm(permission_key, redirect_url='tong_quan', deny_message=None):
    """
    Decorator bảo vệ các view chức năng theo cờ phân quyền trong `get_role_flags`.
    Hỗ trợ cả request thường, AJAX/JSON và HTMX.
    """
    default_msg = deny_message or "Tài khoản của bạn không có quyền thực hiện chức năng này!"

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            flags = get_role_flags(request.user)
            if flags.get('role_code') == 'NGHI_VIEC':
                msg = "Tài khoản nhân viên đã ngừng hoạt động (Nghỉ việc). Vui lòng liên hệ Quản lý."
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': msg}, status=403)
                messages.error(request, msg)
                return redirect('tong_quan')

            if not flags.get(permission_key, False):
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': default_msg}, status=403)
                messages.error(request, default_msg)
                return redirect(redirect_url)

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator