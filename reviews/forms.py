from datetime import timedelta
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
import math
import pycountry
from django.forms.widgets import ClearableFileInput
from .models import KhachHang, HopDongThue, PhuongTien, BienBanBanGiao, NhanVien, DonDatTruoc, DongXe, NhatKyBaoDuong


class MultipleFileInput(ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'multiple': 'multiple', 'accept': 'image/*'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


# ==============================================================================
# 1. HẰNG SỐ LỰA CHỌN
# ==============================================================================
ALL_COUNTRIES = [('Việt Nam', '🇻🇳 Việt Nam')] + [
    (c.name, c.name) for c in sorted(pycountry.countries, key=lambda x: x.name)
    if c.name not in ('Viet Nam', 'Vietnam')
]

MUC_XANG_CHOICES = [
    ('1/4', '1/4 bình'),
    ('1/2', '1/2 bình'),
    ('3/4', '3/4 bình'),
    ('Đầy bình', 'Đầy bình xăng'),
]


# ==============================================================================
# 2. KHÁCH HÀNG
# ==============================================================================
class KhachHangForm(forms.ModelForm):
    ma_khach_hang = forms.CharField(
        label="Mã khách hàng",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-light text-secondary fw-bold',
            'readonly': 'readonly',
            'placeholder': 'Hệ thống tự gán...'
        })
    )

    giay_phep_lai_xe = forms.CharField(
        label="Giấy phép lái xe (GPLX)",
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập số GPLX (Bắt buộc)'})
    )

    quoc_tich = forms.ChoiceField(
        choices=ALL_COUNTRIES,
        initial='Việt Nam',
        label="Quốc tịch",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = KhachHang
        fields = [
            'ma_khach_hang', 'ho_ten', 'so_dien_thoai', 'quoc_tich',
            'dia_chi', 'email', 'so_cccd', 'giay_phep_lai_xe',
            'muc_tin_nhiem', 'ly_do_blacklist'
        ]
        widgets = {
            'ho_ten': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập họ và tên'}),
            'so_dien_thoai': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'VD: 0905123456'}),
            'dia_chi': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Địa chỉ lưu trú / khách sạn'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
            'so_cccd': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số CCCD / Hộ chiếu'}),
            'muc_tin_nhiem': forms.Select(attrs={'class': 'form-select form-select-sm text-dark fw-semibold'}),
            'ly_do_blacklist': forms.Textarea(attrs={
                'class': 'form-control form-control-sm',
                'rows': 2,
                'placeholder': 'Nhập chi tiết lý do đưa vào danh sách đen hoặc lưu ý...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Khi tạo mới (chưa có pk), không bắt buộc phải gửi muc_tin_nhiem lên từ HTML
        if not self.instance.pk:
            self.fields['muc_tin_nhiem'].required = False
            self.fields['ly_do_blacklist'].required = False

    def clean_so_dien_thoai(self):
        sdt = (self.cleaned_data.get('so_dien_thoai') or '').strip()
        qs = KhachHang.objects.filter(so_dien_thoai=sdt)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Số điện thoại {sdt} đã thuộc về khách hàng {qs.first().ho_ten} ({qs.first().ma_khach_hang}).")
        return sdt

    def clean_so_cccd(self):
        val = (self.cleaned_data.get('so_cccd') or '').strip().upper()
        if not val:
            return None
        qs = KhachHang.objects.filter(so_cccd=val)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Số CCCD/Hộ chiếu {val} đã tồn tại trên hệ thống ({qs.first().ho_ten}).")
        return val

    def clean_giay_phep_lai_xe(self):
        return (self.cleaned_data.get('giay_phep_lai_xe') or '').strip().upper()

    def clean(self):
        cleaned_data = super().clean()
        muc_tn = cleaned_data.get('muc_tin_nhiem')
        ly_do = (cleaned_data.get('ly_do_blacklist') or '').strip()
        if muc_tn in ('BLACKLIST', 'CAN_LUU_Y') and not ly_do:
            self.add_error('ly_do_blacklist', "Vui lòng nhập rõ lý do lưu ý hoặc đưa khách hàng vào danh sách đen.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.ma_khach_hang:
            last_kh = KhachHang.objects.filter(ma_khach_hang__startswith='KH').get_next_customer_id()
            if last_kh and last_kh.ma_khach_hang[2:].isdigit():
                next_num = int(last_kh.ma_khach_hang[2:]) + 1
            else:
                next_num = 1
            instance.ma_khach_hang = f"KH{next_num:04d}"

        if instance._state.adding:
            instance.muc_tin_nhiem = 'TOT'
            instance.ly_do_blacklist = ''

        if commit:
            instance.save()
        return instance


# ==============================================================================
# 3. HỢP ĐỒNG
# ==============================================================================
class HopDongThueCreateForm(forms.ModelForm):
    """Form lập hợp đồng thuê xe tại quầy"""

    hinh_thuc_dat_coc = forms.ChoiceField(
        label="Phương thức cọc bảo đảm",
        choices=[
            ('GIU_CCCD', 'Giữ CCCD gốc'),
            ('TIEN_MAT', 'Đặt cọc tiền'),
        ],
        initial='GIU_CCCD',
        widget=forms.Select(attrs={'class': 'form-select text-dark fw-bold', 'id': 'id_hinh_thuc_dat_coc'})
    )

    ma_hop_dong = forms.CharField(
        label="Mã hợp đồng",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-light text-secondary fw-bold font-monospace',
            'readonly': 'readonly',
            'placeholder': 'Hệ thống tự gán...'
        })
    )

    ma_khach_hang = forms.ModelChoiceField(
        queryset=KhachHang.objects.all(),
        widget=forms.HiddenInput(attrs={'id': 'id_ma_khach_hang'}),
        error_messages={'required': 'Vui lòng nhập đúng số điện thoại khách hàng đã có trong hệ thống.'}
    )

    don_gia_ap_dung = forms.DecimalField(
        label="Đơn giá ngày áp dụng (VNĐ/ngày)",
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control bg-light text-dark fw-bold',
            'readonly': 'readonly',
            'id': 'id_don_gia_ap_dung',
            'placeholder': 'Tự động theo xe...'
        })
    )

    tien_coc_quy_dinh = forms.DecimalField(
        label="Tiền cọc quy định (VNĐ)",
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control bg-light text-dark fw-bold',
            'readonly': 'readonly',
            'id': 'id_tien_coc_quy_dinh',
            'placeholder': 'Tự động theo xe...'
        })
    )

    hinh_thuc_thanh_toan = forms.ChoiceField(
        label="Hình thức thanh toán tại quầy",
        choices=[
            ('CHUYEN_KHOAN', 'Chuyển khoản QR'),
            ('TIEN_MAT', 'Tiền mặt'),
            ('THE', 'Quẹt thẻ POS'),
        ],
        initial='CHUYEN_KHOAN',
        widget=forms.Select(attrs={'class': 'form-select text-dark fw-semibold'})
    )

    ghi_chu_hop_dong = forms.CharField(
        label="Ghi chú giao nhận / Yêu cầu thêm",
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ghi chú địa điểm giao xe, số lượng mũ bảo hiểm hoặc mã giao dịch...'
        })
    )

    class Meta:
        model = HopDongThue
        fields = [
            'ma_hop_dong', 'ma_khach_hang', 'bien_so_xe',
            'ngay_bat_dau', 'ngay_ket_thuc_du_kien',
            'don_gia_ap_dung', 'tien_coc_quy_dinh'
        ]
        widgets = {
            'bien_so_xe': forms.Select(attrs={
                'class': 'form-select text-dark fw-semibold',
                'id': 'select-xe'
            }),
            'ngay_bat_dau': forms.DateTimeInput(
                attrs={
                    'class': 'form-control text-dark fw-semibold',
                    'type': 'datetime-local',
                    'id': 'id_ngay_bat_dau'
                }
            ),
            'ngay_ket_thuc_du_kien': forms.DateTimeInput(
                attrs={
                    'class': 'form-control text-dark fw-semibold',
                    'type': 'datetime-local',
                    'id': 'id_ngay_ket_thuc_du_kien'
                }
            ),
        }

    def __init__(self, *args, don_dat=None, **kwargs):
        self.don_dat = don_dat
        super().__init__(*args, **kwargs)
        qs = PhuongTien.objects.filter(trang_thai_xe='CON_TRONG').select_related('ma_dong_xe').order_by('bien_so_xe')
        if self.don_dat and self.don_dat.bien_so_xe_id:
            qs = PhuongTien.objects.filter(
                Q(trang_thai_xe='CON_TRONG') | Q(pk=self.don_dat.bien_so_xe_id)
            ).select_related('ma_dong_xe').order_by('bien_so_xe')
            if not self.is_bound:
                self.initial.setdefault('ma_khach_hang', self.don_dat.ma_khach_hang_id)
                self.initial.setdefault('bien_so_xe', self.don_dat.bien_so_xe_id)
                self.initial.setdefault('ngay_bat_dau', timezone.localtime(self.don_dat.thoi_gian_hen_nhan).strftime('%Y-%m-%dT%H:%M'))
                self.initial.setdefault('ngay_ket_thuc_du_kien', timezone.localtime(self.don_dat.thoi_gian_du_kien_tra).strftime('%Y-%m-%dT%H:%M'))
                self.initial.setdefault('don_gia_ap_dung', self.don_dat.bien_so_xe.ma_dong_xe.don_gia_ngay)
                self.initial.setdefault('tien_coc_quy_dinh', self.don_dat.bien_so_xe.ma_dong_xe.tien_coc_dinh_muc)

        self.fields['bien_so_xe'].queryset = qs
        # Hiển thị "Biển số · Tên loại xe" giống hệt trang tạo đơn đặt trước
        self.fields['bien_so_xe'].label_from_instance = (
            lambda obj: f"{obj.bien_so_xe} · {obj.ma_dong_xe.ten_dong_xe}"
        )

    def clean(self):
        cleaned_data = super().clean()
        ngay_bd = cleaned_data.get('ngay_bat_dau')
        ngay_kt = cleaned_data.get('ngay_ket_thuc_du_kien')
        khach_hang = cleaned_data.get('ma_khach_hang')
        bien_so_xe = cleaned_data.get('bien_so_xe')

        if bien_so_xe and ngay_bd and ngay_kt:
            dat_xe_qs = DonDatTruoc.objects.filter(
                bien_so_xe=bien_so_xe,
                trang_thai_don__in=['DA_GIU_CHO', 'CHO_XAC_NHAN'],
                thoi_gian_hen_nhan__lt=ngay_kt,
                thoi_gian_du_kien_tra__gt=ngay_bd,
            )
            if self.don_dat:
                dat_xe_qs = dat_xe_qs.exclude(pk=self.don_dat.pk)

            dat_xe_truoc = dat_xe_qs.order_by('thoi_gian_hen_nhan').first()
            if dat_xe_truoc:
                raise ValidationError(
                    f"Xe này đã có khách đặt trước lấy lúc {timezone.localtime(dat_xe_truoc.thoi_gian_hen_nhan).strftime('%H:%M %d/%m')}. "
                    f"Vui lòng chọn xe khác hoặc giảm số ngày thuê!"
                )

            hd_trung_qs = HopDongThue.objects.filter(
                bien_so_xe=bien_so_xe,
                trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE'],
                ngay_bat_dau__lt=ngay_kt,
                ngay_ket_thuc_du_kien__gt=ngay_bd,
            )
            if self.instance.pk:
                hd_trung_qs = hd_trung_qs.exclude(pk=self.instance.pk)

            hd_trung = hd_trung_qs.order_by('ngay_bat_dau').first()
            if hd_trung:
                raise ValidationError(
                    f"Xe {bien_so_xe.bien_so_xe} đã thuộc HĐ {hd_trung.ma_hop_dong} "
                    f"(đến {timezone.localtime(hd_trung.ngay_ket_thuc_du_kien).strftime('%H:%M %d/%m')})."
                )

        if ngay_bd and ngay_kt and ngay_kt <= ngay_bd:
            raise ValidationError("Thời điểm hẹn trả phải sau thời điểm nhận xe.")

        if khach_hang and getattr(khach_hang, 'muc_tin_nhiem', '') == 'BLACKLIST':
            raise ValidationError(
                f"CẢNH BÁO: Khách hàng {khach_hang.ho_ten} nằm trong danh sách Blacklist "
                f"(Từ chối phục vụ). Không được phép lập hợp đồng!"
            )

        if khach_hang:
            hd_active = HopDongThue.objects.filter(
                ma_khach_hang=khach_hang,
                trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE']
            )
            if self.instance.pk:
                hd_active = hd_active.exclude(pk=self.instance.pk)
            if hd_active.exists():
                active = hd_active.first()
                raise ValidationError(
                    f"Khách hàng {khach_hang.ho_ten} hiện đang thuê xe "
                    f"{active.bien_so_xe.bien_so_xe} (HĐ: {active.ma_hop_dong}). "
                    f"Hệ thống chỉ cho phép mỗi khách hàng thuê đúng 1 xe!"
                )
        return cleaned_data


