"""Visual end-to-end test for the Vietmoto rental lifecycle.

Run from the Django project root:
    python manage.py test reviews.test_e2e_visual

To run without showing Chromium:
    set VIETMOTO_HEADLESS=1   (Windows CMD)
    export VIETMOTO_HEADLESS=1  (macOS/Linux)

Adjust robot speed with VIETMOTO_SLOW_MO_MS (default: 1000 ms).

The test uses the real frontend forms and URLs. ORM is used only for fixtures
and assertions; it does not create business records to bypass the UI.
"""

import math
import os
import struct
import zlib
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

# Keep this before Django model imports. The live server and Playwright run in
# different threads while the test also performs ORM assertions.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import sync_playwright

from reviews.models import (
    BienBanBanGiao,
    DongXe,
    DonDatTruoc,
    HinhAnhBienBan,
    HopDongThue,
    KhachHang,
    NhanVien,
    NhatKyBaoDuong,
    PhuongTien,
    ThanhToan,
)

User = get_user_model()


def _make_tiny_png():
    """Return a valid 1x1 RGBA PNG for mandatory image-upload fields."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw_pixel = b"\x00\xff\xff\xff\xff"  # filter byte + opaque white RGBA pixel
    return (
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw_pixel))
        + chunk(b"IEND", b"")
    )


class VietmotoFullSystemRobotTest(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        headless = os.getenv("VIETMOTO_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}
        slow_mo = int(os.getenv("VIETMOTO_SLOW_MO_MS", "1000"))
        try:
            cls.browser = cls.playwright.chromium.launch(
                headless=headless,
                slow_mo=slow_mo,
            )
        except Exception:
            cls.playwright.stop()
            super().tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, "browser"):
                cls.browser.close()
        finally:
            cls.playwright.stop()
            super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_robot",
            email="robot@vietmoto.test",
            password="Robot-Test-Only-123!",
        )

        # The maintenance completion form only offers active technicians.
        self.technician = NhanVien.objects.create(
            ma_nhan_vien="NV_ROBOT_KT",
            ho_ten="Kỹ thuật viên Robot",
            ten_dang_nhap="kt_robot_test",
            mat_khau="not-used-by-this-test",
            vai_tro="KY_THUAT",
            trang_thai="DANG_LAM",
        )

        self.dong_xe = DongXe.objects.create(
            ma_dong_xe="DX_ROBOT",
            ten_dong_xe="Honda Air Blade 125cc",
            loai_xe="Xe tay ga",
            loai_dong_co="XANG",
            don_gia_ngay=Decimal("180000"),
            tien_coc_dinh_muc=Decimal("1000000"),
            dang_kinh_doanh=True,
        )
        self.xe = PhuongTien.objects.create(
            bien_so_xe="43K1-999.99",
            ma_dong_xe=self.dong_xe,
            trang_thai_xe="CON_TRONG",
            odo_hien_tai=1500,
            odo_luy_ke_bao_duong=0,
            muc_nhien_lieu_pin=100,
        )

        self.context = None
        self.page = None

    def tearDown(self):
        if self.context:
            self.context.close()
        super().tearDown()

    def _goto(self, path):
        response = self.page.goto(
            f"{self.live_server_url}{path}",
            wait_until="domcontentloaded",
        )
        self.assertIsNotNone(response, f"Không nhận được response khi mở {path}")
        self.assertLess(response.status, 400, f"Trang {path} trả HTTP {response.status}")
        return response

    def _post_form(self, form_selector, expected_path):
        """Submit either a normal form or an HTMX-boosted form and await POST."""
        form = self.page.locator(form_selector)
        self.assertTrue(form.count(), f"Không tìm thấy form {form_selector}")
        submit = form.locator('button[type="submit"]').last
        self.assertTrue(submit.count(), f"Form {form_selector} không có nút submit")
        with self.page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and expected_path in response.url
            ),
            timeout=25000,
        ):
            submit.click()
        # Allow HTMX swaps / redirect handling to settle before assertions.
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            # HTMX submissions update the current document without navigation.
            pass
        self.page.wait_for_timeout(350)

    def _upload_test_image(self, selector):
        self.page.locator(selector).set_input_files({
            "name": "robot-test.png",
            "mimeType": "image/png",
            "buffer": _make_tiny_png(),
        })

    def _set_flatpickr_value(self, selector, value):
        self.page.wait_for_function(
            "(sel) => { const el = document.querySelector(sel); return !!(el && el._flatpickr); }",
            arg=selector,
            timeout=20000,
        )
        self.page.locator(selector).evaluate(
            "(el, val) => el._flatpickr.setDate(val, true)",
            value,
        )
        actual = self.page.locator(selector).input_value()
        self.assertEqual(actual, value, f"Flatpickr không cập nhật đúng {selector}")

    def test_full_rental_lifecycle_through_real_ui(self):
        self.context = self.browser.new_context(
            viewport={"width": 1440, "height": 950},
            accept_downloads=True,
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.page.on("dialog", lambda dialog: dialog.accept())

        # Generate future local times rounded to the picker’s 15-minute step.
        local_now = timezone.localtime(timezone.now())
        start_dt = local_now + timedelta(hours=3)
        rounded_minute = int(math.ceil(start_dt.minute / 15.0) * 15)
        if rounded_minute == 60:
            start_dt = start_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            start_dt = start_dt.replace(minute=rounded_minute, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=2)
        extend_dt = start_dt + timedelta(days=3)
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M")
        extend_str = extend_dt.strftime("%Y-%m-%dT%H:%M")

        try:
            # 0. LOGIN
            print("\n[0/11] Robot đăng nhập Vietmoto...")
            self._goto(reverse("login"))
            self.page.fill('input[name="username"]', "admin_robot")
            self.page.fill('input[name="password"]', "Robot-Test-Only-123!")
            self._post_form('form:has(input[name="username"])', "/accounts/login/")
            self.assertNotIn("/accounts/login/", self.page.url, "Đăng nhập thất bại")

            # 1. CREATE CUSTOMER THROUGH CUSTOMER FORM
            print("[1/11] Robot tạo hồ sơ khách hàng qua giao diện...")
            self._goto(reverse("khach_hang_create"))
            self.page.fill('input[name="ho_ten"]', "Lê Hoàng Robot")
            self.page.fill('input[name="so_dien_thoai"]', "0905777888")
            self.page.fill('input[name="so_cccd"]', "048099777888")
            self.page.fill('input[name="giay_phep_lai_xe"]', "GPLX-ROBOT-001")
            self._post_form('form:has(input[name="ho_ten"])', "/khach-hang/them/")

            khach = KhachHang.objects.filter(so_dien_thoai="0905777888").first()
            self.assertIsNotNone(
                khach,
                "Backend: Không tạo được khách hàng qua biểu mẫu frontend (test không tự tạo bù bằng ORM).",
            )
            self.assertEqual(khach.ho_ten, "Lê Hoàng Robot")

            # 2. CREATE BOOKING THROUGH CUSTOM CUSTOMER PICKER + FLATPICKR
            print("[2/11] Robot chọn khách, chọn xe và tạo đơn đặt trước...")
            self._goto(reverse("booking_create"))
            search = self.page.locator("#bookingCustomerSearch")
            search.fill("0905777888")
            customer_option = self.page.locator(".booking-customer-item").filter(
                has_text="0905777888"
            ).first
            customer_option.wait_for(state="visible")
            customer_option.click()
            self.assertEqual(
                self.page.locator("#id_ma_khach_hang").input_value(),
                str(khach.pk),
                "Frontend không gắn mã khách hàng vào hidden field.",
            )

            self.page.locator("#id_bien_so_xe").select_option(value=self.xe.bien_so_xe)
            self._set_flatpickr_value("#id_thoi_gian_hen_nhan", start_str)
            self._set_flatpickr_value("#id_thoi_gian_du_kien_tra", end_str)
            self.assertEqual(self.page.locator("#id_tien_coc_giu_cho").input_value(), "100000")
            self._post_form("#bookingCreateForm", "/bookings/create/")

            booking = DonDatTruoc.objects.filter(
                ma_khach_hang=khach,
                bien_so_xe=self.xe,
            ).latest("ngay_tao")
            self.assertEqual(booking.trang_thai_don, "DA_GIU_CHO")
            self.assertTrue(booking.da_thanh_toan_coc)
            self.assertEqual(booking.tien_coc_giu_cho, Decimal("100000"))

            # 3. OPEN BOOKING DETAIL AND CONVERT IT TO A CONTRACT
            print("[3/11] Robot chuyển đơn đặt trước thành hợp đồng...")
            self._goto(reverse("booking_list"))
            detail_button = self.page.locator(
                f'.js-open-detail[data-code="{booking.ma_don_dat}"]'
            )
            detail_button.wait_for(state="visible")
            detail_button.click()
            self.page.locator("#bookingDetailModal.show").wait_for(state="visible")
            self.assertTrue(self.page.locator("#btn_lap_hop_dong").is_visible())
            with self.page.expect_navigation(wait_until="domcontentloaded"):
                self.page.click("#btn_lap_hop_dong")

            self.assertIn(reverse("hop_dong_create"), self.page.url)
            self.assertEqual(
                self.page.locator("#id_ma_khach_hang").input_value(),
                str(khach.pk),
                "Form hợp đồng không nhận khách hàng từ đơn đặt trước.",
            )
            contract_form = self.page.locator("#contractCreateForm")
            self.assertTrue(contract_form.is_visible())
            self._post_form("#contractCreateForm", "/hop-dong/lap-moi/")

            hd = HopDongThue.objects.filter(ma_don_dat=booking).first()
            self.assertIsNotNone(hd, "Backend: Chưa sinh hợp đồng từ đơn đặt trước.")
            self.assertEqual(hd.trang_thai_hop_dong, "CHO_BAN_GIAO")
            booking.refresh_from_db()
            self.assertEqual(booking.trang_thai_don, "DA_CHUYEN_HD")
            self.xe.refresh_from_db()
            self.assertEqual(self.xe.trang_thai_xe, "DANG_THUE")

            # 4. HANDOVER: REQUIRED CHECKLIST + REQUIRED PHOTO UPLOAD
            print("[4/11] Robot nghiệm thu và bàn giao xe...")
            self.assertIn(reverse("bien_ban_xuat_bai", args=[hd.ma_hop_dong]), self.page.url)
            self.page.locator('input[name="so_km_odo"]').fill("1500")
            self.page.locator('select[name="muc_vach_xang"]').select_option(label="Đầy bình xăng")
            self.page.locator('textarea[name="tinh_trang_ngoai_quan"]').fill(
                "Xe sạch, ngoại quan tốt, không phát hiện hư hỏng trước khi giao."
            )
            self.page.locator('input[name="xac_nhan_ban_giao"]').check()
            self._upload_test_image('input[name="hinh_anh_xe"]')
            self._post_form("#form-xuat-bai", "/hop-dong/")

            hd.refresh_from_db()
            self.xe.refresh_from_db()
            bb_xuat = BienBanBanGiao.objects.filter(
                ma_hop_dong=hd,
                loai_bien_ban="XUAT",
            ).first()
            self.assertIsNotNone(bb_xuat, "Chưa tạo biên bản xuất bãi.")
            self.assertEqual(hd.trang_thai_hop_dong, "DANG_THUE")
            self.assertEqual(self.xe.trang_thai_xe, "DANG_THUE")
            self.assertTrue(HinhAnhBienBan.objects.filter(ma_bien_ban=bb_xuat).exists())
            self.assertTrue(
                ThanhToan.objects.filter(
                    ma_hop_dong=hd,
                    loai_thanh_toan="THANH_TOAN_CUOI",
                    trang_thai="THANH_CONG",
                ).exists(),
                "Không tìm thấy giao dịch thanh toán cước được ghi nhận khi bàn giao.",
            )

            # 5. PRINT CONTRACT AND VIEW HANDOVER RECORD
            print("[5/11] Robot kiểm tra bản in hợp đồng và biên bản xuất...")
            self._goto(reverse("hop_dong_print", args=[hd.ma_hop_dong]))
            self.assertIn(hd.ma_hop_dong, self.page.locator("body").inner_text())
            self._goto(reverse("bien_ban_detail", args=[bb_xuat.ma_bien_ban]))
            self.assertIn(bb_xuat.ma_bien_ban, self.page.locator("body").inner_text())

            # 6. EXTEND CONTRACT
            print("[6/11] Robot gia hạn hợp đồng...")
            self._goto(reverse("hop_dong_gia_han", args=[hd.ma_hop_dong]))
            self._set_flatpickr_value("#id_ngay_ket_thuc_moi", extend_str)
            self.page.locator('textarea[name="ghi_chu_gia_han"]').fill(
                "Kiểm thử tự động gia hạn thêm một ngày."
            )
            self._post_form(
                'form:has(input[name="ngay_ket_thuc_moi"])',
                f"/hop-dong/{hd.ma_hop_dong}/gia-han/",
            )
            hd.refresh_from_db()
            self.assertEqual(
                timezone.localtime(hd.ngay_ket_thuc_du_kien).strftime("%Y-%m-%dT%H:%M"),
                extend_str,
                "Hạn trả hợp đồng chưa được cập nhật sau gia hạn.",
            )

            # 7. RETURN VEHICLE: REQUIRED PHOTO + ODO
            print("[7/11] Robot nghiệm thu trả xe và tất toán...")
            self._goto(reverse("bien_ban_tra_xe", args=[hd.ma_hop_dong]))
            self.page.locator("#id_odo_tra").fill("1680")
            self.page.locator("#id_vach_xang_tra").select_option(label="Đầy bình xăng")
            self.page.locator('input[name="tinh_trang_ngoai_quan"]').fill(
                "Xe được trả lại trong tình trạng hoạt động bình thường."
            )
            self._upload_test_image("#id_hinh_anh_xe")
            self._post_form('form:has(#id_odo_tra)', f"/hop-dong/{hd.ma_hop_dong}/thu-hoi/")

            hd.refresh_from_db()
            self.xe.refresh_from_db()
            bb_tra = BienBanBanGiao.objects.filter(
                ma_hop_dong=hd,
                loai_bien_ban="TRA",
            ).first()
            self.assertIsNotNone(bb_tra, "Chưa tạo biên bản thu hồi xe.")
            self.assertEqual(hd.trang_thai_hop_dong, "DA_TRA")
            self.assertEqual(self.xe.odo_hien_tai, 1680)
            self.assertEqual(self.xe.trang_thai_xe, "CHO_VE_SINH")
            self.assertTrue(HinhAnhBienBan.objects.filter(ma_bien_ban=bb_tra).exists())

            # 8. COMPLETE WASHING / CHARGING USING THE VEHICLE LIST UI
            print("[8/11] Robot xác nhận hoàn tất vệ sinh xe tại bãi...")
            self._goto(reverse("vehicle_list"))
            row = self.page.locator(f'tr[data-plate="{self.xe.bien_so_xe}"]')
            ready_button = row.locator('button[onclick*="openQuickReadyModal"]')
            ready_button.wait_for(state="visible")
            ready_button.click()
            self.page.locator("#quickReadyModal").wait_for(state="visible")
            # This is a hidden input populated by openQuickReadyModal(); do not fill it.
            self.assertEqual(
                self.page.locator("#quickReadyPlateInput").input_value(),
                self.xe.bien_so_xe,
                "Modal xác nhận sẵn sàng chưa nhận đúng biển số xe.",
            )
            self.page.locator("#quickReadyFuelInput").fill("100")
            self._post_form("#quickReadyModal form", "/quan-ly-xe/")
            self.xe.refresh_from_db()
            self.assertEqual(self.xe.trang_thai_xe, "CON_TRONG")

            # 9. REPORT A FAULT, THEN COMPLETE THE MAINTENANCE TICKET THROUGH UI
            print("[9/11] Robot tạo và hoàn tất phiếu bảo dưỡng qua giao diện...")
            self._goto(reverse("vehicle_list"))
            row = self.page.locator(f'tr[data-plate="{self.xe.bien_so_xe}"]')
            row.locator('button[onclick*="openQuickMaintModal"]').click()
            self.page.locator("#quickMaintModal").wait_for(state="visible")
            # Hidden field is populated by the maintenance modal JavaScript.
            self.assertEqual(
                self.page.locator("#quickMaintPlateInput").input_value(),
                self.xe.bien_so_xe,
                "Modal bảo dưỡng chưa nhận đúng biển số xe.",
            )
            self.page.locator("#quickMaintType").select_option("SUA_CHUA")
            self.page.locator("#quickMaintReason").fill(
                "Kiểm tra định kỳ bằng robot: kiểm tra phanh và lốp."
            )
            self._post_form("#quickMaintModal form", "/quan-ly-xe/")

            self.xe.refresh_from_db()
            self.assertEqual(self.xe.trang_thai_xe, "BAO_DUONG")
            phieu = NhatKyBaoDuong.objects.filter(
                bien_so_xe=self.xe,
                trang_thai="DANG_XU_LY",
            ).latest("ngay_tao")

            self._goto(reverse("vehicle_list"))
            row = self.page.locator(f'tr[data-plate="{self.xe.bien_so_xe}"]')
            row.locator('button[onclick*="openMaintenanceModal"]').click()
            self.page.locator("#maintenanceModal").wait_for(state="visible")
            self.page.locator('select[name="ma_nhan_vien"]').select_option(
                value=self.technician.ma_nhan_vien
            )
            self.page.locator('textarea[name="tinh_trang_phat_hien"]').fill(
                "Không phát hiện lỗi nghiêm trọng trong kiểm tra tự động."
            )
            self.page.locator('textarea[name="noi_dung_sua_chua"]').fill(
                "Kiểm tra phanh, lốp và siết lại các vị trí cần thiết."
            )
            self.page.locator('textarea[name="ket_qua_xu_ly"]').fill(
                "Đã kiểm tra, xe đủ điều kiện vận hành."
            )
            self.page.locator("#maintenanceStatus").select_option("HOAN_THANH")
            # Flatpickr uses a hidden original input when altInput is enabled.
            # Set the date through the Flatpickr instance, not Locator.fill().
            self._set_flatpickr_value(
                "#maintenanceCompletionDate",
                timezone.localdate().strftime("%Y-%m-%d"),
            )
            self.page.locator("#maintenanceAfterStatus").select_option("CON_TRONG")
            self._post_form("#maintenanceForm", "/quan-ly-xe/")

            phieu.refresh_from_db()
            self.xe.refresh_from_db()
            self.assertEqual(phieu.trang_thai, "HOAN_THANH")
            self.assertEqual(self.xe.trang_thai_xe, "CON_TRONG")

            # 10. DASHBOARD
            print("[10/11] Robot kiểm tra Dashboard tổng quan...")
            response = self._goto(reverse("tong_quan"))
            self.assertEqual(response.status, 200)
            self.assertTrue(self.page.locator("body").inner_text().strip())

            # 11. REPORTS
            print("[11/11] Robot kiểm tra Báo cáo & Thống kê...")
            response = self._goto(reverse("bao_cao"))
            self.assertEqual(response.status, 200)
            self.assertTrue(self.page.locator("body").inner_text().strip())

            print("\nHOÀN TẤT: kiểm thử vòng đời Vietmoto từ khách hàng đến báo cáo.")

        except Exception:
            # Keep a visual artifact whenever a step fails, so the failing page
            # can be inspected without rerunning the whole lifecycle immediately.
            result_dir = Path.cwd() / "test-results"
            result_dir.mkdir(parents=True, exist_ok=True)
            screenshot = result_dir / "vietmoto_e2e_failure.png"
            try:
                self.page.screenshot(path=str(screenshot), full_page=True)
                print(f"\nẢnh chụp màn hình khi lỗi: {screenshot}")
                print(f"URL tại thời điểm lỗi: {self.page.url}")
            except Exception:
                pass
            raise
