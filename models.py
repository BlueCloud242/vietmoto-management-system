from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User

# Hằng số nghiệp vụ cố định cho toàn bộ đội xe Vietmoto
DINH_MUC_BAO_DUONG_KM = 2000
NGUONG_CANH_BAO_SOM_KM = 1800


class DongXe(models.Model):
    """Dòng xe / Model xe"""
    ma_dong_xe = models.CharField(max_length=20, primary_key=True, verbose_name="Mã dòng xe")
    ten_dong_xe = models.CharField(max_length=100, verbose_name="Tên dòng xe")
    loai_xe = models.CharField(max_length=50, verbose_name="Loại xe")  # VD: Xe tay ga, Xe số, Xe điện
    LOAI_DONG_CO_CHOICES = [("XANG", "Xe xăng"), ("DIEN", "Xe điện")]
    loai_dong_co = models.CharField(
        max_length=10, choices=LOAI_DONG_CO_CHOICES, default="XANG", verbose_name="Loại động cơ"
    )
    don_gia_ngay = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Đơn giá/ngày")
    tien_coc_dinh_muc = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Tiền cọc định mức")
    mo_ta = models.TextField(blank=True, null=True, verbose_name="Mô tả")
    hinh_anh = models.ImageField(upload_to="dong_xe/", blank=True, null=True, verbose_name="Ảnh đại diện dòng xe")

    # Trường mới: Cho phép ẩn dòng xe cũ không nhập thêm nhưng vẫn giữ lịch sử
    dang_kinh_doanh = models.BooleanField(default=True, verbose_name="Đang kinh doanh")

    class Meta:
        db_table = "dong_xe"
        verbose_name = "Dòng xe"
        verbose_name_plural = "Dòng xe"

    def __str__(self):
        return f"{self.ma_dong_xe} - {self.ten_dong_xe}"


class PhuongTien(models.Model):
    """Phương tiện (xe cụ thể)"""
    TRANG_THAI_CHOICES = [
        ("CON_TRONG", "Còn trống"),
        ("DANG_THUE", "Đang thuê"),
        ("CHO_VE_SINH", "Chờ rửa xe / Sạc pin"),  # Mới: Trạng thái đệm sau khi khách trả xe
        ("BAO_DUONG", "Bảo dưỡng"),
        ("NGUNG_HOAT_DONG", "Ngưng hoạt động"),
    ]

    bien_so_xe = models.CharField(max_length=15, primary_key=True, verbose_name="Biển số xe")
    ma_dong_xe = models.ForeignKey(
        DongXe, on_delete=models.PROTECT, related_name="danh_sach_xe", verbose_name="Dòng xe"
    )
    trang_thai_xe = models.CharField(
        max_length=30, choices=TRANG_THAI_CHOICES, default="CON_TRONG", db_index=True, verbose_name="Trạng thái xe"
    )

    # Giữ nguyên cơ chế tính ODO cũ (odo_luy_ke_bao_duong cộng dồn từ 0 -> 2000)
    odo_hien_tai = models.PositiveIntegerField(default=0, verbose_name="ODO hiện tại")
    odo_luy_ke_bao_duong = models.PositiveIntegerField(default=0, verbose_name="ODO lũy kế bảo dưỡng")

    # Trường mới: Kiểm soát tình trạng thực tế tại bãi & Tài sản
    muc_nhien_lieu_pin = models.PositiveSmallIntegerField(
        default=100, verbose_name="Mức xăng/pin (%)", help_text="Từ 0 đến 100%"
    )
    ghi_chu_tinh_trang = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Ghi chú tình trạng xe"
    )
    ngay_mua = models.DateField(blank=True, null=True, verbose_name="Ngày mua xe")
    gia_tri_mua = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="Giá trị mua ban đầu"
    )

    # Thông tin giấy tờ & kỹ thuật cũ
    han_bao_hiem = models.DateField(blank=True, null=True, verbose_name="Hạn bảo hiểm")
    hinh_anh = models.ImageField(
        upload_to='phuong_tien/',
        blank=True,
        null=True,
        verbose_name="Hình ảnh xe"
    )
    so_khung = models.CharField(max_length=50, blank=True, null=True, verbose_name="Số khung")
    so_may = models.CharField(max_length=50, blank=True, null=True, verbose_name="Số máy")
    nam_san_xuat = models.PositiveIntegerField(blank=True, null=True, verbose_name="Năm sản xuất")
    ngay_tao = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    ngay_cap_nhat = models.DateTimeField(auto_now=True, verbose_name="Ngày cập nhật")

    class Meta:
        db_table = "phuong_tien"
        verbose_name = "Phương tiện"
        verbose_name_plural = "Phương tiện"

    # --- CÁC THUỘC TÍNH TÍNH TOÁN PHỤC VỤ GIAO DIỆN & CẢNH BÁO ---
    @property
    def km_con_lai_bao_duong(self):
        return max(0, DINH_MUC_BAO_DUONG_KM - self.odo_luy_ke_bao_duong)

    @property
    def canh_bao_bao_duong(self):
        """Trả về: 'QUA_HAN' (>=2000), 'SAP_DEN_HAN' (>=1800), 'BINH_THUONG'"""
        if self.odo_luy_ke_bao_duong >= DINH_MUC_BAO_DUONG_KM:
            return "QUA_HAN"
        elif self.odo_luy_ke_bao_duong >= NGUONG_CANH_BAO_SOM_KM:
            return "SAP_DEN_HAN"
        return "BINH_THUONG"

    @property
    def canh_bao_bao_hiem(self):
        """Cảnh báo hạn bảo hiểm TNDS (< 15 ngày hoặc đã hết hạn)"""
        if not self.han_bao_hiem:
            return "CHUA_CAP_NHAT"
        today = timezone.now().date()
        if self.han_bao_hiem < today:
            return "HET_HAN"
        elif self.han_bao_hiem <= today + timedelta(days=15):
            return "SAP_HET_HAN"
        return "CON_HAN"

    def __str__(self):
        return self.bien_so_xe