class GiaHanHopDongForm(forms.Form):
    ngay_ket_thuc_moi = forms.DateTimeField(
        label="Thời điểm kết thúc mới (Giờ & Ngày)",
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control text-dark fw-bold',
            'type': 'datetime-local',
            'id': 'id_ngay_ket_thuc_moi'
        })
    )

    hinh_thuc_thanh_toan = forms.ChoiceField(
        label="Hình thức thanh toán cước phát sinh",
        choices=[
            ('TIEN_MAT', 'Tiền mặt'),
            ('CHUYEN_KHOAN', 'Chuyển khoản QR'),
            ('THE', 'Quẹt thẻ POS'),
        ],
        initial='CHUYEN_KHOAN',
        widget=forms.Select(attrs={'class': 'form-select text-dark fw-semibold'})
    )

    ghi_chu_gia_han = forms.CharField(
        label="Ghi chú gia hạn",
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ghi chú lý do gia hạn của khách hoặc mã giao dịch chuyển khoản...'
        })
    )

    def __init__(self, hop_dong, *args, **kwargs):
        self.hop_dong = hop_dong
        super().__init__(*args, **kwargs)

    def clean_ngay_ket_thuc_moi(self):
        ngay_moi = self.cleaned_data.get('ngay_ket_thuc_moi')
        if ngay_moi and ngay_moi <= self.hop_dong.ngay_ket_thuc_du_kien:
            raise forms.ValidationError(
                "Thời điểm gia hạn mới phải sau hạn trả dự kiến hiện tại."
            )
        return ngay_moi


