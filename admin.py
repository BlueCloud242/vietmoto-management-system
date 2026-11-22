from django.contrib import admin
from .models import (
    DongXe,
    PhuongTien,
    NhanVien,
    KhachHang,
    DonDatTruoc,
    HopDongThue,
    ThanhToan,
    BienBanBanGiao,
    NhatKyBaoDuong,
    HinhAnhBaoDuong,
    NhatKyVanHanhXe,
    HinhAnhBienBan
)


@admin.register(DongXe)
class DongXeAdmin(admin.ModelAdmin):
    list_display = ("ma_dong_xe", "ten_dong_xe", "loai_xe", "don_gia_ngay", "tien_coc_dinh_muc")
    search_fields = ("ma_dong_xe", "ten_dong_xe", "loai_xe")
    list_filter = ("loai_xe", "loai_dong_co")
    ordering = ("ten_dong_xe",)


@admin.register(PhuongTien)
class PhuongTienAdmin(admin.ModelAdmin):
    list_display = (
        "bien_so_xe",
        "ma_dong_xe",
        "trang_thai_xe",
        "odo_hien_tai",
        "han_bao_hiem",
        "nam_san_xuat",
    )
    search_fields = ("bien_so_xe", "so_khung", "so_may")
    list_filter = ("trang_thai_xe", "ma_dong_xe", "nam_san_xuat")
    ordering = ("bien_so_xe",)
    readonly_fields = ("ngay_tao", "ngay_cap_nhat")


@admin.register(NhanVien)
class NhanVienAdmin(admin.ModelAdmin):
    list_display = ('ma_nhan_vien', 'ho_ten', 'so_dien_thoai', 'vai_tro', 'trang_thai', 'ngay_vao_lam')
    list_filter = ('vai_tro', 'trang_thai', 'ngay_vao_lam')
    search_fields = ('ma_nhan_vien', 'ho_ten', 'so_dien_thoai', 'cccd')
    ordering = ('-ngay_vao_lam',)


@admin.register(KhachHang)
class KhachHangAdmin(admin.ModelAdmin):
    list_display = (
        "ma_khach_hang",
        "ho_ten",
        "so_dien_thoai",
        "email",
        "so_cccd",
        "muc_tin_nhiem",
        "quoc_tich",
    )
    search_fields = (
        "ma_khach_hang",
        "ho_ten",
        "so_dien_thoai",
        "so_cccd",
        "email",
        "giay_phep_lai_xe",
    )
    list_filter = ("muc_tin_nhiem", "quoc_tich")
    list_editable = ("muc_tin_nhiem",)
    ordering = ("ho_ten",)
    readonly_fields = ("ngay_tao", "ngay_cap_nhat")
    fieldsets = (
        ("Thông tin cá nhân", {
            "fields": (
                "ma_khach_hang",
                "ho_ten",
                "so_dien_thoai",
                "email",
                "quoc_tich",
                "dia_chi",
            )
        }),
        ("Giấy tờ", {
            "fields": ("so_cccd", "giay_phep_lai_xe")
        }),
        ("Tín nhiệm", {
            "fields": ("muc_tin_nhiem", "ly_do_blacklist")
        }),
        ("Hệ thống", {
            "fields": ("ngay_tao", "ngay_cap_nhat"),
            "classes": ("collapse",),
        }),
    )


@admin.register(DonDatTruoc)
class DonDatTruocAdmin(admin.ModelAdmin):
    list_display = (
        "ma_don_dat",
        "ma_khach_hang",
        "bien_so_xe",
        "thoi_gian_hen_nhan",
        "thoi_gian_du_kien_tra",
        "display_tien_coc_giu_cho",
        "trang_thai_don",
    )
    search_fields = ("ma_don_dat", "ma_khach_hang__ho_ten", "bien_so_xe__bien_so_xe")
    list_filter = ("trang_thai_don", "thoi_gian_hen_nhan")
    ordering = ("-ngay_tao",)
    readonly_fields = ("ngay_tao", "ngay_cap_nhat")
    autocomplete_fields = ("ma_khach_hang", "bien_so_xe")

    @admin.display(description="Tiền cọc giữ chỗ")
    def display_tien_coc_giu_cho(self, obj):
        val = getattr(obj, "tien_coc_giu_cho", 0) or 0
        return f"{val:,.0f} VNĐ"