class NhanVien(models.Model):
    """Nhân viên"""
    VAI_TRO_CHOICES = [
        ("ADMIN", "Quản trị viên"),
        ('QUAN_LY', 'Quản lý chi nhánh'),
        ("QUAY", "Nhân viên quầy"),
        ("KY_THUAT", "Kỹ thuật viên"),
    ]
    TRANG_THAI_CHOICES = [
        ("DANG_LAM", "Đang làm việc"),
        ("NGHI_VIEC", "Nghỉ việc"),
    ]

    ma_nhan_vien = models.CharField(max_length=20, primary_key=True, verbose_name="Mã nhân viên")
    ho_ten = models.CharField(max_length=100, verbose_name="Họ tên")
    ten_dang_nhap = models.CharField(max_length=50, unique=True, verbose_name="Tên đăng nhập")
    mat_khau = models.CharField(max_length=255, verbose_name="Mật khẩu (hash)")
    vai_tro = models.CharField(max_length=30, choices=VAI_TRO_CHOICES, verbose_name="Vai trò")
    so_dien_thoai = models.CharField(max_length=15, blank=True, null=True, verbose_name="Số điện thoại")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    trang_thai = models.CharField(
        max_length=20, choices=TRANG_THAI_CHOICES, default="DANG_LAM", verbose_name="Trạng thái"
    )
    ngay_tao = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    ngay_cap_nhat = models.DateTimeField(auto_now=True, verbose_name="Ngày cập nhật")

    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="nhanvien", verbose_name="Tài khoản hệ thống"
    )
    cccd = models.CharField(max_length=20, blank=True, null=True, verbose_name="Số CCCD/CMND")
    ngay_vao_lam = models.DateField(blank=True, null=True, verbose_name="Ngày vào làm")

    class Meta:
        db_table = "nhan_vien"
        verbose_name = "Nhân viên"
        verbose_name_plural = "Nhân viên"

    def __str__(self):
        return f"{self.ma_nhan_vien} - {self.ho_ten}"