# ==============================================================================
# 4. BIÊN BẢN
# ==============================================================================
class BienBanTraXeForm(forms.ModelForm):
    ma_bien_ban = forms.CharField(
        label="Mã biên bản thu hồi",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-light text-secondary fw-bold',
            'readonly': 'readonly',
            'placeholder': 'Hệ thống tự gán...'
        })
    )

    muc_vach_xang = forms.ChoiceField(
        choices=MUC_XANG_CHOICES,
        label="Mức vạch xăng lúc trả",
        widget=forms.Select(attrs={'class': 'form-select text-dark fw-semibold', 'id': 'id_muc_xang_tra'})
    )

    phu_phi_tre_gio = forms.DecimalField(
        label="Phụ phí trả trễ (VNĐ)",
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control text-dark fw-bold', 'id': 'id_phu_phi_tre'})
    )

    khau_tru_hu_hai = forms.DecimalField(
        label="Khấu trừ hư hại / hao hụt xăng (VNĐ)",
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control text-dark fw-bold', 'id': 'id_khau_tru_hu_hai'})
    )

    tien_hoan_coc = forms.DecimalField(
        label="Tiền cọc thực tế hoàn trả khách (VNĐ)",
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control bg-light text-success fw-bold fs-5',
            'readonly': 'readonly',
            'id': 'id_tien_hoan_coc'
        })
    )

    hinh_thuc_hoan_coc = forms.ChoiceField(
        label="Hình thức hoàn trả tiền cọc",
        choices=[
            ('TIEN_MAT', 'Tiền mặt'),
            ('CHUYEN_KHOAN', 'Chuyển khoản QR'),
        ],
        initial='TIEN_MAT',
        widget=forms.Select(attrs={'class': 'form-select text-dark fw-semibold'})
    )

    hinh_anh_xe = MultipleFileField(
        label="Tải lên hình ảnh hiện trạng xe lúc nhận lại",
        required=True
    )

    class Meta:
        model = BienBanBanGiao
        fields = [
            'ma_bien_ban', 'ma_nhan_vien', 'so_km_odo', 'muc_vach_xang',
            'phu_phi_tre_gio', 'tinh_trang_ngoai_quan', 'hinh_anh_xe', 'ghi_chu'
        ]
        widgets = {
            'ma_nhan_vien': forms.Select(attrs={'class': 'form-select text-dark fw-semibold'}),
            'so_km_odo': forms.NumberInput(attrs={
                'class': 'form-control text-dark fw-bold',
                'id': 'id_odo_tra'
            }),
            'tinh_trang_ngoai_quan': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ghi nhận hiện trạng sau khi kiểm tra (trầy xước mới, nứt vỡ, thiếu mũ bảo hiểm)...'
            }),
            'ghi_chu': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class BienBanXuatBaiForm(forms.ModelForm):
    ma_bien_ban = forms.CharField(
        label="Mã biên bản xuất bãi",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-light text-secondary fw-bold',
            'readonly': 'readonly'
        })
    )

    muc_vach_xang = forms.ChoiceField(
        label="Nhiên liệu / Dung lượng Pin lúc giao",
        widget=forms.Select(attrs={
            'class': 'form-select text-dark fw-bold',
            'id': 'id_nhien_lieu_giao'
        })
    )

    so_mu_bao_hiem = forms.ChoiceField(
        label="Số mũ bảo hiểm kèm theo",
        choices=[
            ('2', '02 mũ bảo hiểm đạt chuẩn'),
            ('1', '01 mũ bảo hiểm'),
            ('0', 'Không lấy mũ')
        ],
        initial='2',
        widget=forms.Select(attrs={'class': 'form-select text-dark fw-semibold'})
    )

    du_hai_guong = forms.BooleanField(
        label="Đủ 02 gương chiếu hậu đạt chuẩn",
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    giay_to_xe = forms.BooleanField(
        label="Đã bàn giao Cavet công chứng + BH TNDS",
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    kem_bo_sac = forms.BooleanField(
        label="Đã kèm bộ sạc xe điện chính hãng (đối với xe điện)",
        initial=False,
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_kem_bo_sac'
        })
    )

    tinh_trang_ngoai_quan = forms.CharField(
        label="Tình trạng ngoại quan phương tiện lúc giao",
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control text-dark',
            'rows': 2,
            'placeholder': 'Ghi nhận các vết xước có sẵn, tình trạng lốp, phanh, đèn còi (bắt buộc)...'
        }),
        error_messages={
            'required': 'Vui lòng nhập ghi nhận ngoại quan phương tiện lúc giao để làm căn cứ đối soát.'
        }
    )

    hinh_anh_xe = MultipleFileField(
        label="Tải lên hình ảnh hiện trạng xe (4 góc xe)",
        required=True,
        error_messages={
            'required': 'Vui lòng chọn ít nhất một hình ảnh hiện trạng xe trước khi xuất bãi.'
        }
    )

    xac_nhan_ban_giao = forms.BooleanField(
        label="Xác nhận phương tiện đủ điều kiện an toàn, khách hàng đã kiểm tra thực tế và đồng ý nhận xe xuất bãi.",
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input border-danger',
            'style': 'width: 1.25rem; height: 1.25rem;'
        }),
        error_messages={
            'required': 'Cần tích chọn xác nhận phương tiện đủ điều kiện an toàn và khách đồng ý nhận xe.'
        }
    )

    class Meta:
        model = BienBanBanGiao
        fields = [
            'ma_bien_ban', 'so_km_odo', 'muc_vach_xang',
            'tinh_trang_ngoai_quan', 'hinh_anh_xe', 'ghi_chu'
        ]
        widgets = {
            'so_km_odo': forms.NumberInput(attrs={'class': 'form-control text-dark fw-bold'}),
            'ghi_chu': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ghi chú thêm...'
            }),
        }

    def __init__(self, *args, **kwargs):
        is_xe_dien = kwargs.pop('is_xe_dien', False)
        super().__init__(*args, **kwargs)

        if is_xe_dien:
            self.fields['muc_vach_xang'].choices = [
                ('100% Pin (Đầy)', '100% Pin (Đầy bình)'),
                ('75% Pin', '75% Pin'),
                ('50% Pin', '50% Pin'),
                ('Dưới 50% Pin', '⚠️ Dưới 50% Pin (Cần sạc thêm)'),
            ]
            self.fields['muc_vach_xang'].label = "Dung lượng Pin lúc giao (%)"
            self.fields['kem_bo_sac'].initial = True
        else:
            self.fields['muc_vach_xang'].choices = [
                ('Đầy bình xăng', 'Đầy bình xăng'),
                ('3/4', '3/4 bình xăng'),
                ('1/2', '1/2 bình xăng'),
                ('1/4', '1/4 bình xăng'),
            ]
            self.fields['muc_vach_xang'].label = "Mức vạch xăng lúc giao"


