from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, NoReverseMatch
from . import models as review_models
from django.http import HttpResponseRedirect
from django.db import transaction, connection
from django.contrib import messages
from django.db.models import Q, Sum, Count, ProtectedError
from django.http import JsonResponse
from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_date
import datetime
import calendar
import json
import logging
from decimal import Decimal, InvalidOperation
import uuid
import urllib.parse
from django.utils import timezone
import math
from django.core.paginator import Paginator
from django.core.files.storage import default_storage
from django.db.models.functions import TruncDate
from collections import defaultdict
from django.db.models import F
from .permissions import permission_required_vm, has_permission, get_role_flags

from .models import (
    KhachHang, HopDongThue, PhuongTien, BienBanBanGiao, DongXe, ThanhToan,
    NhanVien, DonDatTruoc, NhatKyBaoDuong, HinhAnhBaoDuong, NhatKyVanHanhXe,
    HinhAnhBienBan
)
from .forms import (
    KhachHangForm, HopDongThueCreateForm, GiaHanHopDongForm,
    BienBanXuatBaiForm, BienBanTraXeForm, DonDatTruocForm, DonDatTruocEditForm,
    DongXeForm, PhuongTienCreateForm, PhuongTienUpdateForm
)


def _parse_fuel_percent(val_str, default=100):
    """Quy đổi chuỗi mức xăng/pin (VD: '80% Pin', 'Đầy bình', '1/2 bình') sang số nguyên 0-100"""
    if not val_str:
        return default
    s = str(val_str).lower().strip()
    digits = ''.join(filter(str.isdigit, s))
    if digits and '%' in s:
        return min(100, max(0, int(digits)))
    if 'đầy' in s or 'full' in s or '4/4' in s:
        return 100
    if '3/4' in s:
        return 75
    if '1/2' in s or 'nửa' in s:
        return 50
    if '1/4' in s or 'gần hết' in s:
        return 25
    if 'hết' in s or 'cạn' in s:
        return 10
    return default

# ==============================================================================
# PROFILE
# ==============================================================================

@login_required
def account_profile(request):
    user = request.user
    nhan_vien = get_current_nhan_vien(user)
    is_manager = user.is_superuser or (nhan_vien and nhan_vien.vai_tro in ['ADMIN', 'QUAN_LY'])

    ho_ten_hien_thi = None
    if nhan_vien and nhan_vien.ho_ten:
        ho_ten_hien_thi = nhan_vien.ho_ten
    elif user.get_full_name():
        ho_ten_hien_thi = user.get_full_name()

    return render(request, 'reviews/profile.html', {
        'user': user,
        'nhan_vien_info': nhan_vien,
        'ho_ten_hien_thi': ho_ten_hien_thi,
        'is_manager': is_manager,
        'active_page': 'profile',
    })
# ==============================================================================
# PHÂN HỆ KHÁCH HÀNG
# ==============================================================================

def get_next_customer_id():
    """Sinh mã KH0001, KH0002... chuẩn theo giá trị số lớn nhất."""
    existing_ids = KhachHang.objects.filter(
        ma_khach_hang__startswith='KH'
    ).values_list('ma_khach_hang', flat=True)
    max_num = 0
    for cid in existing_ids:
        suffix = cid[2:]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    return f"KH{max_num + 1:04d}"


