import os
import sys
import random
import uuid
import django
from datetime import datetime, timedelta, time
from decimal import Decimal
from django.utils import timezone
from django.db import transaction

# Thiết lập môi trường Django (khớp thư mục Vietmoto của bạn)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Vietmoto.settings")
django.setup()

from django.contrib.auth.models import User
from reviews.models import (
    DongXe,
    PhuongTien,
    NhanVien,
    KhachHang,
    DonDatTruoc,
    HopDongThue,
    BienBanBanGiao,
    ThanhToan,
    NhatKyVanHanhXe,
    NhatKyBaoDuong,
    HinhAnhBaoDuong,
    HinhAnhBienBan,
)


def random_aware_dt(days_offset_min, days_offset_max, hour_min=8, hour_max=19):
    """Tạo mốc thời gian có timezone chuẩn xác"""
    now = timezone.now()
    base_date = (now + timedelta(days=random.randint(days_offset_min, days_offset_max))).date()
    dt_naive = datetime.combine(
        base_date,
        time(hour=random.randint(hour_min, hour_max), minute=random.choice([0, 15, 30, 45]))
    )
    return timezone.make_aware(dt_naive)


@transaction.atomic
def run_seed():
    print("==================================================================")
    print("🚀 BẮT ĐẦU KHỞI TẠO DỮ LIỆU MẪU ĐỒ SỘ CHO HỆ THỐNG VIETMOTO")
    print("==================================================================")

    # ------------------------------------------------------------------
    # 1. XÓA SẠCH DỮ LIỆU CŨ AN TOÀN THEO THỨ TỰ KHÓA NGOẠI (PROTECT)
    # ------------------------------------------------------------------
    print("1/9. Đang dọn dẹp dữ liệu cũ...")
    HinhAnhBienBan.objects.all().delete()
    HinhAnhBaoDuong.objects.all().delete()
    BienBanBanGiao.objects.all().delete()
    ThanhToan.objects.all().delete()
    HopDongThue.objects.all().delete()
    DonDatTruoc.objects.all().delete()
    NhatKyVanHanhXe.objects.all().delete()
    NhatKyBaoDuong.objects.all().delete()
    PhuongTien.objects.all().delete()
    DongXe.objects.all().delete()
    KhachHang.objects.all().delete()
    NhanVien.objects.all().delete()

    now = timezone.now()
    today = timezone.localdate()

    # ------------------------------------------------------------------
    # 2. TẠO NHÂN VIÊN (ĐẦY ĐỦ CÁC VAI TRÒ + LIÊN KẾT DJANGO USER)
    # ------------------------------------------------------------------
    print("2/9. Đang khởi tạo đội ngũ Nhân viên (7 nhân sự)...")
    nhan_vien_specs = [
        ("NV001", "Lê Nguyễn Thu Thủy", "thuy.admin", "ADMIN", "0905111222", "thuy.admin@vietmoto.vn", "048198001122", today - timedelta(days=730), True),
        ("NV002", "Nguyễn Thị Thảo Vân", "van.manager", "QUAN_LY", "0905222333", "van.manager@vietmoto.vn", "048199002233", today - timedelta(days=540), True),
        ("NV003", "Đinh Thị Cẩm Quy", "quy.staff", "QUAY", "0905333444", "quy.staff@vietmoto.vn", "048200003344", today - timedelta(days=365), False),
        ("NV004", "Trần Hoàng Minh Anh", "anh.staff", "QUAY", "0905444555", "anh.staff@vietmoto.vn", "048201004455", today - timedelta(days=200), False),
        ("NV005", "Phạm Quốc Bảo", "bao.tech", "KY_THUAT", "0905555666", "bao.tech@vietmoto.vn", "048197005566", today - timedelta(days=450), False),
        ("NV006", "Võ Văn Hùng", "hung.tech", "KY_THUAT", "0905666777", "hung.tech@vietmoto.vn", "048196006677", today - timedelta(days=300), False),
        ("NV007", "Hoàng Thị Lan (Đã nghỉ)", "lan.old", "QUAY", "0905777888", "lan.old@vietmoto.vn", "048202007788", today - timedelta(days=400), False),
    ]

    nhan_viens = {}
    for ma, ho_ten, username, vai_tro, sdt, email, cccd, ngay_vao, is_super in nhan_vien_specs:
        trang_thai_nv = "NGHI_VIEC" if ma == "NV007" else "DANG_LAM"
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "first_name": ho_ten.split()[-1],
                "last_name": " ".join(ho_ten.split()[:-1]),
                "is_staff": is_super,
                "is_superuser": is_super,
                "is_active": trang_thai_nv == "DANG_LAM",
            }
        )
        user.set_password("Vietmoto@123")
        user.is_active = (trang_thai_nv == "DANG_LAM")
        user.save()

        nv = NhanVien.objects.create(
            ma_nhan_vien=ma,
            ho_ten=ho_ten,
            ten_dang_nhap=username,
            mat_khau=user.password,
            vai_tro=vai_tro,
            so_dien_thoai=sdt,
            email=email,
            trang_thai=trang_thai_nv,
            user=user,
            cccd=cccd,
            ngay_vao_lam=ngay_vao,
        )
        nhan_viens[ma] = nv

    staff_quay = [nhan_viens["NV001"], nhan_viens["NV002"], nhan_viens["NV003"], nhan_viens["NV004"]]
    staff_tech = [nhan_viens["NV005"], nhan_viens["NV006"]]

    # ------------------------------------------------------------------
    # 3. TẠO DÒNG XE (8 DÒNG XE: 5 XĂNG, 3 ĐIỆN - BAO GỒM 1 DÒNG NGỪNG KD)
    # ------------------------------------------------------------------
    print("3/9. Đang khởi tạo danh mục Dòng xe (5 Xăng, 3 Điện)...")
    dong_xe_specs = [
        # Xe xăng (5 dòng)
        ("DX001", "Honda Vision 110cc", "Xe tay ga", "XANG", Decimal("150000"), Decimal("1000000"),
         "Xe tay ga quốc dân gọn nhẹ, cốp rộng, tiết kiệm nhiên liệu 1.8L/100km. Kèm 2 mũ bảo hiểm & 2 áo mưa.", True),
        ("DX002", "Honda Air Blade 125cc", "Xe tay ga", "XANG", Decimal("180000"), Decimal("1500000"),
         "Xe tay ga thể thao mạnh mẽ, phanh ABS an toàn, phù hợp đi đèo Hải Vân & đường dài Đà Nẵng - Hội An.", True),
        ("DX003", "Honda Lead 125cc", "Xe tay ga", "XANG", Decimal("170000"), Decimal("1500000"),
         "Cốp siêu rộng 37L đựng vừa 2 vali xách tay, yên êm ái dành cho gia đình & khách du lịch.", True),
        ("DX004", "Honda Wave Alpha 110cc", "Xe số", "XANG", Decimal("110000"), Decimal("500000"),
         "Xe số bền bỉ, dễ điều khiển, chi phí tiết kiệm nhất cho sinh viên và khách phượt bụi.", True),
        ("DX005", "Yamaha Exciter 155 VVA (Đời cũ)", "Xe côn tay", "XANG", Decimal("250000"), Decimal("3000000"),
         "Dòng xe côn tay thể thao đã ngừng nhập mới để chuyển đổi sang đội xe xanh.", False),

        # Xe điện (3 dòng)
        ("DX006", "VinFast Feliz S (Xe điện)", "Xe điện", "DIEN", Decimal("170000"), Decimal("1500000"),
         "Xe máy điện Pin LFP đi được 198km/lần sạc, vận hành êm ái không tiếng ồn, kèm bộ sạc nhanh 1000W.", True),
        ("DX007", "VinFast Klara S2 (Xe điện)", "Xe điện", "DIEN", Decimal("190000"), Decimal("2000000"),
         "Thiết kế phong cách Ý thanh lịch, chống nước chuẩn IP67, quãng đường 194km/lần sạc đầy.", True),
        ("DX008", "Honda ICON-e (Xe điện)", "Xe điện", "DIEN", Decimal("160000"), Decimal("2000000"),
         "Xe điện đô thị thế hệ mới nhỏ gọn, pin Lithium-ion tháo rời sạc tiện lợi tại khách sạn.", True),
    ]

    dong_xes = {}
    for ma, ten, loai, dong_co, gia, coc, mo_ta, dang_kd in dong_xe_specs:
        dx = DongXe.objects.create(
            ma_dong_xe=ma,
            ten_dong_xe=ten,
            loai_xe=loai,
            loai_dong_co=dong_co,
            don_gia_ngay=gia,
            tien_coc_dinh_muc=coc,
            mo_ta=mo_ta,
            dang_kinh_doanh=dang_kd,
        )
        dong_xes[ma] = dx

    # ------------------------------------------------------------------
    # 4. TẠO 80 PHƯƠNG TIỆN (55 XE XĂNG + 25 XE ĐIỆN) ĐẦY ĐỦ MỌI TRẠNG THÁI
    # ------------------------------------------------------------------
    print("4/9. Đang khởi tạo 80 Phương tiện (55 xe xăng, 25 xe điện)...")
    # Phân bổ 80 xe:
    # - 55 Xe xăng: DX001 (20), DX002 (15), DX003 (10), DX004 (8), DX005 (2)
    # - 25 Xe điện: DX006 (10), DX007 (8), DX008 (7)
    fleet_plan = (
        [("DX001", "43D1", 101)] * 20 +
        [("DX002", "43K1", 201)] * 15 +
        [("DX003", "43H1", 301)] * 10 +
        [("DX004", "43F1", 401)] * 8 +
        [("DX005", "43C1", 501)] * 2 +
        [("DX006", "43MD1", 601)] * 10 +
        [("DX007", "43MD2", 701)] * 8 +
        [("DX008", "43MD3", 801)] * 7
    )

    # Phân bổ trạng thái vật lý ban đầu cho 80 xe:
    # - 24 xe sẽ gắn với 24 Hợp đồng DANG_THUE
    # - 6 xe sẽ gắn với 6 Hợp đồng CHO_BAN_GIAO (khóa sang DANG_THUE theo đúng logic views.py)
    # - 36 xe CON_TRONG (trong đó có 5 xe ODO lũy kế 1.820 - 1.960 km để hiện cảnh báo vàng sắp bảo dưỡng)
    # - 7 xe CHO_VE_SINH (chờ rửa xe / sạc pin tại bãi)
    # - 5 xe BAO_DUONG (đang nằm xưởng sửa chữa / bảo dưỡng)
    # - 2 xe NGUNG_HOAT_DONG (thuộc DX005 thanh lý)
    vehicles = []
    dx_counters = {}
    for idx, (dx_code, prefix, start_num) in enumerate(fleet_plan):
        dx_counters[dx_code] = dx_counters.get(dx_code, 0) + 1
        num = start_num + dx_counters[dx_code] - 1
        bien_so = f"{prefix}-{num:03d}.{random.randint(10, 99)}"

        dx_obj = dong_xes[dx_code]
        is_dien = (dx_obj.loai_dong_co == "DIEN")

        # Xác định trạng thái & chỉ số kỹ thuật
        if dx_code == "DX005":
            trang_thai = "NGUNG_HOAT_DONG"
            odo = random.randint(42000, 55000)
            odo_bd = 800
            fuel = 20
            note = "Xe đời cũ đã ngưng khai thác, chờ thanh lý tài sản."
            han_bh = today - timedelta(days=45)
        elif idx < 24:
            # 24 xe đang cho thuê (20 xăng + 4 điện, hoặc phân bổ đều xăng & điện)
            trang_thai = "DANG_THUE"
            odo = random.randint(4500, 24000)
            odo_bd = random.randint(300, 1650)
            fuel = random.randint(65, 100)
            note = "Xe đang lưu hành cùng khách thuê, tình trạng vận hành ổn định."
            han_bh = today + timedelta(days=random.randint(60, 320))
        elif idx < 30:
            # 6 xe thuộc hợp đồng CHO_BAN_GIAO (trong views.py khóa xe sang DANG_THUE)
            trang_thai = "DANG_THUE"
            odo = random.randint(2000, 15000)
            odo_bd = random.randint(150, 1200)
            fuel = 100
            note = "Đã vệ sinh sạch sẽ, kiểm tra áp suất lốp, chờ khách ký biên bản xuất bãi."
            han_bh = today + timedelta(days=random.randint(90, 340))
        elif idx < 37:
            # 7 xe CHO_VE_SINH (chờ rửa xe / sạc pin)
            trang_thai = "CHO_VE_SINH"
            odo = random.randint(3500, 19000)
            odo_bd = random.randint(400, 1500)
            fuel = random.randint(25, 45) if is_dien else random.randint(30, 55)
            note = (
                f"Khách vừa trả xe, pin còn {fuel}%, đang cắm sạc nhanh tại trạm."
                if is_dien else
                f"Khách vừa trả xe đi biển về dính cát, đang chờ rửa xe & châm xăng ({fuel}%)."
            )
            han_bh = today + timedelta(days=random.randint(45, 300))
        elif idx < 42:
            # 5 xe BAO_DUONG (đang nằm xưởng)
            trang_thai = "BAO_DUONG"
            odo = random.randint(12000, 32000)
            odo_bd = random.randint(2010, 2280) if idx < 40 else random.randint(950, 1400)
            fuel = random.randint(50, 90)
            note = "Đang nằm xưởng kỹ thuật Vietmoto kiểm tra & bảo dưỡng."
            han_bh = today + timedelta(days=random.randint(30, 280))
        else:
            # 36 xe CON_TRONG (sẵn sàng giao khách)
            trang_thai = "CON_TRONG"
            odo = random.randint(1200, 26000)
            # 5 xe đầu tiên trong nhóm CON_TRONG sẽ sát ngưỡng bảo dưỡng (1830 - 1975 km) để test cảnh báo vàng
            if idx < 47:
                odo_bd = random.randint(1830, 1975)
                note = "Sẵn sàng cho thuê ngắn ngày (Lưu ý: ODO sắp chạm mốc 2.000 km bảo dưỡng)."
            else:
                odo_bd = random.randint(50, 1550)
                note = "Xe đẹp, đầy đủ 2 gương, 2 mũ bảo hiểm, sẵn sàng giao ngay."

            fuel = random.randint(85, 100)
            # Tạo 4 xe sắp hết hạn / hết hạn bảo hiểm TNDS để test cảnh báo bảo hiểm
            if idx in (48, 49):
                han_bh = today - timedelta(days=random.randint(2, 10))
            elif idx in (50, 51):
                han_bh = today + timedelta(days=random.randint(3, 12))
            else:
                han_bh = today + timedelta(days=random.randint(60, 360))

        # Đảm bảo một số xe điện cũng nằm trong nhóm DANG_THUE, CHO_BAN_GIAO, CHO_VE_SINH, BAO_DUONG, CON_TRONG
        gia_mua_map = {
            "DX001": Decimal("34500000"),
            "DX002": Decimal("43000000"),
            "DX003": Decimal("41500000"),
            "DX004": Decimal("19500000"),
            "DX005": Decimal("48000000"),
            "DX006": Decimal("29900000"),
            "DX007": Decimal("36900000"),
            "DX008": Decimal("26900000"),
        }

        pt = PhuongTien.objects.create(
            bien_so_xe=bien_so,
            ma_dong_xe=dx_obj,
            trang_thai_xe=trang_thai,
            odo_hien_tai=odo,
            odo_luy_ke_bao_duong=odo_bd,
            muc_nhien_lieu_pin=fuel,
            ghi_chu_tinh_trang=note,
            ngay_mua=today - timedelta(days=random.randint(180, 900)),
            gia_tri_mua=gia_mua_map[dx_code],
            han_bao_hiem=han_bh,
            so_khung=f"RLH{dx_code[-2:]}{random.randint(10000000, 99999999)}",
            so_may=f"JF{random.randint(10, 99)}E{random.randint(1000000, 9999999)}",
            nam_san_xuat=random.choice([2023, 2024, 2025, 2026]),
        )
        vehicles.append(pt)

    # Đảm bảo có ít nhất 6 xe điện trong nhóm DANG_THUE và 2 xe điện trong CHO_BAN_GIAO để test đa dạng
    electric_vehicles = [v for v in vehicles if v.ma_dong_xe.loai_dong_co == "DIEN"]
    gas_vehicles = [v for v in vehicles if v.ma_dong_xe.loai_dong_co == "XANG"]

    # Sắp xếp lại danh sách xe theo vai trò sử dụng:
    # 24 xe DANG_THUE (18 xăng + 6 điện)
    # 6 xe CHO_BAN_GIAO (4 xăng + 2 điện)
    # 7 xe CHO_VE_SINH (5 xăng + 2 điện)
    # 5 xe BAO_DUONG (4 xăng + 1 điện)
    # 36 xe CON_TRONG (22 xăng + 14 điện)
    # 2 xe NGUNG_HOAT_DONG (2 xăng DX005)
    active_gas = [v for v in gas_vehicles if v.ma_dong_xe_id != "DX005"]
    inactive_gas = [v for v in gas_vehicles if v.ma_dong_xe_id == "DX005"]

    xe_dang_thue_list = active_gas[:18] + electric_vehicles[:6]
    xe_cho_ban_giao_list = active_gas[18:22] + electric_vehicles[6:8]
    xe_cho_ve_sinh_list = active_gas[22:27] + electric_vehicles[8:10]
    xe_bao_duong_list = active_gas[27:31] + electric_vehicles[10:11]
    xe_con_trong_list = active_gas[31:] + electric_vehicles[11:]

    for idx_v, v in enumerate(xe_dang_thue_list):
        v.trang_thai_xe = "DANG_THUE"
        v.muc_nhien_lieu_pin = random.randint(70, 100)
        v.ghi_chu_tinh_trang = "Xe đang phục vụ khách thuê dài ngày."
        v.save(update_fields=["trang_thai_xe", "muc_nhien_lieu_pin", "ghi_chu_tinh_trang"])

    for v in xe_cho_ban_giao_list:
        v.trang_thai_xe = "DANG_THUE"
        v.muc_nhien_lieu_pin = 100
        v.ghi_chu_tinh_trang = "Đã sẵn sàng tại quầy, chờ xuất bãi giao khách."
        v.save(update_fields=["trang_thai_xe", "muc_nhien_lieu_pin", "ghi_chu_tinh_trang"])

    for v in xe_cho_ve_sinh_list:
        is_d = v.ma_dong_xe.loai_dong_co == "DIEN"
        v.trang_thai_xe = "CHO_VE_SINH"
        v.muc_nhien_lieu_pin = random.randint(20, 45)
        v.ghi_chu_tinh_trang = (
            f"Đang sạc pin tại trạm (hiện đạt {v.muc_nhien_lieu_pin}%)."
            if is_d else
            f"Chờ rửa xe & đổ đầy bình xăng (hiện còn {v.muc_nhien_lieu_pin}%)."
        )
        v.save(update_fields=["trang_thai_xe", "muc_nhien_lieu_pin", "ghi_chu_tinh_trang"])

    for idx_b, v in enumerate(xe_bao_duong_list):
        v.trang_thai_xe = "BAO_DUONG"
        if idx_b < 3:
            v.odo_luy_ke_bao_duong = random.randint(2015, 2240)
        v.ghi_chu_tinh_trang = "Xe đang trong xưởng bảo dưỡng kỹ thuật Vietmoto."
        v.save(update_fields=["trang_thai_xe", "odo_luy_ke_bao_duong", "ghi_chu_tinh_trang"])

    for idx_c, v in enumerate(xe_con_trong_list):
        v.trang_thai_xe = "CON_TRONG"
        v.muc_nhien_lieu_pin = random.randint(85, 100)
        if idx_c < 6:
            v.odo_luy_ke_bao_duong = random.randint(1835, 1980)
            v.ghi_chu_tinh_trang = "Còn trống - Sắp chạm mốc bảo dưỡng 2.000 km."
        else:
            v.odo_luy_ke_bao_duong = random.randint(80, 1500)
            v.ghi_chu_tinh_trang = "Xe nguyên bản, sạch đẹp, sẵn sàng giao khách."
        v.save(update_fields=["trang_thai_xe", "odo_luy_ke_bao_duong", "muc_nhien_lieu_pin", "ghi_chu_tinh_trang"])

    # ------------------------------------------------------------------
    # 5. TẠO 40 KHÁCH HÀNG (30 KHÁCH NƯỚC NGOÀI + 10 KHÁCH VIỆT NAM)
    # ------------------------------------------------------------------
    print("5/9. Đang khởi tạo 40 Khách hàng (30 Quốc tế, 10 Việt Nam)...")
    foreign_customers_data = [
        ("Liam O'Connor", "Australia", "PASS-AU-849201", "IDP-AU-55102", "Khách sạn TMS Luxury, Mỹ Khê, Đà Nẵng"),
        ("Min-jun Kim", "Hàn Quốc", "M48291044", "IDP-KR-99201", "Novotel Danang Premier Han River, Hải Châu"),
        ("Ji-hoon Park", "Hàn Quốc", "M73920188", "IDP-KR-33812", "Furama Resort Danang, Ngũ Hành Sơn"),
        ("Seo-yeon Choi", "Hàn Quốc", "M91028374", "IDP-KR-77410", "Hyatt Regency Danang Resort & Spa"),
        ("Haruto Takahashi", "Nhật Bản", "TK9283746", "IDP-JP-11290", "Mikazuki Japanese Resorts & Spa, Liên Chiểu"),
        ("Yui Watanabe", "Nhật Bản", "TZ4491028", "IDP-JP-66301", "Hilton Danang, Bạch Đằng, Hải Châu"),
        ("James Anderson", "Mỹ", "592837461", "IDP-US-44019", "InterContinental Danang Sun Peninsula Resort"),
        ("Emily Carter", "Mỹ", "610293847", "IDP-US-88210", "Sala Danang Beach Hotel, Sơn Trà"),
        ("Oliver Thompson", "Anh", "538291045", "IDP-UK-20934", "Pullman Danang Beach Resort, Ngũ Hành Sơn"),
        ("Charlotte Davies", "Anh", "549102836", "IDP-UK-71823", "An Thượng 29, Khu phố Tây, Ngũ Hành Sơn"),
        ("Lucas Moreau", "Pháp", "21AF83920", "IDP-FR-90123", "Mercure Danang French Village Bana Hills"),
        ("Camille Laurent", "Pháp", "22BC49102", "IDP-FR-45109", "Đường Trần Bạch Đằng, Sơn Trà, Đà Nẵng"),
        ("Lukas Weber", "Đức", "C01X92837", "IDP-DE-33091", "Radisson Hotel Danang, Võ Nguyên Giáp"),
        ("Hannah Becker", "Đức", "C02Y48192", "IDP-DE-88120", "Châu Thị Vĩnh Tế, Ngũ Hành Sơn, Đà Nẵng"),
        ("Wei-Ting Chen", "Đài Loan", "358291047", "IDP-TW-11029", "Melia Vinpearl Danang Riverfront"),
        ("Yu-Hsuan Lin", "Đài Loan", "369102834", "IDP-TW-55820", "Haian Beach Hotel & Spa, Sơn Trà"),
        ("Hao Zhang", "Trung Quốc", "E84920193", "IDP-CN-66712", "Sheraton Grand Danang Resort"),
        ("Mei-Ling Wang", "Trung Quốc", "E91028365", "IDP-CN-22918", "Crowne Plaza Danang, Ngũ Hành Sơn"),
        ("Ethan Wilson", "Canada", "GA829104", "IDP-CA-77412", "Monarque Hotel Danang, Võ Nguyên Giáp"),
        ("Sophia Martin", "Canada", "GB491028", "IDP-CA-19283", "Lê Quang Đạo, Bắc Mỹ An, Ngũ Hành Sơn"),
        ("Dmitry Ivanov", "Nga", "758291048", "IDP-RU-99012", "Paris Deli Danang Beach Hotel"),
        ("Anastasia Smirnova", "Nga", "769102839", "IDP-RU-33410", "Đường Hồ Nghinh, Phước Mỹ, Sơn Trà"),
        ("Somchai Srisai", "Thái Lan", "AA9283741", "IDP-TH-55109", "Vanda Hotel Danang, Nguyễn Văn Linh"),
        ("Nattapong Chaiya", "Thái Lan", "AB4910283", "IDP-TH-88412", "A La Carte Danang Beach, Sơn Trà"),
        ("Wei Jie Tan", "Singapore", "K4829104J", "IDP-SG-10293", "Risemount Premier Resort Danang"),
        ("Aisyah Rahman", "Malaysia", "A59283746", "IDP-MY-66102", "Naman Retreat, Trường Sa, Ngũ Hành Sơn"),
        ("Arjun Sharma", "Ấn Độ", "Z4829104", "IDP-IN-77219", "Grand Mercure Danang, Đảo Xanh"),
        ("Priya Patel", "Ấn Độ", "Z9102837", "IDP-IN-33910", "Danang Marriott Resort & Spa"),
        ("Marco Rossi", "Ý", "YA8291042", "IDP-IT-44102", "Hoàng Kế Viêm, Mỹ An, Ngũ Hành Sơn"),
        ("Elena Fernandez", "Tây Ban Nha", "PAA928374", "IDP-ES-99182", "GIC Luxury Hotel & Spa, Lê Duẩn"),
    ]

    vietnam_customers_data = [
        ("Nguyễn Hoàng Minh Phúc", "Việt Nam", "048096001122", "480196001122", "124 Nguyễn Văn Linh, Hải Châu, Đà Nẵng"),
        ("Trần Thị Thanh Thảo", "Việt Nam", "048198002233", "481198002233", "56 Lê Duẩn, Thạch Thang, Hải Châu, Đà Nẵng"),
        ("Lê Quang Khải", "Việt Nam", "048094003344", "480194003344", "89 Phan Châu Trinh, Hải Châu, Đà Nẵng"),
        ("Phạm Ngọc Bảo Trân", "Việt Nam", "048199004455", "481199004455", "210 Ngô Quyền, An Hải Bắc, Sơn Trà, Đà Nẵng"),
        ("Võ Đình Khoa", "Việt Nam", "048092005566", "480192005566", "45 Tôn Đức Thắng, Hòa Minh, Liên Chiểu, Đà Nẵng"),
        ("Đặng Quốc Huy", "Việt Nam", "048095006677", "480195006677", "178 Núi Thành, Hòa Cường Bắc, Hải Châu, Đà Nẵng"),
        ("Bùi Thị Mai Phương", "Việt Nam", "048197007788", "481197007788", "33 Võ Nguyên Giáp, Phước Mỹ, Sơn Trà, Đà Nẵng"),
        ("Huỳnh Tấn Phát", "Việt Nam", "048091008899", "480191008899", "92 Ông Ích Khiêm, Thanh Bình, Hải Châu, Đà Nẵng"),
        ("Ngô Minh Trí", "Việt Nam", "048093009900", "480193009900", "145 Hoàng Diệu, Nam Dương, Hải Châu, Đà Nẵng"),
        ("Trịnh Văn Quyết", "Việt Nam", "048090001234", "480190001234", "77 Điện Biên Phủ, Chính Gián, Thanh Khê, Đà Nẵng"),
    ]

    customers = []
    # 30 khách quốc tế (KH0001 -> KH0030)
    for i, (name, nation, passport, idp, addr) in enumerate(foreign_customers_data, start=1):
        # KH0026..KH0028: CAN_LUU_Y, KH0029..KH0030: BLACKLIST, còn lại TOT
        if i in (29, 30):
            tin_nhiem = "BLACKLIST"
            ly_do = (
                "Trả xe trễ 2 ngày không thông báo, làm trầy xước nặng dàn áo bên phải và từ chối thanh toán phí sửa chữa."
                if i == 29 else
                "Sử dụng giấy phép lái xe quốc tế giả mạo, tự ý mang xe ra khỏi địa bàn thành phố trái cam kết."
            )
        elif i in (26, 27, 28):
            tin_nhiem = "CAN_LUU_Y"
            ly_do = "Từng phát sinh phụ phí trả xe trễ giờ và giao xe cạn nhiên liệu."
        else:
            tin_nhiem = "TOT"
            ly_do = None

        email_slug = name.lower().replace(" ", ".").replace("'", "")
        kh = KhachHang.objects.create(
            ma_khach_hang=f"KH{i:04d}",
            ho_ten=name,
            so_dien_thoai=f"+849{random.randint(10000000, 99999999)}" if i % 3 == 0 else f"09{random.randint(10000000, 99999999)}",
            quoc_tich=nation,
            dia_chi=addr,
            email=f"{email_slug}@example.com",
            so_cccd=passport,
            giay_phep_lai_xe=idp,
            muc_tin_nhiem=tin_nhiem,
            ly_do_blacklist=ly_do,
        )
        customers.append(kh)

    # 10 khách Việt Nam (KH0031 -> KH0040)
    for j, (name, nation, cccd, gplx, addr) in enumerate(vietnam_customers_data, start=31):
        if j == 40:
            tin_nhiem = "BLACKLIST"
            ly_do = "Từng bùng tiền phụ phí trả trễ 5 ngày và tự ý tháo phụ kiện zin của xe."
        elif j in (38, 39):
            tin_nhiem = "CAN_LUU_Y"
            ly_do = "Từng trả xe trễ 3 tiếng và làm mất mũ bảo hiểm kèm theo xe."
        else:
            tin_nhiem = "TOT"
            ly_do = None

        kh = KhachHang.objects.create(
            ma_khach_hang=f"KH{j:04d}",
            ho_ten=name,
            so_dien_thoai=f"0905{random.randint(100000, 999999)}",
            quoc_tich=nation,
            dia_chi=addr,
            email=f"khach.vn{j}@gmail.com",
            so_cccd=cccd,
            giay_phep_lai_xe=gplx,
            muc_tin_nhiem=tin_nhiem,
            ly_do_blacklist=ly_do,
        )
        customers.append(kh)

    kh_tot_list = [k for k in customers if k.muc_tin_nhiem == "TOT"]
    kh_luu_y_list = [k for k in customers if k.muc_tin_nhiem == "CAN_LUU_Y"]
    kh_blacklist_list = [k for k in customers if k.muc_tin_nhiem == "BLACKLIST"]

    # ------------------------------------------------------------------
    # 6. TẠO ĐƠN ĐẶT TRƯỚC (18 ĐƠN: ĐỦ 5 TRẠNG THÁI CHO_XAC_NHAN, DA_GIU_CHO, DA_CHUYEN_HD, DA_HUY, KHONG_DEN)
    # ------------------------------------------------------------------
    print("6/9. Đang khởi tạo 18 Đơn đặt trước (đầy đủ 5 trạng thái)...")
    bookings_created = []
    # Lấy các xe đang CON_TRONG để gán đơn đặt tương lai (tránh trùng xe đang chạy)
    booking_pool_vehicles = xe_con_trong_list[:18]

    booking_scenarios = [
        # 6 đơn DA_GIU_CHO (hiển thị chính trên trang Đặt xe, bao gồm 3 đơn trong 24h tới để hiện trên Tổng quan)
        ("DA_GIU_CHO", now + timedelta(hours=3), 4, True, "Sân bay Quốc tế Đà Nẵng - Cổng đến Quốc tế", "Khách hạ cánh chuyến bay VJ881, yêu cầu chuẩn bị sẵn 2 mũ bảo hiểm cỡ lớn."),
        ("DA_GIU_CHO", now + timedelta(hours=8), 7, True, "Khách sạn TMS Luxury, 292 Võ Nguyên Giáp", "Giao xe tận nơi tại sảnh khách sạn, khách quốc tế thanh toán cọc qua chuyển khoản."),
        ("DA_GIU_CHO", now + timedelta(hours=19), 5, True, "Tại trạm Vietmoto - 120 Nguyễn Văn Linh", "Khách đến trực tiếp quầy nhận xe, ưu tiên xe mới ODO thấp."),
        ("DA_GIU_CHO", now + timedelta(days=2, hours=2), 10, True, "Furama Resort Danang", "Khách thuê dài ngày đi Đà Nẵng - Hội An, cần giá đỡ điện thoại."),
        ("DA_GIU_CHO", now + timedelta(days=4, hours=1), 6, True, "Ga Đà Nẵng - Hải Châu", "Khách đi tàu SE3 tới Đà Nẵng lúc sáng sớm."),
        ("DA_GIU_CHO", now + timedelta(days=7), 14, True, "Hyatt Regency Danang Resort", "Khách đặt giữ chỗ trước 1 tuần, đã thanh toán cọc giữ chỗ 100.000đ."),

        # 3 đơn CHO_XAC_NHAN (khách vừa đặt online, chưa chuyển khoản cọc giữ chỗ)
        ("CHO_XAC_NHAN", now + timedelta(hours=6), 3, False, "Tại trạm Vietmoto - 120 Nguyễn Văn Linh", "Đơn đặt từ website, lễ tân đang gọi điện xác nhận lịch bay."),
        ("CHO_XAC_NHAN", now + timedelta(days=1, hours=5), 4, False, "Khách sạn Novotel Đà Nẵng", "Khách hỏi thêm về thủ tục giữ hộ chiếu gốc."),
        ("CHO_XAC_NHAN", now + timedelta(days=3, hours=4), 5, False, "An Thượng 29, Ngũ Hành Sơn", "Chờ khách xác nhận lại giờ nhận xe buổi chiều."),

        # 5 đơn DA_CHUYEN_HD (đã chuyển thành hợp đồng thuê thực tế)
        ("DA_CHUYEN_HD", now - timedelta(days=12), 35, True, "Sân bay Quốc tế Đà Nẵng", "Đã chuyển thành hợp đồng thuê dài hạn."),
        ("DA_CHUYEN_HD", now - timedelta(days=8), 40, True, "Tại trạm Vietmoto", "Khách đến đúng giờ, đã ký hợp đồng tại quầy."),
        ("DA_CHUYEN_HD", now - timedelta(days=5), 32, True, "Khách sạn Sala Danang", "Giao xe tận nơi và kích hoạt hợp đồng."),
        ("DA_CHUYEN_HD", now - timedelta(days=25), 5, True, "Tại trạm Vietmoto", "Đã hoàn tất chuyến đi và thanh lý hợp đồng."),
        ("DA_CHUYEN_HD", now - timedelta(days=18), 4, True, "Ga Đà Nẵng", "Khách quen quay lại thuê lần 2."),

        # 2 đơn DA_HUY
        ("DA_HUY", now + timedelta(days=1), 3, False, "Sân bay Đà Nẵng", "Khách báo hoãn chuyến bay do thời tiết xấu nên xin hủy lịch."),
        ("DA_HUY", now - timedelta(days=4), 5, True, "Khách sạn Hilton Đà Nẵng", "Khách thay đổi lịch trình đi Huế trước 48h, đã hoàn cọc giữ chỗ."),

        # 2 đơn KHONG_DEN (No-show quá 2 giờ hẹn nhận)
        ("KHONG_DEN", now - timedelta(days=3), 4, False, "Tại trạm Vietmoto", "Hệ thống tự động ghi nhận khách không đến nhận xe sau 2 giờ hẹn."),
        ("KHONG_DEN", now - timedelta(days=9), 3, False, "Tại trạm Vietmoto", "Liên hệ không nghe máy sau 2 tiếng quá giờ hẹn nhận."),
    ]

    converted_bookings = []
    for idx_b, (st, start_dt, dur_days, paid_coc, loc, note) in enumerate(booking_scenarios, start=1):
        kh_b = kh_tot_list[idx_b % len(kh_tot_list)] if st != "KHONG_DEN" else kh_luu_y_list[idx_b % len(kh_luu_y_list)]
        xe_b = booking_pool_vehicles[idx_b % len(booking_pool_vehicles)]
        nv_b = staff_quay[idx_b % len(staff_quay)]
        don_gia = xe_b.ma_dong_xe.don_gia_ngay
        tong_du_kien = don_gia * dur_days

        bk = DonDatTruoc.objects.create(
            ma_don_dat=f"BK{idx_b:03d}",
            ma_khach_hang=kh_b,
            bien_so_xe=xe_b,
            ma_nhan_vien=nv_b,
            thoi_gian_hen_nhan=start_dt,
            thoi_gian_du_kien_tra=start_dt + timedelta(days=dur_days),
            don_gia_du_kien=don_gia,
            tong_tien_du_kien=tong_du_kien,
            tien_coc_giu_cho=Decimal("100000") if paid_coc else Decimal("0"),
            da_thanh_toan_coc=paid_coc,
            dia_diem_giao_xe=loc,
            trang_thai_don=st,
            ghi_chu=note,
            ly_do_huy=note if st in ("DA_HUY", "KHONG_DEN") else None,
        )
        bookings_created.append(bk)
        if st == "DA_CHUYEN_HD":
            converted_bookings.append(bk)

    # ------------------------------------------------------------------
    # 7. TẠO 46 HỢP ĐỒNG THUÊ + BIÊN BẢN BÀN GIAO + GIAO DỊCH THANH TOÁN
    #    - 24 HĐ DANG_THUE:
    #        * 18 HĐ dài hạn (35 - 60 ngày) -> Đảm bảo 1 tháng nữa báo cáo vẫn DANG_THUE!
    #        * 4 HĐ SAP_HET_HAN (còn 6h - 20h nữa hết hạn) -> Test tab Sắp hết hạn & Gia hạn
    #        * 2 HĐ QUA_HAN (trễ 4h và 18h) -> Test tab Quá hạn & tính phụ phí trễ giờ
    #    - 6 HĐ CHO_BAN_GIAO -> Test nút Xuất bãi giao xe
    #    - 14 HĐ DA_TRA (trong 7 ngày gần nhất & tháng qua) -> Tạo biểu đồ doanh thu 7 ngày & Báo cáo
    #    - 2 HĐ DA_HUY -> Đầy đủ mọi trạng thái hợp đồng
    # ------------------------------------------------------------------
    print("7/9. Đang khởi tạo 46 Hợp đồng thuê, Biên bản bàn giao & Phiếu thanh toán...")
    hd_counter = 1

    def create_contract_bundle(
        kh, xe, nv_lap, nv_tech, trang_thai_hd, ngay_bd, ngay_kt_dk,
        ngay_kt_tt=None, phu_phi=Decimal("0"), ma_don_dat=None,
        hinh_thuc_coc=None, ghi_chu_hd="", tt_days_ago=0
    ):
        nonlocal hd_counter
        ma_hd = f"HD-{hd_counter:03d}"
        hd_counter += 1

        dong_xe = xe.ma_dong_xe
        don_gia = dong_xe.don_gia_ngay
        coc_qd = dong_xe.tien_coc_dinh_muc

        diff_hours = max(24.0, (ngay_kt_dk - ngay_bd).total_seconds() / 3600.0)
        so_ngay = max(1, int(round(diff_hours / 24.0)))
        tong_tien_thue = don_gia * so_ngay

        is_vn = (kh.quoc_tich or "").strip().lower() == "việt nam"
        if hinh_thuc_coc is None:
            hinh_thuc_coc = "GIU_CCCD" if (is_vn and hd_counter % 2 == 0) else "TIEN_MAT"

        coc_thuc_thu = Decimal("0") if hinh_thuc_coc == "GIU_CCCD" else coc_qd

        if trang_thai_hd == "CHO_BAN_GIAO":
            tt_status = "DA_COC" if coc_thuc_thu > 0 else "CHUA_THANH_TOAN"
        elif trang_thai_hd == "DA_HUY":
            tt_status = "CHUA_THANH_TOAN"
        else:
            tt_status = "DA_THANH_TOAN_DU"

        hd = HopDongThue.objects.create(
            ma_hop_dong=ma_hd,
            ma_khach_hang=kh,
            bien_so_xe=xe,
            ma_nhan_vien=nv_lap,
            ma_don_dat=ma_don_dat,
            trang_thai_hop_dong=trang_thai_hd,
            don_gia_ap_dung=don_gia,
            tien_coc_quy_dinh=coc_qd,
            hinh_thuc_dat_coc=hinh_thuc_coc,
            so_tien_coc_thuc_thu=coc_thuc_thu,
            ngay_bat_dau=ngay_bd,
            ngay_ket_thuc_du_kien=ngay_kt_dk,
            ngay_ket_thuc_thuc_te=ngay_kt_tt,
            so_ngay_thue=so_ngay,
            phu_phi=phu_phi,
            tong_tien_thanh_toan=tong_tien_thue,
            trang_thai_thanh_toan=tt_status,
            chu_ky_khach_hang=f"Signed electronically by {kh.ho_ten}",
            ghi_chu=ghi_chu_hd,
        )

        # Tạo ThanhToan cọc nếu có thu cọc tiền mặt
        if coc_thuc_thu > 0 and trang_thai_hd in ("CHO_BAN_GIAO", "DANG_THUE", "DA_TRA"):
            ThanhToan.objects.create(
                ma_thanh_toan=f"TT-COC-{ma_hd}",
                ma_hop_dong=hd,
                ma_nhan_vien=nv_lap,
                so_tien=coc_thuc_thu,
                loai_thanh_toan="COC",
                hinh_thuc="CHUYEN_KHOAN" if not is_vn else "TIEN_MAT",
                trang_thai="THANH_CONG",
                thoi_gian_thanh_toan=ngay_bd - timedelta(minutes=15),
                ma_giao_dich=f"Thu cọc hợp đồng {ma_hd}",
            )

        # Nếu đã bàn giao xe (DANG_THUE hoặc DA_TRA) -> Tạo Biên bản xuất bãi + Thanh toán cước thuê
        if trang_thai_hd in ("DANG_THUE", "DA_TRA"):
            is_dien = dong_xe.loai_dong_co == "DIEN"
            odo_xuat = max(100, xe.odo_hien_tai - random.randint(150, 900))
            BienBanBanGiao.objects.create(
                ma_bien_ban=f"BBX-{ma_hd}",
                ma_hop_dong=hd,
                ma_nhan_vien=nv_tech,
                thoi_diem_thuc_hien=ngay_bd,
                so_km_odo=odo_xuat,
                muc_vach_xang="100% Pin (Đầy)" if is_dien else "Đầy bình xăng",
                tinh_trang_ngoai_quan="Ngoại quan nguyên bản, đèn còi xi-nhan hoạt động tốt, đủ 2 gương chiếu hậu.",
                phu_phi_tre_gio=Decimal("0"),
                tien_hoan_coc=None,
                ma_token_tra_cuu=uuid.uuid4().hex[:16],
                loai_bien_ban="XUAT",
                ghi_chu=f"[Phụ kiện: 2 mũ BH, Đủ 2 gương, Đã giao Cavet+BH{', Kèm bộ sạc zin' if is_dien else ''}]",
                chu_ky_khach_hang=f"Confirmed handover - {kh.ho_ten}",
            )

            # Thời điểm ghi nhận doanh thu
            tg_thu_cuoc = ngay_bd if tt_days_ago == 0 else (now - timedelta(days=tt_days_ago))
            ThanhToan.objects.create(
                ma_thanh_toan=f"TT-THUE-{ma_hd}",
                ma_hop_dong=hd,
                ma_nhan_vien=nv_lap,
                so_tien=tong_tien_thue,
                loai_thanh_toan="THANH_TOAN_CUOI",
                hinh_thuc="CHUYEN_KHOAN" if not is_vn else random.choice(["TIEN_MAT", "CHUYEN_KHOAN", "THE"]),
                trang_thai="THANH_CONG",
                thoi_gian_thanh_toan=tg_thu_cuoc,
                ma_giao_dich=f"Thu tiền cước thuê xe {ma_hd}",
            )

            NhatKyVanHanhXe.objects.create(
                bien_so_xe=xe,
                ma_nhan_vien=nv_tech,
                tu_trang_thai="CON_TRONG",
                den_trang_thai="DANG_THUE",
                odo_ghi_nhan=odo_xuat,
                muc_nhien_lieu_pin=100,
                ghi_chu=f"Xuất bãi bàn giao xe cho HĐ {ma_hd}",
            )

        # Nếu đã trả xe (DA_TRA) -> Tạo Biên bản trả xe + Hoàn cọc / Thu phụ phí
        if trang_thai_hd == "DA_TRA":
            is_dien = dong_xe.loai_dong_co == "DIEN"
            odo_tra = xe.odo_hien_tai
            tien_hoan_coc = max(Decimal("0"), coc_thuc_thu - phu_phi)
            tien_thu_them = max(Decimal("0"), phu_phi - coc_thuc_thu)

            BienBanBanGiao.objects.create(
                ma_bien_ban=f"BBT-{ma_hd}",
                ma_hop_dong=hd,
                ma_nhan_vien=nv_tech,
                thoi_diem_thuc_hien=ngay_kt_tt or ngay_kt_dk,
                so_km_odo=odo_tra,
                muc_vach_xang="85% Pin" if is_dien else "Đầy bình xăng",
                tinh_trang_ngoai_quan="Xe hoạt động bình thường, đầy đủ phụ kiện bàn giao ban đầu." if phu_phi == 0 else "Trả xe trễ giờ quy định / thiếu nhiên liệu khi nghiệm thu.",
                phu_phi_tre_gio=phu_phi,
                tien_hoan_coc=tien_hoan_coc,
                ma_token_tra_cuu=uuid.uuid4().hex[:16],
                loai_bien_ban="TRA",
                ghi_chu=f"Nghiệm thu thu hồi xe hoàn tất HĐ {ma_hd}.",
                chu_ky_khach_hang=f"Confirmed return - {kh.ho_ten}",
            )

            if tien_hoan_coc > 0:
                ThanhToan.objects.create(
                    ma_thanh_toan=f"TT-HC-{ma_hd}",
                    ma_hop_dong=hd,
                    ma_nhan_vien=nv_lap,
                    so_tien=tien_hoan_coc,
                    loai_thanh_toan="HOAN_COC",
                    hinh_thuc="CHUYEN_KHOAN" if not is_vn else "TIEN_MAT",
                    trang_thai="THANH_CONG",
                    thoi_gian_thanh_toan=ngay_kt_tt or ngay_kt_dk,
                    ma_giao_dich=f"Hoàn cọc xe {xe.bien_so_xe} HĐ {ma_hd}",
                )

            if phu_phi > 0:
                so_tien_pp = tien_thu_them if tien_thu_them > 0 else phu_phi
                ThanhToan.objects.create(
                    ma_thanh_toan=f"TT-PHU-{ma_hd}",
                    ma_hop_dong=hd,
                    ma_nhan_vien=nv_lap,
                    so_tien=so_tien_pp,
                    loai_thanh_toan="PHU_PHI",
                    hinh_thuc="TIEN_MAT",
                    trang_thai="THANH_CONG",
                    thoi_gian_thanh_toan=ngay_kt_tt or ngay_kt_dk,
                    ma_giao_dich=f"Thu phụ phí phát sinh HĐ {ma_hd}",
                )

        return hd

    # A. 24 Hợp đồng DANG_THUE:
    # - 18 HĐ thuê dài hạn (bắt đầu cách đây 2-10 ngày, kết thúc sau 35 - 65 ngày nữa -> 1 tháng sau báo cáo vẫn DANG_THUE!)
    for i in range(18):
        xe = xe_dang_thue_list[i]
        kh = customers[i % 35]  # Ưu tiên khách quốc tế (0..29) và vài khách VN uy tín
        nv_l = staff_quay[i % len(staff_quay)]
        nv_t = staff_tech[i % len(staff_tech)]
        bd = now - timedelta(days=random.randint(1, 10), hours=random.randint(1, 5))
        kt_dk = now + timedelta(days=random.randint(36, 65))
        don_link = converted_bookings[i] if i < 3 else None
        create_contract_bundle(
            kh=kh, xe=xe, nv_lap=nv_l, nv_tech=nv_t,
            trang_thai_hd="DANG_THUE",
            ngay_bd=bd, ngay_kt_dk=kt_dk,
            ma_don_dat=don_link,
            ghi_chu_hd="Hợp đồng thuê dài hạn theo tháng cho chuyên gia / khách lưu trú dài ngày tại Đà Nẵng.",
            tt_days_ago=i % 7,  # Rải đều doanh thu trong 7 ngày gần nhất để biểu đồ 7 ngày đẹp
        )

    # - 4 HĐ DANG_THUE nhưng SẮP HẾT HẠN (<24h tới: còn 5h, 10h, 16h, 21h) -> Test cảnh báo vàng & nút Gia hạn
    sap_het_han_hours = [5, 10, 16, 21]
    for idx_s, hrs_left in enumerate(sap_het_han_hours):
        xe = xe_dang_thue_list[18 + idx_s]
        kh = customers[idx_s]
        nv_l = staff_quay[idx_s % len(staff_quay)]
        nv_t = staff_tech[idx_s % len(staff_tech)]
        bd = now - timedelta(days=3, hours=(24 - hrs_left))
        kt_dk = now + timedelta(hours=hrs_left)
        create_contract_bundle(
            kh=kh, xe=xe, nv_lap=nv_l, nv_tech=nv_t,
            trang_thai_hd="DANG_THUE",
            ngay_bd=bd, ngay_kt_dk=kt_dk,
            ghi_chu_hd=f"Hợp đồng sắp đến hạn trả xe trong {hrs_left} giờ tới.",
            tt_days_ago=3,
        )

    # - 2 HĐ DANG_THUE nhưng QUÁ HẠN (trễ 3 tiếng và trễ 19 tiếng) -> Test cảnh báo đỏ Quá hạn & tính phí trễ
    qua_han_hours = [3, 19]
    for idx_q, hrs_over in enumerate(qua_han_hours):
        xe = xe_dang_thue_list[22 + idx_q]
        kh = kh_luu_y_list[idx_q % len(kh_luu_y_list)]
        nv_l = staff_quay[idx_q % len(staff_quay)]
        nv_t = staff_tech[idx_q % len(staff_tech)]
        bd = now - timedelta(days=4, hours=hrs_over)
        kt_dk = now - timedelta(hours=hrs_over)
        create_contract_bundle(
            kh=kh, xe=xe, nv_lap=nv_l, nv_tech=nv_t,
            trang_thai_hd="DANG_THUE",
            ngay_bd=bd, ngay_kt_dk=kt_dk,
            ghi_chu_hd=f"Cảnh báo: Khách đã quá hạn trả xe {hrs_over} giờ, lễ tân đã liên hệ nhắc trả xe.",
            tt_days_ago=4,
        )

    # B. 6 Hợp đồng CHO_BAN_GIAO -> Test nút Xuất bãi giao xe
    for idx_cbg in range(6):
        xe = xe_cho_ban_giao_list[idx_cbg]
        kh = customers[5 + idx_cbg]
        nv_l = staff_quay[idx_cbg % len(staff_quay)]
        nv_t = staff_tech[idx_cbg % len(staff_tech)]
        bd = now + timedelta(hours=idx_cbg + 1)
        kt_dk = bd + timedelta(days=random.randint(3, 15))
        create_contract_bundle(
            kh=kh, xe=xe, nv_lap=nv_l, nv_tech=nv_t,
            trang_thai_hd="CHO_BAN_GIAO",
            ngay_bd=bd, ngay_kt_dk=kt_dk,
            ghi_chu_hd="Khách đã ký hợp đồng tại quầy, đang dắt xe ra bãi để kiểm tra bàn giao.",
        )

    # C. 14 Hợp đồng DA_TRA (trong 7 ngày gần nhất & tháng trước) -> Tạo lịch sử cho toàn bộ 40 khách hàng + Doanh thu 7 ngày
    for idx_dt in range(14):
        xe = xe_con_trong_list[idx_dt % len(xe_con_trong_list)]
        # Gán cho các khách chưa có lịch sử (từ KH0012 đến KH0039) + 3 khách Blacklist có hợp đồng vi phạm
        if idx_dt < 3:
            kh = kh_blacklist_list[idx_dt]
            phu_phi_val = Decimal("500000")
            days_ago = random.randint(15, 28)
            dur = 3
            bd = now - timedelta(days=days_ago + dur)
            kt_dk = now - timedelta(days=days_ago)
            kt_tt = kt_dk + timedelta(days=2)  # Trễ 2 ngày
            note_dt = "Hợp đồng vi phạm nghiêm trọng dẫn đến đưa vào danh sách Blacklist."
        else:
            kh = customers[(12 + idx_dt * 2) % len(customers)]
            if kh.muc_tin_nhiem == "BLACKLIST":
                kh = kh_tot_list[idx_dt % len(kh_tot_list)]
            phu_phi_val = Decimal("90000") if idx_dt in (4, 8) else Decimal("0")
            days_ago = idx_dt % 7  # Rải đều trong 7 ngày gần đây để biểu đồ 7 ngày có cột đẹp!
            dur = random.randint(2, 6)
            bd = now - timedelta(days=days_ago + dur)
            kt_dk = now - timedelta(days=days_ago)
            kt_tt = kt_dk + (timedelta(hours=3) if phu_phi_val > 0 else timedelta(minutes=-15))
            note_dt = "Khách trả xe đúng hẹn, hoàn tất thanh lý." if phu_phi_val == 0 else "Khách trả trễ 3 giờ, đã khấu trừ phụ phí vào tiền cọc."

        create_contract_bundle(
            kh=kh, xe=xe, nv_lap=staff_quay[idx_dt % len(staff_quay)], nv_tech=staff_tech[idx_dt % len(staff_tech)],
            trang_thai_hd="DA_TRA",
            ngay_bd=bd, ngay_kt_dk=kt_dk, ngay_kt_tt=kt_tt,
            phu_phi=phu_phi_val,
            ghi_chu_hd=note_dt,
            tt_days_ago=days_ago,
        )

    # D. 2 Hợp đồng DA_HUY -> Đủ 4 trạng thái hợp đồng
    for idx_huy in range(2):
        xe = xe_con_trong_list[20 + idx_huy]
        kh = kh_tot_list[15 + idx_huy]
        bd = now - timedelta(days=6 + idx_huy)
        kt_dk = bd + timedelta(days=3)
        create_contract_bundle(
            kh=kh, xe=xe, nv_lap=staff_quay[0], nv_tech=staff_tech[0],
            trang_thai_hd="DA_HUY",
            ngay_bd=bd, ngay_kt_dk=kt_dk,
            hinh_thuc_coc="GIU_CCCD",
            ghi_chu_hd="Khách hủy hợp đồng trước khi xuất bãi do thay đổi kế hoạch công tác.",
        )

    # ------------------------------------------------------------------
    # 8. TẠO 12 PHIẾU BẢO DƯỠNG (5 PHIẾU DANG_XU_LY + 7 PHIẾU HOAN_THANH)
    # ------------------------------------------------------------------
    print("8/9. Đang khởi tạo 12 Phiếu bảo dưỡng kỹ thuật (Đang xử lý & Hoàn thành)...")
    # 5 phiếu DANG_XU_LY tương ứng chính xác với 5 xe đang ở trạng thái BAO_DUONG
    maint_active_specs = [
        ("BD001", xe_bao_duong_list[0], "DINH_KY", "CAO", True,
         ["Thay nhớt máy", "Thay nhớt hộp số (nhớt lap)", "Kiểm tra hệ thống phanh", "Kiểm tra lốp & áp suất"],
         "Xe chạm ngưỡng bảo dưỡng định kỳ 2.000 km, má phanh trước mòn 70%.",
         "Thay nhớt Motul Scooter, thay nhớt lap, thay bố thắng đĩa trước.",
         "", Decimal("320000"), Decimal("80000")),
        ("BD002", xe_bao_duong_list[1], "DINH_KY", "BINH_THUONG", True,
         ["Thay nhớt máy", "Vệ sinh lọc gió", "Kiểm tra bugi & hệ thống điện"],
         "Bảo dưỡng định kỳ 2.000 km sau chuyến thuê dài ngày.",
         "Thay nhớt máy, vệ sinh kim phun buồng đốt, thay lọc gió chính hãng.",
         "", Decimal("280000"), Decimal("50000")),
        ("BD003", xe_bao_duong_list[2], "SUA_CHUA", "KHAN_CAP", False,
         ["Kiểm tra giảm xóc", "Kiểm tra hệ thống phanh", "Kiểm tra lốp & áp suất"],
         "Lốp sau cán đinh lớn rách thành lốp, giảm xóc sau hơi yếu.",
         "Thay mới lốp không săm Chengshin chính hãng, cân chỉnh phuộc sau.",
         "", Decimal("550000"), Decimal("100000")),
        ("BD004", xe_bao_duong_list[3], "KIEM_TRA", "THAP", False,
         ["Kiểm tra đèn, còi, xi-nhan", "Kiểm tra ắc quy"],
         "Đèn pha cốt chập chờn khi đi trời mưa.",
         "Thay bóng LED pha, bọc lại giắc cắm chống nước.",
         "", Decimal("180000"), Decimal("40000")),
        ("BD005", xe_bao_duong_list[4], "DINH_KY", "CAO", True,
         ["Kiểm tra pin & cell pin", "Kiểm tra bộ sạc & cổng sạc", "Kiểm tra động cơ điện / IC", "Kiểm tra hệ thống phanh"],
         "Xe máy điện bảo dưỡng định kỳ 2.000 km, kiểm tra hiệu suất pin LFP.",
         "Cân bằng cell pin trên máy chẩn đoán, vệ sinh cổng sạc, thay má phanh sau.",
         "", Decimal("250000"), Decimal("100000")),
    ]

    for ma_bd, xe_bd, loai, uu_tien, reset_flag, hang_muc, tinh_trang, noi_dung_sc, ket_qua, cp_pt, cp_khac in maint_active_specs:
        NhatKyBaoDuong.objects.create(
            ma_phieu_bao_duong=ma_bd,
            bien_so_xe=xe_bd,
            ma_nhan_vien=staff_tech[0] if int(ma_bd[-1]) % 2 == 1 else staff_tech[1],
            ngay_bao_duong=today - timedelta(days=random.randint(0, 2)),
            ngay_hoan_thanh=None,
            loai_bao_duong=loai,
            muc_do_uu_tien=uu_tien,
            odo_luc_bao_duong=xe_bd.odo_hien_tai,
            odo_hoan_thanh=None,
            reset_odo_luy_ke=reset_flag,
            don_vi_sua_chua="Xưởng nội bộ Vietmoto",
            hang_muc_kiem_tra=hang_muc,
            tinh_trang_phat_hien=tinh_trang,
            noi_dung_sua_chua=noi_dung_sc,
            ket_qua_xu_ly=ket_qua,
            noi_dung=noi_dung_sc,
            chi_phi_phu_tung=cp_pt,
            chi_phi_khac=cp_khac,
            trang_thai="DANG_XU_LY",
        )

    # 7 phiếu HOAN_THANH trong quá khứ (để trang Báo cáo thống kê đầy đủ Chi phí bảo dưỡng & Lợi nhuận ròng)
    for idx_ht in range(6, 13):
        xe_ht = xe_con_trong_list[idx_ht]
        is_dien_ht = xe_ht.ma_dong_xe.loai_dong_co == "DIEN"
        ngay_tiep_nhan = today - timedelta(days=random.randint(3, 25))
        ngay_xong = ngay_tiep_nhan + timedelta(days=1)
        odo_tn = max(2000, xe_ht.odo_hien_tai - random.randint(500, 1400))

        NhatKyBaoDuong.objects.create(
            ma_phieu_bao_duong=f"BD{idx_ht:03d}",
            bien_so_xe=xe_ht,
            ma_nhan_vien=staff_tech[idx_ht % 2],
            ngay_bao_duong=ngay_tiep_nhan,
            ngay_hoan_thanh=ngay_xong,
            loai_bao_duong="DINH_KY",
            muc_do_uu_tien="BINH_THUONG",
            odo_luc_bao_duong=odo_tn,
            odo_hoan_thanh=odo_tn + 2,
            reset_odo_luy_ke=True,
            don_vi_sua_chua="Xưởng nội bộ Vietmoto",
            hang_muc_kiem_tra=(
                ["Kiểm tra pin & cell pin", "Kiểm tra bộ sạc & cổng sạc", "Kiểm tra hệ thống phanh"]
                if is_dien_ht else
                ["Thay nhớt máy", "Thay nhớt hộp số (nhớt lap)", "Kiểm tra hệ thống phanh", "Kiểm tra lốp & áp suất"]
            ),
            tinh_trang_phat_hien="Xe đến chu kỳ bảo dưỡng định kỳ 2.000 km.",
            noi_dung_sua_chua="Bảo dưỡng toàn diện định kỳ theo tiêu chuẩn kỹ thuật Vietmoto.",
            ket_qua_xu_ly="Đã hoàn tất bảo dưỡng, chạy thử ổn định, reset ODO lũy kế về 0 km.",
            noi_dung="Bảo dưỡng định kỳ 2.000 km hoàn tất.",
            chi_phi_phu_tung=Decimal(random.choice([250000, 300000, 350000, 420000])),
            chi_phi_khac=Decimal(random.choice([50000, 80000, 100000])),
            trang_thai="HOAN_THANH",
        )

    # ------------------------------------------------------------------
    # 9. BỔ SUNG NHẬT KÝ VẬN HÀNH BÃI XE CHO CÁC XE CHỜ VỆ SINH / MỚI NHẬP
    # ------------------------------------------------------------------
    print("9/9. Đang ghi nhận Nhật ký vận hành bãi xe...")
    for v in xe_cho_ve_sinh_list:
        NhatKyVanHanhXe.objects.create(
            bien_so_xe=v,
            ma_nhan_vien=staff_tech[0],
            tu_trang_thai="DANG_THUE",
            den_trang_thai="CHO_VE_SINH",
            odo_ghi_nhan=v.odo_hien_tai,
            muc_nhien_lieu_pin=v.muc_nhien_lieu_pin,
            ghi_chu="Thu hồi xe sau chuyến thuê, chuyển khu vực rửa xe / trạm sạc pin.",
        )

    print("==================================================================")
    print("✅ HOÀN TẤT NẠP DỮ LIỆU MẪU THÀNH CÔNG!")
    print(f"   • Nhân viên      : {NhanVien.objects.count()} (Mật khẩu đăng nhập: Vietmoto@123)")
    print(f"   • Dòng xe        : {DongXe.objects.count()} (5 Xăng, 3 Điện)")
    print(f"   • Phương tiện    : {PhuongTien.objects.count()} (55 Xe xăng, 25 Xe điện)")
    print(f"   • Khách hàng     : {KhachHang.objects.count()} (30 Khách quốc tế, 10 Khách Việt Nam)")
    print(f"   • Đơn đặt trước  : {DonDatTruoc.objects.count()} (Đủ 5 trạng thái)")
    print(f"   • Hợp đồng thuê  : {HopDongThue.objects.count()} (24 Đang thuê [18 dài hạn >1 tháng, 4 sắp hết hạn, 2 quá hạn], 6 Chờ bàn giao, 14 Đã trả, 2 Đã hủy)")
    print(f"   • Biên bản BG    : {BienBanBanGiao.objects.count()} (Xuất bãi & Thu hồi)")
    print(f"   • Phiếu bảo dưỡng: {NhatKyBaoDuong.objects.count()} (5 Đang xử lý, 7 Hoàn thành)")
    print(f"   • Thanh toán     : {ThanhToan.objects.count()} giao dịch")
    print("==================================================================")


if __name__ == "__main__":
    run_seed()