class KhachHang(models.Model):
    MUC_TIN_NHIEM_CHOICES = [
        ('TOT', 'Uy tín tốt'),
        ('CAN_LUU_Y', 'Cần lưu ý'),
        ('BLACKLIST', 'Danh sách đen'),
    ]

    ma_khach_hang = models.CharField(max_length=20, primary_key=True)
    ho_ten = models.CharField(max_length=100)
    so_dien_thoai = models.CharField(max_length=15)
    quoc_tich = models.CharField(max_length=50, blank=True, null=True)
    dia_chi = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    so_cccd = models.CharField(max_length=20, unique=True, blank=True, null=True)
    giay_phep_lai_xe = models.CharField(max_length=30, blank=True, null=True)
    muc_tin_nhiem = models.CharField(max_length=20, choices=MUC_TIN_NHIEM_CHOICES, default='TOT')
    ly_do_blacklist = models.TextField(blank=True, null=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "khach_hang"
        verbose_name = "Khách hàng"
        verbose_name_plural = "Khách hàng"

    def __str__(self):
        return f"{self.ma_khach_hang} - {self.ho_ten}"


class DonDatTruoc(models.Model):
    """Đơn đặt trước"""
    TRANG_THAI_CHOICES = [
        ("CHO_XAC_NHAN", "Chờ xác nhận"),
        ("DA_GIU_CHO", "Đã giữ chỗ"),
        ("DA_CHUYEN_HD", "Đã chuyển hợp đồng"),
        ("DA_HUY", "Đã hủy"),
        ("KHONG_DEN", "Khách không đến"),
    ]

    ma_don_dat = models.CharField(max_length=20, primary_key=True, verbose_name="Mã đơn đặt")
    ma_khach_hang = models.ForeignKey(
        KhachHang, on_delete=models.PROTECT, related_name="don_dat_truoc", verbose_name="Khách hàng"
    )
    bien_so_xe = models.ForeignKey(
        PhuongTien, on_delete=models.PROTECT, related_name="don_dat_truoc", verbose_name="Xe"
    )
    ma_nhan_vien = models.ForeignKey(
        NhanVien,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="don_dat_xu_ly",
        verbose_name="Nhân viên xử lý",
    )

    thoi_gian_hen_nhan = models.DateTimeField(verbose_name="Thời gian hẹn nhận")
    thoi_gian_du_kien_tra = models.DateTimeField(verbose_name="Thời gian dự kiến trả")

    # Chốt giá & cọc tại thời điểm đặt để tránh nhảy giá khi DongXe thay đổi đơn giá
    don_gia_du_kien = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="Đơn giá áp dụng"
    )
    tong_tien_du_kien = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="Tổng tiền thuê dự kiến"
    )
    tien_coc_giu_cho = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="Tiền cọc giữ chỗ"
    )
    da_thanh_toan_coc = models.BooleanField(
        default=False, verbose_name="Đã thu cọc giữ chỗ"
    )

    dia_diem_giao_xe = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Địa điểm giao xe"
    )
    trang_thai_don = models.CharField(
        max_length=30, choices=TRANG_THAI_CHOICES, default="CHO_XAC_NHAN", verbose_name="Trạng thái đơn"
    )
    ghi_chu = models.TextField(blank=True, null=True, verbose_name="Ghi chú")
    ly_do_huy = models.TextField(blank=True, null=True, verbose_name="Lý do hủy / Không đến")

    ngay_tao = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    ngay_cap_nhat = models.DateTimeField(auto_now=True, verbose_name="Ngày cập nhật")

    class Meta:
        db_table = "don_dat_truoc"
        verbose_name = "Đơn đặt trước"
        verbose_name_plural = "Đơn đặt trước"
        ordering = ["-ngay_tao"]

    def __str__(self):
        return f"{self.ma_don_dat} - {self.ma_khach_hang.ho_ten}"

    @property
    def tien_coc_dinh_muc(self):
        """Truy xuất định mức cọc theo dòng xe đặt"""
        if self.bien_so_xe and self.bien_so_xe.ma_dong_xe:
            return self.bien_so_xe.ma_dong_xe.tien_coc_dinh_muc
        return 0