# ==============================================================================
# 5. ĐƠN ĐẶT TRƯỚC
# ==============================================================================
class DonDatTruocForm(forms.ModelForm):
    """Biểu mẫu tạo đơn đặt xe trước (đồng bộ với form lập hợp đồng)"""
    BUFFER_MINUTES = 60
    FIXED_BOOKING_DEPOSIT = 100000  # 100k cố định cho tất cả đơn giữ chỗ

    ma_don_dat = forms.CharField(
        label="Mã đơn đặt",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-light text-secondary fw-bold font-monospace',
            'readonly': 'readonly',
            'placeholder': 'Hệ thống tự gán...'
        })
    )

    class Meta:
        model = DonDatTruoc
        fields = [
            'ma_don_dat', 'ma_khach_hang', 'bien_so_xe',
            'thoi_gian_hen_nhan', 'thoi_gian_du_kien_tra',
            'tien_coc_giu_cho', 'da_thanh_toan_coc', 'trang_thai_don',
            'dia_diem_giao_xe', 'ghi_chu'
        ]
        widgets = {
            'ma_khach_hang': forms.HiddenInput(attrs={'id': 'id_ma_khach_hang'}),
            'bien_so_xe': forms.Select(attrs={'class': 'form-select text-dark fw-semibold', 'id': 'id_bien_so_xe'}),
            'thoi_gian_hen_nhan': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-control text-dark fw-semibold', 'type': 'datetime-local', 'id': 'id_thoi_gian_hen_nhan'}
            ),
            'thoi_gian_du_kien_tra': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-control text-dark fw-semibold', 'type': 'datetime-local', 'id': 'id_thoi_gian_du_kien_tra'}
            ),
            'tien_coc_giu_cho': forms.NumberInput(attrs={
                'class': 'form-control bg-light text-success fw-bold font-monospace',
                'readonly': 'readonly',
                'id': 'id_tien_coc_giu_cho',
                'value': 100000
            }),
            'da_thanh_toan_coc': forms.HiddenInput(attrs={'id': 'id_da_thanh_toan_coc'}),
            'trang_thai_don': forms.HiddenInput(attrs={'id': 'id_trang_thai_don'}),
            'dia_diem_giao_xe': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tại bãi hoặc Sân bay, Khách sạn...'
            }),
            'ghi_chu': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Yêu cầu thêm (2 mũ bảo hiểm, áo mưa, giá đỡ điện thoại...)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Chỉ lấy các phương tiện đang ở trạng thái "Trống" (CON_TRONG)
        self.fields['bien_so_xe'].queryset = (
            PhuongTien.objects.filter(trang_thai_xe='CON_TRONG')
            .select_related('ma_dong_xe')
            .order_by('bien_so_xe')
        )
        self.fields['bien_so_xe'].label_from_instance = (
            lambda obj: f"{obj.bien_so_xe} · {obj.ma_dong_xe.ten_dong_xe}"
        )

        # Chỉ có 1 trạng thái khi tạo đơn là Đã giữ chỗ (đã nộp 100k cọc)
        self.initial.setdefault('tien_coc_giu_cho', self.FIXED_BOOKING_DEPOSIT)
        self.initial.setdefault('da_thanh_toan_coc', True)
        self.initial.setdefault('trang_thai_don', 'DA_GIU_CHO')

        for f in ['tien_coc_giu_cho', 'da_thanh_toan_coc', 'trang_thai_don', 'dia_diem_giao_xe', 'ghi_chu']:
            self.fields[f].required = False

    def clean(self):
        cleaned_data = super().clean()
        khach_hang = cleaned_data.get('ma_khach_hang')
        xe = cleaned_data.get('bien_so_xe')
        hen_nhan = cleaned_data.get('thoi_gian_hen_nhan')
        du_kien_tra = cleaned_data.get('thoi_gian_du_kien_tra')

        # Ép cứng cọc 100k, đã nộp cọc & trạng thái Đã giữ chỗ
        cleaned_data['tien_coc_giu_cho'] = self.FIXED_BOOKING_DEPOSIT
        cleaned_data['da_thanh_toan_coc'] = True
        cleaned_data['trang_thai_don'] = 'DA_GIU_CHO'

        if xe and getattr(xe, 'trang_thai_xe', '') != 'CON_TRONG':
            self.add_error('bien_so_xe', f"Xe {xe.bien_so_xe} hiện không ở trạng thái Trống.")

        if khach_hang and getattr(khach_hang, 'muc_tin_nhiem', '') == 'BLACKLIST':
            ly_do = getattr(khach_hang, 'ly_do_blacklist', '') or 'Từng vi phạm nghiêm trọng hợp đồng'
            self.add_error(
                'ma_khach_hang',
                f"CẢNH BÁO: Khách hàng {khach_hang.ho_ten} thuộc danh sách Blacklist ({ly_do}). Không thể nhận đặt xe!"
            )

        if hen_nhan and du_kien_tra:
            if du_kien_tra <= hen_nhan:
                self.add_error('thoi_gian_du_kien_tra', "Thời gian trả xe dự kiến phải sau thời gian hẹn nhận xe.")
            elif hen_nhan < timezone.now() - timedelta(minutes=15):
                self.add_error('thoi_gian_hen_nhan', "Thời gian hẹn nhận xe không được nằm trong quá khứ.")

        if xe and hen_nhan and du_kien_tra and du_kien_tra > hen_nhan:
            buffer = timedelta(minutes=self.BUFFER_MINUTES)
            start_with_buffer = hen_nhan - buffer
            end_with_buffer = du_kien_tra + buffer

            trung_don = DonDatTruoc.objects.filter(
                bien_so_xe=xe,
                trang_thai_don='DA_GIU_CHO',
                thoi_gian_hen_nhan__lt=end_with_buffer,
                thoi_gian_du_kien_tra__gt=start_with_buffer,
            ).first()
            if trung_don:
                self.add_error(
                    'bien_so_xe',
                    f"Xe {xe.bien_so_xe} trùng lịch (hoặc sát giờ vệ sinh) với đơn {trung_don.ma_don_dat} "
                    f"({timezone.localtime(trung_don.thoi_gian_hen_nhan):%d/%m %H:%M} - "
                    f"{timezone.localtime(trung_don.thoi_gian_du_kien_tra):%d/%m %H:%M})."
                )

            trung_hd = HopDongThue.objects.filter(
                bien_so_xe=xe,
                trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE'],
                ngay_bat_dau__lt=end_with_buffer,
                ngay_ket_thuc_du_kien__gt=start_with_buffer,
            ).first()
            if trung_hd:
                self.add_error(
                    'bien_so_xe',
                    f"Xe {xe.bien_so_xe} đang vướng hợp đồng {trung_hd.ma_hop_dong} "
                    f"(dự kiến trả {timezone.localtime(trung_hd.ngay_ket_thuc_du_kien):%d/%m %H:%M})."
                )

        return cleaned_data

    def save(self, commit=True, nhan_vien=None):
        instance = super().save(commit=False)
        instance.tien_coc_giu_cho = self.FIXED_BOOKING_DEPOSIT
        instance.da_thanh_toan_coc = True
        instance.trang_thai_don = 'DA_GIU_CHO'

        if nhan_vien and not instance.ma_nhan_vien_id:
            instance.ma_nhan_vien = nhan_vien

        if instance.bien_so_xe and instance.bien_so_xe.ma_dong_xe:
            don_gia = instance.bien_so_xe.ma_dong_xe.don_gia_ngay or 0
            instance.don_gia_du_kien = don_gia
            if instance.thoi_gian_hen_nhan and instance.thoi_gian_du_kien_tra:
                seconds = (instance.thoi_gian_du_kien_tra - instance.thoi_gian_hen_nhan).total_seconds()
                so_ngay = max(1, math.ceil(seconds / 86400))
                instance.tong_tien_du_kien = don_gia * so_ngay

        if commit:
            instance.save()
        return instance