@login_required
def khach_hang_list(request):
    query = request.GET.get('q', '').strip()
    loc_uy_tin = request.GET.get('uy_tin', '').strip()

    khach_hangs = KhachHang.objects.annotate(
        so_lan_thue_xong=Count('hop_dong', filter=Q(hop_dong__trang_thai_hop_dong='DA_TRA'), distinct=True),
        so_hd_dang_mo=Count('hop_dong', filter=Q(hop_dong__trang_thai_hop_dong__in=['DANG_THUE', 'CHO_BAN_GIAO']),
                            distinct=True),
        so_don_dat_truoc=Count('don_dat_truoc', filter=Q(don_dat_truoc__trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO']),
                               distinct=True)
    ).order_by('-ngay_tao')

    if query:
        khach_hangs = khach_hangs.filter(
            Q(so_dien_thoai__icontains=query) |
            Q(ho_ten__icontains=query) |
            Q(so_cccd__icontains=query) |
            Q(ma_khach_hang__icontains=query)
        )

    danh_sach = []
    counts_uy_tin = {'ALL': 0, 'TOT': 0, 'MOI': 0, 'DAT_TRUOC': 0, 'CAN_LUU_Y': 0, 'BLACKLIST': 0}

    for kh in khach_hangs:
        muc_tn = getattr(kh, 'muc_tin_nhiem', '')

        if muc_tn == 'BLACKLIST':
            kh.trang_thai_uy_tin = 'BLACKLIST'
            kh.uy_tin_label = 'Blacklist'
            kh.uy_tin_icon = 'fa-ban'
        elif muc_tn == 'CAN_LUU_Y':
            kh.trang_thai_uy_tin = 'CAN_LUU_Y'
            kh.uy_tin_label = 'Cần lưu ý'
            kh.uy_tin_icon = 'fa-triangle-exclamation'
        elif kh.so_lan_thue_xong >= 1:
            kh.trang_thai_uy_tin = 'TOT'
            kh.uy_tin_label = 'Uy tín tốt'
            kh.uy_tin_icon = 'fa-circle-check'
        elif kh.so_hd_dang_mo >= 1:
            kh.trang_thai_uy_tin = 'MOI'
            kh.uy_tin_label = 'Khách mới'
            kh.uy_tin_icon = 'fa-user-clock'
        else:
            kh.trang_thai_uy_tin = 'DAT_TRUOC'
            kh.uy_tin_label = 'Đặt trước'
            kh.uy_tin_icon = 'fa-calendar-check'

        counts_uy_tin['ALL'] += 1
        counts_uy_tin[kh.trang_thai_uy_tin] += 1

        if not loc_uy_tin or kh.trang_thai_uy_tin == loc_uy_tin:
            danh_sach.append(kh)

    paginator = Paginator(danh_sach, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'reviews/khach_hang_list.html', {
        'khach_hangs': page_obj,
        'query': query,
        'loc_uy_tin': loc_uy_tin,
        'counts_uy_tin': counts_uy_tin,
        'page_obj': page_obj,
        'active_page': 'khach_hang',
    })


@login_required
@permission_required_vm(
    'can_manage_customers',
    redirect_url='khach_hang_list',
    deny_message='Kỹ thuật viên chỉ có quyền xem hồ sơ khách hàng, không thể thêm hoặc chỉnh sửa!'
)
def khach_hang_create(request):
    next_ma_kh = get_next_customer_id()

    # Lấy nhân viên đang đăng nhập (hoặc lấy mặc định nếu chưa gắn user)
    nhan_vien = getattr(request.user, 'nhanvien', None) or NhanVien.objects.first()

    if request.method == 'POST':
        form = KhachHangForm(request.POST)
        if form.is_valid():
            khach_hang = form.save(commit=False)
            khach_hang.ma_khach_hang = next_ma_kh
            khach_hang.muc_tin_nhiem = 'TOT'  # Hồ sơ sạch mặc định, chưa thuê sẽ hiển thị "Khách mới"
            khach_hang.save()
            messages.success(request, f"Thêm mới hồ sơ khách hàng {khach_hang.ma_khach_hang} thành công!")
            return redirect('khach_hang_list')
    else:
        form = KhachHangForm(initial={
            'ma_khach_hang': next_ma_kh,
            'quoc_tich': 'Việt Nam'
        })

    return render(request, 'reviews/khach_hang_form.html', {'form': form, 'title': 'Thêm Khách Hàng', 'nhan_vien': nhan_vien, 'active_page': 'khach_hang',})


@login_required
@permission_required_vm(
    'can_manage_customers',
    redirect_url='khach_hang_list',
    deny_message='Kỹ thuật viên chỉ có quyền xem hồ sơ khách hàng, không thể chỉnh sửa!'
)
def khach_hang_update(request, pk):
    # Lấy nhân viên đang đăng nhập (hoặc lấy mặc định nếu chưa gắn user)
    nhan_vien = getattr(request.user, 'nhanvien', None) or NhanVien.objects.first()

    khach_hang = get_object_or_404(KhachHang, pk=pk)
    if request.method == 'POST':
        form = KhachHangForm(request.POST, instance=khach_hang)
        if form.is_valid():
            form.save()
            messages.success(request, f"Cập nhật hồ sơ khách hàng {khach_hang.ho_ten} thành công!")
            return redirect('khach_hang_list')
    else:
        form = KhachHangForm(instance=khach_hang)
    return render(request, 'reviews/khach_hang_form.html', {'form': form, 'title': 'Cập Nhật Khách Hàng', 'nhan_vien': nhan_vien, 'active_page': 'khach_hang',})


@login_required
def khach_hang_history(request, pk):
    khach_hang = get_object_or_404(KhachHang, pk=pk)
    danh_sach_hop_dong = khach_hang.hop_dong.select_related(
        'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'
    ).order_by('-ngay_tao')

    # Lấy toàn bộ lịch sử đặt xe trước của khách (bao gồm Đã giữ chỗ, Đã chuyển HĐ, Đã hủy, Không đến)
    danh_sach_don_dat = DonDatTruoc.objects.filter(
        ma_khach_hang=khach_hang
    ).select_related('bien_so_xe__ma_dong_xe', 'ma_nhan_vien').order_by('-ngay_tao')

    so_don_huy = danh_sach_don_dat.filter(trang_thai_don__in=['DA_HUY', 'KHONG_DEN']).count()

    tong_lan_thue = danh_sach_hop_dong.filter(trang_thai_hop_dong='DA_TRA').count()
    tong_chi_tieu = danh_sach_hop_dong.filter(
        trang_thai_hop_dong__in=['DA_TRA', 'DANG_THUE']
    ).aggregate(Sum('tong_tien_thanh_toan'))['tong_tien_thanh_toan__sum'] or 0
    xe_dang_giu = danh_sach_hop_dong.filter(trang_thai_hop_dong='DANG_THUE').count()
    so_hd_vi_pham = danh_sach_hop_dong.filter(
        Q(trang_thai_hop_dong='DA_TRA', phu_phi__gt=0) |
        Q(ngay_ket_thuc_thuc_te__gt=F('ngay_ket_thuc_du_kien'))
    ).distinct().count()
    so_lan_khong_den = danh_sach_don_dat.filter(trang_thai_don='KHONG_DEN').count()
    so_lan_vi_pham = so_hd_vi_pham + so_lan_khong_den

    muc_tn = getattr(khach_hang, 'muc_tin_nhiem', 'TOT')
    if muc_tn == 'BLACKLIST':
        tin_nhiem_badge = 'danger'
        tin_nhiem_icon = 'fa-ban'
        tin_nhiem_text = f'Blacklist ({khach_hang.ly_do_blacklist or "Vi phạm nghiêm trọng"})'
    elif muc_tn == 'CAN_LUU_Y':
        tin_nhiem_badge = 'warning text-dark'
        tin_nhiem_icon = 'fa-triangle-exclamation'
        tin_nhiem_text = f'Cần lưu ý (Phát sinh vi phạm / lưu ý {so_lan_vi_pham} lần)'
    elif tong_lan_thue >= 1:
        tin_nhiem_badge = 'success'
        tin_nhiem_icon = 'fa-circle-check'
        tin_nhiem_text = f'Khách hàng uy tín tốt (Đã thuê {tong_lan_thue} lượt)'
    else:
        tin_nhiem_badge = 'secondary'
        tin_nhiem_icon = 'fa-user-clock'
        tin_nhiem_text = 'Khách hàng mới (Chưa có lịch sử thuê)'

    for hd in danh_sach_hop_dong:
        if not hd.so_ngay_thue or hd.so_ngay_thue <= 0:
            if hd.ngay_bat_dau and hd.ngay_ket_thuc_du_kien:
                diff_sec = (hd.ngay_ket_thuc_du_kien - hd.ngay_bat_dau).total_seconds()
                hd.so_ngay_thue = max(1, math.ceil(diff_sec / 86400))
            else:
                hd.so_ngay_thue = 1

        if not hd.tong_tien_thanh_toan or hd.tong_tien_thanh_toan <= 0:
            don_gia = hd.don_gia_ap_dung or (hd.bien_so_xe.ma_dong_xe.don_gia_ngay if hd.bien_so_xe else 0)
            hd.tong_tien_thanh_toan = hd.so_ngay_thue * don_gia

        hd.tong_thu_du_kien = (hd.tong_tien_thanh_toan or 0) + (hd.tien_coc_quy_dinh or 0)
        phat = hd.phu_phi or 0
        coc = hd.so_tien_coc_thuc_thu if hd.hinh_thuc_dat_coc != 'GIU_CCCD' else 0
        hd.tien_hoan_coc_thuc_te = max(0, coc - phat)
        hd.tien_khach_con_thieu = max(0, phat - coc)
        hd.is_tre_han = bool(
            hd.ngay_ket_thuc_thuc_te and hd.ngay_ket_thuc_du_kien and
            hd.ngay_ket_thuc_thuc_te > hd.ngay_ket_thuc_du_kien
        )

    context = {
        'khach_hang': khach_hang,
        'danh_sach_hop_dong': danh_sach_hop_dong,
        'danh_sach_don_dat': danh_sach_don_dat,
        'so_don_huy': so_don_huy,
        'tong_lan_thue': tong_lan_thue,
        'tong_chi_tieu': tong_chi_tieu,
        'xe_dang_giu': xe_dang_giu,
        'so_lan_vi_pham': so_lan_vi_pham,
        'tin_nhiem_badge': tin_nhiem_badge,
        'tin_nhiem_icon': tin_nhiem_icon,
        'tin_nhiem_text': tin_nhiem_text,
        'active_page': 'khach_hang',
    }
    return render(request, 'reviews/khach_hang_history.html', context)


# ==============================================================================
# PHÂN HỆ HỢP ĐỒNG THUÊ XE
# ==============================================================================

def kiem_tra_xung_dot_dat_truoc(xe, tu_thoi_diem, den_thoi_diem=None):
    """
    BRULE-02: Kiểm tra xe có lịch đặt trước/hợp đồng chờ bàn giao nào
    trong khoảng [tu_thoi_diem -> den_thoi_diem + 24h] không.
    """
    moc_cuoi = (den_thoi_diem or tu_thoi_diem) + timedelta(hours=24)

    hd_tiep_theo = HopDongThue.objects.filter(
        bien_so_xe=xe,
        trang_thai_hop_dong='CHO_BAN_GIAO',
        ngay_bat_dau__range=[tu_thoi_diem, moc_cuoi]
    ).select_related('ma_khach_hang').first()
    if hd_tiep_theo:
        return True, (
            f"HĐ {hd_tiep_theo.ma_hop_dong} "
            f"(Khách: {hd_tiep_theo.ma_khach_hang.ho_ten}) "
            f"nhận lúc {hd_tiep_theo.ngay_bat_dau.strftime('%H:%M - %d/%m/%Y')}"
        )

    dat_xe = DonDatTruoc.objects.filter(
        bien_so_xe=xe,
        trang_thai_don__in=['DA_GIU_CHO', 'CHO_XAC_NHAN'],
        thoi_gian_hen_nhan__range=[tu_thoi_diem, moc_cuoi]
    ).select_related('ma_khach_hang').first()
    if dat_xe:
        return True, (
            f"Đơn đặt {dat_xe.ma_don_dat} "
            f"(Khách: {dat_xe.ma_khach_hang.ho_ten}) "
            f"nhận lúc {dat_xe.thoi_gian_hen_nhan.strftime('%H:%M - %d/%m/%Y')}"
        )

    return False, None


@login_required
def hop_dong_list(request):
    query = request.GET.get('q', '').strip()
    trang_thai = request.GET.get('trang_thai', 'ALL')
    now = timezone.now()
    next_24h = now + timedelta(hours=24)

    # 1. Truy vấn gốc (các hợp đồng chưa trả)
    base_qs = HopDongThue.objects.select_related(
        'ma_khach_hang', 'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'
    ).exclude(trang_thai_hop_dong='DA_TRA').order_by('-ngay_tao')

    # 2. Lọc theo từ khóa tìm kiếm trước (để số badge trên 5 tab phản ánh đúng kết quả tìm kiếm)
    if query:
        base_qs = base_qs.filter(
            Q(ma_hop_dong__icontains=query) |
            Q(ma_khach_hang__ho_ten__icontains=query) |
            Q(ma_khach_hang__so_dien_thoai__icontains=query) |
            Q(bien_so_xe__bien_so_xe__icontains=query)
        )

    # 3. Đếm số lượng cho 5 tab (trước khi lọc theo từng tab)
    count_all = base_qs.count()
    count_cho_ban_giao = base_qs.filter(trang_thai_hop_dong='CHO_BAN_GIAO').count()
    count_dang_thue = base_qs.filter(trang_thai_hop_dong='DANG_THUE').count()
    count_sap_het_han = base_qs.filter(
        trang_thai_hop_dong='DANG_THUE',
        ngay_ket_thuc_du_kien__range=[now, next_24h]
    ).count()
    count_qua_han = base_qs.filter(
        trang_thai_hop_dong='DANG_THUE',
        ngay_ket_thuc_du_kien__lt=now
    ).count()

    # 4. Lọc theo tab trạng thái đang chọn
    hop_dongs = base_qs
    if trang_thai == 'CHO_BAN_GIAO':
        hop_dongs = hop_dongs.filter(trang_thai_hop_dong='CHO_BAN_GIAO')
    elif trang_thai == 'DANG_THUE':
        hop_dongs = hop_dongs.filter(trang_thai_hop_dong='DANG_THUE')
    elif trang_thai == 'SAP_HET_HAN':
        hop_dongs = hop_dongs.filter(trang_thai_hop_dong='DANG_THUE', ngay_ket_thuc_du_kien__range=[now, next_24h])
    elif trang_thai == 'QUA_HAN':
        hop_dongs = hop_dongs.filter(trang_thai_hop_dong='DANG_THUE', ngay_ket_thuc_du_kien__lt=now)

    # 5. Phân trang (5 hợp đồng / trang)
    paginator = Paginator(hop_dongs, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 6. Bổ sung cờ cảnh báo cho các hợp đồng trong trang hiện tại
    for hd in page_obj:
        hd.is_sap_het_han = (
            hd.trang_thai_hop_dong == 'DANG_THUE' and
            now <= hd.ngay_ket_thuc_du_kien <= next_24h
        )
        co_lich, ly_do = kiem_tra_xung_dot_dat_truoc(hd.bien_so_xe, hd.ngay_ket_thuc_du_kien)
        hd.is_extension_locked = (hd.is_sap_het_han and co_lich)
        hd.booking_conflict_reason = ly_do

    return render(request, 'reviews/hop_dong_list.html', {
        'page_obj': page_obj,
        'hop_dongs': page_obj,
        'current_tab': trang_thai,
        'query': query,
        'now': now,
        'count_all': count_all,
        'count_cho_ban_giao': count_cho_ban_giao,
        'count_dang_thue': count_dang_thue,
        'count_sap_het_han': count_sap_het_han,
        'count_qua_han': count_qua_han,
    })


def get_next_contract_id():
    existing_ids = HopDongThue.objects.values_list('ma_hop_dong', flat=True)
    max_num = 0
    for mid in existing_ids:
        digits = ''.join(filter(str.isdigit, mid))
        if digits:
            max_num = max(max_num, int(digits))
    return f"HD-{max_num + 1:03d}"


@login_required
@permission_required_vm(
    'can_manage_contracts',
    redirect_url='hop_dong_list',
    deny_message='Chỉ Nhân viên quầy hoặc Quản lý mới được phép lập hợp đồng thuê xe!'
)
def hop_dong_create(request):
    don_dat_id = request.GET.get('don_dat')
    don_dat = None
    kh_dat_san = None

    if don_dat_id:
        don_dat = get_object_or_404(DonDatTruoc, pk=don_dat_id)
        kh_dat_san = don_dat.ma_khach_hang

    nhan_vien_truc = get_current_nhan_vien(request.user)
    next_ma_hd = get_next_contract_id()

    if request.method == 'POST':
        form = HopDongThueCreateForm(request.POST, don_dat=don_dat)
        form.fields['bien_so_xe'].queryset = (
            form.fields['bien_so_xe'].queryset
            .filter(ma_dong_xe__dang_kinh_doanh=True)
            .exclude(trang_thai_xe__in=['NGUNG_HOAT_DONG', 'BAO_DUONG'])
        )

        if form.is_valid():
            with transaction.atomic():
                hop_dong = form.save(commit=False)
                xe = PhuongTien.objects.select_for_update().select_related('ma_dong_xe').get(
                    pk=hop_dong.bien_so_xe.pk
                )

                # Kiểm tra trạng thái vật lý của xe tại bãi trước khi lập hợp đồng
                allowed_states = ['CON_TRONG']
                if don_dat and xe.pk == don_dat.bien_so_xe_id:
                    allowed_states.append('DA_DAT_TRUOC')

                if xe.trang_thai_xe == 'CHO_VE_SINH':
                    messages.error(
                        request,
                        f"Xe {xe.bien_so_xe} đang ở trạng thái 'Chờ rửa xe / Sạc pin'. "
                        f"Vui lòng xác nhận hoàn tất vệ sinh tại Quản lý xe trước khi lập hợp đồng!"
                    )
                    return redirect(request.get_full_path())
                elif xe.trang_thai_xe not in allowed_states:
                    messages.error(
                        request,
                        f"Xe {xe.bien_so_xe} hiện không khả dụng ({xe.get_trang_thai_xe_display()})."
                    )
                    return redirect(request.get_full_path())

                hop_dong.ma_hop_dong = get_next_contract_id()
                hop_dong.ma_nhan_vien = nhan_vien_truc

                dong_xe = xe.ma_dong_xe
                hop_dong.don_gia_ap_dung = dong_xe.don_gia_ngay

                # 1. Tính số ngày thuê & tổng tiền thuê
                khoang_cach = hop_dong.ngay_ket_thuc_du_kien - hop_dong.ngay_bat_dau
                so_gio = khoang_cach.total_seconds() / 3600
                hop_dong.so_ngay_thue = max(1, math.ceil(so_gio / 24))
                hop_dong.tong_tien_thanh_toan = hop_dong.so_ngay_thue * hop_dong.don_gia_ap_dung

                # 2. Xử lý chính sách đặt cọc theo quốc tịch
                khach = hop_dong.ma_khach_hang
                quoc_tich = (khach.quoc_tich or '').lower().strip()
                is_viet_nam = quoc_tich in ['việt nam', 'viet nam', 'vietnam', 'vn', '']
                hinh_thuc_coc = form.cleaned_data.get('hinh_thuc_dat_coc') or 'GIU_CCCD'

                coc_giu_cho_da_thu = (
                    int(don_dat.tien_coc_giu_cho or 0)
                    if (don_dat and don_dat.da_thanh_toan_coc)
                    else 0
                )

                hop_dong.tien_coc_quy_dinh = dong_xe.tien_coc_dinh_muc
                if is_viet_nam and hinh_thuc_coc == 'GIU_CCCD':
                    hop_dong.hinh_thuc_dat_coc = 'GIU_CCCD'
                    # Nếu khách đã đóng 100k giữ chỗ nhưng tại quầy chọn giữ CCCD -> ghi nhận để hoàn/trừ cước
                    hop_dong.so_tien_coc_thuc_thu = coc_giu_cho_da_thu
                else:
                    hop_dong.hinh_thuc_dat_coc = 'TIEN_MAT'
                    hop_dong.so_tien_coc_thuc_thu = dong_xe.tien_coc_dinh_muc

                # 3. Lưu HĐ ở trạng thái CHO_BAN_GIAO để chuyển sang Biên bản xuất bãi
                hop_dong.trang_thai_hop_dong = 'CHO_BAN_GIAO'
                hop_dong.trang_thai_thanh_toan = (
                    'DA_COC' if hop_dong.so_tien_coc_thuc_thu > 0 else 'CHUA_THANH_TOAN'
                )

                if don_dat:
                    hop_dong.ma_don_dat = don_dat

                ghi_chu_user = form.cleaned_data.get('ghi_chu_hop_dong') or ''
                if coc_giu_cho_da_thu > 0:
                    note_coc = f"[Đã đối trừ {coc_giu_cho_da_thu:,.0f}đ cọc giữ chỗ từ đơn {don_dat.ma_don_dat}]"
                    hop_dong.ghi_chu = f"{note_coc} {ghi_chu_user}".strip()
                elif ghi_chu_user:
                    hop_dong.ghi_chu = ghi_chu_user

                hop_dong.save()

                # 4. Ghi nhận giao dịch thu cọc (chỉ thu phần chênh lệch còn thiếu tại quầy)
                hinh_thuc_tt = form.cleaned_data.get('hinh_thuc_thanh_toan') or 'CHUYEN_KHOAN'
                if coc_giu_cho_da_thu > 0:
                    ThanhToan.objects.create(
                        ma_thanh_toan=f"TT-COC-BK-{hop_dong.ma_hop_dong}",
                        ma_hop_dong=hop_dong,
                        ma_nhan_vien=nhan_vien_truc,
                        so_tien=coc_giu_cho_da_thu,
                        loai_thanh_toan='COC',
                        hinh_thuc=hinh_thuc_tt,
                        trang_thai='THANH_CONG',
                        thoi_gian_thanh_toan=timezone.now(),
                        ma_giao_dich=f"Chuyển cọc giữ chỗ từ đơn {don_dat.ma_don_dat}"
                    )

                coc_thu_them_tai_quay = max(0, int(hop_dong.so_tien_coc_thuc_thu) - coc_giu_cho_da_thu)
                if coc_thu_them_tai_quay > 0:
                    ThanhToan.objects.create(
                        ma_thanh_toan=f"TT-COC-{hop_dong.ma_hop_dong}",
                        ma_hop_dong=hop_dong,
                        ma_nhan_vien=nhan_vien_truc,
                        so_tien=coc_thu_them_tai_quay,
                        loai_thanh_toan='COC',
                        hinh_thuc=hinh_thuc_tt,
                        trang_thai='THANH_CONG',
                        thoi_gian_thanh_toan=timezone.now(),
                        ma_giao_dich=f"Thu cọc bổ sung tại quầy HĐ {hop_dong.ma_hop_dong}"
                    )

                # 5. Khóa xe chờ giao, ghi log vận hành & cập nhật đơn đặt trước
                trang_thai_cu = xe.trang_thai_xe
                xe.trang_thai_xe = 'DANG_THUE'
                xe.save(update_fields=['trang_thai_xe', 'ngay_cap_nhat'])

                NhatKyVanHanhXe.objects.create(
                    bien_so_xe=xe,
                    ma_nhan_vien=nhan_vien_truc,
                    tu_trang_thai=trang_thai_cu,
                    den_trang_thai='DANG_THUE',
                    odo_ghi_nhan=xe.odo_hien_tai,
                    muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                    ghi_chu=f"Khóa xe chờ bàn giao theo HĐ {hop_dong.ma_hop_dong}",
                )

                if don_dat:
                    don_dat.trang_thai_don = 'DA_CHUYEN_HD'
                    don_dat.save(update_fields=['trang_thai_don', 'ngay_cap_nhat'])

            messages.success(
                request,
                f"Đã lập hợp đồng {hop_dong.ma_hop_dong} thành công! Vui lòng hoàn tất Biên bản xuất bãi để giao xe."
            )
            return redirect('bien_ban_xuat_bai', hop_dong_id=hop_dong.ma_hop_dong)
    else:
        form = HopDongThueCreateForm(initial={'ma_hop_dong': next_ma_hd}, don_dat=don_dat)
        form.fields['bien_so_xe'].queryset = (
            form.fields['bien_so_xe'].queryset
            .filter(ma_dong_xe__dang_kinh_doanh=True)
            .exclude(trang_thai_xe__in=['NGUNG_HOAT_DONG', 'BAO_DUONG'])
        )

    danh_sach_khach = KhachHang.objects.all().order_by('ho_ten')
    khach_hang_list_json = [
        {
            'ma_khach_hang': kh.pk,
            'ho_ten': kh.ho_ten,
            'so_dien_thoai': kh.so_dien_thoai,
            'so_cccd': kh.so_cccd or 'Chưa cập nhật',
            'giay_phep_lai_xe': kh.giay_phep_lai_xe or 'Chưa cập nhật',
            'quoc_tich': kh.quoc_tich or 'Việt Nam',
            'dia_chi': kh.dia_chi or 'Chưa cập nhật',
            'muc_tin_nhiem': getattr(kh, 'muc_tin_nhiem', 'TOT'),
            'ly_do_blacklist': getattr(kh, 'ly_do_blacklist', '') or '',
        }
        for kh in danh_sach_khach
    ]

    contract_vehicles = list(
        form.fields['bien_so_xe'].queryset.values(
            'bien_so_xe',
            'trang_thai_xe',
            'muc_nhien_lieu_pin',
            'ma_dong_xe__ten_dong_xe',
            'ma_dong_xe__don_gia_ngay',
            'ma_dong_xe__tien_coc_dinh_muc',
        )
    )

    busy_intervals = []
    for d in DonDatTruoc.objects.filter(trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO']):
        if don_dat and d.pk == don_dat.pk:
            continue
        busy_intervals.append({
            'vehicle': d.bien_so_xe_id,
            'start': timezone.localtime(d.thoi_gian_hen_nhan).strftime('%Y-%m-%dT%H:%M'),
            'end': timezone.localtime(d.thoi_gian_du_kien_tra).strftime('%Y-%m-%dT%H:%M'),
            'ref': f"Đơn {d.ma_don_dat}",
        })
    for hd in HopDongThue.objects.filter(trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE']):
        busy_intervals.append({
            'vehicle': hd.bien_so_xe_id,
            'start': timezone.localtime(hd.ngay_bat_dau).strftime('%Y-%m-%dT%H:%M'),
            'end': timezone.localtime(hd.ngay_ket_thuc_du_kien).strftime('%Y-%m-%dT%H:%M'),
            'ref': f"HĐ {hd.ma_hop_dong}",
        })

    return render(request, 'reviews/hop_dong_form.html', {
        'form': form,
        'next_ma_hd': next_ma_hd,
        'don_dat': don_dat,
        'nhan_vien_truc': nhan_vien_truc,
        'kh_dat_san': kh_dat_san,
        'danh_sach_khach': danh_sach_khach,
        'khach_hang_list_json': khach_hang_list_json,
        'contract_vehicles': contract_vehicles,
        'busy_intervals': busy_intervals,
    })


@login_required
@permission_required_vm(
    'can_manage_contracts',
    redirect_url='hop_dong_list',
    deny_message='Chỉ Nhân viên quầy hoặc Quản lý mới được phép gia hạn hợp đồng!'
)
def hop_dong_gia_han(request, pk):
    hop_dong = get_object_or_404(
        HopDongThue.objects.select_related('ma_khach_hang', 'bien_so_xe__ma_dong_xe'),
        pk=pk
    )

    if hop_dong.trang_thai_hop_dong != 'DANG_THUE':
        messages.warning(request, "Chỉ được gia hạn hợp đồng đang thuê!")
        return redirect('hop_dong_list')

    xe = hop_dong.bien_so_xe
    don_gia = hop_dong.don_gia_ap_dung or xe.ma_dong_xe.don_gia_ngay
    nhan_vien_truc = get_current_nhan_vien(request.user)

    # Kiểm tra trước xem hiện tại xe đã vướng lịch trong 24h tới chưa (BRULE-02)
    co_lich_hien_tai, ly_do_hien_tai = kiem_tra_xung_dot_dat_truoc(
        xe, hop_dong.ngay_ket_thuc_du_kien
    )

    if request.method == 'POST':
        form = GiaHanHopDongForm(hop_dong, request.POST)
        if form.is_valid():
            ngay_moi = form.cleaned_data['ngay_ket_thuc_moi']

            # Quét toàn bộ dải [hạn trả hiện tại -> ngày kết thúc mới + 24h]
            co_xung_dot, ly_do = kiem_tra_xung_dot_dat_truoc(
                xe, hop_dong.ngay_ket_thuc_du_kien, ngay_moi
            )
            if co_xung_dot:
                messages.error(request, f"Không thể gia hạn! Xe đã có lịch đặt trước: {ly_do}")
                return redirect('hop_dong_list')

            diff_seconds = (ngay_moi - hop_dong.ngay_ket_thuc_du_kien).total_seconds()
            if diff_seconds > 0:
                so_ngay_them = max(1, math.ceil((diff_seconds - 300) / 86400))
            else:
                so_ngay_them = 0

            tien_phat_sinh = so_ngay_them * don_gia

            with transaction.atomic():
                hop_dong.ngay_ket_thuc_du_kien = ngay_moi
                hop_dong.so_ngay_thue = (hop_dong.so_ngay_thue or 0) + so_ngay_them
                hop_dong.tong_tien_thanh_toan = (hop_dong.tong_tien_thanh_toan or 0) + tien_phat_sinh

                update_fields = ['ngay_ket_thuc_du_kien', 'so_ngay_thue', 'tong_tien_thanh_toan']
                ghi_chu_gh = (form.cleaned_data.get('ghi_chu_gia_han') or '').strip()
                if ghi_chu_gh:
                    prefix = f"[Gia hạn +{so_ngay_them} ngày: {ghi_chu_gh}]"
                    hop_dong.ghi_chu = f"{hop_dong.ghi_chu or ''} {prefix}".strip()
                    update_fields.append('ghi_chu')

                hop_dong.save(update_fields=update_fields)

                hinh_thuc = form.cleaned_data.get('hinh_thuc_thanh_toan', 'CHUYEN_KHOAN')
                if tien_phat_sinh > 0:
                    ThanhToan.objects.create(
                        ma_thanh_toan=f"TT-GH-{hop_dong.ma_hop_dong}-{timezone.now().strftime('%H%M%S')}",
                        ma_hop_dong=hop_dong,
                        ma_nhan_vien=nhan_vien_truc,
                        so_tien=tien_phat_sinh,
                        loai_thanh_toan='PHU_PHI',
                        hinh_thuc=hinh_thuc,
                        trang_thai='THANH_CONG',
                        thoi_gian_thanh_toan=timezone.now(),
                        ma_giao_dich=f"Gia hạn thêm {so_ngay_them} ngày"
                    )

            msg_coc = (
                " (Giữ CCCD - Miễn cọc tiền)"
                if hop_dong.hinh_thuc_dat_coc == 'GIU_CCCD'
                else f" (Tiền cọc giữ: {hop_dong.so_tien_coc_thuc_thu:,.0f}đ)"
            )
            messages.success(
                request,
                f"Gia hạn thành công HĐ {hop_dong.ma_hop_dong} thêm {so_ngay_them} ngày! "
                f"Cước thu thêm: {tien_phat_sinh:,.0f}đ{msg_coc}."
            )
            return redirect('hop_dong_list')
        else:
            first_err = next(iter(form.errors.values()))[0]
            messages.error(request, first_err)
    else:
        form = GiaHanHopDongForm(hop_dong)

    return render(request, 'reviews/hop_dong_gia_han.html', {
        'form': form,
        'hop_dong': hop_dong,
        'xe': xe,
        'han_tra_hien_tai': hop_dong.ngay_ket_thuc_du_kien,
        'don_gia': don_gia,
        'is_extension_locked': co_lich_hien_tai,
        'thong_tin_don_dat': ly_do_hien_tai,
    })


@login_required
def hop_dong_print_view(request, pk):
    hop_dong = get_object_or_404(
        HopDongThue.objects.select_related('ma_khach_hang', 'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'),
        pk=pk
    )
    thanh_toan = hop_dong.thanh_toan.filter(trang_thai='THANH_CONG').first()

    tra_cuu_url = request.build_absolute_uri(f"/hop-dong/xem-dien-tu/{hop_dong.ma_hop_dong}/")
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=160x160&data={urllib.parse.quote(tra_cuu_url)}"

    return render(request, 'reviews/hop_dong_print.html', {
        'hop_dong': hop_dong,
        'thanh_toan': thanh_toan,
        'qr_code_url': qr_code_url,
        'tra_cuu_url': tra_cuu_url,
    })


@login_required
def api_get_vehicle_pricing(request, bien_so):
    xe = get_object_or_404(PhuongTien, pk=bien_so)
    return JsonResponse({
        'don_gia_ngay': float(xe.ma_dong_xe.don_gia_ngay),
        'tien_coc_dinh_muc': float(xe.ma_dong_xe.tien_coc_dinh_muc),
    })


# ==============================================================================
# PHÂN HỆ BIÊN BẢN BÀN GIAO XE
# ==============================================================================

def _safe_int(val, default=0):
    """Ép kiểu số nguyên an toàn từ request.POST, tránh lỗi 500 khi nhập rỗng/ký tự lạ."""
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default


def _is_electric_vehicle(dong_xe):
    """Nhận diện xe điện chuẩn theo trường loai_dong_co hoặc tên dòng xe."""
    if getattr(dong_xe, 'loai_dong_co', '') == 'DIEN':
        return True
    ten_dong_lower = f"{dong_xe.ten_dong_xe or ''} {dong_xe.loai_xe or ''}".lower()
    return any(kw in ten_dong_lower for kw in ['điện', 'dien', 'vinfast', 'feliz', 'klara', 'evo', 'icone'])


@login_required
@permission_required_vm(
    'can_manage_handover',
    redirect_url='hop_dong_list',
    deny_message='Chỉ Kỹ thuật viên bãi xe hoặc Quản lý mới được lập Biên bản xuất bãi!'
)
def bien_ban_xuat_bai(request, hop_dong_id):
    hop_dong = get_object_or_404(
        HopDongThue.objects.select_related('ma_khach_hang', 'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'),
        pk=hop_dong_id
    )
    xe = hop_dong.bien_so_xe
    dong_xe = xe.ma_dong_xe
    nhan_vien_hien_tai = get_current_nhan_vien(request.user)
    is_xe_dien = _is_electric_vehicle(dong_xe)

    if hop_dong.trang_thai_hop_dong != 'CHO_BAN_GIAO':
        messages.warning(request, f"Hợp đồng {hop_dong.ma_hop_dong} không ở trạng thái Chờ bàn giao!")
        return redirect('hop_dong_list')

    ma_bb_xuat = f"BBX-{hop_dong.ma_hop_dong}"

    if request.method == 'POST':
        form = BienBanXuatBaiForm(request.POST, request.FILES, is_xe_dien=is_xe_dien)
        if form.is_valid():
            with transaction.atomic():
                bien_ban = form.save(commit=False)
                bien_ban.ma_hop_dong = hop_dong
                bien_ban.ma_bien_ban = ma_bb_xuat
                bien_ban.ma_nhan_vien = nhan_vien_hien_tai
                bien_ban.loai_bien_ban = 'XUAT'
                bien_ban.thoi_diem_thuc_hien = timezone.now()
                bien_ban.ma_token_tra_cuu = uuid.uuid4().hex[:16]

                # Lưu danh sách hình ảnh hiện trạng lúc xuất bãi (nếu có)
                uploaded_files = request.FILES.getlist('hinh_anh_xe')
                if uploaded_files:
                    bien_ban.hinh_anh_xe = uploaded_files[0]

                # Ghi nhận checklist phụ kiện bàn giao vào ghi chú
                so_mu = form.cleaned_data.get('so_mu_bao_hiem', 2)
                du_guong = "Đủ 2 gương" if form.cleaned_data.get('du_hai_guong') else "Thiếu gương"
                giay_to = "Đã giao Cavet+BH" if form.cleaned_data.get('giay_to_xe') else "Chưa giao giấy tờ"
                bo_sac = ", Kèm bộ sạc zin" if (is_xe_dien and form.cleaned_data.get('kem_bo_sac')) else ""
                phu_kien_note = f"[Phụ kiện: {so_mu} mũ BH, {du_guong}, {giay_to}{bo_sac}]"
                bien_ban.ghi_chu = f"{phu_kien_note} - {bien_ban.ghi_chu or ''}".strip(" - ")
                bien_ban.save()

                for idx, f in enumerate(uploaded_files, start=1):
                    HinhAnhBienBan.objects.create(
                        ma_bien_ban=bien_ban,
                        hinh_anh=f,
                        mo_ta=f"Ảnh xuất bãi #{idx}"
                    )

                # 1. Cập nhật ODO thực tế và khóa xe sang trạng thái Đang thuê
                trang_thai_cu = xe.trang_thai_xe
                xe.odo_hien_tai = bien_ban.so_km_odo
                xe.muc_nhien_lieu_pin = _parse_fuel_percent(bien_ban.muc_vach_xang, default=100)
                xe.trang_thai_xe = 'DANG_THUE'
                xe.save(update_fields=['odo_hien_tai', 'muc_nhien_lieu_pin', 'trang_thai_xe', 'ngay_cap_nhat'])

                NhatKyVanHanhXe.objects.create(
                    bien_so_xe=xe,
                    ma_nhan_vien=nhan_vien_hien_tai,
                    tu_trang_thai=trang_thai_cu,
                    den_trang_thai='DANG_THUE',
                    odo_ghi_nhan=xe.odo_hien_tai,
                    muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                    ghi_chu=f"Giao xe theo HĐ {hop_dong.ma_hop_dong}",
                )

                # 2. Kích hoạt hiệu lực hợp đồng (BRULE-03)
                hop_dong.trang_thai_hop_dong = 'DANG_THUE'
                hop_dong.trang_thai_thanh_toan = 'DA_THANH_TOAN_DU'
                hop_dong.save(update_fields=['trang_thai_hop_dong', 'trang_thai_thanh_toan', 'ngay_cap_nhat'])

                # 3. Ghi nhận phiếu thu tiền cước thuê xe
                hinh_thuc_tt = request.POST.get('hinh_thuc_thanh_toan') or 'CHUYEN_KHOAN'
                if hinh_thuc_tt not in ['TIEN_MAT', 'CHUYEN_KHOAN', 'THE']:
                    hinh_thuc_tt = 'CHUYEN_KHOAN'

                ThanhToan.objects.get_or_create(
                    ma_thanh_toan=f"TT-THUE-{hop_dong.ma_hop_dong}",
                    defaults={
                        'ma_hop_dong': hop_dong,
                        'ma_nhan_vien': nhan_vien_hien_tai,
                        'so_tien': hop_dong.tong_tien_thanh_toan,
                        'loai_thanh_toan': 'THANH_TOAN_CUOI',
                        'hinh_thuc': hinh_thuc_tt,
                        'trang_thai': 'THANH_CONG',
                        'thoi_gian_thanh_toan': timezone.now(),
                        'ma_giao_dich': f"Thu tiền cước thuê HĐ {hop_dong.ma_hop_dong}",
                    }
                )

            messages.success(
                request,
                f"Bàn giao xe {xe.bien_so_xe} thành công! HĐ {hop_dong.ma_hop_dong} đã có hiệu lực."
            )
            return redirect('bien_ban_detail', pk=bien_ban.ma_bien_ban)
    else:
        muc_nang_luong_mac_dinh = '100% Pin (Đầy)' if is_xe_dien else 'Đầy bình xăng'
        form = BienBanXuatBaiForm(initial={
            'ma_bien_ban': ma_bb_xuat,
            'so_km_odo': xe.odo_hien_tai or 0,
            'muc_vach_xang': muc_nang_luong_mac_dinh,
        }, is_xe_dien=is_xe_dien)

    return render(request, 'reviews/bien_ban_xuat_form.html', {
        'form': form,
        'hop_dong': hop_dong,
        'xe': xe,
        'is_xe_dien': is_xe_dien,
        'ky_thuat_vien': nhan_vien_hien_tai,
    })


@login_required
@permission_required_vm(
    'can_manage_handover',
    redirect_url='hop_dong_list',
    deny_message='Chỉ Kỹ thuật viên bãi xe hoặc Quản lý mới được nghiệm thu Biên bản trả xe!'
)
def bien_ban_tra_xe(request, hop_dong_id):
    hop_dong = get_object_or_404(
        HopDongThue.objects.select_related('ma_khach_hang', 'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'),
        pk=hop_dong_id
    )

    if hop_dong.trang_thai_hop_dong != 'DANG_THUE':
        messages.warning(request, f"Hợp đồng {hop_dong.ma_hop_dong} không ở trạng thái Đang thuê!")
        return redirect('hop_dong_list')

    nhan_vien_hien_tai = get_current_nhan_vien(request.user)
    xe = hop_dong.bien_so_xe
    dong_xe = xe.ma_dong_xe
    now = timezone.now()
    is_xe_dien = _is_electric_vehicle(dong_xe)

    ky_thuat_vien = (
        NhanVien.objects.filter(vai_tro='KY_THUAT', trang_thai='DANG_LAM').first()
        or NhanVien.objects.filter(trang_thai='DANG_LAM').first()
        or nhan_vien_hien_tai
    )

    bb_xuat = BienBanBanGiao.objects.filter(ma_hop_dong=hop_dong, loai_bien_ban='XUAT').first()
    odo_xuat = bb_xuat.so_km_odo if bb_xuat else (xe.odo_hien_tai or 0)

    if bb_xuat and bb_xuat.muc_vach_xang:
        nang_luong_xuat = bb_xuat.muc_vach_xang
    else:
        nang_luong_xuat = '100% Pin (Đầy)' if is_xe_dien else 'Đầy bình xăng'

    # Tính phụ phí trả trễ theo BRULE-04
    han_tra = hop_dong.ngay_ket_thuc_du_kien
    diff = now - han_tra
    mins_tre = max(0, int(diff.total_seconds() / 60))
    phu_phi_tre = 0
    ly_do_tre = "Trả đúng hạn"

    is_tay_ga = 'ga' in (dong_xe.loai_xe or '').lower() or any(
        k in (dong_xe.ten_dong_xe or '').lower() for k in ['lead', 'air', 'vision']
    )
    gia_gio = 30000 if (is_tay_ga or is_xe_dien) else 20000

    if mins_tre <= 30:
        phu_phi_tre = 0
        ly_do_tre = f"Trễ {mins_tre} phút (Ân hạn ≤ 30p: Miễn phí)"
    elif 30 < mins_tre <= 180:
        so_gio_tre = math.ceil(mins_tre / 60)
        phu_phi_tre = so_gio_tre * gia_gio
        ly_do_tre = f"Trễ {mins_tre} phút (~{so_gio_tre}h × {gia_gio:,.0f}đ/h)"
    else:
        so_ngay_tre = math.ceil(mins_tre / (24 * 60))
        phu_phi_tre = so_ngay_tre * int(hop_dong.don_gia_ap_dung or 0)
        ly_do_tre = f"Trễ {mins_tre} phút (Quá 3h: Tính {so_ngay_tre} ngày cước)"

    tien_coc_goc = int(hop_dong.so_tien_coc_thuc_thu or 0)
    is_giu_cccd = (hop_dong.hinh_thuc_dat_coc == 'GIU_CCCD' or tien_coc_goc == 0)

    if request.method == 'POST':
        odo_tra = _safe_int(request.POST.get('so_km_odo'), default=0)

        if odo_tra < odo_xuat:
            messages.error(
                request,
                f"Số km ODO lúc trả ({odo_tra}) không được nhỏ hơn lúc xuất bãi ({odo_xuat})!"
            )
            return redirect(request.path)

        nang_luong_tra = request.POST.get('muc_vach_xang', '')
        khau_tru_xang = 0 if is_xe_dien else _safe_int(request.POST.get('khau_tru_xang'), default=0)
        khau_tru_phu_kien = _safe_int(request.POST.get('khau_tru_phu_kien'), default=0)
        khau_tru_khac = _safe_int(request.POST.get('khau_tru_khac'), default=0)
        ly_do_khau_tru_khac = request.POST.get('ly_do_khau_tru_khac', '').strip()
        ghi_chu = request.POST.get('ghi_chu', '').strip()
        tinh_trang = request.POST.get('tinh_trang_ngoai_quan', '').strip()
        hinh_thuc_hoan = request.POST.get('hinh_thuc_hoan_coc', 'TIEN_MAT')
        if hinh_thuc_hoan not in ['TIEN_MAT', 'CHUYEN_KHOAN', 'THE']:
            hinh_thuc_hoan = 'TIEN_MAT'

        if khau_tru_khac > 0 and not ly_do_khau_tru_khac:
            messages.error(request, "Vui lòng nhập lý do phát sinh khoản chi phí khác!")
            return redirect(request.path)

        # Lấy danh sách file ảnh tải lên lúc trả xe
        uploaded_files = request.FILES.getlist('hinh_anh_xe')

        tong_khau_tru = phu_phi_tre + khau_tru_xang + khau_tru_phu_kien + khau_tru_khac

        if is_giu_cccd:
            tien_hoan_coc = 0
            tien_khach_phai_tra_them = tong_khau_tru
        else:
            tien_hoan_coc = max(0, tien_coc_goc - tong_khau_tru)
            tien_khach_phai_tra_them = max(0, tong_khau_tru - tien_coc_goc)

        ma_bb_tra = f"BBT-{hop_dong.ma_hop_dong}"
        ghi_chu_nl = f"Pin lúc trả: {nang_luong_tra}" if is_xe_dien else f"Bù xăng: {khau_tru_xang:,.0f}đ"
        chi_tiet_khac = f"{khau_tru_khac:,.0f}đ ({ly_do_khau_tru_khac})" if khau_tru_khac > 0 else "0đ"

        with transaction.atomic():
            defaults_bb = {
                'ma_hop_dong': hop_dong,
                'ma_nhan_vien': nhan_vien_hien_tai,
                'thoi_diem_thuc_hien': now,
                'so_km_odo': odo_tra,
                'muc_vach_xang': nang_luong_tra,
                'tinh_trang_ngoai_quan': tinh_trang,
                'phu_phi_tre_gio': phu_phi_tre,
                'tien_hoan_coc': tien_hoan_coc,
                'loai_bien_ban': 'TRA',
                'ghi_chu': f"[{ghi_chu_nl}, Phụ kiện: {khau_tru_phu_kien:,.0f}đ, Khác: {chi_tiet_khac}] - {ghi_chu}".strip(" - "),
                'ma_token_tra_cuu': uuid.uuid4().hex[:16],
            }
            if uploaded_files:
                defaults_bb['hinh_anh_xe'] = uploaded_files[0]

            bien_ban_tra, _ = BienBanBanGiao.objects.update_or_create(
                ma_bien_ban=ma_bb_tra,
                defaults=defaults_bb,
            )

            if uploaded_files:
                bien_ban_tra.hinh_anh_list.all().delete()
                for idx, f in enumerate(uploaded_files, start=1):
                    HinhAnhBienBan.objects.create(
                        ma_bien_ban=bien_ban_tra,
                        hinh_anh=f,
                        mo_ta=f"Ảnh thu hồi xe #{idx}",
                    )

            # 1. Cập nhật ODO, mức nhiên liệu/pin & tình trạng thực tế của xe
            km_chay_dot_nay = max(0, odo_tra - odo_xuat)
            trang_thai_cu = xe.trang_thai_xe
            xe.odo_hien_tai = odo_tra
            xe.odo_luy_ke_bao_duong = (xe.odo_luy_ke_bao_duong or 0) + km_chay_dot_nay
            xe.muc_nhien_lieu_pin = _parse_fuel_percent(nang_luong_tra, default=xe.muc_nhien_lieu_pin)
            if tinh_trang:
                xe.ghi_chu_tinh_trang = tinh_trang

            can_bao_duong = xe.odo_luy_ke_bao_duong >= 2000
            xe.trang_thai_xe = 'BAO_DUONG' if can_bao_duong else 'CHO_VE_SINH'

            xe.save(update_fields=[
                'odo_hien_tai', 'odo_luy_ke_bao_duong', 'muc_nhien_lieu_pin',
                'ghi_chu_tinh_trang', 'trang_thai_xe', 'ngay_cap_nhat'
            ])

            # Ghi 1 bản ghi nhật ký vận hành duy nhất cho sự kiện thu hồi xe
            NhatKyVanHanhXe.objects.create(
                bien_so_xe=xe,
                ma_nhan_vien=nhan_vien_hien_tai,
                tu_trang_thai=trang_thai_cu,
                den_trang_thai=xe.trang_thai_xe,
                odo_ghi_nhan=xe.odo_hien_tai,
                muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                ghi_chu=f"Khách trả xe HĐ {hop_dong.ma_hop_dong}",
            )

            # Nếu chạm ngưỡng >= 2.000 km thì lập phiếu bảo dưỡng định kỳ (do xe đã ở BAO_DUONG nên model save() sẽ không tạo trùng log)
            if can_bao_duong:
                ma_phieu = f"BD-{xe.bien_so_xe}-{now.strftime('%Y%m%d%H%M')}"
                NhatKyBaoDuong.objects.create(
                    ma_phieu_bao_duong=ma_phieu,
                    bien_so_xe=xe,
                    ma_nhan_vien=ky_thuat_vien,
                    ngay_bao_duong=now.date(),
                    loai_bao_duong='DINH_KY',
                    reset_odo_luy_ke=True,
                    noi_dung=f"Tự động tạo do ODO lũy kế đạt {xe.odo_luy_ke_bao_duong} km (≥ 2.000 km)",
                    odo_luc_bao_duong=odo_tra,
                    trang_thai='DANG_XU_LY'
                )
                msg_xe = f"Xe {xe.bien_so_xe} đạt {xe.odo_luy_ke_bao_duong} km → Khóa BẢO DƯỠNG (Phiếu {ma_phieu})."
            else:
                msg_xe = f"Xe {xe.bien_so_xe} đã thu hồi → Chuyển trạng thái Chờ rửa xe / Sạc pin."

            # 2. Đóng hợp đồng & cập nhật hạng uy tín khách nếu phát sinh khấu trừ vi phạm
            hop_dong.ngay_ket_thuc_thuc_te = now
            hop_dong.phu_phi = tong_khau_tru
            hop_dong.trang_thai_hop_dong = 'DA_TRA'
            hop_dong.trang_thai_thanh_toan = 'DA_THANH_TOAN_DU'
            hop_dong.save(update_fields=[
                'ngay_ket_thuc_thuc_te', 'phu_phi', 'trang_thai_hop_dong', 'trang_thai_thanh_toan', 'ngay_cap_nhat'
            ])

            if tong_khau_tru > 0:
                khach = hop_dong.ma_khach_hang
                if khach.muc_tin_nhiem == 'TOT':
                    khach.muc_tin_nhiem = 'CAN_LUU_Y'
                    khach.save(update_fields=['muc_tin_nhiem', 'ngay_cap_nhat'])

            # 3. Ghi nhận giao dịch hoàn cọc hoặc thu phụ phí
            if tien_hoan_coc > 0:
                ThanhToan.objects.create(
                    ma_thanh_toan=f"TT-HC-{hop_dong.ma_hop_dong}",
                    ma_hop_dong=hop_dong,
                    ma_nhan_vien=nhan_vien_hien_tai,
                    so_tien=tien_hoan_coc,
                    loai_thanh_toan='HOAN_COC',
                    hinh_thuc=hinh_thuc_hoan,
                    trang_thai='THANH_CONG',
                    thoi_gian_thanh_toan=now,
                    ma_giao_dich=f"Hoàn cọc xe {xe.bien_so_xe} (đã trừ phụ phí {tong_khau_tru:,.0f}đ)"
                )
            elif tien_khach_phai_tra_them > 0:
                ThanhToan.objects.create(
                    ma_thanh_toan=f"TT-PHU-{hop_dong.ma_hop_dong}",
                    ma_hop_dong=hop_dong,
                    ma_nhan_vien=nhan_vien_hien_tai,
                    so_tien=tien_khach_phai_tra_them,
                    loai_thanh_toan='PHU_PHI',
                    hinh_thuc=hinh_thuc_hoan,
                    trang_thai='THANH_CONG',
                    thoi_gian_thanh_toan=now,
                    ma_giao_dich=f"Thu thêm phụ phí HĐ {hop_dong.ma_hop_dong}"
                )

        messages.success(request, f"Nghiệm thu thu hồi xe thành công! {msg_xe}")
        return redirect('bien_ban_detail', pk=ma_bb_tra)

    return render(request, 'reviews/bien_ban_tra_form.html', {
        'hop_dong': hop_dong,
        'xe': xe,
        'is_xe_dien': is_xe_dien,
        'bb_xuat': bb_xuat,
        'odo_xuat': odo_xuat,
        'xang_xuat': nang_luong_xuat,
        'ky_thuat_vien': nhan_vien_hien_tai,
        'phu_phi_tre': phu_phi_tre,
        'mins_tre': mins_tre,
        'ly_do_tre': ly_do_tre,
        'tien_coc_goc': tien_coc_goc,
        'is_giu_cccd': is_giu_cccd,
        'ma_bb_tra': f"BBT-{hop_dong.ma_hop_dong}",
    })


@login_required
def bien_ban_detail(request, pk):
    bien_ban = get_object_or_404(
        BienBanBanGiao.objects.select_related(
            'ma_nhan_vien', 'ma_hop_dong__ma_khach_hang', 'ma_hop_dong__bien_so_xe__ma_dong_xe'
        ).prefetch_related('hinh_anh_list'),
        pk=pk
    )
    hop_dong = bien_ban.ma_hop_dong
    xe = hop_dong.bien_so_xe

    token = bien_ban.ma_token_tra_cuu or bien_ban.ma_bien_ban
    tra_cuu_url = request.build_absolute_uri(f"/bien-ban/tra-cuu/{token}/")
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=160x160&data={urllib.parse.quote(tra_cuu_url)}"

    danh_sach_anh = [
        item.hinh_anh.url
        for item in bien_ban.hinh_anh_list.all()
        if item.hinh_anh
    ]
    if not danh_sach_anh and bien_ban.hinh_anh_xe:
        try:
            danh_sach_anh = [bien_ban.hinh_anh_xe.url]
        except ValueError:
            pass

    return render(request, 'reviews/bien_ban_detail.html', {
        'bien_ban': bien_ban,
        'hop_dong': hop_dong,
        'xe': xe,
        'qr_code_url': qr_code_url,
        'tra_cuu_url': tra_cuu_url,
        'danh_sach_anh': danh_sach_anh,
    })


def bien_ban_public_view(request, token):
    bien_ban = get_object_or_404(
        BienBanBanGiao.objects.select_related(
            'ma_hop_dong__ma_khach_hang', 'ma_hop_dong__bien_so_xe__ma_dong_xe'
        ).prefetch_related('hinh_anh_list'),
        ma_token_tra_cuu=token
    )
    danh_sach_anh = [item.hinh_anh.url for item in bien_ban.hinh_anh_list.all() if item.hinh_anh]
    if not danh_sach_anh and bien_ban.hinh_anh_xe:
        try:
            danh_sach_anh = [bien_ban.hinh_anh_xe.url]
        except ValueError:
            pass
    return render(request, 'reviews/bien_ban_public_view.html', {
        'bien_ban': bien_ban,
        'hop_dong': bien_ban.ma_hop_dong,
        'danh_sach_anh': danh_sach_anh,
    })


# ============================================================
# PHÂN HỆ THỐNG KÊ TỔNG QUAN / BÁO CÁO
# ============================================================

def get_analytics_data():
    try:
        _expire_unconfirmed_bookings()
    except Exception:
        pass

    today = timezone.localdate()
    now = timezone.now()
    models_used = (
        DongXe, PhuongTien, NhanVien, KhachHang, DonDatTruoc,
        HopDongThue, ThanhToan, BienBanBanGiao, NhatKyBaoDuong,
    )

    def format_money(value):
        return f"{int(value or 0):,}".replace(",", ".")

    def total_amount(queryset):
        return queryset.aggregate(total=Sum("so_tien"))["total"] or 0

    existing_tables = set(connection.introspection.table_names())
    if not all(model._meta.db_table in existing_tables for model in models_used):
        blank_chart = [
            {
                "ngay": (today - timedelta(days=i)).strftime("%d/%m"),
                "so_tien": 0,
                "so_tien_text": "0",
                "chieu_cao": 0,
            }
            for i in range(6, -1, -1)
        ]
        return {
            "nguon_du_lieu": "CHUA_MIGRATE",
            "tong_quan": {
                "tong_xe": 0, "xe_con_trong": 0, "xe_dang_thue": 0,
                "xe_cho_ve_sinh": 0, "xe_bao_duong": 0,
                "don_giu_cho_24h": 0, "hop_dong_dang_thue": 0,
                "hop_dong_sap_het_han": 0, "bao_duong_dang_xu_ly": 0,
                "hop_dong_qua_han": 0, "giao_hom_nay": 0, "tra_hom_nay": 0,
                "xe_canh_bao_bao_duong": 0, "cong_viec": [],
                "doanh_thu_hom_nay_text": "0",
                "tien_coc_dang_giu_text": "0",
                "ty_le_khai_thac": 0,
            },
            "bao_cao": {
                "tong_xe": 0, "tong_hop_dong": 0,
                "hop_dong_dang_thue": 0, "hop_dong_hoan_tat": 0,
                "tong_don_dat": 0, "don_cho_xac_nhan": 0,
                "doanh_thu": 0, "doanh_thu_text": "0",
                "tien_coc": 0, "tien_coc_text": "0",
                "phu_phi": 0, "phu_phi_text": "0",
                "ty_le_khai_thac": 0, "bieu_do_7_ngay": blank_chart,
                "trang_thai_xe": [], "loai_xe": [], "nhan_vien": [],
            },
        }

    # 1. Phương tiện - Chỉ tính đội xe đang kinh doanh (loại trừ NGUNG_HOAT_DONG)
    active_vehicles_qs = PhuongTien.objects.exclude(trang_thai_xe="NGUNG_HOAT_DONG")
    tong_xe = active_vehicles_qs.count()
    counts = dict(
        active_vehicles_qs.values("trang_thai_xe")
        .annotate(n=Count("bien_so_xe"))
        .values_list("trang_thai_xe", "n")
    )
    xe_con_trong = counts.get("CON_TRONG", 0)
    xe_dang_thue = counts.get("DANG_THUE", 0)
    xe_cho_ve_sinh = counts.get("CHO_VE_SINH", 0)
    xe_bao_duong = counts.get("BAO_DUONG", 0)
    ty_le_dang_thue = round(100 * xe_dang_thue / tong_xe, 1) if tong_xe else 0

    trang_thai_xe = [
        {
            "ten": label,
            "so_luong": quantity,
            "ty_le": round(100 * quantity / tong_xe, 1) if tong_xe else 0,
        }
        for label, quantity in (
            ("Còn trống", xe_con_trong),
            ("Đang thuê", xe_dang_thue),
            ("Chờ rửa/Sạc pin", xe_cho_ve_sinh),
            ("Bảo dưỡng", xe_bao_duong),
        )
    ]

    # 2. Đơn đặt trước, hợp đồng & bảo dưỡng
    due_until = now + timedelta(hours=24)

    tong_don_dat = DonDatTruoc.objects.count()
    don_giu_cho_qs = DonDatTruoc.objects.filter(
        trang_thai_don__in=["DA_GIU_CHO", "CHO_XAC_NHAN"]
    ).select_related("ma_khach_hang", "bien_so_xe")
    don_giu_cho_24h_qs = don_giu_cho_qs.filter(
        thoi_gian_hen_nhan__gte=now - timedelta(hours=2),
        thoi_gian_hen_nhan__lte=due_until,
    )
    don_giu_cho_24h = don_giu_cho_24h_qs.count()

    tong_hop_dong = HopDongThue.objects.count()
    hop_dong_dang_thue_qs = HopDongThue.objects.filter(
        trang_thai_hop_dong="DANG_THUE"
    ).select_related("ma_khach_hang", "bien_so_xe")
    hop_dong_dang_thue = hop_dong_dang_thue_qs.count()
    hop_dong_qua_han = hop_dong_dang_thue_qs.filter(ngay_ket_thuc_du_kien__lt=now).count()
    hop_dong_hoan_tat = HopDongThue.objects.filter(trang_thai_hop_dong="DA_TRA").count()

    hop_dong_sap_het_han = hop_dong_dang_thue_qs.filter(
        ngay_ket_thuc_du_kien__gte=now,
        ngay_ket_thuc_du_kien__lte=due_until,
    ).count()

    bao_duong_dang_xu_ly = NhatKyBaoDuong.objects.filter(trang_thai="DANG_XU_LY").count()
    xe_canh_bao_bao_duong = active_vehicles_qs.filter(
        odo_luy_ke_bao_duong__gte=1800,
        odo_luy_ke_bao_duong__lt=2000,
    ).exclude(trang_thai_xe="BAO_DUONG").count()

    cho_ban_giao_qs = HopDongThue.objects.filter(
        trang_thai_hop_dong="CHO_BAN_GIAO"
    ).select_related("ma_khach_hang", "bien_so_xe")
    giao_hom_nay = cho_ban_giao_qs.count()
    tra_hom_nay = hop_dong_dang_thue_qs.filter(ngay_ket_thuc_du_kien__date=today).count()

    # 3. Doanh thu thực thu & Quỹ tiền cọc
    payments_ok = ThanhToan.objects.filter(trang_thai="THANH_CONG")
    revenue_payments = payments_ok.filter(
        Q(loai_thanh_toan="PHU_PHI") | Q(loai_thanh_toan="THANH_TOAN_CUOI")
    ).exclude(ma_giao_dich__icontains="Hoàn cọc")

    paid_final = total_amount(revenue_payments.filter(loai_thanh_toan="THANH_TOAN_CUOI"))
    paid_extra = total_amount(revenue_payments.filter(loai_thanh_toan="PHU_PHI"))
    paid_coc_type = total_amount(payments_ok.filter(loai_thanh_toan="COC"))
    amount_display = paid_final + paid_extra

    doanh_thu_hom_nay = total_amount(
        revenue_payments.filter(thoi_gian_thanh_toan__date=today)
    )
    tien_coc_dang_giu = (
        HopDongThue.objects.filter(
            trang_thai_hop_dong__in=["CHO_BAN_GIAO", "DANG_THUE"],
            hinh_thuc_dat_coc="TIEN_MAT",
        ).aggregate(total=Sum("so_tien_coc_thuc_thu"))["total"] or 0
    )

    # 4. Biểu đồ doanh thu 7 ngày gần nhất
    since = today - timedelta(days=6)
    daily_rows = (
        revenue_payments.filter(thoi_gian_thanh_toan__date__range=(since, today))
        .annotate(day=TruncDate("thoi_gian_thanh_toan"))
        .values("day")
        .annotate(amount=Sum("so_tien"))
    )
    amount_by_day = {r["day"]: r["amount"] or 0 for r in daily_rows}
    bieu_do_7_ngay = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        money = amount_by_day.get(day, 0)
        bieu_do_7_ngay.append({
            "ngay": day.strftime("%d/%m"),
            "so_tien": float(money),
            "so_tien_text": format_money(money),
        })
    max_amount = max((p["so_tien"] for p in bieu_do_7_ngay), default=0)
    for point in bieu_do_7_ngay:
        point["chieu_cao"] = round(point["so_tien"] * 100 / max_amount) if max_amount else 0

    # 5. Phân bổ xe theo loại & Nhân viên
    loai_xe = [
        {
            "ten": row["ma_dong_xe__loai_xe"] or "Chưa phân loại",
            "so_luong": row["so_luong"],
            "dang_thue": row["dang_thue"],
            "chua_dang_thue": row["so_luong"] - row["dang_thue"],
        }
        for row in active_vehicles_qs.values("ma_dong_xe__loai_xe")
        .annotate(
            so_luong=Count("bien_so_xe"),
            dang_thue=Count("bien_so_xe", filter=Q(trang_thai_xe="DANG_THUE")),
        )
        .order_by("ma_dong_xe__loai_xe")
    ]

    nhan_vien = [
        {
            "ten": row["ma_nhan_vien__ho_ten"] or "Chưa xác định",
            "so_giao_dich": row["so_giao_dich"],
            "so_tien_text": format_money(row["tong"]),
        }
        for row in revenue_payments.values("ma_nhan_vien__ho_ten")
        .annotate(so_giao_dich=Count("ma_thanh_toan"), tong=Sum("so_tien"))
        .order_by("-tong")
    ]

    # 6. Danh sách việc cần xử lý
    cong_viec = []

    # Ưu tiên 1: Hợp đồng quá hạn trả
    for contract in hop_dong_dang_thue_qs.filter(ngay_ket_thuc_du_kien__lt=now).order_by("ngay_ket_thuc_du_kien"):
        han_tra = timezone.localtime(contract.ngay_ket_thuc_du_kien).strftime("%H:%M %d/%m")
        cong_viec.append({
            "ma": contract.ma_hop_dong,
            "nhan": "Quá hạn trả",
            "badge_class": "bg-danger-subtle text-danger border-danger-subtle",
            "noi_dung": f"Quá hạn trả xe ({contract.bien_so_xe.bien_so_xe})",
            "ghi_chu": f"Khách {contract.ma_khach_hang.ho_ten} · Hạn trả: {han_tra}",
            "url": f"{reverse('hop_dong_list')}?trang_thai=QUA_HAN&q={contract.ma_hop_dong}",
        })

    # Ưu tiên 2: Chờ bàn giao xe tại quầy
    for contract in cho_ban_giao_qs.order_by("ngay_bat_dau"):
        gio_nhan = timezone.localtime(contract.ngay_bat_dau).strftime("%H:%M %d/%m")
        cong_viec.append({
            "ma": contract.ma_hop_dong,
            "nhan": "Chờ xuất bãi",
            "badge_class": "bg-info-subtle text-info-emphasis border-info-subtle",
            "noi_dung": f"Lập biên bản xuất bãi ({contract.bien_so_xe.bien_so_xe})",
            "ghi_chu": f"Khách {contract.ma_khach_hang.ho_ten} · Hẹn nhận {gio_nhan}",
            "url": reverse("bien_ban_xuat_bai", kwargs={"hop_dong_id": contract.ma_hop_dong}),
        })

    # Ưu tiên 3: Đơn đặt giữ chỗ sắp đến giờ nhận (trong 24h tới)
    for booking in don_giu_cho_24h_qs.order_by("thoi_gian_hen_nhan"):
        gio_hen = timezone.localtime(booking.thoi_gian_hen_nhan).strftime("%H:%M %d/%m")
        cong_viec.append({
            "ma": booking.ma_don_dat,
            "nhan": "Đơn đặt sắp tới",
            "badge_class": "bg-primary-subtle text-primary border-primary-subtle",
            "noi_dung": f"Chuẩn bị xe giao khách đặt trước ({booking.bien_so_xe.bien_so_xe})",
            "ghi_chu": f"Khách {booking.ma_khach_hang.ho_ten} · Hẹn nhận {gio_hen}",
            "url": f"{reverse('booking_list')}?q={booking.ma_don_dat}",
        })

    # Ưu tiên 4: Hợp đồng sắp hết hạn trả (trong 24h tới)
    for contract in hop_dong_dang_thue_qs.filter(
        ngay_ket_thuc_du_kien__gte=now,
        ngay_ket_thuc_du_kien__lte=due_until,
    ).order_by("ngay_ket_thuc_du_kien"):
        han_tra = timezone.localtime(contract.ngay_ket_thuc_du_kien).strftime("%H:%M %d/%m")
        cong_viec.append({
            "ma": contract.ma_hop_dong,
            "nhan": "Sắp đến hạn trả",
            "badge_class": "bg-warning-subtle text-warning-emphasis border-warning-subtle",
            "noi_dung": f"Nhắc hẹn trả xe ({contract.bien_so_xe.bien_so_xe})",
            "ghi_chu": f"Khách {contract.ma_khach_hang.ho_ten} · Đến hạn lúc {han_tra}",
            "url": f"{reverse('hop_dong_list')}?trang_thai=SAP_HET_HAN&q={contract.ma_hop_dong}",
        })

    # Ưu tiên 5: Xe đang bảo dưỡng tại xưởng hoặc cảnh báo sắp tới hạn BD (1.800 - 2.000 km)
    for xe in active_vehicles_qs.filter(
        Q(trang_thai_xe="BAO_DUONG") | Q(odo_luy_ke_bao_duong__gte=1800)
    ):
        is_in_shop = xe.trang_thai_xe == "BAO_DUONG" or xe.odo_luy_ke_bao_duong >= 2000
        cong_viec.append({
            "ma": xe.bien_so_xe,
            "nhan": "Đang bảo dưỡng" if is_in_shop else "Sắp tới hạn BD",
            "badge_class": "bg-danger-subtle text-danger border-danger-subtle" if is_in_shop else "bg-warning-subtle text-warning-emphasis border-warning-subtle",
            "noi_dung": "Xe đang nằm xưởng bảo dưỡng kỹ thuật" if is_in_shop else "Cảnh báo bảo dưỡng định kỳ dự phòng",
            "ghi_chu": f"ODO lũy kế: {xe.odo_luy_ke_bao_duong:,} / 2.000 km",
            "url": f"{reverse('vehicle_list')}?tab=maintenance&plate={xe.bien_so_xe}&open_maint=1",
        })

    # Ưu tiên 6: Xe chờ rửa xe / sạc pin tại bãi
    for xe in active_vehicles_qs.filter(trang_thai_xe="CHO_VE_SINH"):
        cong_viec.append({
            "ma": xe.bien_so_xe,
            "nhan": "Chờ rửa/Sạc pin",
            "badge_class": "bg-warning-subtle text-warning-emphasis border-warning-subtle",
            "noi_dung": f"Xe chờ vệ sinh / sạc đầy ({xe.muc_nhien_lieu_pin}%)",
            "ghi_chu": xe.ghi_chu_tinh_trang or "Xác nhận sẵn sàng tại bãi sau khi hoàn tất",
            "url": f"{reverse('vehicle_list')}?status=CHO_VE_SINH",
        })

    # Ưu tiên 7: Xe hết hạn hoặc sắp hết hạn bảo hiểm TNDS (trong 15 ngày tới)
    han_bh_canh_bao = today + timedelta(days=15)
    xe_canh_bao_bh_qs = active_vehicles_qs.filter(
        Q(han_bao_hiem__isnull=True) | Q(han_bao_hiem__lte=han_bh_canh_bao)
    )
    for xe in xe_canh_bao_bh_qs:
        if not xe.han_bao_hiem:
            ghi_chu_bh = "Chưa cập nhật ngày hết hạn bảo hiểm"
        elif xe.han_bao_hiem < today:
            ghi_chu_bh = f"Đã hết hạn ngày {xe.han_bao_hiem.strftime('%d/%m/%Y')}"
        else:
            ghi_chu_bh = f"Sắp hết hạn ngày {xe.han_bao_hiem.strftime('%d/%m/%Y')}"

        cong_viec.append({
            "ma": xe.bien_so_xe,
            "nhan": "Bảo hiểm xe",
            "badge_class": "bg-secondary-subtle text-secondary-emphasis border-secondary-subtle",
            "noi_dung": f"Kiểm tra bảo hiểm TNDS ({xe.bien_so_xe})",
            "ghi_chu": ghi_chu_bh,
            "url": f"{reverse('vehicle_list')}?q={xe.bien_so_xe}",
        })

    return {
        "nguon_du_lieu": "DATABASE",
        "tong_quan": {
            "tong_xe": tong_xe,
            "xe_con_trong": xe_con_trong,
            "xe_dang_thue": xe_dang_thue,
            "xe_cho_ve_sinh": xe_cho_ve_sinh,
            "xe_bao_duong": xe_bao_duong,
            "xe_canh_bao_bao_hiem": xe_canh_bao_bh_qs.count(),
            "don_giu_cho_24h": don_giu_cho_24h,
            "hop_dong_dang_thue": hop_dong_dang_thue,
            "hop_dong_sap_het_han": hop_dong_sap_het_han,
            "bao_duong_dang_xu_ly": bao_duong_dang_xu_ly,
            "xe_canh_bao_bao_duong": xe_canh_bao_bao_duong,
            "cong_viec": cong_viec,
            "hop_dong_qua_han": hop_dong_qua_han,
            "giao_hom_nay": giao_hom_nay,
            "tra_hom_nay": tra_hom_nay,
            "doanh_thu_hom_nay_text": format_money(doanh_thu_hom_nay),
            "tien_coc_dang_giu_text": format_money(tien_coc_dang_giu),
            "ty_le_khai_thac": ty_le_dang_thue,
        },
        "bao_cao": {
            "tong_xe": tong_xe,
            "tong_hop_dong": tong_hop_dong,
            "hop_dong_dang_thue": hop_dong_dang_thue,
            "hop_dong_hoan_tat": hop_dong_hoan_tat,
            "tong_don_dat": tong_don_dat,
            "don_cho_xac_nhan": don_giu_cho_24h,
            "doanh_thu": float(amount_display),
            "doanh_thu_text": format_money(amount_display),
            "tien_coc": float(paid_coc_type),
            "tien_coc_text": format_money(paid_coc_type),
            "phu_phi": float(paid_extra),
            "phu_phi_text": format_money(paid_extra),
            "ty_le_khai_thac": ty_le_dang_thue,
            "bieu_do_7_ngay": bieu_do_7_ngay,
            "trang_thai_xe": trang_thai_xe,
            "loai_xe": loai_xe,
            "nhan_vien": nhan_vien,
        },
    }


@login_required
def tong_quan(request):
    data = get_analytics_data()
    tq_data = data["tong_quan"]

    paginator = Paginator(tq_data.get("cong_viec", []), 7)
    page_number = request.GET.get("page")
    cong_viec_page = paginator.get_page(page_number)

    return render(
        request,
        "reviews/tong_quan.html",
        {
            "tong_quan": tq_data,
            "cong_viec_page": cong_viec_page,
            "nguon_du_lieu": data["nguon_du_lieu"],
            "active_page": "tong_quan",
        },
    )


@login_required
def api_tong_quan(request):
    data = get_analytics_data()
    return JsonResponse({
        "nguon_du_lieu": data["nguon_du_lieu"],
        "tong_quan": data["tong_quan"],
    })


@login_required
@permission_required_vm(
    'can_view_reports',
    redirect_url='tong_quan',
    deny_message='Kỹ thuật viên không có quyền truy cập trang Báo cáo thống kê!'
)
def bao_cao(request):
    import datetime as dt_module
    from django.utils.dateparse import parse_date
    from .models import HopDongThue, ThanhToan, NhatKyBaoDuong, DongXe

    def format_money(value):
        return f"{int(round(value or 0)):,}".replace(",", ".")

    tu_ngay_str = (request.GET.get("tu_ngay") or "").strip()
    den_ngay_str = (request.GET.get("den_ngay") or "").strip()
    trang_thai_loc = (request.GET.get("trang_thai") or "").strip()
    dong_xe_loc = (request.GET.get("dong_xe") or "").strip()

    d_tu = parse_date(tu_ngay_str) if tu_ngay_str else None
    d_den = parse_date(den_ngay_str) if den_ngay_str else None

    hd_qs = HopDongThue.objects.select_related(
        "ma_khach_hang", "bien_so_xe", "bien_so_xe__ma_dong_xe"
    ).order_by("-ngay_bat_dau")

    if d_tu:
        dt_tu = dt_module.datetime.combine(d_tu, dt_module.time.min)
        if timezone.is_naive(dt_tu) and getattr(timezone, "get_current_timezone", None):
            try:
                dt_tu = timezone.make_aware(dt_tu)
            except Exception:
                pass
        hd_qs = hd_qs.filter(ngay_bat_dau__gte=dt_tu)

    if d_den:
        dt_den = dt_module.datetime.combine(d_den, dt_module.time.max)
        if timezone.is_naive(dt_den) and getattr(timezone, "get_current_timezone", None):
            try:
                dt_den = timezone.make_aware(dt_den)
            except Exception:
                pass
        hd_qs = hd_qs.filter(ngay_bat_dau__lte=dt_den)

    if trang_thai_loc:
        hd_qs = hd_qs.filter(trang_thai_hop_dong=trang_thai_loc)

    if dong_xe_loc:
        hd_qs = hd_qs.filter(bien_so_xe__ma_dong_xe__ten_dong_xe=dong_xe_loc)

    hd_ids = list(hd_qs.values_list("ma_hop_dong", flat=True))

    tt_qs = ThanhToan.objects.filter(
        ma_hop_dong_id__in=hd_ids,
        trang_thai="THANH_CONG",
    )

    tt_by_hd = defaultdict(lambda: {"coc": 0, "cuoi": 0, "phu_phi": 0, "hoan_coc": 0})
    tong_tien_coc_thu = 0
    tong_hoan_coc = 0

    for tt in tt_qs:
        hid = tt.ma_hop_dong_id
        so_tien = int(tt.so_tien or 0)
        loai = tt.loai_thanh_toan or ""
        ma_gd = (tt.ma_giao_dich or "").lower()

        if loai == "HOAN_COC" or "hoàn cọc" in ma_gd or so_tien < 0:
            amt = abs(so_tien)
            tong_hoan_coc += amt
            tt_by_hd[hid]["hoan_coc"] += amt
        elif loai == "COC":
            tong_tien_coc_thu += so_tien
            tt_by_hd[hid]["coc"] += so_tien
        elif loai == "THANH_TOAN_CUOI":
            tt_by_hd[hid]["cuoi"] += so_tien
        elif loai == "PHU_PHI":
            tt_by_hd[hid]["phu_phi"] += so_tien

    danh_sach = []
    tong_doanh_thu_thuc = 0

    for hd in hd_qs:
        ten_dong = (
            hd.bien_so_xe.ma_dong_xe.ten_dong_xe
            if hd.bien_so_xe and hd.bien_so_xe.ma_dong_xe
            else "Chưa xác định"
        )
        phu_phi = int(hd.phu_phi or 0)
        so_ngay = hd.so_ngay_thue or 1
        tien_thue = (
            int(hd.tong_tien_thanh_toan)
            if hd.tong_tien_thanh_toan is not None
            else int((hd.don_gia_ap_dung or 0) * so_ngay)
        )
        gia_tri_hd = tien_thue + phu_phi

        info_tt = tt_by_hd[hd.ma_hop_dong]
        doanh_thu_thuc = info_tt["cuoi"] + info_tt["phu_phi"]
        tong_doanh_thu_thuc += doanh_thu_thuc

        danh_sach.append({
            "ma_hd": hd.ma_hop_dong,
            "dong_xe": ten_dong,
            "trang_thai_ma": hd.trang_thai_hop_dong,
            "tien_thue": tien_thue,
            "phu_phi": phu_phi,
            "gia_tri_hd": gia_tri_hd,
            "doanh_thu_thuc": doanh_thu_thuc,
        })

    bd_qs = NhatKyBaoDuong.objects.filter(trang_thai="HOAN_THANH")
    if d_tu:
        bd_qs = bd_qs.filter(ngay_bao_duong__gte=d_tu)
    if d_den:
        bd_qs = bd_qs.filter(ngay_bao_duong__lte=d_den)
    if dong_xe_loc:
        bd_qs = bd_qs.filter(bien_so_xe__ma_dong_xe__ten_dong_xe=dong_xe_loc)

    tong_chi_phi_bd = int(bd_qs.aggregate(total=Sum("chi_phi"))["total"] or 0)
    loi_nhuan_rong = tong_doanh_thu_thuc - tong_chi_phi_bd

    ds_dong_xe = list(
        DongXe.objects.order_by("ten_dong_xe")
        .values_list("ten_dong_xe", flat=True)
        .distinct()
    )

    bang_bao_cao = {
        "tu_ngay": tu_ngay_str,
        "den_ngay": den_ngay_str,
        "trang_thai_loc": trang_thai_loc,
        "dong_xe_loc": dong_xe_loc,
        "ds_dong_xe": ds_dong_xe,
        "danh_sach": danh_sach,
        "tong_tien_coc_thu": format_money(tong_tien_coc_thu),
        "tong_hoan_coc": format_money(tong_hoan_coc),
        "tong_chi_phi_bd": format_money(tong_chi_phi_bd),
        "tong_chi_phi_bd_raw": tong_chi_phi_bd,
        "loi_nhuan_rong": format_money(loi_nhuan_rong),
    }

    if not has_permission(request.user, 'can_view_profit'):
        bang_bao_cao["tong_chi_phi_bd"] = None
        bang_bao_cao["tong_chi_phi_bd_raw"] = None
        bang_bao_cao["loi_nhuan_rong"] = None

    return render(
        request,
        "reviews/bao_cao.html",
        {
            "bang_bao_cao": bang_bao_cao,
            "nguon_du_lieu": "DATABASE",
            "active_page": "bao_cao",
        },
    )


@login_required
@permission_required_vm(
    'can_view_reports',
    redirect_url='tong_quan',
    deny_message='Bạn không có quyền truy cập dữ liệu báo cáo!'
)
def api_bao_cao(request):
    data = get_analytics_data()
    return JsonResponse({
        "nguon_du_lieu": data["nguon_du_lieu"],
        "bao_cao": data["bao_cao"],
    })


# ==============================================================================
# PHÂN HỆ ĐẶT XE TRƯỚC
# ==============================================================================

def get_current_nhan_vien(user):
    """Lấy đối tượng NhanVien tương ứng với User đang đăng nhập."""
    if not user.is_authenticated:
        return None

    nhan_vien = getattr(user, 'nhanvien', None)
    if nhan_vien:
        return nhan_vien

    nhan_vien = NhanVien.objects.filter(ten_dang_nhap=user.username).first()
    if nhan_vien:
        return nhan_vien

    ho_ten = user.get_full_name() or user.username
    ma_nv = f"NV{user.id:03d}"
    nhan_vien, _ = NhanVien.objects.get_or_create(
        ma_nhan_vien=ma_nv,
        defaults={
            'ho_ten': ho_ten,
            'ten_dang_nhap': user.username,
            'mat_khau': user.password,
            'vai_tro': 'QUAN_LY' if user.is_superuser else 'QUAY',
            'email': user.email or '',
            'trang_thai': 'DANG_LAM',
            'user': user,
        }
    )
    return nhan_vien


def _next_booking_code():
    highest = 0
    for code in DonDatTruoc.objects.filter(ma_don_dat__startswith='BK').values_list('ma_don_dat', flat=True):
        suffix = code[2:]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f'BK{highest + 1:03d}'


def _sync_booking_vehicle_states(vehicle_ids):
    """
    Đồng bộ trạng thái vật lý của phương tiện tại bãi:
    - Giữ nguyên NGUNG_HOAT_DONG, BAO_DUONG, và CHO_VE_SINH (chờ rửa xe/sạc pin tại bãi).
    - Chỉ chuyển DANG_THUE khi có Hợp đồng đang thuê hoặc đang chờ xuất bãi tại quầy.
    - Đơn đặt trước tương lai được quản lý qua lịch Gantt & chống trùng giờ, không khóa vật lý xe tại bãi.
    """
    ids = sorted({value for value in vehicle_ids if value})
    if not ids:
        return

    vehicles = PhuongTien.objects.select_for_update().filter(pk__in=ids)
    for vehicle in vehicles:
        if vehicle.trang_thai_xe in ('NGUNG_HOAT_DONG', 'CHO_VE_SINH'):
            continue

        has_maintenance = NhatKyBaoDuong.objects.filter(
            bien_so_xe=vehicle, trang_thai='DANG_XU_LY'
        ).exists()
        if vehicle.trang_thai_xe == 'BAO_DUONG' or has_maintenance:
            continue

        has_active_contract = HopDongThue.objects.filter(
            bien_so_xe=vehicle,
            trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE'],
        ).exists()

        new_state = 'DANG_THUE' if has_active_contract else 'CON_TRONG'
        if vehicle.trang_thai_xe != new_state:
            vehicle.trang_thai_xe = new_state
            vehicle.save(update_fields=['trang_thai_xe', 'ngay_cap_nhat'])


def _expire_unconfirmed_bookings():
    """
    BRULE-01: Tự động chuyển trạng thái sang KHONG_DEN (No-show) nếu quá 2 giờ
    kể từ giờ hẹn nhận mà khách không đến nhận xe, đồng thời ghi nhận lưu ý uy tín khách.
    """
    now = timezone.now()
    deadline = now - datetime.timedelta(hours=2)
    with transaction.atomic():
        overdue_qs = DonDatTruoc.objects.select_for_update().filter(
            trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO'],
            thoi_gian_hen_nhan__lte=deadline,
        )
        overdue_list = list(overdue_qs.values('ma_don_dat', 'bien_so_xe_id', 'ma_khach_hang_id'))
        if overdue_list:
            affected_vehicles = [item['bien_so_xe_id'] for item in overdue_list]
            customer_ids = {item['ma_khach_hang_id'] for item in overdue_list}

            overdue_qs.update(
                trang_thai_don='KHONG_DEN',
                ly_do_huy='Hệ thống tự động ghi nhận khách không đến nhận xe sau 2 giờ hẹn.',
                ngay_cap_nhat=now,
            )

            # Hạ bậc uy tín khách từ TOT -> CAN_LUU_Y nếu bùng hẹn đặt trước
            KhachHang.objects.filter(
                pk__in=customer_ids,
                muc_tin_nhiem='TOT',
            ).update(muc_tin_nhiem='CAN_LUU_Y', ngay_cap_nhat=now)

            _sync_booking_vehicle_states(affected_vehicles)


def _parse_custom_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    try:
        return datetime.datetime.strptime(date_str, '%d/%m/%Y').date()
    except ValueError:
        pass
    return parse_date(date_str)


@login_required
@permission_required_vm(
    'can_manage_bookings',
    redirect_url='booking_list',
    deny_message='Kỹ thuật viên chỉ có quyền xem danh sách đặt xe, không thể tạo đơn mới!'
)
def booking_list(request):
    _expire_unconfirmed_bookings()
    now = timezone.now()

    if request.method == 'POST':
        if not has_permission(request.user, 'can_manage_bookings'):
            messages.error(request, 'Tài khoản của bạn không có quyền thao tác cập nhật đơn đặt xe!')
            return redirect('booking_list')
        action = request.POST.get('action')

        if action == 'quick_mark_paid':
            ma_don = request.POST.get('ma_don')
            don = get_object_or_404(DonDatTruoc, ma_don_dat=ma_don)
            if don.tien_coc_giu_cho > 0 and not don.da_thanh_toan_coc:
                don.da_thanh_toan_coc = True
                don.trang_thai_don = 'DA_GIU_CHO'
                don.save(update_fields=['da_thanh_toan_coc', 'trang_thai_don'])
                messages.success(request, f'Đã xác nhận thu tiền cọc giữ chỗ cho đơn {ma_don}.')
            return redirect(request.get_full_path())

        elif action == 'quick_cancel':
            ma_don = request.POST.get('ma_don')
            ly_do = (request.POST.get('ly_do_huy') or '').strip() or 'Khách báo hủy lịch'
            don = get_object_or_404(DonDatTruoc, ma_don_dat=ma_don)
            if don.trang_thai_don in ['CHO_XAC_NHAN', 'DA_GIU_CHO']:
                don.trang_thai_don = 'DA_HUY'
                don.ly_do_huy = ly_do
                don.save(update_fields=['trang_thai_don', 'ly_do_huy'])
                messages.warning(request, f'Đã hủy đơn đặt trước {ma_don} (Lưu vào lịch sử khách hàng).')
            return redirect(request.get_full_path())


        elif action == 'edit_booking':
            ma_don = request.POST.get('edit_ma_don')
            don = get_object_or_404(DonDatTruoc, ma_don_dat=ma_don)
            old_vehicle_id = don.bien_so_xe_id
            edit_form = DonDatTruocEditForm(request.POST, instance=don)
            if edit_form.is_valid():
                with transaction.atomic():
                    updated_don = edit_form.save()
                    if updated_don.trang_thai_don == 'KHONG_DEN':
                        KhachHang.objects.filter(
                            pk=updated_don.ma_khach_hang_id,
                            muc_tin_nhiem='TOT',
                        ).update(muc_tin_nhiem='CAN_LUU_Y', ngay_cap_nhat=now)
                    _sync_booking_vehicle_states([old_vehicle_id, updated_don.bien_so_xe_id])
                messages.success(request, f'Đã cập nhật đơn đặt trước {ma_don}.')
            else:
                first_err = next(iter(edit_form.errors.values()))[0]
                messages.error(request, f'Không thể cập nhật đơn {ma_don}: {first_err}')
            return redirect(request.get_full_path())

    # Chỉ lấy các đơn đặt trước đang giữ chỗ để chuyển sang lập hợp đồng
    qs = DonDatTruoc.objects.select_related(
        'ma_khach_hang', 'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'
    ).filter(trang_thai_don='DA_GIU_CHO').order_by('thoi_gian_hen_nhan')

    # Bộ lọc tìm kiếm & thời gian
    search_query = (request.GET.get('q') or '').strip()
    if search_query:
        qs = qs.filter(
            Q(ma_don_dat__icontains=search_query) |
            Q(ma_khach_hang__ho_ten__icontains=search_query) |
            Q(ma_khach_hang__so_dien_thoai__icontains=search_query) |
            Q(bien_so_xe__bien_so_xe__icontains=search_query) |
            Q(dia_diem_giao_xe__icontains=search_query)
        )

    time_filter = request.GET.get('time', 'all')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    if start_date_str or end_date_str:
        time_filter = 'custom'
        d_start = _parse_custom_date(start_date_str)
        d_end = _parse_custom_date(end_date_str)
        tz = timezone.get_current_timezone()
        if d_start:
            dt_start = timezone.make_aware(datetime.datetime.combine(d_start, datetime.time.min), tz)
            qs = qs.filter(thoi_gian_hen_nhan__gte=dt_start)
        if d_end:
            dt_end = timezone.make_aware(datetime.datetime.combine(d_end, datetime.time.max), tz)
            qs = qs.filter(thoi_gian_hen_nhan__lte=dt_end)
    elif time_filter == 'upcoming_24h':
        qs = qs.filter(thoi_gian_hen_nhan__gte=now, thoi_gian_hen_nhan__lte=now + timedelta(hours=24))
    elif time_filter == 'today':
        qs = qs.filter(thoi_gian_hen_nhan__date=now.date())
    elif time_filter == 'week':
        qs = qs.filter(
            thoi_gian_hen_nhan__date__gte=now.date() - timedelta(days=7),
            thoi_gian_hen_nhan__date__lte=now.date() + timedelta(days=7)
        )
    elif time_filter == 'month':
        qs = qs.filter(
            thoi_gian_hen_nhan__date__gte=now.date() - timedelta(days=30),
            thoi_gian_hen_nhan__date__lte=now.date() + timedelta(days=30)
        )

    paginator = Paginator(qs, 5)
    page_obj = paginator.get_page(request.GET.get('page'))

    booking_vehicles = list(
        PhuongTien.objects.filter(ma_dong_xe__dang_kinh_doanh=True)
        .exclude(trang_thai_xe='NGUNG_HOAT_DONG')
        .select_related('ma_dong_xe')
        .values(
            'bien_so_xe',
            'trang_thai_xe',
            'ma_dong_xe__ten_dong_xe',
            'ma_dong_xe__don_gia_ngay',
            'ma_dong_xe__tien_coc_dinh_muc',
        )
    )

    booking_details = []
    for b in page_obj:
        local_start = timezone.localtime(b.thoi_gian_hen_nhan)
        local_end = timezone.localtime(b.thoi_gian_du_kien_tra)
        booking_details.append({
            'code': b.ma_don_dat,
            'status': b.trang_thai_don,
            'nhan_vien': b.ma_nhan_vien.ho_ten if b.ma_nhan_vien else '',
            'customer': b.ma_khach_hang.ho_ten,
            'phone': b.ma_khach_hang.so_dien_thoai,
            'email': getattr(b.ma_khach_hang, 'email', '') or '',
            'address': getattr(b.ma_khach_hang, 'dia_chi', '') or '',
            'dia_diem_giao_xe': b.dia_diem_giao_xe or '',
            'vehicle': b.bien_so_xe.bien_so_xe,
            'vehicle_name': b.bien_so_xe.ma_dong_xe.ten_dong_xe,
            'start': local_start.strftime('%Y-%m-%dT%H:%M'),
            'end': local_end.strftime('%Y-%m-%dT%H:%M'),
            'daily_price': float(b.bien_so_xe.ma_dong_xe.don_gia_ngay or 0),
            'deposit': float(b.bien_so_xe.ma_dong_xe.tien_coc_dinh_muc or 0),
            'total_estimated': float(b.tong_tien_du_kien or 0),
            'tien_coc_giu_cho': float(b.tien_coc_giu_cho or 0),
            'da_thanh_toan_coc': bool(b.da_thanh_toan_coc),
            'ghi_chu': b.ghi_chu or '',
            'ly_do_huy': b.ly_do_huy or '',
        })

    context = {
        'page_obj': page_obj,
        'now': now,
        'search_query': search_query,
        'time_filter': time_filter,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'booking_vehicles': booking_vehicles,
        'booking_details': booking_details,
        'active_page': 'booking',
    }
    return render(request, 'reviews/list2.html', context)

@login_required
@permission_required_vm(
    'can_manage_bookings',
    redirect_url='booking_list',
    deny_message='Kỹ thuật viên chỉ có quyền xem danh sách đặt xe, không thể tạo đơn mới!'
)
@login_required
def booking_create(request):
    """Trang riêng tạo mới Đơn đặt xe trước"""
    _expire_unconfirmed_bookings()
    nhan_vien_truc = get_current_nhan_vien(request.user)
    next_code = _next_booking_code()
    booking_form = DonDatTruocForm(initial={'ma_don_dat': next_code})

    if request.method == 'POST':
        booking_form = DonDatTruocForm(request.POST)
        if booking_form.is_valid():
            with transaction.atomic():
                booking = booking_form.save(commit=False, nhan_vien=nhan_vien_truc)
                booking.ma_don_dat = _next_booking_code()
                booking.trang_thai_don = 'DA_GIU_CHO'
                booking.tien_coc_giu_cho = 100000
                booking.da_thanh_toan_coc = True
                booking.save()
                _sync_booking_vehicle_states([booking.bien_so_xe_id])
            messages.success(
                request,
                f'Đã tạo đơn đặt xe {booking.ma_don_dat} (Đã giữ chỗ - Cọc 100.000 đ) thành công.'
            )
            return redirect('booking_list')
        messages.error(request, 'Vui lòng kiểm tra lại thông tin đơn đặt trước.')

    booking_customers = list(
        KhachHang.objects.order_by('ho_ten').values(
            'ma_khach_hang', 'ho_ten', 'so_dien_thoai',
            'so_cccd', 'giay_phep_lai_xe', 'quoc_tich',
            'email', 'dia_chi', 'muc_tin_nhiem', 'ly_do_blacklist'
        )
    )
    booking_vehicles = list(
        PhuongTien.objects.filter(ma_dong_xe__dang_kinh_doanh=True)
        .exclude(trang_thai_xe='NGUNG_HOAT_DONG')
        .select_related('ma_dong_xe')
        .order_by('bien_so_xe')
        .values(
            'bien_so_xe', 'trang_thai_xe',
            'ma_dong_xe__ten_dong_xe',
            'ma_dong_xe__don_gia_ngay',
            'ma_dong_xe__tien_coc_dinh_muc',
        )
    )

    busy_intervals = []
    for d in DonDatTruoc.objects.filter(trang_thai_don='DA_GIU_CHO'):
        busy_intervals.append({
            'vehicle': d.bien_so_xe_id,
            'start': timezone.localtime(d.thoi_gian_hen_nhan).strftime('%Y-%m-%dT%H:%M'),
            'end': timezone.localtime(d.thoi_gian_du_kien_tra).strftime('%Y-%m-%dT%H:%M'),
            'ref': f"Đơn {d.ma_don_dat}",
        })
    for hd in HopDongThue.objects.filter(trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE']):
        busy_intervals.append({
            'vehicle': hd.bien_so_xe_id,
            'start': timezone.localtime(hd.ngay_bat_dau).strftime('%Y-%m-%dT%H:%M'),
            'end': timezone.localtime(hd.ngay_ket_thuc_du_kien).strftime('%Y-%m-%dT%H:%M'),
            'ref': f"HĐ {hd.ma_hop_dong}",
        })

    context = {
        'booking_form': booking_form,
        'next_ma_don_dat': next_code,
        'nhan_vien_truc': nhan_vien_truc,
        'booking_customers': booking_customers,
        'booking_vehicles': booking_vehicles,
        'busy_intervals': busy_intervals,
        'active_page': 'booking',
    }
    return render(request, 'reviews/booking_create.html', context)

# ==============================================================================
# PHÂN HỆ QUẢN LÝ XE
# ==============================================================================
def vehicle_list_maintenance():
    return HttpResponseRedirect(reverse('vehicle_list') + '?tab=maintenance#tab-maintenance')


def _next_dong_xe_code():
    existing_ids = DongXe.objects.filter(ma_dong_xe__startswith='DX').values_list('ma_dong_xe', flat=True)
    max_num = 0
    for code in existing_ids:
        suffix = code[2:]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    return f"DX{max_num + 1:03d}"


def _next_maintenance_code():
    existing_ids = set(NhatKyBaoDuong.objects.values_list('ma_phieu_bao_duong', flat=True))
    next_number = 1
    while f"BD{next_number:03d}" in existing_ids:
        next_number += 1
    return f"BD{next_number:03d}"


def _build_vehicle_gantt(vehicles_list, year, month, today):
    """Xây dựng dữ liệu biểu đồ Gantt điều phối xe theo tháng."""
    previous_month = (datetime.date(year, month, 1) - datetime.timedelta(days=1)).strftime('%Y-%m')
    next_month = (datetime.date(year + (month == 12), month % 12 + 1, 1)).strftime('%Y-%m')
    num_days = calendar.monthrange(year, month)[1]
    date_list = [datetime.date(year, month, day) for day in range(1, num_days + 1)]
    start_date, end_date = date_list[0], date_list[-1]

    bookings = DonDatTruoc.objects.filter(
        trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO'],
        thoi_gian_hen_nhan__date__lte=end_date,
        thoi_gian_du_kien_tra__date__gte=start_date,
    )
    contracts = HopDongThue.objects.filter(
        trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE', 'DA_TRA'],
        ngay_bat_dau__lte=end_date,
    )
    maintenance_logs = NhatKyBaoDuong.objects.filter(
        ngay_bao_duong__lte=end_date,
    ).order_by('ngay_bao_duong')

    bookings_by_v = defaultdict(list)
    for b in bookings:
        bookings_by_v[b.bien_so_xe_id].append(b)

    contracts_by_v = defaultdict(list)
    for c in contracts:
        contracts_by_v[c.bien_so_xe_id].append(c)

    maint_by_v = defaultdict(list)
    for m in maintenance_logs:
        maint_by_v[m.bien_so_xe_id].append(m)

    for v in vehicles_list:
        day_status = ['CON_TRONG'] * num_days
        day_label = [''] * num_days

        def mark_period(first_day, last_day, status, label):
            if not first_day or not last_day:
                return
            if hasattr(first_day, 'date'):
                first_day = first_day.date()
            if hasattr(last_day, 'date'):
                last_day = last_day.date()
            first_day = max(first_day, start_date)
            last_day = min(last_day, end_date)
            if first_day > last_day:
                return
            for idx in range((first_day - start_date).days, (last_day - start_date).days + 1):
                day_status[idx] = status
                day_label[idx] = label

        for booking in bookings_by_v.get(v.pk, []):
            mark_period(booking.thoi_gian_hen_nhan, booking.thoi_gian_du_kien_tra, 'DANG_THUE', 'Đặt trước')

        for contract in contracts_by_v.get(v.pk, []):
            contract_end = (
                (contract.ngay_ket_thuc_thuc_te or contract.ngay_ket_thuc_du_kien)
                if contract.trang_thai_hop_dong == 'DA_TRA'
                else contract.ngay_ket_thuc_du_kien
            )
            mark_period(contract.ngay_bat_dau, contract_end, 'DANG_THUE', 'Đang thuê')

        for log in maint_by_v.get(v.pk, []):
            if log.trang_thai == 'HOAN_THANH' and log.ngay_hoan_thanh:
                mark_period(log.ngay_bao_duong, log.ngay_hoan_thanh, 'BAO_DUONG', 'Bảo dưỡng')
            elif log.trang_thai == 'DANG_XU_LY' and v.trang_thai_xe == 'BAO_DUONG':
                mark_period(log.ngay_bao_duong, end_date, 'BAO_DUONG', 'Bảo dưỡng')

        if (year, month) == (today.year, today.month):
            if v.trang_thai_xe == 'BAO_DUONG' and not any(
                    log.trang_thai == 'DANG_XU_LY' for log in maint_by_v.get(v.pk, [])):
                mark_period(today, end_date, 'BAO_DUONG', 'Bảo dưỡng')
            elif v.trang_thai_xe == 'CHO_VE_SINH':
                mark_period(today, today, 'CHO_VE_SINH', 'Rửa xe/Sạc pin')

        segments = []
        if num_days > 0:
            curr_status, curr_label, start_col = day_status[0], day_label[0], 1
            for i in range(1, num_days):
                if day_status[i] != curr_status or day_label[i] != curr_label:
                    segments.append({'status': curr_status, 'label': curr_label, 'start': start_col, 'end': i + 1})
                    curr_status, curr_label, start_col = day_status[i], day_label[i], i + 1
            segments.append({'status': curr_status, 'label': curr_label, 'start': start_col, 'end': num_days + 1})
        v.gantt_segments = segments

    return date_list, previous_month, next_month


@login_required
def vehicle_list(request):
    _expire_unconfirmed_bookings()
    nhan_vien_hien_tai = get_current_nhan_vien(request.user)
    today = timezone.localdate()

    with transaction.atomic():
        active_booking_vehicle_ids = DonDatTruoc.objects.filter(
            trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO']
        ).values_list('bien_so_xe_id', flat=True).distinct()
        _sync_booking_vehicle_states(list(active_booking_vehicle_ids))

    # Tự động khóa xe sang BAO_DUONG + tạo phiếu + ghi log nếu ODO lũy kế >= 2.000 km
    overdue_maint_vehicles = list(
        PhuongTien.objects.filter(
            odo_luy_ke_bao_duong__gte=2000,
            trang_thai_xe__in=['CON_TRONG', 'CHO_VE_SINH'],
        )
    )
    if overdue_maint_vehicles:
        ktv_mac_dinh = NhanVien.objects.filter(vai_tro='KY_THUAT',
                                               trang_thai='DANG_LAM').first() or nhan_vien_hien_tai
        with transaction.atomic():
            for xe_bd in overdue_maint_vehicles:
                if ktv_mac_dinh and not NhatKyBaoDuong.objects.filter(bien_so_xe=xe_bd,
                                                                      trang_thai='DANG_XU_LY').exists():
                    NhatKyBaoDuong.objects.create(
                        ma_phieu_bao_duong=_next_maintenance_code(),
                        bien_so_xe=xe_bd,
                        ma_nhan_vien=ktv_mac_dinh,
                        ngay_bao_duong=today,
                        loai_bao_duong='DINH_KY',
                        reset_odo_luy_ke=True,
                        odo_luc_bao_duong=xe_bd.odo_hien_tai,
                        noi_dung=f'Tự động lập do ODO lũy kế đạt {xe_bd.odo_luy_ke_bao_duong:,} km (≥ 2.000 km)',
                        trang_thai='DANG_XU_LY',
                    )
                else:
                    trang_thai_cu = xe_bd.trang_thai_xe
                    xe_bd.trang_thai_xe = 'BAO_DUONG'
                    xe_bd.save(update_fields=['trang_thai_xe', 'ngay_cap_nhat'])
                    NhatKyVanHanhXe.objects.create(
                        bien_so_xe=xe_bd,
                        ma_nhan_vien=nhan_vien_hien_tai,
                        tu_trang_thai=trang_thai_cu,
                        den_trang_thai='BAO_DUONG',
                        odo_ghi_nhan=xe_bd.odo_hien_tai,
                        muc_nhien_lieu_pin=xe_bd.muc_nhien_lieu_pin,
                        ghi_chu=f'Tự động khóa bảo dưỡng do ODO lũy kế đạt {xe_bd.odo_luy_ke_bao_duong:,} km',
                    )

    if request.method == 'POST':
        action = request.POST.get('action')
        role_flags = get_role_flags(request.user)

        if role_flags.get('role_code') == 'NGHI_VIEC':
            messages.error(request, 'Tài khoản đã nghỉ việc, không thể thực hiện thao tác!')
            return redirect('vehicle_list')

        if action in ('delete_vehicles', 'add_vehicle', 'add_dong_xe', 'update_pricing') and not role_flags.get(
                'can_manage_fleet'):
            messages.error(request,
                           'Kỹ thuật viên chỉ có quyền xem thông tin đội xe, không được thêm/sửa/xóa xe hoặc dòng xe!')
            return redirect('vehicle_list')

        if action in ('mark_ready', 'quick_maintenance') and not role_flags.get('can_ready_vehicle'):
            messages.error(request, 'Bạn không có quyền cập nhật trạng thái sẵn sàng hoặc báo hỏng xe!')
            return redirect('vehicle_list')

        if action == 'add_maintenance' and not role_flags.get('can_manage_maintenance'):
            messages.error(request, 'Chỉ Kỹ thuật viên hoặc Quản lý mới được lập và hoàn tất phiếu bảo dưỡng!')
            return vehicle_list_maintenance()

        # 1. XÓA HÀNG LOẠT PHƯƠNG TIỆN
        if action == 'delete_vehicles':
            selected_ids = request.POST.getlist('selected_vehicles')
            if selected_ids:
                try:
                    deleted_count, _ = PhuongTien.objects.filter(bien_so_xe__in=selected_ids).delete()
                    messages.success(request, f'Đã xóa {deleted_count} phương tiện thành công.')
                except ProtectedError:
                    messages.error(
                        request,
                        'Không thể xóa phương tiện đã có lịch sử hợp đồng, đặt xe hoặc bảo dưỡng! '
                        'Vui lòng mở Chi tiết xe và chuyển sang trạng thái "Ngưng hoạt động".'
                    )
            return redirect('vehicle_list')

        # 2. THÊM PHƯƠNG TIỆN MỚI
        elif action == 'add_vehicle':
            form = PhuongTienCreateForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    xe = form.save()
                    NhatKyVanHanhXe.objects.create(
                        bien_so_xe=xe,
                        ma_nhan_vien=nhan_vien_hien_tai,
                        tu_trang_thai='MOI_NHAP',
                        den_trang_thai=xe.trang_thai_xe,
                        odo_ghi_nhan=xe.odo_hien_tai,
                        muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                        ghi_chu='Nhập mới phương tiện vào đội xe',
                    )
                    if xe.trang_thai_xe == 'BAO_DUONG':
                        ktv = NhanVien.objects.filter(vai_tro='KY_THUAT',
                                                      trang_thai='DANG_LAM').first() or nhan_vien_hien_tai
                        if ktv:
                            NhatKyBaoDuong.objects.create(
                                ma_phieu_bao_duong=_next_maintenance_code(),
                                bien_so_xe=xe,
                                ma_nhan_vien=ktv,
                                ngay_bao_duong=today,
                                loai_bao_duong='KIEM_TRA',
                                reset_odo_luy_ke=False,
                                odo_luc_bao_duong=xe.odo_hien_tai,
                                noi_dung='Kiểm tra kỹ thuật khi tiếp nhận xe mới',
                                trang_thai='DANG_XU_LY',
                            )
                messages.success(request, f'Đã thêm phương tiện {xe.bien_so_xe} thành công.')
            else:
                first_err = next(iter(form.errors.values()))[0]
                messages.error(request, first_err)
            return redirect('vehicle_list')

        # 3. THÊM / CẬP NHẬT DÒNG XE
        elif action == 'add_dong_xe':
            ma_dong = (request.POST.get('ma_dong_xe') or '').strip().upper()
            existing_dx = DongXe.objects.filter(ma_dong_xe=ma_dong).first()
            form = DongXeForm(request.POST, request.FILES, instance=existing_dx)
            if form.is_valid():
                dx = form.save()
                msg = f'Đã cập nhật dòng xe {dx.ten_dong_xe}.' if existing_dx else f'Đã thêm dòng xe {dx.ten_dong_xe} thành công.'
                messages.success(request, msg)
            else:
                first_err = next(iter(form.errors.values()))[0]
                messages.error(request, first_err)
            return redirect('vehicle_list')

        # 4. CẬP NHẬT CHI TIẾT XE & GIÁ DÒNG XE
        elif action == 'update_pricing':
            form = PhuongTienUpdateForm(request.POST, request.FILES)
            if not form.is_valid():
                first_err = next(iter(form.errors.values()))[0]
                messages.error(request, f'Dữ liệu cập nhật không hợp lệ: {first_err}')
                return redirect('vehicle_list')

            cd = form.cleaned_data
            bien_so = cd['bien_so_xe'].strip()
            with transaction.atomic():
                xe = get_object_or_404(
                    PhuongTien.objects.select_for_update().select_related('ma_dong_xe'),
                    bien_so_xe=bien_so,
                )
                if cd['odo_hien_tai'] < xe.odo_hien_tai:
                    messages.error(request, 'ODO mới không được nhỏ hơn ODO hiện tại.')
                    return redirect('vehicle_list')

                trang_thai_cu = xe.trang_thai_xe
                xe.odo_hien_tai = cd['odo_hien_tai']
                xe.nam_san_xuat = cd.get('nam_san_xuat')
                xe.so_khung = (cd.get('so_khung') or '').strip() or None
                xe.so_may = (cd.get('so_may') or '').strip() or None
                xe.han_bao_hiem = cd.get('han_bao_hiem')
                xe_update_fields = [
                    'odo_hien_tai', 'nam_san_xuat', 'so_khung',
                    'so_may', 'han_bao_hiem', 'ngay_cap_nhat'
                ]

                # Cập nhật thêm các trường tài sản & tình trạng thực tế nếu form/request có gửi lên
                if 'muc_nhien_lieu_pin' in request.POST and request.POST.get('muc_nhien_lieu_pin') != '':
                    muc_nl = _safe_int(request.POST.get('muc_nhien_lieu_pin'), default=xe.muc_nhien_lieu_pin)
                    xe.muc_nhien_lieu_pin = min(100, max(0, muc_nl))
                    xe_update_fields.append('muc_nhien_lieu_pin')

                if 'ghi_chu_tinh_trang' in request.POST:
                    xe.ghi_chu_tinh_trang = (request.POST.get('ghi_chu_tinh_trang') or '').strip() or None
                    xe_update_fields.append('ghi_chu_tinh_trang')

                if 'ngay_mua' in request.POST:
                    xe.ngay_mua = parse_date(request.POST.get('ngay_mua', '').strip())
                    xe_update_fields.append('ngay_mua')

                if 'gia_tri_mua' in request.POST and request.POST.get('gia_tri_mua') != '':
                    try:
                        gia_mua = Decimal(request.POST.get('gia_tri_mua') or '0')
                        if gia_mua >= 0:
                            xe.gia_tri_mua = gia_mua
                            xe_update_fields.append('gia_tri_mua')
                    except (InvalidOperation, TypeError):
                        pass

                # Cho phép chuyển đổi linh hoạt giữa CON_TRONG, CHO_VE_SINH và NGUNG_HOAT_DONG
                trang_thai_moi = cd.get('trang_thai_xe')
                if trang_thai_moi in ('CON_TRONG', 'CHO_VE_SINH', 'NGUNG_HOAT_DONG') and trang_thai_moi != xe.trang_thai_xe:
                    if xe.trang_thai_xe in ('DANG_THUE', 'BAO_DUONG'):
                        messages.error(
                            request,
                            f'Xe {bien_so} đang ở trạng thái "{xe.get_trang_thai_xe_display()}", '
                            f'không thể chuyển trực tiếp sang trạng thái khác!'
                        )
                        return redirect('vehicle_list')
                    if trang_thai_moi == 'NGUNG_HOAT_DONG' and DonDatTruoc.objects.filter(
                        bien_so_xe=xe, trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO']
                    ).exists():
                        messages.error(
                            request,
                            f'Xe {bien_so} đang có đơn đặt trước hiệu lực, vui lòng hủy/chuyển đơn trước!'
                        )
                        return redirect('vehicle_list')
                    xe.trang_thai_xe = trang_thai_moi
                    xe_update_fields.append('trang_thai_xe')

                xe.save(update_fields=xe_update_fields)

                if trang_thai_moi and trang_thai_moi != trang_thai_cu:
                    NhatKyVanHanhXe.objects.create(
                        bien_so_xe=xe,
                        ma_nhan_vien=nhan_vien_hien_tai,
                        tu_trang_thai=trang_thai_cu,
                        den_trang_thai=trang_thai_moi,
                        odo_ghi_nhan=xe.odo_hien_tai,
                        muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                        ghi_chu='Cập nhật trạng thái trong chi tiết xe',
                    )

                dong_xe = xe.ma_dong_xe
                dong_xe.don_gia_ngay = cd['don_gia_ngay']
                dong_xe.tien_coc_dinh_muc = cd['tien_coc']
                updated_fields = ['don_gia_ngay', 'tien_coc_dinh_muc']
                if cd.get('hinh_anh'):
                    dong_xe.hinh_anh = cd['hinh_anh']
                    updated_fields.append('hinh_anh')
                dong_xe.save(update_fields=updated_fields)

            messages.success(request, f'Cập nhật thông tin phương tiện {bien_so} thành công.')
            return redirect('vehicle_list')

        # 5. THAO TÁC NHANH TẠI BÃI: HOÀN TẤT RỬA XE / SẠC PIN (1 CLICK)
        elif action == 'mark_ready':
            bien_so = (request.POST.get('bien_so_xe') or '').strip()
            muc_nl = _safe_int(request.POST.get('muc_nhien_lieu_pin'), default=100)
            with transaction.atomic():
                xe = get_object_or_404(PhuongTien.objects.select_for_update(), pk=bien_so)
                if xe.trang_thai_xe == 'CHO_VE_SINH':
                    xe.trang_thai_xe = 'CON_TRONG'
                    xe.muc_nhien_lieu_pin = min(100, max(0, muc_nl))
                    xe.save(update_fields=['trang_thai_xe', 'muc_nhien_lieu_pin', 'ngay_cap_nhat'])

                    NhatKyVanHanhXe.objects.create(
                        bien_so_xe=xe,
                        ma_nhan_vien=nhan_vien_hien_tai,
                        tu_trang_thai='CHO_VE_SINH',
                        den_trang_thai='CON_TRONG',
                        odo_ghi_nhan=xe.odo_hien_tai,
                        muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                        ghi_chu='Hoàn tất rửa xe / sạc đầy pin tại bãi',
                    )
                    messages.success(request, f'Xe {bien_so} đã sẵn sàng giao khách ({xe.muc_nhien_lieu_pin}% xăng/pin).')
                else:
                    messages.warning(request, f'Xe {bien_so} không ở trạng thái Chờ rửa xe / Sạc pin.')
            return redirect('vehicle_list')

        # 6. THAO TÁC NHANH TẠI BÃI: BÁO HỎNG / ĐƯA VÀO XƯỞNG
        elif action == 'quick_maintenance':
            bien_so = (request.POST.get('bien_so_xe') or '').strip()
            ly_do = (request.POST.get('ly_do_hong') or '').strip() or 'Kiểm tra / sửa chữa phát sinh tại bãi'
            loai_bd = request.POST.get('loai_bao_duong', 'SUA_CHUA')
            if loai_bd not in dict(NhatKyBaoDuong.LOAI_BAO_DUONG_CHOICES):
                loai_bd = 'SUA_CHUA'

            with transaction.atomic():
                xe = get_object_or_404(PhuongTien.objects.select_for_update(), pk=bien_so)
                if xe.trang_thai_xe == 'DANG_THUE':
                    messages.error(request, f'Xe {bien_so} đang được thuê, không thể đưa vào xưởng.')
                    return redirect('vehicle_list')

                ktv = NhanVien.objects.filter(vai_tro='KY_THUAT', trang_thai='DANG_LAM').first() or nhan_vien_hien_tai
                ma_phieu = _next_maintenance_code()
                NhatKyBaoDuong.objects.create(
                    ma_phieu_bao_duong=ma_phieu,
                    bien_so_xe=xe,
                    ma_nhan_vien=ktv,
                    ngay_bao_duong=today,
                    loai_bao_duong=loai_bd,
                    muc_do_uu_tien='CAO',
                    odo_luc_bao_duong=xe.odo_hien_tai,
                    reset_odo_luy_ke=(loai_bd == 'DINH_KY'),
                    tinh_trang_phat_hien=ly_do,
                    noi_dung=ly_do,
                    trang_thai='DANG_XU_LY',
                )
            messages.warning(request, f'Đã khóa xe {bien_so} vào xưởng bảo dưỡng (Phiếu {ma_phieu}).')
            return redirect('vehicle_list')

        # 7. LẬP / CẬP NHẬT PHIẾU BẢO DƯỠNG
        elif action == 'add_maintenance':
            ma_phieu = request.POST.get('ma_phieu_bao_duong', '').strip()
            bien_so = request.POST.get('bien_so_xe', '').strip()
            ma_nv = request.POST.get('ma_nhan_vien', '').strip()
            ngay_bd = parse_date(request.POST.get('ngay_bao_duong', ''))
            loai_bd = request.POST.get('loai_bao_duong', 'DINH_KY')
            muc_do = request.POST.get('muc_do_uu_tien', 'BINH_THUONG')
            trang_thai_bd = request.POST.get('trang_thai_bd', 'DANG_XU_LY')
            don_vi_sc = (request.POST.get('don_vi_sua_chua') or '').strip() or 'Xưởng nội bộ Vietmoto'
            hang_muc = request.POST.getlist('hang_muc_kiem_tra')
            tinh_trang = request.POST.get('tinh_trang_phat_hien', '').strip()
            noi_dung = request.POST.get('noi_dung_sua_chua', '').strip()
            ket_qua = request.POST.get('ket_qua_xu_ly', '').strip()

            # Xử lý cờ reset_odo_luy_ke (nếu form có gửi thì lấy theo form, không thì mặc định True với DINH_KY)
            if 'reset_odo_luy_ke' in request.POST:
                reset_odo = request.POST.get('reset_odo_luy_ke') in ('on', 'true', '1')
            else:
                reset_odo = (loai_bd == 'DINH_KY')

            try:
                odo_bd = int(request.POST.get('odo_luc_bao_duong', ''))
                odo_ht_raw = request.POST.get('odo_hoan_thanh', '').strip()
                odo_ht_val = int(odo_ht_raw) if odo_ht_raw else odo_bd
                parts = Decimal(request.POST.get('chi_phi_phu_tung') or '0')
                other = Decimal(request.POST.get('chi_phi_khac') or '0')
                if odo_bd < 0 or odo_ht_val < odo_bd or parts < 0 or other < 0:
                    raise ValueError()
            except (ValueError, InvalidOperation, TypeError):
                messages.error(request, 'ODO hoặc chi phí không hợp lệ (ODO hoàn thành phải ≥ ODO tiếp nhận).')
                return vehicle_list_maintenance()

            if not ma_phieu or not bien_so or not ma_nv or not ngay_bd:
                messages.error(request, 'Thiếu thông tin bắt buộc.')
                return vehicle_list_maintenance()
            if (loai_bd not in dict(NhatKyBaoDuong.LOAI_BAO_DUONG_CHOICES)
                    or muc_do not in dict(NhatKyBaoDuong.MUC_DO_UU_TIEN_CHOICES)
                    or trang_thai_bd not in dict(NhatKyBaoDuong.TRANG_THAI_CHOICES)):
                messages.error(request, 'Lựa chọn không hợp lệ.')
                return vehicle_list_maintenance()

            phieu_cu = NhatKyBaoDuong.objects.filter(pk=ma_phieu).first()
            if phieu_cu and phieu_cu.trang_thai == 'HOAN_THANH':
                trang_thai_bd = 'HOAN_THANH'

            ngay_ht = None
            if trang_thai_bd == 'HOAN_THANH':
                ngay_ht_raw = request.POST.get('ngay_hoan_thanh', '').strip()
                ngay_ht = (
                    parse_date(ngay_ht_raw) if ngay_ht_raw
                    else (phieu_cu.ngay_hoan_thanh if phieu_cu and phieu_cu.ngay_hoan_thanh else today)
                )
                if not ngay_ht:
                    messages.error(request, 'Ngày hoàn thành không hợp lệ.')
                    return vehicle_list_maintenance()
                if ngay_ht < ngay_bd:
                    messages.error(request, 'Ngày hoàn thành không được trước ngày tiếp nhận.')
                    return vehicle_list_maintenance()

            images = request.FILES.getlist('hinh_anh')
            try:
                stages = json.loads(request.POST.get('giai_doan_anh_list', '[]'))
                if not isinstance(stages, list) or len(stages) != len(images):
                    raise ValueError()
            except (ValueError, TypeError):
                messages.error(request, 'Dữ liệu giai đoạn ảnh không hợp lệ.')
                return vehicle_list_maintenance()

            valid_stages = {'TRUOC', 'TRONG', 'SAU'}
            for img, stage in zip(images, stages):
                if stage not in valid_stages or img.size > 8 * 1024 * 1024 or not (img.content_type or '').startswith('image/'):
                    messages.error(request, 'Ảnh hoặc giai đoạn ảnh không hợp lệ (tối đa 8 MB/ảnh).')
                    return vehicle_list_maintenance()
                try:
                    from PIL import Image
                    img.seek(0)
                    with Image.open(img) as image_check:
                        image_check.verify()
                    img.seek(0)
                except Exception:
                    messages.error(request, 'Tệp ảnh bị lỗi.')
                    return vehicle_list_maintenance()

            try:
                with transaction.atomic():
                    xe = get_object_or_404(PhuongTien.objects.select_for_update(), pk=bien_so)
                    if xe.trang_thai_xe == 'DANG_THUE':
                        raise ValueError(f'Xe {bien_so} đang được thuê, không thể lập phiếu bảo dưỡng.')
                    nv = get_object_or_404(NhanVien, pk=ma_nv, vai_tro='KY_THUAT')
                    phieu = NhatKyBaoDuong.objects.select_for_update().filter(pk=ma_phieu).first()
                    active = NhatKyBaoDuong.objects.select_for_update().filter(
                        bien_so_xe=xe, trang_thai='DANG_XU_LY'
                    ).first()
                    phieu_was_completed = bool(phieu and phieu.trang_thai == 'HOAN_THANH')

                    if phieu:
                        if phieu.bien_so_xe_id != bien_so:
                            raise ValueError('Không thể đổi xe của phiếu.')
                        if active and active.pk != phieu.pk:
                            raise ValueError('Xe đang có phiếu khác chưa hoàn thành.')
                        if odo_bd != phieu.odo_luc_bao_duong:
                            raise ValueError('ODO tiếp nhận của phiếu không được thay đổi.')
                    else:
                        if active:
                            raise ValueError('Xe đã có phiếu đang xử lý; hãy chọn Cập nhật.')
                        if odo_bd < xe.odo_hien_tai:
                            raise ValueError('ODO tiếp nhận không được nhỏ hơn ODO xe.')
                        phieu = NhatKyBaoDuong(
                            ma_phieu_bao_duong=ma_phieu,
                            bien_so_xe=xe,
                            odo_luc_bao_duong=odo_bd,
                        )

                    phieu.ma_nhan_vien = nv
                    phieu.ngay_bao_duong = ngay_bd
                    phieu.ngay_hoan_thanh = ngay_ht
                    phieu.loai_bao_duong = loai_bd
                    phieu.muc_do_uu_tien = muc_do
                    phieu.reset_odo_luy_ke = reset_odo
                    phieu.don_vi_sua_chua = don_vi_sc
                    phieu.odo_hoan_thanh = odo_ht_val if trang_thai_bd == 'HOAN_THANH' else None
                    phieu.hang_muc_kiem_tra = hang_muc
                    phieu.tinh_trang_phat_hien = tinh_trang
                    phieu.noi_dung_sua_chua = noi_dung
                    phieu.ket_qua_xu_ly = ket_qua
                    phieu.noi_dung = noi_dung or tinh_trang or 'Đang kiểm tra'
                    phieu.chi_phi_phu_tung = parts
                    phieu.chi_phi_khac = other
                    phieu.chi_phi = parts + other
                    phieu.trang_thai = trang_thai_bd
                    phieu.save()

                    for img, stage in zip(images, stages):
                        HinhAnhBaoDuong.objects.create(phieu_bao_duong=phieu, tep_anh=img, giai_doan=stage)

                    if trang_thai_bd == 'HOAN_THANH':
                        trang_thai_cu = xe.trang_thai_xe
                        sau_bd = request.POST.get('trang_thai_sau_bd', 'CON_TRONG')
                        if sau_bd not in ('CON_TRONG', 'CHO_VE_SINH'):
                            sau_bd = 'CON_TRONG'
                        if not NhatKyBaoDuong.objects.filter(
                                bien_so_xe=xe, trang_thai='DANG_XU_LY'
                        ).exclude(pk=phieu.pk).exists():
                            xe.trang_thai_xe = sau_bd
                        xe.odo_hien_tai = max(xe.odo_hien_tai, odo_ht_val)
                        if phieu.reset_odo_luy_ke and not phieu_was_completed:
                            xe.odo_luy_ke_bao_duong = 0
                        xe.save(
                            update_fields=['trang_thai_xe', 'odo_hien_tai', 'odo_luy_ke_bao_duong', 'ngay_cap_nhat'])

                        if not phieu_was_completed:
                            NhatKyVanHanhXe.objects.create(
                                bien_so_xe=xe,
                                ma_nhan_vien=nhan_vien_hien_tai or nv,
                                tu_trang_thai=trang_thai_cu,
                                den_trang_thai=xe.trang_thai_xe,
                                odo_ghi_nhan=xe.odo_hien_tai,
                                muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                                ghi_chu=f'Hoàn thành phiếu bảo dưỡng {phieu.ma_phieu_bao_duong}',
                            )
                    else:
                        xe.trang_thai_xe = 'BAO_DUONG'
                        xe.save(update_fields=['trang_thai_xe', 'ngay_cap_nhat'])

                messages.success(
                    request,
                    'Đã hoàn thành phiếu bảo dưỡng.' if trang_thai_bd == 'HOAN_THANH' else 'Đã lưu tiến độ phiếu bảo dưỡng.',
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            except Exception:
                logging.getLogger(__name__).exception('Lỗi lưu phiếu bảo dưỡng %s', ma_phieu)
                messages.error(request, 'Không thể lưu phiếu bảo dưỡng. Vui lòng kiểm tra lỗi trên terminal.')
            return vehicle_list_maintenance()

    # ==========================================================================
    # TRUY VẤN HIỂN THỊ DỮ LIỆU & TỔNG HỢP VEHICLE 360°
    # ==========================================================================
    vehicles = list(PhuongTien.objects.select_related('ma_dong_xe').all().order_by('bien_so_xe'))
    dong_xes = DongXe.objects.all().order_by('ten_dong_xe')
    nhan_viens = NhanVien.objects.filter(vai_tro='KY_THUAT', trang_thai='DANG_LAM')
    maintenance_logs = NhatKyBaoDuong.objects.select_related(
        'bien_so_xe__ma_dong_xe', 'ma_nhan_vien'
    ).prefetch_related('hinh_anh').order_by('-ngay_bao_duong', '-ma_phieu_bao_duong')

    status_param = request.GET.get('status', '').strip()

    # Tổng hợp chỉ số tài chính & vận hành từng xe (Vehicle 360°)
    doanh_thu_theo_xe = dict(
        HopDongThue.objects.filter(trang_thai_hop_dong__in=['DANG_THUE', 'DA_TRA'])
        .values('bien_so_xe')
        .annotate(tong_thu=Sum('tong_tien_thanh_toan'))
        .values_list('bien_so_xe', 'tong_thu')
    )
    so_chuyen_theo_xe = dict(
        HopDongThue.objects.filter(trang_thai_hop_dong__in=['DANG_THUE', 'DA_TRA'])
        .values('bien_so_xe')
        .annotate(so_chuyen=Count('ma_hop_dong'))
        .values_list('bien_so_xe', 'so_chuyen')
    )
    chi_phi_bd_theo_xe = dict(
        NhatKyBaoDuong.objects.filter(trang_thai='HOAN_THANH')
        .values('bien_so_xe')
        .annotate(tong_chi=Sum('chi_phi'))
        .values_list('bien_so_xe', 'tong_chi')
    )

    active_maintenance_by_vehicle = {}
    maintenance_details = {}
    for log in maintenance_logs:
        if log.trang_thai == 'DANG_XU_LY':
            so_ngay_bd = max(1, (today - log.ngay_bao_duong).days) if log.ngay_bao_duong else 1
            active_maintenance_by_vehicle[log.bien_so_xe_id] = {
                'ma_phieu': log.ma_phieu_bao_duong,
                'so_ngay': so_ngay_bd,
            }

        maintenance_details[log.ma_phieu_bao_duong] = {
            'ma_phieu_bao_duong': log.ma_phieu_bao_duong,
            'bien_so_xe': log.bien_so_xe_id,
            'ma_nhan_vien': log.ma_nhan_vien_id,
            'ten_nhan_vien': log.ma_nhan_vien.ho_ten if log.ma_nhan_vien else '',
            'ngay_bao_duong': log.ngay_bao_duong.isoformat(),
            'ngay_hoan_thanh': log.ngay_hoan_thanh.isoformat() if log.ngay_hoan_thanh else '',
            'loai_bao_duong': log.loai_bao_duong,
            'muc_do_uu_tien': log.muc_do_uu_tien,
            'odo_luc_bao_duong': log.odo_luc_bao_duong,
            'odo_hoan_thanh': log.odo_hoan_thanh,
            'reset_odo_luy_ke': log.reset_odo_luy_ke,
            'don_vi_sua_chua': log.don_vi_sua_chua,
            'hang_muc_kiem_tra': log.hang_muc_kiem_tra or [],
            'tinh_trang_phat_hien': log.tinh_trang_phat_hien,
            'noi_dung_sua_chua': log.noi_dung_sua_chua,
            'ket_qua_xu_ly': log.ket_qua_xu_ly,
            'chi_phi_phu_tung': str(log.chi_phi_phu_tung),
            'chi_phi_khac': str(log.chi_phi_khac),
            'chi_phi': str(log.chi_phi or 0),
            'trang_thai': log.trang_thai,
            'loai_dong_co': log.bien_so_xe.ma_dong_xe.loai_dong_co,
            'images': [
                {'url': img.tep_anh.url, 'stage': img.giai_doan}
                for img in log.hinh_anh.all() if img.tep_anh
            ],
        }

    selected_month = request.GET.get('month', '')
    try:
        selected_date = datetime.datetime.strptime(selected_month, '%Y-%m').date()
        year, month = selected_date.year, selected_date.month
    except (ValueError, TypeError):
        year, month = today.year, today.month

    date_list, previous_month, next_month = _build_vehicle_gantt(vehicles, year, month, today)

    vehicles_warning = []
    vehicles_meta = {}
    count_trong = count_thue = count_ve_sinh = count_bd = count_ngung = count_canh_bao_bh = 0

    for v in vehicles:
        if v.trang_thai_xe == 'CON_TRONG':
            count_trong += 1
        elif v.trang_thai_xe == 'DANG_THUE':
            count_thue += 1
        elif v.trang_thai_xe == 'CHO_VE_SINH':
            count_ve_sinh += 1
        elif v.trang_thai_xe == 'BAO_DUONG':
            count_bd += 1
        elif v.trang_thai_xe == 'NGUNG_HOAT_DONG':
            count_ngung += 1

        if v.canh_bao_bao_hiem in ('HET_HAN', 'SAP_HET_HAN'):
            count_canh_bao_bh += 1

        if v.canh_bao_bao_duong == 'SAP_DEN_HAN' and v.trang_thai_xe not in ('BAO_DUONG', 'NGUNG_HOAT_DONG'):
            vehicles_warning.append(v)

        # Gắn chỉ số 360° trực tiếp lên đối tượng xe
        v.tong_doanh_thu = doanh_thu_theo_xe.get(v.pk) or 0
        v.tong_chi_phi_bd = chi_phi_bd_theo_xe.get(v.pk) or 0
        v.loi_nhuan_gop = v.tong_doanh_thu - v.tong_chi_phi_bd
        v.tong_so_chuyen = so_chuyen_theo_xe.get(v.pk) or 0

        can_see_profit = has_permission(request.user, 'can_view_profit')
        vehicles_meta[v.bien_so_xe] = {
            'odo': v.odo_hien_tai,
            'odo_bd': v.odo_luy_ke_bao_duong,
            'fuel': v.muc_nhien_lieu_pin,
            'engine': v.ma_dong_xe.loai_dong_co,
            'status': v.trang_thai_xe,
            'note': v.ghi_chu_tinh_trang or '',
            'insurance_alert': v.canh_bao_bao_hiem,
            'revenue': float(v.tong_doanh_thu) if can_see_profit else None,
            'maint_cost': float(v.tong_chi_phi_bd) if can_see_profit else None,
            'profit': float(v.loi_nhuan_gop) if can_see_profit else None,
            'trips': v.tong_so_chuyen,
        }

        maint_info = active_maintenance_by_vehicle.get(v.pk, {})
        v.active_maintenance_id = maint_info.get('ma_phieu', '')
        v.so_ngay_bao_duong = maint_info.get('so_ngay', 0)

    next_ma_dong_xe = _next_dong_xe_code()

    return render(request, 'reviews/list.html', {
        'vehicles': vehicles,
        'vehicles_meta': vehicles_meta,
        'vehicles_warning': vehicles_warning,
        'dong_xes': dong_xes,
        'nhan_viens': nhan_viens,
        'count_trong': count_trong,
        'count_thue': count_thue,
        'count_ve_sinh': count_ve_sinh,
        'count_bd': count_bd,
        'count_ngung': count_ngung,
        'count_canh_bao_bh': count_canh_bao_bh,
        'maintenance_logs': maintenance_logs,
        'maintenance_details': maintenance_details,
        'date_list': date_list,
        'current_month_str': f"Tháng {month}/{year}",
        'selected_month': f'{year:04d}-{month:02d}',
        'today': today,
        'previous_month': previous_month,
        'next_month': next_month,
        'next_ma_dong_xe': next_ma_dong_xe,
        'next_ma_phieu_bd': _next_maintenance_code(),
        'status_param': status_param,
        'selected_month_num': month,
        'selected_year_num': year,
        'gantt_years': range(today.year - 1, today.year + 3),
    })