@admin.register(HopDongThue)
class HopDongThueAdmin(admin.ModelAdmin):
    list_display = (
        "ma_hop_dong",
        "ma_khach_hang",
        "bien_so_xe",
        "ngay_bat_dau",
        "ngay_ket_thuc_du_kien",
        "trang_thai_hop_dong",
        "trang_thai_thanh_toan",
        "hinh_thuc_dat_coc",
        "tong_tien_thanh_toan",
    )
    search_fields = (
        "ma_hop_dong",
        "ma_khach_hang__ho_ten",
        "bien_so_xe__bien_so_xe",
        "ma_nhan_vien__ho_ten",
    )
    list_filter = (
        "trang_thai_hop_dong",
        "trang_thai_thanh_toan",
        "hinh_thuc_dat_coc",
        "ngay_bat_dau",
    )
    list_editable = ("trang_thai_hop_dong", "trang_thai_thanh_toan")
    ordering = ("-ngay_tao",)
    readonly_fields = ("ngay_tao", "ngay_cap_nhat")
    autocomplete_fields = ("ma_khach_hang", "bien_so_xe", "ma_nhan_vien", "ma_don_dat")

    fieldsets = (
        ("Thông tin cơ bản", {
            "fields": (
                "ma_hop_dong",
                "ma_khach_hang",
                "bien_so_xe",
                "ma_nhan_vien",
                "ma_don_dat",
            )
        }),
        ("Thời gian thuê", {
            "fields": (
                "ngay_bat_dau",
                "ngay_ket_thuc_du_kien",
                "ngay_ket_thuc_thuc_te",
                "so_ngay_thue",
            )
        }),
        ("Tài chính & Cọc", {
            "fields": (
                "don_gia_ap_dung",
                "tien_coc_quy_dinh",
                "hinh_thuc_dat_coc",
                "so_tien_coc_thuc_thu",
                "phu_phi",
                "tong_tien_thanh_toan",
                "trang_thai_thanh_toan",
            )
        }),
        ("Trạng thái & Ghi chú", {
            "fields": (
                "trang_thai_hop_dong",
                "chu_ky_khach_hang",
                "ghi_chu",
            )
        }),
        ("Hệ thống", {
            "fields": ("ngay_tao", "ngay_cap_nhat"),
            "classes": ("collapse",),
        }),
    )


@admin.register(ThanhToan)
class ThanhToanAdmin(admin.ModelAdmin):
    list_display = (
        "ma_thanh_toan",
        "ma_hop_dong",
        "ma_nhan_vien",
        "so_tien",
        "loai_thanh_toan",
        "hinh_thuc",
        "trang_thai",
        "thoi_gian_thanh_toan",
    )
    search_fields = ("ma_thanh_toan", "ma_hop_dong__ma_hop_dong", "ma_giao_dich")
    list_filter = ("loai_thanh_toan", "hinh_thuc", "trang_thai")
    ordering = ("-thoi_gian_thanh_toan",)
    readonly_fields = ("ngay_tao",)
    autocomplete_fields = ("ma_hop_dong", "ma_nhan_vien")


class HinhAnhBienBanInline(admin.TabularInline):
    model = HinhAnhBienBan
    extra = 0
    fields = ("hinh_anh", "mo_ta", "ngay_tai_len")
    readonly_fields = ("ngay_tai_len",)