class DonDatTruocEditForm(forms.ModelForm):
    """Biểu mẫu cập nhật thông tin và trạng thái đơn đặt xe trước"""
    BUFFER_MINUTES = 60

    class Meta:
        model = DonDatTruoc
        fields = [
            'bien_so_xe', 'trang_thai_don',
            'thoi_gian_hen_nhan', 'thoi_gian_du_kien_tra',
            'tien_coc_giu_cho', 'da_thanh_toan_coc',
            'dia_diem_giao_xe', 'ghi_chu', 'ly_do_huy'
        ]
        widgets = {
            'bien_so_xe': forms.Select(attrs={'class': 'form-select', 'id': 'form_edit_xe'}),
            'trang_thai_don': forms.Select(attrs={'class': 'form-select', 'id': 'form_edit_trang_thai'}),
            'thoi_gian_hen_nhan': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-control', 'type': 'datetime-local', 'id': 'form_edit_start'}
            ),
            'thoi_gian_du_kien_tra': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-control', 'type': 'datetime-local', 'id': 'form_edit_end'}
            ),
            'tien_coc_giu_cho': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 10000}),
            'da_thanh_toan_coc': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'dia_diem_giao_xe': forms.TextInput(attrs={'class': 'form-control'}),
            'ghi_chu': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'ly_do_huy': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Nhập lý do nếu hủy đơn hoặc khách không đến nhận xe...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bien_so_xe'].queryset = (
            PhuongTien.objects.exclude(trang_thai_xe='NGUNG_HOAT_DONG')
            .select_related('ma_dong_xe')
            .order_by('bien_so_xe')
        )
        # Không cho chọn trực tiếp 'DA_CHUYEN_HD' khi sửa tay (phải qua luồng Lập hợp đồng)
        self.fields['trang_thai_don'].choices = [
            c for c in DonDatTruoc.TRANG_THAI_CHOICES if c[0] != 'DA_CHUYEN_HD'
        ]
        for optional_field in ['tien_coc_giu_cho', 'da_thanh_toan_coc', 'dia_diem_giao_xe', 'ghi_chu', 'ly_do_huy']:
            self.fields[optional_field].required = False

    def clean(self):
        cleaned_data = super().clean()
        xe = cleaned_data.get('bien_so_xe')
        trang_thai = cleaned_data.get('trang_thai_don')
        hen_nhan = cleaned_data.get('thoi_gian_hen_nhan')
        du_kien_tra = cleaned_data.get('thoi_gian_du_kien_tra')
        ly_do_huy = (cleaned_data.get('ly_do_huy') or '').strip()

        # Không cho phép sửa đơn đã chuyển thành hợp đồng
        if self.instance and self.instance.trang_thai_don == 'DA_CHUYEN_HD':
            raise ValidationError("Đơn đặt này đã được chuyển thành hợp đồng thuê, không thể chỉnh sửa.")

        if hen_nhan and du_kien_tra and du_kien_tra <= hen_nhan:
            self.add_error('thoi_gian_du_kien_tra', "Thời gian trả xe dự kiến phải sau thời gian hẹn nhận xe.")

        # Bắt buộc nhập lý do nếu chuyển trạng thái sang Hủy hoặc Khách không đến
        if trang_thai in ['DA_HUY', 'KHONG_DEN'] and not ly_do_huy:
            self.add_error('ly_do_huy', "Vui lòng ghi rõ lý do hủy đơn hoặc ghi nhận khách không đến.")

        # Chỉ kiểm tra trùng lịch nếu đơn vẫn đang giữ chỗ
        if xe and trang_thai in ['CHO_XAC_NHAN', 'DA_GIU_CHO'] and hen_nhan and du_kien_tra and du_kien_tra > hen_nhan:
            buffer = timedelta(minutes=self.BUFFER_MINUTES)
            start_with_buffer = hen_nhan - buffer
            end_with_buffer = du_kien_tra + buffer

            trung_don = DonDatTruoc.objects.filter(
                bien_so_xe=xe,
                trang_thai_don__in=['CHO_XAC_NHAN', 'DA_GIU_CHO'],
                thoi_gian_hen_nhan__lt=end_with_buffer,
                thoi_gian_du_kien_tra__gt=start_with_buffer,
            ).exclude(pk=self.instance.pk).first()
            if trung_don:
                self.add_error(
                    'bien_so_xe',
                    f"Xe {xe.bien_so_xe} bị trùng khung giờ (hoặc sát giờ vệ sinh) với đơn {trung_don.ma_don_dat}."
                )

            trung_hd = HopDongThue.objects.filter(
                bien_so_xe=xe,
                trang_thai_hop_dong__in=['CHO_BAN_GIAO', 'DANG_THUE'],
                ngay_bat_dau__lt=end_with_buffer,
                ngay_ket_thuc_du_kien__gt=start_with_buffer,
            ).first()
            if trung_hd:
                self.add_error(
                    'bien_so_xe',
                    f"Xe {xe.bien_so_xe} đang có hợp đồng {trung_hd.ma_hop_dong} trong khung giờ này."
                )

        if cleaned_data.get('tien_coc_giu_cho') is None:
            cleaned_data['tien_coc_giu_cho'] = 0

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Cập nhật lại đơn giá & tổng tiền dự kiến nếu có đổi xe hoặc đổi thời gian thuê
        if instance.bien_so_xe and instance.bien_so_xe.ma_dong_xe:
            don_gia = instance.bien_so_xe.ma_dong_xe.don_gia_ngay or 0
            instance.don_gia_du_kien = don_gia
            if instance.thoi_gian_hen_nhan and instance.thoi_gian_du_kien_tra:
                seconds = (instance.thoi_gian_du_kien_tra - instance.thoi_gian_hen_nhan).total_seconds()
                so_ngay = max(1, math.ceil(seconds / 86400))
                instance.tong_tien_du_kien = don_gia * so_ngay

        if commit:
            instance.save()
        return instance