class HopDongThue(models.Model):
    TRANG_THAI_HD_CHOICES = [
        ("CHO_BAN_GIAO", "Chờ bàn giao"),
        ("DANG_THUE", "Đang thuê"),
        ("DA_TRA", "Đã trả"),
        ("DA_HUY", "Đã hủy"),
    ]
    TRANG_THAI_TT_CHOICES = [
        ("CHUA_THANH_TOAN", "Chưa thanh toán"),
        ("DA_COC", "Đã cọc"),
        ("DA_THANH_TOAN_DU", "Đã thanh toán đủ"),
    ]
    HINH_THUC_COC_CHOICES = [
        ('TIEN_MAT', 'Đặt cọc bằng tiền mặt / Chuyển khoản'),
        ('GIU_CCCD', 'Giữ CCCD gốc (Khách Việt Nam)'),
    ]

    ma_hop_dong = models.CharField(max_length=20, primary_key=True)
    ma_khach_hang = models.ForeignKey(KhachHang, on_delete=models.PROTECT, related_name="hop_dong")
    bien_so_xe = models.ForeignKey(PhuongTien, on_delete=models.PROTECT, related_name="hop_dong")
    ma_nhan_vien = models.ForeignKey(NhanVien, on_delete=models.PROTECT, related_name="hop_dong_lap")
    ma_don_dat = models.ForeignKey(DonDatTruoc, on_delete=models.SET_NULL, null=True, blank=True, related_name="hop_dong_thue")

    trang_thai_hop_dong = models.CharField(max_length=30, choices=TRANG_THAI_HD_CHOICES, default="CHO_BAN_GIAO")
    don_gia_ap_dung = models.DecimalField(max_digits=12, decimal_places=0)
    tien_coc_quy_dinh = models.DecimalField(max_digits=12, decimal_places=0)
    hinh_thuc_dat_coc = models.CharField(max_length=30, choices=HINH_THUC_COC_CHOICES, default='TIEN_MAT')
    so_tien_coc_thuc_thu = models.DecimalField(max_digits=12, decimal_places=0, default=0)

    ngay_bat_dau = models.DateTimeField()
    ngay_ket_thuc_du_kien = models.DateTimeField()
    ngay_ket_thuc_thuc_te = models.DateTimeField(blank=True, null=True)
    so_ngay_thue = models.PositiveIntegerField(blank=True, null=True)
    phu_phi = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    tong_tien_thanh_toan = models.DecimalField(max_digits=12, decimal_places=0, blank=True, null=True)
    trang_thai_thanh_toan = models.CharField(max_length=30, choices=TRANG_THAI_TT_CHOICES, default="CHUA_THANH_TOAN")

    chu_ky_khach_hang = models.TextField(blank=True, null=True)
    ghi_chu = models.TextField(blank=True, null=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hop_dong_thue"
        verbose_name = "Hợp đồng thuê"
        verbose_name_plural = "Hợp đồng thuê"

    def __str__(self):
        return self.ma_hop_dong


class ThanhToan(models.Model):
    LOAI_TT_CHOICES = [
        ("COC", "Cọc"),
        ("THANH_TOAN_CUOI", "Thanh toán cuối"),
        ("PHU_PHI", "Phụ phí"),
        ("HOAN_COC", "Hoàn cọc"),
    ]
    HINH_THUC_CHOICES = [
        ("TIEN_MAT", "Tiền mặt"),
        ("CHUYEN_KHOAN", "Chuyển khoản"),
        ("THE", "Thẻ"),
    ]
    TRANG_THAI_CHOICES = [
        ("THANH_CONG", "Thành công"),
        ("CHO_XU_LY", "Chờ xử lý"),
        ("THAT_BAI", "Thất bại"),
    ]

    ma_thanh_toan = models.CharField(max_length=20, primary_key=True)
    ma_hop_dong = models.ForeignKey(HopDongThue, on_delete=models.PROTECT, related_name="thanh_toan")
    ma_nhan_vien = models.ForeignKey(NhanVien, on_delete=models.PROTECT, related_name="thanh_toan_thu")
    so_tien = models.DecimalField(max_digits=12, decimal_places=0)
    loai_thanh_toan = models.CharField(max_length=30, choices=LOAI_TT_CHOICES)
    hinh_thuc = models.CharField(max_length=30, choices=HINH_THUC_CHOICES)
    trang_thai = models.CharField(max_length=30, choices=TRANG_THAI_CHOICES, default="CHO_XU_LY")
    thoi_gian_thanh_toan = models.DateTimeField()
    ma_giao_dich = models.CharField(max_length=50, blank=True, null=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "thanh_toan"
        verbose_name = "Thanh toán"
        verbose_name_plural = "Thanh toán"

    def __str__(self):
        return self.ma_thanh_toan


class BienBanBanGiao(models.Model):
    LOAI_BB_CHOICES = [
        ("XUAT", "Xuất (giao xe)"),
        ("TRA", "Trả (nhận xe)"),
    ]

    ma_bien_ban = models.CharField(max_length=20, primary_key=True)
    ma_hop_dong = models.ForeignKey(HopDongThue, on_delete=models.PROTECT, related_name="bien_ban")
    ma_nhan_vien = models.ForeignKey(NhanVien, on_delete=models.PROTECT, related_name="bien_ban_lap")
    thoi_diem_thuc_hien = models.DateTimeField()
    so_km_odo = models.PositiveIntegerField()
    muc_vach_xang = models.CharField(max_length=30, blank=True, null=True)
    tinh_trang_ngoai_quan = models.TextField(blank=True, null=True)
    phu_phi_tre_gio = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    tien_hoan_coc = models.DecimalField(max_digits=12, decimal_places=0, blank=True, null=True)
    ma_token_tra_cuu = models.CharField(max_length=50, unique=True, blank=True, null=True)
    loai_bien_ban = models.CharField(max_length=10, choices=LOAI_BB_CHOICES)
    ghi_chu = models.TextField(blank=True, null=True)
    chu_ky_khach_hang = models.TextField(blank=True, null=True)
    hinh_anh_xe = models.ImageField(upload_to='bien_ban/', blank=True, null=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bien_ban_ban_giao"
        verbose_name = "Biên bản bàn giao"
        verbose_name_plural = "Biên bản bàn giao"

    def __str__(self):
        return f"{self.ma_bien_ban} ({self.loai_bien_ban})"


class NhatKyVanHanhXe(models.Model):
    """Lưu vết chuyển đổi trạng thái xe tại bãi (Giao xe -> Trả xe -> Rửa xe/Sạc pin -> Sẵn sàng)"""
    bien_so_xe = models.ForeignKey(
        PhuongTien, on_delete=models.CASCADE, related_name="nhat_ky_van_hanh", verbose_name="Biển số xe"
    )
    ma_nhan_vien = models.ForeignKey(
        NhanVien, on_delete=models.SET_NULL, null=True, blank=True, related_name="nhat_ky_van_hanh_xe", verbose_name="Nhân viên thực hiện"
    )
    thoi_gian = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian")
    tu_trang_thai = models.CharField(max_length=30, verbose_name="Từ trạng thái")
    den_trang_thai = models.CharField(max_length=30, verbose_name="Đến trạng thái")
    odo_ghi_nhan = models.PositiveIntegerField(verbose_name="ODO ghi nhận")
    muc_nhien_lieu_pin = models.PositiveSmallIntegerField(verbose_name="Mức xăng/pin (%)")
    ghi_chu = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ghi chú")

    class Meta:
        db_table = "nhat_ky_van_hanh_xe"
        verbose_name = "Nhật ký vận hành xe"
        verbose_name_plural = "Nhật ký vận hành xe"
        ordering = ["-thoi_gian"]

    def __str__(self):
        return f"{self.bien_so_xe_id}: {self.tu_trang_thai} -> {self.den_trang_thai}"


class NhatKyBaoDuong(models.Model):
    """Phiếu bảo dưỡng phương tiện"""
    TRANG_THAI_CHOICES = [
        ("HOAN_THANH", "Hoàn thành"),
        ("DANG_XU_LY", "Đang xử lý"),
    ]
    LOAI_BAO_DUONG_CHOICES = [
        ("DINH_KY", "Bảo dưỡng định kỳ"),
        ("SUA_CHUA", "Sửa chữa phát sinh"),
        ("KIEM_TRA", "Kiểm tra sự cố"),
    ]
    MUC_DO_UU_TIEN_CHOICES = [
        ("THAP", "Thấp"),
        ("BINH_THUONG", "Bình thường"),
        ("CAO", "Cao"),
        ("KHAN_CAP", "Khẩn cấp"),
    ]

    ma_phieu_bao_duong = models.CharField(max_length=20, primary_key=True, verbose_name="Mã phiếu bảo dưỡng")
    bien_so_xe = models.ForeignKey(
        PhuongTien, on_delete=models.PROTECT, related_name="nhat_ky_bao_duong", verbose_name="Xe"
    )
    ma_nhan_vien = models.ForeignKey(
        NhanVien, on_delete=models.PROTECT, related_name="phieu_bao_duong", verbose_name="Nhân viên kỹ thuật"
    )
    ngay_bao_duong = models.DateField(verbose_name="Ngày tiếp nhận")
    ngay_hoan_thanh = models.DateField(blank=True, null=True, verbose_name="Ngày hoàn thành bảo dưỡng")
    loai_bao_duong = models.CharField(
        max_length=20, choices=LOAI_BAO_DUONG_CHOICES, default="DINH_KY", verbose_name="Loại bảo dưỡng"
    )
    muc_do_uu_tien = models.CharField(
        max_length=20, choices=MUC_DO_UU_TIEN_CHOICES, default="BINH_THUONG", verbose_name="Mức độ ưu tiên"
    )
    odo_luc_bao_duong = models.PositiveIntegerField(blank=True, null=True, verbose_name="ODO lúc tiếp nhận")
    odo_hoan_thanh = models.PositiveIntegerField(blank=True, null=True, verbose_name="ODO khi hoàn thành")

    reset_odo_luy_ke = models.BooleanField(
        default=True,
        verbose_name="Reset ODO lũy kế về 0",
        help_text="Mặc định bật với bảo dưỡng định kỳ. Bỏ chọn nếu chỉ sửa chữa phát sinh nhỏ."
    )
    don_vi_sua_chua = models.CharField(
        max_length=150, blank=True, default="Xưởng nội bộ Vietmoto", verbose_name="Đơn vị thực hiện"
    )

    hang_muc_kiem_tra = models.JSONField(default=list, blank=True, verbose_name="Hạng mục kiểm tra")
    tinh_trang_phat_hien = models.TextField(blank=True, verbose_name="Tình trạng phát hiện")
    noi_dung_sua_chua = models.TextField(blank=True, verbose_name="Nội dung sửa chữa / thay thế")
    ket_qua_xu_ly = models.TextField(blank=True, verbose_name="Kết quả xử lý")
    noi_dung = models.TextField(verbose_name="Nội dung bảo dưỡng")

    chi_phi_phu_tung = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, validators=[MinValueValidator(0)],
        verbose_name="Chi phí phụ tùng"
    )
    chi_phi_khac = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, validators=[MinValueValidator(0)],
        verbose_name="Chi phí khác"
    )
    chi_phi = models.DecimalField(max_digits=12, decimal_places=0, blank=True, null=True, verbose_name="Tổng chi phí")
    trang_thai = models.CharField(
        max_length=30, choices=TRANG_THAI_CHOICES, default="DANG_XU_LY", verbose_name="Trạng thái xử lý"
    )
    ngay_tao = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")

    class Meta:
        db_table = "nhat_ky_bao_duong"
        verbose_name = "Phiếu bảo dưỡng"
        verbose_name_plural = "Phiếu bảo dưỡng"
        ordering = ["-ngay_tao"]

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        # 1. Tự động cộng tổng chi phí
        phu_tung = self.chi_phi_phu_tung or 0
        khac = self.chi_phi_khac or 0
        if self.chi_phi is None or (phu_tung + khac) > 0:
            self.chi_phi = phu_tung + khac

        # 2. Mặc định tắt reset ODO nếu là kiểm tra sự cố
        if is_new and self.loai_bao_duong == "KIEM_TRA":
            self.reset_odo_luy_ke = False

        # 3. Tự điền ODO lúc tiếp nhận nếu chưa nhập
        if is_new and self.odo_luc_bao_duong is None:
            self.odo_luc_bao_duong = self.bien_so_xe.odo_hien_tai

        super().save(*args, **kwargs)

        # 4. Nếu phiếu đang xử lý thì tự động khóa trạng thái xe sang BAO_DUONG
        if self.trang_thai == "DANG_XU_LY" and self.bien_so_xe.trang_thai_xe != "BAO_DUONG":
            xe = self.bien_so_xe
            trang_thai_cu = xe.trang_thai_xe
            xe.trang_thai_xe = "BAO_DUONG"
            xe.save(update_fields=["trang_thai_xe", "ngay_cap_nhat"])

            NhatKyVanHanhXe.objects.create(
                bien_so_xe=xe,
                ma_nhan_vien=self.ma_nhan_vien,
                tu_trang_thai=trang_thai_cu,
                den_trang_thai="BAO_DUONG",
                odo_ghi_nhan=xe.odo_hien_tai,
                muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
                ghi_chu=f"Đưa xe vào xưởng theo phiếu {self.ma_phieu_bao_duong}",
            )

    def hoan_thanh_phieu(self, odo_ra=None, ket_qua="", ma_nhan_vien_xac_nhan=None):
        """Hoàn tất phiếu bảo dưỡng, cập nhật ODO mới nhất và mở khóa xe về CON_TRONG"""
        xe = self.bien_so_xe
        odo_tiep_nhan = self.odo_luc_bao_duong or xe.odo_hien_tai
        odo_thuc_te_ra = max(odo_tiep_nhan, odo_ra or odo_tiep_nhan)

        self.trang_thai = "HOAN_THANH"
        self.ngay_hoan_thanh = timezone.now().date()
        self.odo_hoan_thanh = odo_thuc_te_ra
        if ket_qua:
            self.ket_qua_xu_ly = ket_qua
        self.save()

        trang_thai_cu = xe.trang_thai_xe
        xe.odo_hien_tai = max(xe.odo_hien_tai, odo_thuc_te_ra)
        if self.reset_odo_luy_ke:
            xe.odo_luy_ke_bao_duong = 0
        xe.trang_thai_xe = "CON_TRONG"
        xe.save()

        NhatKyVanHanhXe.objects.create(
            bien_so_xe=xe,
            ma_nhan_vien=ma_nhan_vien_xac_nhan or self.ma_nhan_vien,
            tu_trang_thai=trang_thai_cu,
            den_trang_thai="CON_TRONG",
            odo_ghi_nhan=xe.odo_hien_tai,
            muc_nhien_lieu_pin=xe.muc_nhien_lieu_pin,
            ghi_chu=f"Hoàn thành phiếu bảo dưỡng {self.ma_phieu_bao_duong}",
        )

    def __str__(self):
        return self.ma_phieu_bao_duong


class HinhAnhBaoDuong(models.Model):
    """Nhiều hình ảnh thuộc cùng một phiếu bảo dưỡng."""
    GIAI_DOAN_CHOICES = [
        ("TRUOC", "Trước bảo dưỡng"),
        ("TRONG", "Trong bảo dưỡng"),
        ("SAU", "Sau bảo dưỡng"),
    ]

    phieu_bao_duong = models.ForeignKey(
        NhatKyBaoDuong,
        on_delete=models.CASCADE,
        related_name="hinh_anh",
        verbose_name="Phiếu bảo dưỡng",
    )
    tep_anh = models.ImageField(upload_to="bao_duong/%Y/%m/", verbose_name="Hình ảnh")
    giai_doan = models.CharField(
        max_length=10, choices=GIAI_DOAN_CHOICES, default="TRUOC", verbose_name="Giai đoạn"
    )
    ghi_chu = models.CharField(max_length=255, blank=True, verbose_name="Ghi chú")
    ngay_tai_len = models.DateTimeField(auto_now_add=True, verbose_name="Thời điểm tải lên")

    class Meta:
        db_table = "hinh_anh_bao_duong"
        verbose_name = "Hình ảnh bảo dưỡng"
        verbose_name_plural = "Hình ảnh bảo dưỡng"
        ordering = ("ngay_tai_len",)

    def __str__(self):
        return f"{self.phieu_bao_duong_id} - {self.get_giai_doan_display()}"


class HinhAnhBienBan(models.Model):
    ma_bien_ban = models.ForeignKey(
        BienBanBanGiao,
        on_delete=models.CASCADE,
        related_name='hinh_anh_list',
        verbose_name="Biên bản bàn giao"
    )
    hinh_anh = models.ImageField(
        upload_to='bien_ban_xe/',
        verbose_name="Hình ảnh hiện trạng xe"
    )
    mo_ta = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Mô tả góc chụp"
    )
    ngay_tai_len = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Thời điểm tải lên"
    )

    class Meta:
        db_table = 'hinh_anh_bien_ban'
        verbose_name = "Hình ảnh biên bản bàn giao"
        verbose_name_plural = "Hình ảnh biên bản bàn giao"
        ordering = ['id']

    def __str__(self):
        return f"Ảnh {self.ma_bien_ban_id} (#{self.id})"