@admin.register(BienBanBanGiao)
class BienBanBanGiaoAdmin(admin.ModelAdmin):
    list_display = (
        "ma_bien_ban",
        "ma_hop_dong",
        "loai_bien_ban",
        "thoi_diem_thuc_hien",
        "so_km_odo",
        "phu_phi_tre_gio",
        "tien_hoan_coc",
    )
    search_fields = (
        "ma_bien_ban",
        "ma_hop_dong__ma_hop_dong",
        "ma_token_tra_cuu",
    )
    list_filter = ("loai_bien_ban", "thoi_diem_thuc_hien")
    ordering = ("-thoi_diem_thuc_hien",)
    readonly_fields = ("ngay_tao",)
    autocomplete_fields = ("ma_hop_dong", "ma_nhan_vien")
    inlines = (HinhAnhBienBanInline,)

    fieldsets = (
        ("Thông tin biên bản", {
            "fields": (
                "ma_bien_ban",
                "ma_hop_dong",
                "ma_nhan_vien",
                "loai_bien_ban",
                "thoi_diem_thuc_hien",
            )
        }),
        ("Tình trạng xe", {
            "fields": (
                "so_km_odo",
                "muc_vach_xang",
                "tinh_trang_ngoai_quan",
                "hinh_anh_xe",
            )
        }),
        ("Tài chính", {
            "fields": (
                "phu_phi_tre_gio",
                "tien_hoan_coc",
            )
        }),
        ("Khác", {
            "fields": (
                "ma_token_tra_cuu",
                "ghi_chu",
                "chu_ky_khach_hang",
                "ngay_tao",
            )
        }),
    )


class HinhAnhBaoDuongInline(admin.TabularInline):
    model = HinhAnhBaoDuong
    extra = 0
    fields = ("tep_anh", "giai_doan", "ghi_chu", "ngay_tai_len")
    readonly_fields = ("ngay_tai_len",)


@admin.register(NhatKyBaoDuong)
class NhatKyBaoDuongAdmin(admin.ModelAdmin):
    list_display = (
        "ma_phieu_bao_duong",
        "bien_so_xe",
        "ma_nhan_vien",
        "ngay_bao_duong",
        "ngay_hoan_thanh",
        "chi_phi",
        "trang_thai",
    )
    search_fields = ("ma_phieu_bao_duong", "bien_so_xe__bien_so_xe", "noi_dung", "noi_dung_sua_chua")
    list_filter = ("trang_thai", "loai_bao_duong", "muc_do_uu_tien", "ngay_bao_duong")
    ordering = ("-ngay_bao_duong",)
    readonly_fields = ("ngay_tao",)
    autocomplete_fields = ("bien_so_xe", "ma_nhan_vien")
    inlines = (HinhAnhBaoDuongInline,)
    fieldsets = (
        ("Thông tin phiếu", {
            "fields": (
                "ma_phieu_bao_duong", "bien_so_xe", "ma_nhan_vien",
                "loai_bao_duong", "muc_do_uu_tien", "don_vi_sua_chua",
                "ngay_bao_duong", "odo_luc_bao_duong", "reset_odo_luy_ke",
                "trang_thai",
            )
        }),
        ("Kiểm tra và xử lý kỹ thuật", {
            "fields": (
                "hang_muc_kiem_tra", "tinh_trang_phat_hien",
                "noi_dung_sua_chua", "ket_qua_xu_ly", "noi_dung",
            )
        }),
        ("Chi phí", {
            "fields": ("chi_phi_phu_tung", "chi_phi_khac", "chi_phi")
        }),
        ("Hoàn thành", {
            "fields": ("ngay_hoan_thanh", "odo_hoan_thanh")
        }),
        ("Hệ thống", {
            "fields": ("ngay_tao",),
            "classes": ("collapse",),
        }),
    )


@admin.register(NhatKyVanHanhXe)
class NhatKyVanHanhXeAdmin(admin.ModelAdmin):
    list_display = (
        "bien_so_xe",
        "tu_trang_thai",
        "den_trang_thai",
        "odo_ghi_nhan",
        "muc_nhien_lieu_pin",
        "ma_nhan_vien",
        "thoi_gian",
    )
    list_filter = ("den_trang_thai", "thoi_gian")
    search_fields = ("bien_so_xe__bien_so_xe", "ghi_chu")
    readonly_fields = ("thoi_gian",)
    autocomplete_fields = ("bien_so_xe", "ma_nhan_vien")


@admin.register(HinhAnhBienBan)
class HinhAnhBienBanAdmin(admin.ModelAdmin):
    list_display = ("id", "ma_bien_ban", "mo_ta", "ngay_tai_len")
    search_fields = ("ma_bien_ban__ma_bien_ban", "mo_ta")
    readonly_fields = ("ngay_tai_len",)
    autocomplete_fields = ("ma_bien_ban",)