# ==============================================================================
# 6. QUẢN LÝ XE & BẢO DƯỠNG (ĐÃ ĐỒNG BỘ VỚI MODELS & VIEWS MỚI)
# ==============================================================================
class DongXeForm(forms.ModelForm):
    class Meta:
        model = DongXe
        fields = [
            'ma_dong_xe', 'ten_dong_xe', 'loai_dong_co',
            'loai_xe', 'don_gia_ngay', 'tien_coc_dinh_muc',
            'dang_kinh_doanh', 'mo_ta', 'hinh_anh'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['dang_kinh_doanh'].required = False

    def clean_ma_dong_xe(self):
        return (self.cleaned_data.get('ma_dong_xe') or '').strip().upper()

    def clean_ten_dong_xe(self):
        return (self.cleaned_data.get('ten_dong_xe') or '').strip()

    def clean_dang_kinh_doanh(self):
        if 'dang_kinh_doanh' not in self.data and not self.instance.pk:
            return True
        return bool(self.cleaned_data.get('dang_kinh_doanh'))

    def clean_hinh_anh(self):
        img = self.cleaned_data.get('hinh_anh')
        if img and hasattr(img, 'content_type'):
            if not img.content_type.startswith('image/') or img.size > 8 * 1024 * 1024:
                raise ValidationError("Ảnh phải là tệp hình ảnh và không quá 8 MB.")
        return img


class PhuongTienCreateForm(forms.ModelForm):
    class Meta:
        model = PhuongTien
        fields = [
            'bien_so_xe', 'ma_dong_xe', 'trang_thai_xe',
            'odo_hien_tai', 'odo_luy_ke_bao_duong', 'muc_nhien_lieu_pin',
            'ghi_chu_tinh_trang', 'nam_san_xuat', 'so_khung', 'so_may',
            'han_bao_hiem', 'ngay_mua', 'gia_tri_mua'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for optional_field in [
            'odo_luy_ke_bao_duong', 'muc_nhien_lieu_pin', 'ghi_chu_tinh_trang',
            'nam_san_xuat', 'so_khung', 'so_may', 'han_bao_hiem', 'ngay_mua', 'gia_tri_mua'
        ]:
            self.fields[optional_field].required = False

    def clean_bien_so_xe(self):
        bien_so = (self.cleaned_data.get('bien_so_xe') or '').strip().upper()
        if not bien_so:
            raise ValidationError("Vui lòng nhập biển số xe.")
        if PhuongTien.objects.filter(bien_so_xe=bien_so).exists():
            raise ValidationError(f"Biển số xe {bien_so} đã tồn tại trong hệ thống.")
        return bien_so

    def clean_trang_thai_xe(self):
        st = self.cleaned_data.get('trang_thai_xe') or 'CON_TRONG'
        if st not in ('CON_TRONG', 'CHO_VE_SINH', 'BAO_DUONG'):
            raise ValidationError("Trạng thái khởi tạo chỉ được chọn Còn trống, Chờ vệ sinh hoặc Bảo dưỡng.")
        return st

    def clean_muc_nhien_lieu_pin(self):
        val = self.cleaned_data.get('muc_nhien_lieu_pin')
        if val is None:
            return 100
        return min(100, max(0, val))


class PhuongTienUpdateForm(forms.Form):
    bien_so_xe = forms.CharField(max_length=15)
    odo_hien_tai = forms.IntegerField(min_value=0)
    don_gia_ngay = forms.IntegerField(min_value=0)
    tien_coc = forms.IntegerField(min_value=0)
    trang_thai_xe = forms.ChoiceField(
        choices=[
            ('CON_TRONG', 'Còn trống'),
            ('CHO_VE_SINH', 'Chờ rửa xe / Sạc pin'),
            ('NGUNG_HOAT_DONG', 'Ngưng hoạt động'),
        ],
        required=False
    )
    muc_nhien_lieu_pin = forms.IntegerField(min_value=0, max_value=100, required=False)
    ghi_chu_tinh_trang = forms.CharField(max_length=255, required=False)
    nam_san_xuat = forms.IntegerField(min_value=1900, max_value=2100, required=False)
    so_khung = forms.CharField(max_length=50, required=False)
    so_may = forms.CharField(max_length=50, required=False)
    han_bao_hiem = forms.DateField(required=False)
    ngay_mua = forms.DateField(required=False)
    gia_tri_mua = forms.DecimalField(min_value=0, required=False)
    hinh_anh = forms.ImageField(required=False)

    def clean_hinh_anh(self):
        img = self.cleaned_data.get('hinh_anh')
        if img and hasattr(img, 'content_type'):
            if not img.content_type.startswith('image/') or img.size > 8 * 1024 * 1024:
                raise ValidationError("Ảnh phải là tệp hình ảnh và không quá 8 MB.")
        return img