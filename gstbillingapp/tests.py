import datetime
import json
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, override_settings, TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from . import appusers, syncup_client
from .models import (AppUser as AppUserModel, Customer, Book, BookLog, Employee,
                     Invoice, ChequeLeaf)


class ProductsListTests(TestCase):
    """The migrated (server-paginated) Products list + CSV export."""
    def setUp(self):
        from .models import Product, ProductCategory
        self.user = User.objects.create_user("prodowner", password="pw12345!")
        self.client.force_login(self.user)
        self.cat = ProductCategory.objects.create(user=self.user, category_name="Cement")
        for i in range(30):
            Product.objects.create(user=self.user, model_no=f"MDL-{i:03d}",
                                   product_name=f"Widget {i}", product_category=self.cat,
                                   product_rate_with_gst=100 + i)
        Product.objects.create(user=self.user, model_no="SPECIAL-1", product_name="Findable Gadget")

    def test_list_paginates(self):
        r = self.client.get(reverse("products"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="gs"')          # new design system in use
        self.assertContains(r, "31 products")          # total count shown
        # 25 per page → only 25 rows rendered, not all 31
        self.assertEqual(r.content.decode().count('class="prim"'), 25)
        r2 = self.client.get(reverse("products"), {"page": 2})
        self.assertEqual(r2.content.decode().count('class="prim"'), 6)

    def test_search_filters(self):
        # icontains search (case-insensitive); model uppercases product_name on save.
        r = self.client.get(reverse("products"), {"q": "Findable"})
        self.assertContains(r, "SPECIAL-1")
        self.assertNotContains(r, "MDL-000")

    def test_category_filter(self):
        r = self.client.get(reverse("products"), {"cat": self.cat.id})
        self.assertContains(r, "30 products")

    def test_csv_export_all_rows(self):
        r = self.client.get(reverse("products_export"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        body = r.content.decode()
        self.assertIn("Model No,Product Name,Category", body)
        # header + 31 rows
        self.assertEqual(len([ln for ln in body.splitlines() if ln.strip()]), 32)

    def test_export_respects_search(self):
        r = self.client.get(reverse("products_export"), {"q": "Findable"})
        lines = [ln for ln in r.content.decode().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)  # header + 1 match

    def _form_post(self, model_no):
        return {
            'model_no': model_no, 'product_name': 'New One', 'product_hsn': '1234',
            'product_gst_percentage': 18, 'product_purchase_rate': 100,
            'product_rate_with_gst': 150, 'product_discount': 5,
            'product_division_category': '', 'product_model_category': '',
            'product_colour': '', 'product_image_url': '', 'product_category': '',
        }

    def test_add_product_via_form(self):
        from .models import Product
        r = self.client.post(reverse("product_add"), self._form_post("NEWPROD-1"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Product.objects.filter(user=self.user, model_no="NEWPROD-1").exists())

    def test_edit_product_via_form(self):
        from .models import Product
        p = Product.objects.create(user=self.user, model_no="EDIT-ME", product_name="Old")
        data = self._form_post("EDIT-ME"); data['product_name'] = "Renamed"
        r = self.client.post(reverse("product_edit", args=[p.id]), data)
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.product_name, "RENAMED")  # model uppercases on save


class LoginRememberMeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("shopowner", password="pw12345!")

    def test_remember_me_persists_session(self):
        # Checked → session keeps its cookie age, so it survives a browser close.
        r = self.client.post(reverse("login_view"),
                             {"username": "shopowner", "password": "pw12345!", "remember": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_no_remember_expires_at_browser_close(self):
        # Unchecked → a browser-session cookie that clears on close (shared machine).
        r = self.client.post(reverse("login_view"),
                             {"username": "shopowner", "password": "pw12345!"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.client.session.get_expire_at_browser_close())


class CustomerInsightsTests(TestCase):
    """Point-of-billing 'know your customer' endpoint (Group A + price history)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='shop', password='x')
        cls.customer = Customer.objects.create(
            user=cls.user, customer_name='Acme Traders',
            customer_phone='9876543210', credit_limit=2000,
        )
        cls.book = Book.objects.create(user=cls.user, customer=cls.customer, current_balance=-700)

        # A ₹1000 purchase 40 days ago; a ₹300 payment today. Outstanding = 700.
        BookLog.objects.create(
            parent_book=cls.book, change_type=1, change=1000,
            date=timezone.now() - timedelta(days=40),
        )
        BookLog.objects.create(parent_book=cls.book, change_type=0, change=300, date=timezone.now())

        # One recent order with a single line item.
        cls.invoice = Invoice.objects.create(
            user=cls.user, invoice_number=1, invoice_date=date.today(),
            invoice_customer=cls.customer, is_gst=True,
            invoice_json=json.dumps({
                'invoice_total_amt_with_gst': 500,
                'invoice_total_amt_sgst': 45, 'invoice_total_amt_cgst': 45,
                'items': [{
                    'invoice_model_no': 'M1', 'invoice_product': 'Widget',
                    'invoice_qty': 2, 'invoice_rate_with_gst': 250,
                }],
            }),
        )

        ChequeLeaf.objects.create(
            user=cls.user, cheque_number='CHQ-BOUNCE-1',
            status='BOUNCED', payee_name='Acme Traders',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _get(self):
        resp = self.client.get(reverse('customer_insights'), {'customer': self.customer.id})
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_outstanding_and_status(self):
        data = self._get()
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'owes')
        self.assertAlmostEqual(data['outstanding'], 700.0)

    def test_aging_uses_oldest_open_purchase(self):
        # 1000 purchased, only 300 settled → oldest purchase (~40d) is still open.
        # Allow 40/41 for the UTC/local date boundary at run time.
        self.assertIn(self._get()['oldest_unpaid_days'], (40, 41))

    def test_last_payment(self):
        self.assertAlmostEqual(self._get()['last_payment']['amount'], 300.0)

    def test_last_order(self):
        lo = self._get()['last_order']
        self.assertAlmostEqual(lo['amount'], 500.0)
        self.assertEqual(lo['days_ago'], 0)

    def test_bounced_cheque_flag(self):
        self.assertEqual(self._get()['bounced_cheques'], 1)

    def test_credit_headroom(self):
        data = self._get()
        self.assertAlmostEqual(data['credit_limit'], 2000.0)
        self.assertAlmostEqual(data['credit_available'], 1300.0)  # 2000 - 700

    def test_price_history_and_usual_items(self):
        data = self._get()
        self.assertAlmostEqual(data['product_last_prices']['M1'], 250.0)
        self.assertTrue(any(i['model_no'] == 'M1' for i in data['usual_items']))

    def test_scoped_to_user(self):
        other = User.objects.create_user(username='other', password='x')
        self.client.force_login(other)
        resp = self.client.get(reverse('customer_insights'), {'customer': self.customer.id})
        self.assertEqual(resp.status_code, 404)

    def test_bad_request_without_customer(self):
        self.assertEqual(self.client.get(reverse('customer_insights')).status_code, 400)


class TodaySummaryTests(TestCase):
    """Running tally + GST set-aside meter (Group C)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='shop2', password='x')
        cls.customer = Customer.objects.create(user=cls.user, customer_name='Beta')
        Invoice.objects.create(
            user=cls.user, invoice_number=1, invoice_date=date.today(),
            invoice_customer=cls.customer, is_gst=True,
            invoice_json=json.dumps({
                'invoice_total_amt_with_gst': 500,
                'invoice_total_amt_sgst': 45, 'invoice_total_amt_cgst': 45,
            }),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_today_sales_and_gst(self):
        data = self.client.get(reverse('today_summary')).json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['invoice_count'], 1)
        self.assertAlmostEqual(data['sales_total'], 500.0)
        self.assertAlmostEqual(data['gst_month'], 90.0)  # 45 + 45


class MobileAuthTests(TestCase):
    """Signed-token auth for the /m/ mobile web pages (Phase 1 foundation)."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, Employee
        cls.owner = User.objects.create_user(username="owner", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Acme Distributors")
        cls.customer = Customer.objects.create(
            user=cls.owner, customer_name="Beta Store", customer_phone="9876543210",
            is_mobile_user=True,
        )
        book = Book.objects.create(user=cls.owner, customer=cls.customer, current_balance=-1500)
        BookLog.objects.create(parent_book=book, change_type=1, change=1500)   # ₹1500 purchase → owes 1500
        cls.emp = Employee.objects.create(business=cls.owner, name="Rep One", email="rep1@syncup.local")

    def test_customer_token_grants_access_and_shows_dues(self):
        token = _app_token(self.customer)
        resp = self.client.get("/m/customer/", {"t": token})           # token → session
        self.assertEqual(resp.status_code, 302)                        # redirects to clean URL
        resp2 = self.client.get("/m/customer/")                        # rides the session
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "BETA STORE")                       # name (upper-cased on save)
        self.assertContains(resp2, "1,500")                            # outstanding shown (Indian format)

    def test_auth_survives_session_wipe(self):
        # The magic-link identity lives in its own m_auth cookie, so a desktop logout
        # (which flushes the shared Django session) must NOT sign the phone out.
        from .mobile_auth import _COOKIE
        self.client.get("/m/customer/", {"t": _app_token(self.customer)})
        self.assertIn(_COOKIE, self.client.cookies)                    # durable cookie set
        s = self.client.session
        s.flush()                                                      # simulate desktop logout
        resp = self.client.get("/m/customer/")                         # rides the m_auth cookie
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "BETA STORE")

    def test_invalid_token_denied(self):
        resp = self.client.get("/m/customer/", {"t": "tampered.token.value"})
        self.assertEqual(resp.status_code, 403)

    def test_no_token_no_session_denied(self):
        self.assertEqual(self.client.get("/m/customer/").status_code, 403)

    def test_customer_cannot_reach_employee_pages(self):
        self.client.get("/m/customer/", {"t": _app_token(self.customer)})  # customer session
        self.assertEqual(self.client.get("/m/employee/").status_code, 403)          # role-gated

    def test_employee_token_grants_access(self):
        token = _app_token(self.emp)
        self.client.get("/m/employee/", {"t": token})
        resp = self.client.get("/m/employee/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ACME DISTRIBUTORS")

    def test_token_tamper_fails_verification(self):
        from .mobile_auth import verify_mobile_token
        token = _app_token(self.customer)
        self.assertIsNotNone(verify_mobile_token(token))
        self.assertIsNone(verify_mobile_token(token + "x"))


class MobileScreensTests(TestCase):
    """Customer + employee mobile screens render and behave (Phase 2/3)."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, Quotation, Employee
        cls.owner = User.objects.create_user("own2", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Shop", business_phone="9999999999")
        cls.emp = Employee.objects.create(business=cls.owner, name="Field Staff", email="fs1@syncup.local")
        cls.cust = Customer.objects.create(
            user=cls.owner, customer_name="Cust One", customer_phone="9876543210",
            collection_day=1, is_mobile_user=True,
        )
        cls.book = Book.objects.create(user=cls.owner, customer=cls.cust, current_balance=-500)
        BookLog.objects.create(parent_book=cls.book, change_type=1, change=500)
        cls.inv = Invoice.objects.create(
            user=cls.owner, invoice_number=1, invoice_date=date.today(), invoice_customer=cls.cust,
            is_gst=True, invoice_json=json.dumps({
                "invoice_total_amt_with_gst": 500, "invoice_total_amt_without_gst": 424,
                "invoice_total_amt_cgst": 38, "invoice_total_amt_sgst": 38,
                "items": [{"invoice_model_no": "M1", "invoice_product": "Widget",
                           "invoice_qty": 2, "invoice_amt_with_gst": 500}],
            }),
        )
        Quotation.objects.create(user=cls.owner, quotation_number=1, quotation_date=date.today(),
                                 quotation_customer=cls.cust, quotation_json="{}", status="DRAFT")

    def _cust(self):
        self.client.get("/m/customer/", {"t": _app_token(self.cust)})

    def _emp(self):
        self.client.get("/m/employee/", {"t": _app_token(self.emp)})

    def test_customer_screens_render(self):
        self._cust()
        for name, args in [("m_customer_home", []), ("m_customer_books", []),
                           ("m_customer_invoices", []), ("m_customer_invoice", [self.inv.id]),
                           ("m_customer_orders", []), ("m_customer_profile", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_customer_cannot_open_foreign_invoice(self):
        other = Customer.objects.create(user=self.owner, customer_name="Other",
                                        customer_phone="9876500051", is_mobile_user=True)
        self.client.get("/m/customer/", {"t": _app_token(other)})
        self.assertEqual(self.client.get(reverse("m_customer_invoice", args=[self.inv.id])).status_code, 404)

    def test_employee_screens_render(self):
        self._emp()
        for name, args in [("m_employee_home", []), ("m_employee_customers", []),
                           ("m_employee_customer", [self.cust.id]), ("m_employee_invoices", []),
                           ("m_employee_collections", []), ("m_employee_orders", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def _pay(self, amount=200):
        return self.client.post(reverse("m_employee_record_payment", args=[self.cust.id]),
                                data=json.dumps({"amount": amount, "note": "part"}),
                                content_type="application/json")

    def test_employee_payment_is_pending(self):
        # A regular employee's payment is held pending — balance does NOT move.
        self._emp()
        r = self._pay(200)
        self.assertTrue(r.json()["pending"])
        self.book.refresh_from_db()
        self.assertAlmostEqual(self.book.current_balance, -500.0)   # unchanged until approved

    def test_admin_payment_posts_immediately(self):
        self.emp.postings.filter(is_home=True).update(is_admin=True)
        self._emp()
        r = self._pay(200)
        self.assertFalse(r.json()["pending"])
        self.book.refresh_from_db()
        self.assertAlmostEqual(self.book.current_balance, -300.0)   # applied at once

    def test_admin_approves_pending_payment(self):
        from .models import BookLog
        # Employee records a pending payment...
        self._emp()
        self._pay(200)
        pending = BookLog.objects.get(parent_book=self.book, is_active=False, change_type=0)
        self.book.refresh_from_db()
        self.assertAlmostEqual(self.book.current_balance, -500.0)
        # ...then an admin approves it → it posts to the ledger.
        self.emp.postings.filter(is_home=True).update(is_admin=True)
        self._emp()
        r = self.client.post(reverse("m_employee_approval_act", args=[pending.id]),
                             data=json.dumps({"action": "approve"}), content_type="application/json")
        self.assertTrue(r.json()["approved"])
        self.book.refresh_from_db()
        self.assertAlmostEqual(self.book.current_balance, -300.0)

    def test_regular_employee_cannot_open_approvals(self):
        self._emp()
        self.assertEqual(self.client.get(reverse("m_employee_approvals")).status_code, 403)

    def test_employee_customer_scoped(self):
        # employee of one business can't open another business's customer
        stranger = User.objects.create_user("own3", password="x")
        foreign = Customer.objects.create(user=stranger, customer_name="Foreign")
        self._emp()
        self.assertEqual(self.client.get(reverse("m_employee_customer", args=[foreign.id])).status_code, 404)

    def test_admin_sees_dashboard_regular_does_not(self):
        # Regular employee: today's tally + payment-collection progress, but not
        # the full-business financial summary.
        self._emp()
        r = self.client.get(reverse("m_employee_home"))
        self.assertNotContains(r, "Overall Summary")
        self.assertContains(r, "Payment Collection")
        # Promote to admin → full dashboard appears.
        self.emp.postings.filter(is_home=True).update(is_admin=True)
        r2 = self.client.get(reverse("m_employee_home"))
        self.assertContains(r2, "Overall Summary")
        self.assertContains(r2, "Payment Collection")

    def test_my_sales_filter(self):
        self.inv.assigned_employee = self.emp
        self.inv.save(update_fields=["assigned_employee"])
        self._emp()
        # "My sales" filters to invoices credited to this employee, with a total.
        r = self.client.get(reverse("m_employee_invoices"), {"mine": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["mine"])
        self.assertEqual(len(r.context["rows"]), 1)          # only the related invoice
        self.assertAlmostEqual(r.context["rows"][0]["amount"], 500.0)
        # "All" view still shows it, flagged as mine.
        r2 = self.client.get(reverse("m_employee_invoices"))
        self.assertTrue(r2.context["rows"][0]["mine"])


class MobileOrderTests(TestCase):
    """Mobile order flow (/m/order): customer self-order + employee order-for-customer."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, Employee, Product, Quotation
        cls.Quotation = Quotation
        cls.owner = User.objects.create_user("mo_owner", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Mobile Shop", business_phone="9000000000")
        cls.emp = Employee.objects.create(business=cls.owner, name="Rep", email="rep@x.local")
        cls.cust = Customer.objects.create(user=cls.owner, customer_name="Buyer One", customer_phone="9111111111", is_mobile_user=True)
        cls.p1 = Product.objects.create(user=cls.owner, model_no="M1", product_name="Widget",
                                        product_rate_with_gst=118, product_gst_percentage=18, product_discount=0)
        cls.p2 = Product.objects.create(user=cls.owner, model_no="M2", product_name="Gadget",
                                        product_rate_with_gst=236, product_gst_percentage=18, product_discount=0)

    def _cust_session(self):
        self.client.get("/m/customer/", {"t": _app_token(self.cust)})

    def _emp_session(self):
        self.client.get("/m/employee/", {"t": _app_token(self.emp)})

    def test_order_screen_renders_for_customer(self):
        self._cust_session()
        r = self.client.get(reverse("m_order"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "WIDGET")             # product name upper-cased on save

    def test_customer_has_place_order_entry(self):
        # The customer starts an order from the Orders tab.
        self._cust_session()
        r = self.client.get(reverse("m_customer_orders"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("m_order"))        # "Place a new order" link present

    def test_employee_without_customer_sees_picker(self):
        self._emp_session()
        r = self.client.get(reverse("m_order"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "BUYER ONE")          # customer picker (name upper-cased on save)

    def test_customer_checkout_creates_draft(self):
        self._cust_session()
        r = self.client.post(reverse("m_order_checkout"),
                             data=json.dumps({"items": [{"id": self.p1.id, "qty": 2}], "is_gst": False}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        q = self.Quotation.objects.get(id=d["quotation_id"])
        # A fresh mobile order is a DRAFT the buyer is still building — not yet submitted.
        self.assertEqual(q.status, "DRAFT")
        self.assertTrue(q.created_by_customer)
        self.assertEqual(q.quotation_customer_id, self.cust.id)

    def test_confirm_moves_draft_to_pending_and_locks_editing(self):
        q = self._draft_order()
        self.assertEqual(q.status, "DRAFT")
        r = self.client.post(reverse("m_order_confirm", args=[q.id]))
        self.assertTrue(r.json()["ok"])
        q.refresh_from_db()
        self.assertEqual(q.status, "PENDING")            # confirmed → awaiting approval
        # A confirmed order is no longer editable from mobile.
        r = self.client.post(reverse("m_order_update", args=[q.id]),
                             data=json.dumps({"items": [{"id": self.p1.id, "qty": 5}]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_draft_hidden_from_desktop_list_until_confirmed(self):
        q = self._draft_order()
        self.client.force_login(self.owner)
        rows = self.client.get(reverse("quotations_ajax"), {"draw": 1, "start": 0, "length": 50}).json()["data"]
        self.assertNotIn(q.id, [self._row_id(x) for x in rows])   # draft cart is private to mobile
        self.client.logout()
        self._cust_session()
        self.client.post(reverse("m_order_confirm", args=[q.id]))
        self.client.force_login(self.owner)
        rows = self.client.get(reverse("quotations_ajax"), {"draw": 1, "start": 0, "length": 50}).json()["data"]
        self.assertIn(q.id, [self._row_id(x) for x in rows])      # visible once confirmed (PENDING)

    @staticmethod
    def _row_id(row):
        import re
        m = re.search(r"/quotation/(\d+)", row.get("actions", ""))
        return int(m.group(1)) if m else None

    def _total(self, q):
        return json.loads(q.quotation_json)["invoice_total_amt_with_gst"]

    def test_mobile_view_auto_syncs_price(self):
        q = self._draft_order()
        before = self._total(q)
        self.p1.product_rate_with_gst = float(self.p1.product_rate_with_gst) + 50
        self.p1.save()
        self._cust_session()
        self.client.get(reverse("m_order_detail", args=[q.id]))   # opening re-prices it
        q.refresh_from_db()
        self.assertGreater(self._total(q), before)

    def test_desktop_list_reprices_mobile_order(self):
        q = self._pending_order()          # mobile order visible on the desktop list
        before = self._total(q)
        self.p1.product_rate_with_gst = float(self.p1.product_rate_with_gst) + 30
        self.p1.save()
        self.client.force_login(self.owner)
        self.client.get(reverse("quotations_ajax"), {"draw": 1, "start": 0, "length": 50})
        q.refresh_from_db()
        self.assertGreater(self._total(q), before)   # list load re-priced it to today's rate

    def test_desktop_viewer_auto_syncs_mobile_order(self):
        q = self._pending_order()          # mobile order (created_from_cart=True)
        before = self._total(q)
        self.p1.product_rate_with_gst = float(self.p1.product_rate_with_gst) + 40
        self.p1.save()
        self.client.force_login(self.owner)
        r = self.client.get(reverse("quotation_viewer", args=[q.id]))   # opening re-prices it
        self.assertEqual(r.status_code, 200)
        q.refresh_from_db()
        self.assertGreater(self._total(q), before)

    def test_desktop_sync_and_freeze_after_invoice(self):
        from .utils import resync_quotation_prices
        q = self._draft_order()
        before = self._total(q)
        self.p1.product_rate_with_gst = float(self.p1.product_rate_with_gst) + 100
        self.p1.save()
        # Desktop Sync button re-prices and reports the change.
        self.client.force_login(self.owner)
        d = self.client.post(reverse("quotation_resync_prices", args=[q.id])).json()
        self.assertTrue(d["success"])
        self.assertTrue(d["changed"])
        q.refresh_from_db()
        self.assertGreater(self._total(q), before)
        # Once invoiced, prices are frozen — a later catalog change doesn't move it.
        q.status = "CONVERTED"
        q.save(update_fields=["status"])
        locked = self._total(q)
        self.p1.product_rate_with_gst = float(self.p1.product_rate_with_gst) + 100
        self.p1.save()
        self.assertFalse(resync_quotation_prices(q)["changed"])
        q.refresh_from_db()
        self.assertEqual(self._total(q), locked)

    def test_employee_checkout_for_customer(self):
        self._emp_session()
        r = self.client.post(reverse("m_order_checkout"),
                             data=json.dumps({"items": [{"id": self.p2.id, "qty": 1}],
                                              "is_gst": False, "customer": self.cust.id}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        q = self.Quotation.objects.get(id=d["quotation_id"])
        self.assertFalse(q.created_by_customer)
        self.assertEqual(q.quotation_customer_id, self.cust.id)
        self.assertEqual(q.order_employee_id, self.emp.id)   # order credited to the field-staff

    def test_price_is_recomputed_server_side(self):
        # A tampered qty of 0 is rejected; prices never come from the client.
        self._cust_session()
        r = self.client.post(reverse("m_order_checkout"),
                             data=json.dumps({"items": [{"id": self.p1.id, "qty": 0}]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_employee_cannot_order_for_foreign_customer(self):
        stranger = User.objects.create_user("mo_stranger", password="x")
        foreign = Customer.objects.create(user=stranger, customer_name="Foreign")
        self._emp_session()
        r = self.client.post(reverse("m_order_checkout"),
                             data=json.dumps({"items": [{"id": self.p1.id, "qty": 1}],
                                              "customer": foreign.id}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def _draft_order(self):
        self._cust_session()
        r = self.client.post(reverse("m_order_checkout"),
                             data=json.dumps({"items": [{"id": self.p1.id, "qty": 1}], "is_gst": False}),
                             content_type="application/json")
        return self.Quotation.objects.get(id=r.json()["quotation_id"])

    def _pending_order(self):
        q = self._draft_order()
        self.client.post(reverse("m_order_confirm", args=[q.id]))   # buyer confirms → PENDING
        q.refresh_from_db()
        return q

    def test_pending_order_cannot_be_converted_until_approved(self):
        q = self._pending_order()
        self.assertTrue(q.needs_approval)
        self.assertFalse(q.can_be_converted())      # PENDING blocks conversion
        self.client.force_login(self.owner)
        r = self.client.post(reverse("quotation_convert_to_invoice", args=[q.id]))
        self.assertEqual(r.status_code, 400)         # can_be_converted() gate rejects it

    def test_approve_opens_conversion(self):
        q = self._pending_order()
        self.assertFalse(q.can_be_converted())       # blocked while PENDING
        self.client.force_login(self.owner)
        r = self.client.post(reverse("quotation_approve", args=[q.id]))
        self.assertTrue(r.json()["success"])
        q.refresh_from_db()
        self.assertEqual(q.status, "APPROVED")
        self.assertTrue(q.can_be_converted())        # now convertible


class InvoiceAssignEmployeeTests(TestCase):
    """Native invoice → employee attribution (replaces the old external proxy)."""

    def setUp(self):
        from .models import Employee, UserProfile
        self.owner = User.objects.create_user("ia_owner", password="x")
        UserProfile.objects.create(user=self.owner, business_title="Shop")
        self.emp = Employee.objects.create(business=self.owner, name="Ravi")
        self.cust = Customer.objects.create(user=self.owner, customer_name="C")
        self.inv = Invoice.objects.create(
            user=self.owner, invoice_number=1, invoice_date=date.today(),
            invoice_customer=self.cust, is_gst=False,
            invoice_json=json.dumps({"invoice_total_amt_with_gst": 100, "items": []}),
        )
        self.client.force_login(self.owner)

    def _url(self):
        return reverse("invoice_assign_employee", args=[self.inv.id])

    def test_get_lists_employees(self):
        d = self.client.get(self._url()).json()
        self.assertEqual(len(d["employees"]), 1)
        self.assertIsNone(d["current"])

    def test_assign_then_clear(self):
        r = self.client.post(self._url(), data=json.dumps({"employee_id": self.emp.id}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.assigned_employee_id, self.emp.id)
        self.assertIsNotNone(self.inv.assigned_employee_at)
        # Blank clears it.
        r2 = self.client.post(self._url(), data=json.dumps({"employee_id": ""}),
                              content_type="application/json")
        self.assertTrue(r2.json()["cleared"])
        self.inv.refresh_from_db()
        self.assertIsNone(self.inv.assigned_employee_id)

    def test_bulk_map_and_unmap(self):
        posting = self.emp.postings.get(is_home=True)
        inv2 = Invoice.objects.create(user=self.owner, invoice_number=2, invoice_date=date.today(),
            invoice_customer=self.cust, is_gst=False,
            invoice_json=json.dumps({"invoice_total_amt_with_gst": 50, "items": []}))
        # Bulk map both invoices to the employee.
        r = self.client.post(reverse("employee_assign_bulk", args=[posting.id]),
            data=json.dumps({"map": [self.inv.id, inv2.id], "unmap": []}), content_type="application/json")
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["mapped"], 2)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.assigned_employee_id, self.emp.id)
        # Bulk unmap one; only invoices currently credited to this employee are cleared.
        r = self.client.post(reverse("employee_assign_bulk", args=[posting.id]),
            data=json.dumps({"map": [], "unmap": [self.inv.id]}), content_type="application/json")
        self.assertEqual(r.json()["unmapped"], 1)
        self.inv.refresh_from_db()
        self.assertIsNone(self.inv.assigned_employee_id)

    def test_pick_shows_current_assignment(self):
        posting = self.emp.postings.get(is_home=True)
        self.inv.assigned_employee = self.emp
        self.inv.save()
        d = self.client.get(reverse("employee_invoices_pick", args=[posting.id])).json()
        row = next(x for x in d["rows"] if x["id"] == self.inv.id)
        self.assertTrue(row["mine"])
        self.assertEqual(row["assigned"], "RAVI")   # employee name upper-cased on save

    def test_cannot_assign_foreign_employee(self):
        from .models import Employee
        other = User.objects.create_user("ia_other", password="x")
        foreign = Employee.objects.create(business=other, name="X")
        r = self.client.post(self._url(), data=json.dumps({"employee_id": foreign.id}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_foreign_invoice_404(self):
        other = User.objects.create_user("ia_stranger", password="x")
        foreign_inv = Invoice.objects.create(
            user=other, invoice_number=1, invoice_date=date.today(), is_gst=False,
            invoice_json=json.dumps({"invoice_total_amt_with_gst": 1, "items": []}),
        )
        r = self.client.get(reverse("invoice_assign_employee", args=[foreign_inv.id]))
        self.assertEqual(r.status_code, 404)

    def test_employee_statement_lists_assigned_with_total(self):
        self.inv.assigned_employee = self.emp
        self.inv.save(update_fields=["assigned_employee"])
        r = self.client.get(reverse("employee_invoices", args=[self.emp.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["record_count"], 1)
        self.assertAlmostEqual(r.context["grand_total"], 100.0)   # from invoice_json
        self.assertContains(r, "RAVI")                            # employee name (upper-cased)

    def test_statement_scoped_to_business(self):
        other = User.objects.create_user("ia_boss2", password="x")
        from .models import Employee
        foreign_emp = Employee.objects.create(business=other, name="Z")
        r = self.client.get(reverse("employee_invoices", args=[foreign_emp.id]))
        self.assertEqual(r.status_code, 404)


class EmployeeManagementTests(TestCase):
    """Desktop management of a business's mobile employees."""

    def setUp(self):
        self.owner = User.objects.create_user("boss", password="x")
        self.client.force_login(self.owner)

    def test_add_employee(self):
        from .models import Employee
        r = self.client.post(reverse("employee_add"), {
            "name": "Ravi", "email": "Ravi@X.com", "phone": "9876543210",
            "address": "Main St", "is_active": "on",
        })
        self.assertEqual(r.status_code, 302)
        emp = Employee.objects.get(business=self.owner, name="RAVI")   # name upper-cased on save
        self.assertEqual(emp.email, "ravi@x.com")                     # email lower-cased on save

    def test_employee_scoped_to_business(self):
        from .models import Employee
        other = User.objects.create_user("other", password="x")
        emp = Employee.objects.create(business=other, name="X")
        self.assertEqual(self.client.get(reverse("employee_edit", args=[emp.id])).status_code, 404)

    def test_mobile_link_endpoints(self):
        # The old link endpoints are gone: customer logins come from the console, and the
        # employee edit page copies the employee's link directly (no endpoint).
        from django.urls import NoReverseMatch
        for name in ("customer_mobile_link", "employee_mobile_link", "employee_revoke"):
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=[1])

    def test_employee_share_and_add(self):
        from .models import Employee, EmployeePosting, UserProfile
        other = User.objects.create_user("otherboss", password="x")
        UserProfile.objects.create(user=other, business_title="Other Co")
        emp = Employee.objects.create(business=self.owner, name="Rep")   # home posting auto-created

        # The other business pulls the person in with their employee share code.
        self.client.force_login(other)
        d = self.client.get(reverse("employee_share_lookup"), {"code": emp.share_code}).json()
        self.assertTrue(d["ok"]); self.assertEqual(d["name"], "REP")
        self.client.post(reverse("employee_add_shared"), {"share_code": emp.share_code})
        self.assertTrue(EmployeePosting.objects.filter(employee=emp, business=other, is_home=False).exists())

        # covered_businesses = home + shared.
        covered = set(emp.covered_businesses().values_list("id", flat=True))
        self.assertEqual(covered, {self.owner.id, other.id})

    def test_own_employee_not_shareable_to_self(self):
        from .models import Employee
        emp = Employee.objects.create(business=self.owner, name="Rep")
        d = self.client.get(reverse("employee_share_lookup"), {"code": emp.share_code}).json()
        self.assertFalse(d["ok"])   # your own employee

    def test_edit_page_copies_the_employee_app_link(self):
        """The home business can copy the person's GSTSync /m/ quick-login link, and it really
        opens — as a browser sign-in with no SyncUp needed, and also once SyncUp is on."""
        from .models import Employee, UserProfile
        UserProfile.objects.create(user=self.owner, business_title="Boss Co")
        emp = Employee.objects.create(business=self.owner, name="Ravi", phone="9876500061",
                                      is_mobile_user=True)
        url = reverse("employee_edit", args=[emp.postings.get(is_home=True).id])
        # No SyncUp login needed — the GSTSync-native web quick-login link is there at once.
        r = self.client.get(url)
        self.assertContains(r, "Copy app link")
        link = r.context["app_link"]
        self.assertIn("/m/?t=", link)
        # It really opens for a fresh browser (the token is dropped → a redirect).
        self.client.logout()
        self.assertEqual(self.client.get(link.split("testserver", 1)[1]).status_code, 302)
        # A SyncUp login plus a public https address then serves the same button over https.
        self.client.force_login(self.owner)
        _live_person(emp)
        _syncup_on()
        self.assertTrue(self.client.get(url).context["app_link"].startswith(
            "https://gstsync.test/m/?t="))

    def test_no_app_link_while_switched_off_or_for_a_shared_employee(self):
        from .models import Employee, EmployeePosting, UserProfile
        UserProfile.objects.create(user=self.owner, business_title="Boss Co")
        emp = Employee.objects.create(business=self.owner, name="Ravi")
        other = User.objects.create_user("sharer", password="x")
        UserProfile.objects.create(user=other, business_title="Other Co")
        shared = EmployeePosting.objects.create(employee=emp, business=other, is_home=False)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("employee_edit", args=[shared.id])),
                               "Copy app link")
        Employee.objects.filter(pk=emp.pk).update(is_active=False)
        self.client.force_login(self.owner)
        home = emp.postings.get(is_home=True)
        self.assertNotContains(self.client.get(reverse("employee_edit", args=[home.id])),
                               "Copy app link")


class MultiBusinessTests(TestCase):
    """Multi-business: customer consolidation by phone, employee explicit coverage + switcher."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, Employee
        gst = "33ABCDE1234F1Z5"
        cls.a = User.objects.create_user("bizA", password="x")
        UserProfile.objects.create(user=cls.a, business_title="Shop A", business_gst=gst)
        cls.b = User.objects.create_user("bizB", password="x")
        UserProfile.objects.create(user=cls.b, business_title="Shop B", business_gst=gst)
        # Same real customer at two shops — the same mobile number IS the link.
        cls.ca = Customer.objects.create(user=cls.a, customer_name="Ram", customer_phone="9876500001",
                                         customer_gst="29ABCDE1234F1Z5", is_mobile_user=True)
        cls.cb = Customer.objects.create(user=cls.b, customer_name="Ram", customer_phone="9876500001",
                                         customer_gst="29ABCDE1234F1Z5", is_mobile_user=True)
        Book.objects.create(user=cls.a, customer=cls.ca, current_balance=-100)
        Book.objects.create(user=cls.b, customer=cls.cb, current_balance=-250)
        from .models import EmployeePosting
        cls.emp = Employee.objects.create(business=cls.a, name="Rep", phone="9876500002")
        EmployeePosting.objects.create(employee=cls.emp, business=cls.b, is_active=True)  # shared @ B

    def test_customer_consolidated_total(self):
        self.client.get("/m/customer/", {"t": _app_token(_person_of(self.ca))})
        r = self.client.get("/m/customer/")
        self.assertContains(r, "350")            # 100 + 250 across the group
        self.assertContains(r, "SHOP A")         # business titles upper-cased on save
        self.assertContains(r, "SHOP B")

    def test_customer_switch_scopes_ledger(self):
        self.client.get("/m/customer/", {"t": _app_token(_person_of(self.ca))})
        r = self.client.get("/m/customer/books", {"biz": self.b.id})   # switch to Shop B
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "250")            # B's due

    def test_employee_coverage_and_switch(self):
        self.client.get("/m/employee/", {"t": _app_token(self.emp)})
        self.assertEqual(self.client.get("/m/employee/customers", {"biz": self.b.id}).status_code, 200)

    def test_employee_invalid_biz_falls_back(self):
        stranger = User.objects.create_user("bizC", password="x")
        from .models import UserProfile
        UserProfile.objects.create(user=stranger, business_title="Shop C", business_gst="OTHERGST")
        self.client.get("/m/employee/", {"t": _app_token(self.emp)})
        # not in coverage → ignored, stays valid (no crash / no 403)
        self.assertEqual(self.client.get("/m/employee/customers", {"biz": stranger.id}).status_code, 200)


class BankDetailsScopingTests(TestCase):
    """A business must only ever see/select its OWN bank accounts (per-business isolation)."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, BankDetails
        cls.BankDetails = BankDetails
        cls.a = User.objects.create_user("bank_a", password="x")
        cls.b = User.objects.create_user("bank_b", password="x")
        pa = UserProfile.objects.create(user=cls.a, business_title="A")
        pb = UserProfile.objects.create(user=cls.b, business_title="B")
        cls.bank_a = BankDetails.objects.create(user=cls.a, account_name="A ACC", account_number="1",
                                                bank_name="BANK", whom_account=0, business_account=pa)
        cls.bank_b = BankDetails.objects.create(user=cls.b, account_name="B ACC", account_number="2",
                                                bank_name="BANK", whom_account=0, business_account=pb)

    def test_profile_form_scopes_bank_choices_to_own_business(self):
        from .forms import UserProfileForm
        ids = set(UserProfileForm(user=self.a).fields['bankdetails'].queryset.values_list('id', flat=True))
        self.assertIn(self.bank_a.id, ids)
        self.assertNotIn(self.bank_b.id, ids)       # B's bank must never be selectable by A

    def test_customer_form_scopes_customer_banks(self):
        from .forms import CustomerForm
        ca = self.BankDetails.objects.create(user=self.a, account_name="CA", account_number="3",
                                             bank_name="B", whom_account=1)
        cb = self.BankDetails.objects.create(user=self.b, account_name="CB", account_number="4",
                                             bank_name="B", whom_account=1)
        ids = set(CustomerForm(user=self.a).fields['bankdetails'].queryset.values_list('id', flat=True))
        self.assertIn(ca.id, ids)
        self.assertNotIn(cb.id, ids)

    def test_bank_edit_denies_other_business(self):
        self.client.force_login(self.a)
        # A cannot open B's bank record — the view is scoped by user, so it 404s.
        self.assertEqual(self.client.get(reverse("bank_details_edit", args=[self.bank_b.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("bank_details_edit", args=[self.bank_a.id])).status_code, 200)


class MobileToggleTests(TestCase):
    """The customer 'Mobile User' toggle gates app access — and it's per business."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile
        cls.owner = User.objects.create_user("tog_owner", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Tog Shop")

    def _open(self, cust):
        return self.client.get("/m/customer/", {"t": _app_token(cust)})

    def test_toggle_off_denies_access(self):
        c = Customer.objects.create(user=self.owner, customer_name="Off",
                                    customer_phone="9876500023", is_mobile_user=False)
        r = self._open(c)
        self.assertEqual(r.status_code, 403)                 # inactive for mobile → denied
        self.assertContains(r, "Mobile access turned off", status_code=403)   # deactivation message
        self.assertContains(r, "contact the business owner", status_code=403)

    def test_invalid_token_shows_session_expired(self):
        r = self.client.get("/m/customer/", {"t": "not.a.valid.token"})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Session expired", status_code=403)   # not the deactivation message

    def test_toggle_on_grants_access(self):
        c = Customer.objects.create(user=self.owner, customer_name="On",
                                    customer_phone="9876500021", is_mobile_user=True)
        self.assertEqual(self._open(c).status_code, 302)     # token accepted → redirect to clean URL

    def test_toggle_is_per_business(self):
        from .models import UserProfile
        from .appusers import visible_rows
        b = User.objects.create_user("tog_b", password="x")
        UserProfile.objects.create(user=b, business_title="Tog B")
        # Same person at two shops (same number): shown here, hidden at B.
        ca = Customer.objects.create(user=self.owner, customer_name="Ram",
                                     customer_phone="9876500011", is_mobile_user=True)
        cb = Customer.objects.create(user=b, customer_name="Ram",
                                     customer_phone="9876500011", is_mobile_user=False)
        person = _person_of(ca)
        ids = [r.user_id for r in visible_rows(person)]
        self.assertIn(self.owner.id, ids)        # shown here
        self.assertNotIn(b.id, ids)              # the business with the toggle off is dropped


class MobileManageTests(TestCase):
    """Admin-only mobile manage hub: team/attendance/salary/incentives, expenses,
    cheques, banks, inventory, products, reports — render, gating, and actions."""

    @classmethod
    def setUpTestData(cls):
        from .models import (UserProfile, Employee, Product, Inventory, ExpenseTracker)
        cls.owner = User.objects.create_user("mg_owner", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Manage Shop", business_phone="9000000000")
        cls.emp = Employee.objects.create(business=cls.owner, name="Boss", email="boss@x.local")
        # Make the home posting an admin on payroll.
        cls.emp.postings.filter(is_home=True).update(is_admin=True, attendance_eligible=True, salary=25000)
        cls.posting = cls.emp.postings.get(is_home=True)
        # A non-admin staffer at the same business.
        cls.emp2 = Employee.objects.create(business=cls.owner, name="Junior", email="jr@x.local")
        cls.cust = Customer.objects.create(user=cls.owner, customer_name="Owing Cust", customer_phone="9111111111")
        book = Book.objects.create(user=cls.owner, customer=cls.cust, current_balance=-1200)
        BookLog.objects.create(parent_book=book, change_type=1, change=1200)
        p = Product.objects.create(user=cls.owner, model_no="M1", product_name="Widget",
                                   product_rate_with_gst=118, product_gst_percentage=18,
                                   product_purchase_rate=80)
        Inventory.objects.create(user=cls.owner, product=p, current_stock=2, alert_level=5)  # low
        ExpenseTracker.objects.create(user=cls.owner, amount=500, category="FUEL", reference="FUEL")

    def _admin(self):
        self.client.get("/m/employee/", {"t": _app_token(self.emp)})

    def _staff(self):
        self.client.get("/m/employee/", {"t": _app_token(self.emp2)})

    def test_all_manage_screens_render_for_admin(self):
        self._admin()
        for name, args in [
            ("m_manage", []), ("m_manage_team", []), ("m_manage_team_member", [self.posting.id]),
            ("m_manage_expenses", []), ("m_manage_cheques", []), ("m_manage_banks", []),
            ("m_manage_inventory", []), ("m_manage_products", []), ("m_manage_reports", []),
        ]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_manage_is_admin_only(self):
        self._staff()
        for name, args in [("m_manage", []), ("m_manage_team", []),
                           ("m_manage_expenses", []), ("m_manage_inventory", []),
                           ("m_manage_reports", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)

    def test_low_stock_filter(self):
        self._admin()
        r = self.client.get(reverse("m_manage_inventory"), {"low": "1"})
        self.assertContains(r, "M1")            # the low item shows under the low filter
        self.assertContains(r, "Low")

    def test_admin_marks_attendance(self):
        from .models import AttendanceLog
        self._admin()
        r = self.client.post(reverse("m_manage_attendance_mark", args=[self.posting.id]),
                             data=json.dumps({"date": date.today().isoformat(), "status": 0}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(AttendanceLog.objects.filter(posting=self.posting, status=0).exists())

    def test_staff_cannot_mark_attendance(self):
        self._staff()
        r = self.client.post(reverse("m_manage_attendance_mark", args=[self.posting.id]),
                             data=json.dumps({"date": date.today().isoformat(), "status": 0}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_admin_adds_expense_and_incentive(self):
        from .models import ExpenseTracker, EmployeeIncentive
        self._admin()
        r = self.client.post(reverse("m_manage_expense_add"),
                             data=json.dumps({"amount": 250, "category": "TEA"}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(ExpenseTracker.objects.filter(user=self.owner, category="TEA").exists())
        r = self.client.post(reverse("m_manage_incentive_add", args=[self.posting.id]),
                             data=json.dumps({"amount": 300, "description": "Bonus"}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(EmployeeIncentive.objects.filter(posting=self.posting, amount=300).exists())

    def test_not_eligible_member_shows_real_incentives(self):
        from .models import Employee, EmployeeIncentive
        emp3 = Employee.objects.create(business=self.owner, name="Casual", email="cz@x.local")
        posting3 = emp3.postings.get(is_home=True)     # attendance_eligible defaults False
        EmployeeIncentive.objects.create(posting=posting3, amount=5000, is_paid=True, description="Diwali")
        self._admin()
        r = self.client.get(reverse("m_manage_team_member", args=[posting3.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Not on payroll")       # not eligible → notice
        # Real incentive shown (the old bug looped the ctx dict's keys → no amount/desc).
        self.assertContains(r, "5,000")
        self.assertContains(r, "Diwali")

    def test_manage_switcher_shows_only_admin_businesses(self):
        from .models import UserProfile, EmployeePosting
        b2 = User.objects.create_user("mg_b2", password="x")
        UserProfile.objects.create(user=b2, business_title="Admin Two")
        b3 = User.objects.create_user("mg_b3", password="x")
        UserProfile.objects.create(user=b3, business_title="Staff Only")
        EmployeePosting.objects.create(employee=self.emp, business=b2, is_active=True, is_admin=True)
        EmployeePosting.objects.create(employee=self.emp, business=b3, is_active=True, is_admin=False)
        self._admin()
        r = self.client.get(reverse("m_manage"))
        self.assertContains(r, "ADMIN TWO")       # admin business appears in the switcher
        self.assertNotContains(r, "STAFF ONLY")   # staff-only business is hidden

    def test_products_screen_has_filter_and_sort(self):
        self._admin()
        r = self.client.get(reverse("m_manage_products"))
        self.assertContains(r, "M1")              # product data embedded (products_json)
        self.assertContains(r, 'id="chips"')      # category filter chips
        self.assertContains(r, 'id="sortchips"')  # sort control

    def test_products_screen_includes_cost_for_admin(self):
        # Admin-only: the cost price (purchase rate) is embedded so the page can show margin.
        self._admin()
        r = self.client.get(reverse("m_manage_products"))
        self.assertContains(r, "product_purchase_rate")   # cost field present in payload
        self.assertContains(r, "80")                      # the purchase rate value

    def test_my_pay_shows_attendance_and_salary(self):
        from .models import AttendanceLog
        AttendanceLog.objects.create(posting=self.posting, date=date.today(), status=0)  # present
        self._admin()                                   # this employee is on payroll
        r = self.client.get(reverse("m_employee_pay"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Attendance")            # read-only attendance calendar section
        self.assertContains(r, "Net pay")               # salary breakdown
        self.assertContains(r, "days paid")

    def test_employee_catalog_has_no_cost(self):
        self._staff()                                    # a NON-admin employee
        r = self.client.get(reverse("m_employee_catalog"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "M1")                     # products are browsable
        self.assertContains(r, "SHOW_COST = false")      # cost/profit hidden
        self.assertNotContains(r, '"product_purchase_rate"')   # cost never in the JSON payload

    def test_admin_home_shows_inventory_tile(self):
        self._admin()
        r = self.client.get(reverse("m_employee_home"))
        self.assertContains(r, "Inventory")
        self.assertContains(r, "1 low")            # M1: stock 2 ≤ alert 5 → one low item

    def test_staff_home_has_no_inventory_tile(self):
        self._staff()                              # non-admin
        r = self.client.get(reverse("m_employee_home"))
        self.assertNotContains(r, "Inventory")     # admin-only tile
        self.assertContains(r, "Products")         # but the catalogue tile is for everyone

    def test_vendor_and_purchase_screens(self):
        from .models import VendorPurchase, PurchaseLog
        v = VendorPurchase.objects.create(user=self.owner, vendor_name="Acme Supply", vendor_phone="9000000001")
        PurchaseLog.objects.create(user=self.owner, vendor=v, change_type=1, change=5000)  # purchase
        PurchaseLog.objects.create(user=self.owner, vendor=v, change_type=0, change=2000)  # paid
        self._admin()
        for name, args in [("m_manage_vendors", []), ("m_manage_vendor", [v.id]), ("m_manage_purchases", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        r = self.client.get(reverse("m_manage_vendor", args=[v.id]))
        self.assertContains(r, "ACME SUPPLY")     # vendor name (upper-cased on save)
        self.assertContains(r, "3,000")           # balance = 5000 purchased − 2000 paid

    def test_vendor_screens_are_admin_only(self):
        self._staff()
        self.assertEqual(self.client.get(reverse("m_manage_vendors")).status_code, 403)
        self.assertEqual(self.client.get(reverse("m_manage_purchases")).status_code, 403)

    def test_purchase_logs_pagination_and_filter(self):
        from .models import VendorPurchase, PurchaseLog
        v = VendorPurchase.objects.create(user=self.owner, vendor_name="Bulk Vendor")
        for _ in range(35):
            PurchaseLog.objects.create(user=self.owner, vendor=v, change_type=1, change=100)
        PurchaseLog.objects.create(user=self.owner, vendor=v, change_type=0, change=500)  # one Paid
        self._admin()
        d = self.client.get(reverse("m_manage_purchases_data"), {"offset": 0, "type": "all"}).json()
        self.assertEqual(d["added"], 30)          # one page
        self.assertTrue(d["has_more"])            # 36 total > 30
        d = self.client.get(reverse("m_manage_purchases_data"), {"offset": 0, "type": "0"}).json()
        self.assertEqual(d["added"], 1)           # only the Paid entry
        self.assertIsNotNone(d["total"])          # frozen total for the filtered type

    def test_admin_add_bank_cheque_purchase_and_settings(self):
        from .models import BankDetails, ChequeLeaf, PurchaseLog, VendorPurchase, UserProfile
        self._admin()
        # Forms render
        for name in ("m_manage_bank_new", "m_manage_cheque_new", "m_manage_purchase_new", "m_manage_settings"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        # Add a bank (with UPI)
        r = self.client.post(reverse("m_manage_bank_save"),
                             data=json.dumps({"bank_name": "HDFC", "account_number": "123", "upi_id": "shop@hdfc"}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(BankDetails.objects.filter(user=self.owner, whom_account=0, upi_id="shop@hdfc").exists())
        # Add a cheque
        r = self.client.post(reverse("m_manage_cheque_save"),
                             data=json.dumps({"cheque_number": "CHQ-1", "amount": "5000", "payee_name": "Ram"}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(ChequeLeaf.objects.filter(user=self.owner, cheque_number="CHQ-1").exists())
        # Add a purchase log against a vendor
        v = VendorPurchase.objects.create(user=self.owner, vendor_name="Supply Co")
        r = self.client.post(reverse("m_manage_purchase_save"),
                             data=json.dumps({"vendor": v.id, "change_type": 1, "amount": "2500"}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(PurchaseLog.objects.filter(user=self.owner, vendor=v, change_type=1).exists())
        # Save business profile
        r = self.client.post(reverse("m_manage_settings_save"),
                             data=json.dumps({"business_title": "My Shop", "business_gst": "27ABC"}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(UserProfile.objects.get(user=self.owner).business_title, "MY SHOP")

    def test_add_forms_are_admin_only(self):
        self._staff()
        for name in ("m_manage_bank_new", "m_manage_cheque_new", "m_manage_settings"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        r = self.client.post(reverse("m_manage_bank_save"),
                             data=json.dumps({"upi_id": "x@y"}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_cheques_past_future_default(self):
        from .models import ChequeLeaf
        from datetime import timedelta
        today = date.today()
        # A future (post-dated) cheque and a past one.
        ChequeLeaf.objects.create(user=self.owner, cheque_number="FUT-1", status="ISSUED",
                                  clearance_date=today + timedelta(days=10))
        ChequeLeaf.objects.create(user=self.owner, cheque_number="PAST-1", status="CLEARED",
                                  clearance_date=today - timedelta(days=10))
        self._admin()
        # Default → Future (there is one upcoming): shows FUT-1, not PAST-1.
        r = self.client.get(reverse("m_manage_cheques"))
        self.assertEqual(r.context["when"], "future")
        self.assertContains(r, "FUT-1")
        self.assertNotContains(r, "PAST-1")
        # Explicit Past filter shows the past one.
        r = self.client.get(reverse("m_manage_cheques"), {"when": "past"})
        self.assertContains(r, "PAST-1")
        self.assertNotContains(r, "FUT-1")

    def test_cheques_default_past_when_no_future(self):
        from .models import ChequeLeaf
        from datetime import timedelta
        ChequeLeaf.objects.create(user=self.owner, cheque_number="OLD-1", status="CLEARED",
                                  clearance_date=date.today() - timedelta(days=5))
        self._admin()
        r = self.client.get(reverse("m_manage_cheques"))
        self.assertEqual(r.context["when"], "past")   # no upcoming → default Past
        self.assertContains(r, "OLD-1")

    def test_purchase_log_without_vendor_is_business_brand(self):
        from .models import PurchaseLog
        self._admin()
        r = self.client.post(reverse("m_manage_purchase_save"),
                             data=json.dumps({"change_type": 1, "amount": "1000"}),  # no vendor
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(PurchaseLog.objects.filter(user=self.owner, vendor__isnull=True, change=1000).exists())
        # Shows under the business brand in the feed (owner's business_title, upper-cased).
        r = self.client.get(reverse("m_manage_purchases"))
        self.assertContains(r, "MANAGE SHOP")

    def test_inventory_excludes_orphans_and_flags_low(self):
        from .models import Inventory
        # An orphaned stock row (product deleted → SET_NULL) must be hidden, not shown as "—".
        Inventory.objects.create(user=self.owner, product=None, current_stock=-10, alert_level=0)
        self._admin()
        r = self.client.get(reverse("m_manage_inventory"))
        self.assertEqual(r.context["count"], 1)          # only M1's stock; orphan excluded
        self.assertEqual(r.context["low_count"], 1)      # M1 (stock 2 ≤ alert 5) is low
        self.assertContains(r, "M1")                     # product embedded in items_json
        self.assertNotContains(r, "\\u2014")             # no "—" orphan rows

    def test_team_member_shows_contact_and_actions(self):
        self.emp.phone = "9876500000"
        self.emp.save()
        self._admin()
        r = self.client.get(reverse("m_manage_team_member", args=[self.posting.id]))
        self.assertContains(r, "tel:9876500000")   # click-to-call
        self.assertContains(r, "M.wa(")            # click-to-message (WhatsApp)
        self.assertContains(r, "boss@x.local")     # email on record

    def test_blank_counts_as_absent(self):
        from .models import AttendanceLog
        from .utils import calculate_employee_salary
        import datetime as dt
        y, m = 2026, 4                     # April = 30 days
        for d in range(1, 21):             # 20 present, remaining 10 days blank
            AttendanceLog.objects.create(posting=self.posting, date=dt.date(y, m, d), status=0)
        rec = calculate_employee_salary(self.posting, y, m)
        self.assertEqual(rec.total_days, 30)          # working days = all 30 (no leave); blanks count
        self.assertEqual(float(rec.paid_units), 20.0)
        self.assertAlmostEqual(float(rec.calculated_salary), round(25000 * 20 / 30, 2), places=2)

    def test_leave_excluded_from_working_days(self):
        from .models import AttendanceLog
        from .utils import calculate_employee_salary
        import datetime as dt
        y, m = 2026, 4
        for d in range(1, 21):             # 20 present
            AttendanceLog.objects.create(posting=self.posting, date=dt.date(y, m, d), status=0)
        for d in range(21, 31):            # 10 leave (weekly-offs / holidays)
            AttendanceLog.objects.create(posting=self.posting, date=dt.date(y, m, d), status=3)
        rec = calculate_employee_salary(self.posting, y, m)
        self.assertEqual(rec.total_days, 20)          # 30 − 10 leave = 20 working days
        self.assertEqual(float(rec.calculated_salary), 25000.0)   # 20 present of 20 working = full pay

    def test_bulk_attendance_mark(self):
        from .models import AttendanceLog
        self._admin()
        dates = ["2026-05-01", "2026-05-02", "2026-05-03"]
        r = self.client.post(reverse("m_manage_attendance_bulk", args=[self.posting.id]),
            data=json.dumps({"dates": dates, "status": 0}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["count"], 3)
        self.assertEqual(AttendanceLog.objects.filter(posting=self.posting, status=0).count(), 3)
        # Bulk clear removes them.
        r = self.client.post(reverse("m_manage_attendance_bulk", args=[self.posting.id]),
            data=json.dumps({"dates": dates, "status": -1}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(AttendanceLog.objects.filter(posting=self.posting).count(), 0)

    def test_desktop_bulk_attendance(self):
        # Desktop attendance multi-select parity: bulk-mark several days, then bulk-clear.
        self.client.force_login(self.owner)
        from .models import AttendanceLog
        dates = ["2026-06-01", "2026-06-02", "2026-06-08"]
        r = self.client.post(reverse("attendance_mark_bulk", args=[self.posting.id]),
            data=json.dumps({"dates": dates, "status": 3}), content_type="application/json")  # Leave
        self.assertTrue(r.json()["ok"])
        self.assertEqual(AttendanceLog.objects.filter(posting=self.posting, status=3).count(), 3)
        r = self.client.post(reverse("attendance_mark_bulk", args=[self.posting.id]),
            data=json.dumps({"dates": dates, "status": -1}), content_type="application/json")
        self.assertEqual(AttendanceLog.objects.filter(posting=self.posting).count(), 0)

    def test_salary_history_frozen_when_salary_changes(self):
        from .utils import calculate_employee_salary
        from .models import AttendanceLog
        import datetime as dt
        today = dt.date.today()
        py, pm = today.year, today.month - 3          # a month safely in the past
        while pm < 1:
            pm += 12; py -= 1
        AttendanceLog.objects.create(posting=self.posting, date=dt.date(py, pm, 1), status=0)
        rec = calculate_employee_salary(self.posting, py, pm)
        self.assertEqual(float(rec.base_salary), 25000.0)     # computed at the original salary
        # Raise the salary.
        self.posting.salary = 40000
        self.posting.save()
        # Re-opening / recomputing the PAST month must NOT rewrite it.
        rec2 = calculate_employee_salary(self.posting, py, pm)
        self.assertEqual(float(rec2.base_salary), 25000.0)    # frozen — history intact
        # The current month picks up the new salary.
        rec3 = calculate_employee_salary(self.posting, today.year, today.month)
        self.assertEqual(float(rec3.base_salary), 40000.0)

    def test_per_month_base_salary_override(self):
        from .utils import calculate_employee_salary
        from .models import AttendanceLog
        import datetime as dt
        y, m = 2026, 4
        for d in range(1, 21):            # 20 present
            AttendanceLog.objects.create(posting=self.posting, date=dt.date(y, m, d), status=0)
        for d in range(21, 31):           # 10 leave → 20 working days
            AttendanceLog.objects.create(posting=self.posting, date=dt.date(y, m, d), status=3)
        # Compute this month at an explicit base of ₹15,000 (profile salary is ₹25,000).
        rec = calculate_employee_salary(self.posting, y, m, base=15000)
        self.assertEqual(float(rec.base_salary), 15000.0)
        self.assertEqual(float(rec.calculated_salary), 15000.0)   # full pay of 20/20 working
        # Later attendance edits keep the month's chosen base — not the profile's ₹25,000.
        calculate_employee_salary(self.posting, y, m)
        rec.refresh_from_db()
        self.assertEqual(float(rec.base_salary), 15000.0)

    def test_mobile_salary_save_sets_base(self):
        from .models import SalaryRecord
        self._admin()
        url = reverse("m_manage_salary_save", args=[self.posting.id]) + "?year=2026&month=7"
        r = self.client.post(url, data=json.dumps({"base": 18000, "advances": 0, "bonus": 0}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(float(SalaryRecord.objects.get(posting=self.posting, year=2026, month=7).base_salary), 18000.0)


class _CronTestBase(object):
    """Shared fixture for the /cron/ tests: a throwaway backup dir and a settings helper."""

    key = "test-cron-key"

    def setUp(self):
        import tempfile
        super().setUp()
        self.backup_dir = tempfile.mkdtemp(prefix="agproj02-backups-")

    def tearDown(self):
        import glob, os, shutil
        from django.conf import settings
        shutil.rmtree(self.backup_dir, ignore_errors=True)
        # Locks live next to the DB; clear any a failed run left behind.
        for f in glob.glob(os.path.join(settings.BASE_DIR, ".cron-*")):
            try:
                os.unlink(f)
            except OSError:
                pass
        super().tearDown()

    def _settings(self, **extra):
        # DB_VACUUM_MIN_RECLAIM_MB=0 by default: a fresh test DB has almost nothing free,
        # so the real floor would short-circuit every vacuum test before the guard under
        # test. The threshold itself is covered by its own case below.
        opts = {"CRON_KEY": self.key, "DB_BACKUP_DIR": self.backup_dir,
                "DB_BACKUP_KEEP": 7, "DB_VACUUM_MIN_RECLAIM_MB": 0}
        opts.update(extra)
        return self.settings(**opts)

    def _get(self, name, qs=""):
        return self.client.get(reverse(name) + "?key=" + self.key + qs)


class CronMaintenanceTests(_CronTestBase, TestCase):
    """The /cron/ endpoints: secret gate, session purge, single-flight, health.

    These URLs are public, so the gate matters as much as the work: an unset or wrong key
    must look like nothing is there at all."""

    # ---------------- the secret gate ----------------
    def test_no_key_configured_closes_the_endpoints(self):
        # An unset CRON_KEY must CLOSE the endpoints, never leave them open.
        with self.settings(CRON_KEY=None):
            self.assertEqual(self.client.get(reverse("cron_health")).status_code, 404)
            self.assertEqual(self.client.get(reverse("cron_cleanup")).status_code, 404)
            self.assertEqual(self.client.get(reverse("cron_backup")).status_code, 404)

    def test_wrong_key_is_404_not_403(self):
        # 404 so a scanner can't confirm the endpoint exists.
        with self._settings():
            self.assertEqual(self.client.get(reverse("cron_health") + "?key=nope").status_code, 404)
            self.assertEqual(self.client.get(reverse("cron_health")).status_code, 404)

    def test_key_accepted_via_query_or_header(self):
        with self._settings():
            self.assertEqual(self._get("cron_health").status_code, 200)
            self.assertEqual(
                self.client.get(reverse("cron_health"), HTTP_X_CRON_KEY=self.key).status_code, 200)

    def test_post_is_allowed_and_needs_no_csrf(self):
        # Cron services issue GET or POST and never carry a CSRF token.
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        with self._settings():
            self.assertEqual(c.post(reverse("cron_health") + "?key=" + self.key).status_code, 200)

    # ---------------- cleanup ----------------
    def test_cleanup_deletes_only_expired_sessions(self):
        from django.contrib.sessions.models import Session
        now = timezone.now()
        Session.objects.create(session_key="expired1", session_data="x",
                               expire_date=now - timedelta(days=3))
        Session.objects.create(session_key="expired2", session_data="x",
                               expire_date=now - timedelta(minutes=1))
        Session.objects.create(session_key="live1", session_data="x",
                               expire_date=now + timedelta(days=3))
        with self._settings():
            r = self._get("cron_cleanup")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["expired_sessions"], 2)
        self.assertEqual(set(Session.objects.values_list("session_key", flat=True)), {"live1"})

    def test_cleanup_never_touches_business_data(self):
        # The whole point: maintenance must not delete invoices/ledger/stock.
        from .models import UserProfile
        u = User.objects.create_user("cron_biz", password="x")
        UserProfile.objects.create(user=u, business_title="Shop")
        cust = Customer.objects.create(user=u, customer_name="ACME")
        inv = Invoice.objects.create(user=u, invoice_number=1, invoice_date=date(2026, 1, 1),
                                     invoice_customer=cust, invoice_json="{}")
        book = Book.objects.create(user=u, customer=cust, current_balance=0)
        log = BookLog.objects.create(parent_book=book, change=100, change_type=0,
                                     date=timezone.now())
        with self._settings():
            r = self._get("cron_cleanup")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=cust.pk).exists())
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())
        self.assertTrue(BookLog.objects.filter(pk=log.pk).exists())

    def test_cleanup_is_idempotent(self):
        from django.contrib.sessions.models import Session
        Session.objects.create(session_key="e", session_data="x",
                               expire_date=timezone.now() - timedelta(days=1))
        with self._settings():
            first = self._get("cron_cleanup").json()
            second = self._get("cron_cleanup").json()
        self.assertEqual(first["expired_sessions"], 1)
        self.assertEqual(second["expired_sessions"], 0)   # nothing left to do

    # ---------------- single-flight ----------------
    def test_overlapping_run_is_skipped_with_200_not_500(self):
        # A cron service retries on timeout; an overlap is normal and must not alert.
        from .cleanup import job_lock
        with self._settings():
            with job_lock("cleanup"):
                r = self._get("cron_cleanup")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["skipped"], "locked")

    def test_stale_lock_is_stolen(self):
        from .cleanup import job_lock, LockBusy
        with job_lock("cleanup"):
            # A lock inside its TTL is respected...
            with self.assertRaises(LockBusy):
                with job_lock("cleanup"):
                    pass
            # ...but one past its TTL belongs to a dead run and is taken over.
            with job_lock("cleanup", ttl_seconds=0):
                pass

    # ---------------- health ----------------
    def test_health_reports_sizes_and_is_read_only(self):
        from django.contrib.sessions.models import Session
        Session.objects.create(session_key="e", session_data="x",
                               expire_date=timezone.now() - timedelta(days=1))
        with self._settings():
            body = self._get("cron_health").json()
        self.assertTrue(body["ok"])
        for field in ("db_mb", "free_pages", "sessions_expired", "sessions_live", "free_disk_mb"):
            self.assertIn(field, body)
        self.assertEqual(body["sessions_expired"], 1)
        self.assertEqual(Session.objects.count(), 1)   # health must not have purged it


class CronOutboxCleanupTests(_CronTestBase, TestCase):
    """The daily cleanup prunes the SyncUp / Telegram outbox: a Telegram report carries its
    whole text, so it goes sooner than a one-line push."""

    def _msg(self, kind, age_days, dedupe, event="x"):
        from .models import SyncUpMessage
        m = SyncUpMessage.objects.create(kind=kind, event=event, external_id="-100", title="t",
                                         text="report" if kind == "telegram" else "",
                                         dedupe_key=dedupe, sent_at=timezone.now())
        SyncUpMessage.objects.filter(pk=m.pk).update(
            created_at=timezone.now() - timedelta(days=age_days))
        return m

    def test_each_kind_is_kept_for_its_own_window(self):
        from .cleanup import purge_outbox
        from .models import SyncUpMessage
        self._msg("telegram", 3, "tg-fresh")
        self._msg("telegram", 9, "tg-old")
        self._msg("notify", 9, "push-fresh")                   # older than a Telegram window…
        self._msg("notify", 20, "push-old")
        self._msg("telegram", 1, "login-fresh", event="login")
        self._msg("telegram", 4, "login-old", event="login")    # logins go soonest of all
        out = purge_outbox()
        self.assertEqual((out["logins"], out["telegram"], out["messages"]), (1, 1, 1))
        left = set(SyncUpMessage.objects.values_list("dedupe_key", flat=True))
        self.assertEqual(left, {"tg-fresh", "push-fresh", "login-fresh"})
        self.assertEqual(out["rows"], 3)                       # …a push is kept a fortnight

    def test_a_message_stuck_unsent_past_its_window_is_dropped_too(self):
        from .cleanup import purge_outbox
        from .models import SyncUpMessage
        m = self._msg("telegram", 9, "stuck")
        SyncUpMessage.objects.filter(pk=m.pk).update(sent_at=None)
        self.assertEqual(purge_outbox()["telegram"], 1)

    def test_the_cleanup_cron_reports_what_it_pruned(self):
        from .models import SyncUpMessage
        self._msg("telegram", 9, "tg-old")
        waiting = SyncUpMessage.objects.create(kind="telegram", event="x", external_id="-100",
                                               title="t", text="soon", dedupe_key="tg-waiting")
        with self._settings():
            body = self._get("cron_cleanup").json()
        self.assertEqual(body["outbox"], {"logins": 0, "telegram": 1, "messages": 0,
                                          "waiting": 1, "rows": 1})
        self.assertTrue(SyncUpMessage.objects.filter(pk=waiting.pk).exists())


class CronBackupVacuumTests(_CronTestBase, TransactionTestCase):
    """Backup and in-place VACUUM.

    TransactionTestCase, not TestCase: SQLite refuses to VACUUM inside a transaction, and
    TestCase wraps every test in one. Production runs these in autocommit (ATOMIC_REQUESTS
    is off), so this is the harness matching reality rather than a workaround."""

    def test_backup_writes_a_readable_copy(self):
        import os, sqlite3
        with self._settings():
            body = self._get("cron_backup").json()
        self.assertTrue(body["ok"], body)
        path = os.path.join(self.backup_dir, body["backup"])
        self.assertTrue(os.path.exists(path))
        # It must be a real, openable SQLite database - not a truncated file.
        con = sqlite3.connect(path)
        try:
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            con.close()

    def test_backup_prunes_to_keep(self):
        import os
        # Seed more stale backups than we retain.
        for d in range(1, 6):
            open(os.path.join(self.backup_dir, "gstbillingdb-2026-01-0%d.sqlite3" % d), "w").close()
        with self._settings(DB_BACKUP_KEEP=3):
            self.assertTrue(self._get("cron_backup").json()["ok"])
        left = [f for f in os.listdir(self.backup_dir) if f.endswith(".sqlite3")]
        self.assertEqual(len(left), 3)

    def test_backup_rerun_same_day_overwrites(self):
        import os
        with self._settings():
            a = self._get("cron_backup").json()
            b = self._get("cron_backup").json()
        self.assertEqual(a["backup"], b["backup"])
        self.assertEqual(len([f for f in os.listdir(self.backup_dir) if f.endswith(".sqlite3")]), 1)

    def test_backup_skips_on_low_disk_without_erroring(self):
        # A backup must never be the thing that fills the server.
        from unittest import mock
        with self._settings():
            with mock.patch("gstbillingapp.cleanup.free_disk_bytes", return_value=1024):
                body = self._get("cron_backup").json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["skipped"], "low_disk")

    def test_vacuum_refuses_without_a_recent_backup(self):
        with self._settings():
            body = self._get("cron_cleanup", "&vacuum=1").json()
        self.assertEqual(body["vacuum"], "skipped")
        self.assertEqual(body["vacuum_reason"], "no_recent_backup")

    def test_vacuum_runs_after_a_backup(self):
        with self._settings():
            self.assertTrue(self._get("cron_backup").json()["ok"])
            body = self._get("cron_cleanup", "&vacuum=1").json()
        self.assertEqual(body["vacuum"], "done")

    # ---------------- single-job mode ----------------
    def test_one_call_does_backup_purge_and_vacuum(self):
        """`?backup=1&vacuum=1` is the whole schedule in one request, for a cron service
        that only allows a single entry."""
        from django.contrib.sessions.models import Session
        Session.objects.create(session_key="e", session_data="x",
                               expire_date=timezone.now() - timedelta(days=1))
        with self._settings():
            body = self._get("cron_cleanup", "&backup=1&vacuum=1").json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["backup_run"]["ok"])          # backed up...
        self.assertEqual(body["expired_sessions"], 1)      # ...purged...
        self.assertEqual(body["vacuum"], "done")           # ...and compacted

    def test_one_call_backup_satisfies_the_vacuum_guard(self):
        """The backup taken by this same call is what unblocks the vacuum — order matters."""
        import os
        # No backup exists at all beforehand.
        self.assertEqual([f for f in os.listdir(self.backup_dir) if f.endswith(".sqlite3")], [])
        with self._settings():
            body = self._get("cron_cleanup", "&backup=1&vacuum=1").json()
        self.assertEqual(body["vacuum"], "done")

    def test_vacuum_alone_stops_compacting_once_the_backup_ages_out(self):
        """Regression guard for the trap: scheduling ONLY `cleanup?vacuum=1` looks healthy
        (HTTP 200, ok:true) but silently stops compacting after 48h with nothing writing
        backups."""
        import os, glob
        with self._settings():
            self.assertTrue(self._get("cron_backup").json()["ok"])
            # Night 1-2: the backup is still fresh, so it works.
            self.assertEqual(self._get("cron_cleanup", "&vacuum=1").json()["vacuum"], "done")

            # Age that backup past the 48h guard, as it would with no backup job scheduled.
            f = glob.glob(os.path.join(self.backup_dir, "*.sqlite3"))[0]
            old = os.path.getmtime(f) - 3 * 86400
            os.utime(f, (old, old))

            body = self._get("cron_cleanup", "&vacuum=1").json()
        self.assertTrue(body["ok"])                        # still reports success...
        self.assertEqual(body["vacuum"], "skipped")        # ...while doing half the job
        self.assertEqual(body["vacuum_reason"], "no_recent_backup")

    def test_vacuum_skips_when_there_is_nothing_worth_reclaiming(self):
        """A daily vacuum must not rewrite the whole file to win back a few kilobytes."""
        # Threshold far above anything this test DB could have freed.
        with self._settings(DB_VACUUM_MIN_RECLAIM_MB=9999):
            self.assertTrue(self._get("cron_backup").json()["ok"])
            body = self._get("cron_cleanup", "&vacuum=1").json()
        self.assertEqual(body["vacuum"], "skipped")
        self.assertEqual(body["vacuum_reason"], "nothing_to_reclaim")
        self.assertIn("reclaimable_mb", body)

    def test_backup_param_off_by_default(self):
        """Existing schedules must be unaffected — no backup unless asked for."""
        import os
        with self._settings():
            body = self._get("cron_cleanup").json()
        self.assertNotIn("backup_run", body)
        self.assertEqual([f for f in os.listdir(self.backup_dir) if f.endswith(".sqlite3")], [])


class CompactJsonStorageTests(TestCase):
    """Stored invoice/quotation JSON carries no whitespace padding, and the one-time
    backfill is lossless."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile
        cls.u = User.objects.create_user("json_biz", password="x")
        UserProfile.objects.create(user=cls.u, business_title="Shop", business_gst="33AAAAA0000A1Z5")
        cls.cust = Customer.objects.create(user=cls.u, customer_name="ACME")

    def test_json_compact_has_no_padding_and_round_trips(self):
        from .utils import json_compact
        data = {"items": [{"name": "TAP", "qty": 2, "rate": 12.5}], "total": 25.0}
        out = json_compact(data)
        self.assertNotIn(", ", out)
        self.assertNotIn(": ", out)
        self.assertEqual(json.loads(out), data)

    def test_json_compact_keeps_unicode_readable(self):
        from .utils import json_compact
        # ensure_ascii=False keeps the rupee sign as one character, not an escape.
        self.assertIn("\u20b9", json_compact({"sym": "\u20b9"}))

    def test_backfill_is_lossless_and_shrinks(self):
        from django.core.management import call_command
        from io import StringIO
        data = {"customer_name": "ACME", "items": [{"invoice_product": "TAP", "invoice_qty": 2}]}
        padded = json.dumps(data)                     # the old, space-padded form
        inv = Invoice.objects.create(user=self.u, invoice_number=1, invoice_date=date(2026, 1, 1),
                                     invoice_customer=self.cust, invoice_json=padded)
        call_command("minify_invoice_json", "--commit", stdout=StringIO())
        inv.refresh_from_db()
        self.assertLess(len(inv.invoice_json), len(padded))       # actually smaller
        self.assertEqual(json.loads(inv.invoice_json), data)      # and identical data

    def test_backfill_dry_run_writes_nothing(self):
        from django.core.management import call_command
        from io import StringIO
        padded = json.dumps({"a": 1, "b": 2})
        inv = Invoice.objects.create(user=self.u, invoice_number=2, invoice_date=date(2026, 1, 1),
                                     invoice_customer=self.cust, invoice_json=padded)
        call_command("minify_invoice_json", stdout=StringIO())
        inv.refresh_from_db()
        self.assertEqual(inv.invoice_json, padded)

    def test_backfill_leaves_unparseable_rows_alone(self):
        from django.core.management import call_command
        from io import StringIO
        junk = "{not json at all"
        inv = Invoice.objects.create(user=self.u, invoice_number=3, invoice_date=date(2026, 1, 1),
                                     invoice_customer=self.cust, invoice_json=junk)
        call_command("minify_invoice_json", "--commit", stdout=StringIO())
        inv.refresh_from_db()
        self.assertEqual(inv.invoice_json, junk)     # reported, never mangled


class QuotationRetentionTests(TestCase):
    """The opt-in stale-quotation purge.

    Policy: every status goes once past the window. These cases pin down that it really is
    every status, that age is measured honestly, and — most importantly — that the financial
    record (invoices, ledger) is never collateral damage."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile
        cls.u = User.objects.create_user("quo_biz", password="x")
        UserProfile.objects.create(user=cls.u, business_title="Shop")
        cls.cust = Customer.objects.create(user=cls.u, customer_name="ACME")

    def _quotation(self, number, days_old, status="DRAFT", invoice=None):
        """A quotation dated `days_old` days ago, with updated_at aged to match."""
        from .models import Quotation
        when = timezone.localtime() - timedelta(days=days_old)
        q = Quotation.objects.create(
            user=self.u, quotation_number=number, quotation_date=when.date(),
            quotation_customer=self.cust, quotation_json="{}", status=status,
            converted_invoice=invoice)
        # updated_at is auto_now, so force it past the model layer.
        Quotation.objects.filter(pk=q.pk).update(updated_at=when)
        return q

    def _invoice(self, number):
        return Invoice.objects.create(user=self.u, invoice_number=number,
                                      invoice_date=date(2026, 1, 1),
                                      invoice_customer=self.cust, invoice_json="{}")

    def _alive(self, q):
        from .models import Quotation
        return Quotation.objects.filter(pk=q.pk).exists()

    # ---------------- what it does remove ----------------
    def test_deletes_abandoned_old_drafts_and_pending(self):
        from .cleanup import purge_quotations
        old_draft = self._quotation(1, 40, "DRAFT")
        old_pending = self._quotation(2, 40, "PENDING")
        out = purge_quotations(15)
        self.assertTrue(out["ok"])
        self.assertEqual(out["deleted"], 2)
        self.assertFalse(self._alive(old_draft))
        self.assertFalse(self._alive(old_pending))

    def test_keeps_anything_inside_the_window(self):
        from .cleanup import purge_quotations
        recent = self._quotation(3, 5, "DRAFT")
        self.assertEqual(purge_quotations(15)["deleted"], 0)
        self.assertTrue(self._alive(recent))

    # ---------------- what it must NOT remove ----------------
    def test_deletes_every_status_once_past_the_window(self):
        """No status is spared — DRAFT, PENDING, APPROVED and CONVERTED all age out."""
        from .cleanup import purge_quotations
        rows = {
            "DRAFT": self._quotation(4, 400, "DRAFT"),
            "PENDING": self._quotation(5, 400, "PENDING"),
            "APPROVED": self._quotation(6, 400, "APPROVED"),
            "CONVERTED": self._quotation(7, 400, "CONVERTED", invoice=self._invoice(9001)),
        }
        out = purge_quotations(15)
        self.assertEqual(out["deleted"], 4)
        self.assertEqual(set(out["by_status"]), set(rows))
        for status, q in rows.items():
            self.assertFalse(self._alive(q), status)

    def test_deletes_a_draft_linked_to_an_invoice_without_harming_the_invoice(self):
        """The real-data case: 12 live rows are DRAFT *and* linked to an invoice. They go
        too — but deleting a quotation must never touch the invoice it points at."""
        from .cleanup import purge_quotations
        inv = self._invoice(9002)
        linked = self._quotation(8, 400, "DRAFT", invoice=inv)
        out = purge_quotations(15)
        self.assertFalse(self._alive(linked))
        self.assertEqual(out["had_invoice_link"], 1)   # reported, not hidden
        inv.refresh_from_db()                          # invoice survives untouched
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    def test_invoice_can_still_become_a_quotation_after_its_source_was_purged(self):
        """The 'restore the original' path degrades gracefully: with the source gone,
        invoice_to_quotation builds a fresh quotation from the invoice instead."""
        from .models import Quotation
        from .cleanup import purge_quotations
        from .views.quotation import _quotation_from_invoice
        inv = self._invoice(9003)
        self._quotation(9, 400, "CONVERTED", invoice=inv)
        purge_quotations(15)
        self.assertFalse(Quotation.objects.filter(converted_invoice=inv).exists())
        # The fallback the real view uses when no source quotation survives.
        rebuilt = _quotation_from_invoice(inv, "rebuilt")
        self.assertEqual(rebuilt.quotation_json, inv.invoice_json)
        self.assertEqual(rebuilt.status, "DRAFT")

    def test_recently_touched_old_quotation_survives(self):
        """quotation_date can be back-dated by hand; updated_at proves nobody has touched
        it. Both clocks must agree before anything is deleted."""
        from .models import Quotation
        from .cleanup import purge_quotations
        q = self._quotation(20, 400, "DRAFT")
        Quotation.objects.filter(pk=q.pk).update(updated_at=timezone.now())  # edited today
        purge_quotations(15)
        self.assertTrue(self._alive(q))

    # ---------------- guards ----------------
    def test_refuses_a_dangerously_short_window(self):
        from .cleanup import purge_quotations, MIN_QUOTATION_RETENTION_DAYS
        q = self._quotation(21, 400, "DRAFT")
        out = purge_quotations(1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["skipped"], "retention_too_short")
        self.assertEqual(out["minimum_days"], MIN_QUOTATION_RETENTION_DAYS)
        self.assertTrue(self._alive(q))               # nothing deleted

    def test_dry_run_deletes_nothing_but_reports_the_count(self):
        from .cleanup import purge_quotations
        q = self._quotation(22, 400, "DRAFT")
        out = purge_quotations(15, commit=False)
        self.assertEqual(out["would_delete"], 1)
        self.assertEqual(out["deleted"], 0)
        self.assertTrue(self._alive(q))

    def test_kept_count_is_correct_after_a_real_delete(self):
        """Regression: `kept` was computed after the delete but still subtracted the
        deleted count, so a live run reported a negative number."""
        from .cleanup import purge_quotations
        self._quotation(30, 400, "DRAFT")      # goes
        self._quotation(31, 400, "DRAFT")      # goes
        survivor = self._quotation(32, 2, "DRAFT")   # inside the window
        out = purge_quotations(15)
        self.assertEqual(out["deleted"], 2)
        self.assertEqual(out["kept"], 1)
        self.assertTrue(self._alive(survivor))

    def test_run_cleanup_touches_no_quotation_by_default(self):
        # Omitting the argument must never be destructive.
        from .cleanup import run_cleanup
        q = self._quotation(23, 400, "DRAFT")
        stats = run_cleanup()
        self.assertNotIn("quotations", stats)
        self.assertTrue(self._alive(q))

    def test_purge_never_touches_invoices_or_ledger(self):
        from .cleanup import purge_quotations
        inv = self._invoice(9003)
        book = Book.objects.create(user=self.u, customer=self.cust, current_balance=0)
        self._quotation(24, 400, "DRAFT")
        purge_quotations(15)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())


class CronQuotationParamTests(_CronTestBase, TestCase):
    """?quotations=N on the cleanup endpoint."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile
        cls.u = User.objects.create_user("quo_cron", password="x")
        UserProfile.objects.create(user=cls.u, business_title="Shop")

    def _old_draft(self, number):
        from .models import Quotation
        when = timezone.localtime() - timedelta(days=90)
        q = Quotation.objects.create(user=self.u, quotation_number=number,
                                     quotation_date=when.date(), quotation_json="{}",
                                     status="DRAFT")
        Quotation.objects.filter(pk=q.pk).update(updated_at=when)
        return q

    def test_param_triggers_the_purge(self):
        from .models import Quotation
        self._old_draft(1)
        with self._settings():
            body = self._get("cron_cleanup", "&quotations=15").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["quotations"]["deleted"], 1)
        self.assertEqual(Quotation.objects.count(), 0)

    def test_absent_param_purges_nothing(self):
        from .models import Quotation
        self._old_draft(2)
        with self._settings():
            body = self._get("cron_cleanup").json()
        self.assertNotIn("quotations", body)
        self.assertEqual(Quotation.objects.count(), 1)

    def test_malformed_param_is_ignored_not_defaulted(self):
        """A typo must not silently become a destructive default."""
        from .models import Quotation
        self._old_draft(3)
        with self._settings():
            for bad in ("abc", "0", "-5", ""):
                body = self._get("cron_cleanup", "&quotations=" + bad).json()
                self.assertNotIn("quotations", body, bad)
        self.assertEqual(Quotation.objects.count(), 1)

    def test_too_short_window_is_refused_over_http(self):
        from .models import Quotation
        self._old_draft(4)
        with self._settings():
            body = self._get("cron_cleanup", "&quotations=2").json()
        self.assertFalse(body["quotations"]["ok"])
        self.assertEqual(body["quotations"]["skipped"], "retention_too_short")
        self.assertEqual(Quotation.objects.count(), 1)


class ConversionWorkflowTests(TestCase):
    """Quotation -> invoice conversion.

    The workflow: an admin either bills directly, or raises a quotation and converts it.
    On conversion the DESKTOP quotation is deleted (the invoice is then the single source
    of truth), while a MOBILE order survives as CONVERTED because /m/c/orders is the
    customer's own record of what they ordered."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile
        cls.owner = User.objects.create_user("conv_owner", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Shop",
                                   business_gst="33AAAAA0000A1Z5")
        cls.cust = Customer.objects.create(user=cls.owner, customer_name="ACME")
        # Conversion posts to the customer ledger, which add_customer_book() normally
        # creates alongside the customer.
        Book.objects.create(user=cls.owner, customer=cls.cust, current_balance=0)

    def _quotation(self, number, from_cart):
        from .models import Quotation
        payload = {"customer_name": "ACME", "items": [], "invoice_total_amt_with_gst": 0}
        return Quotation.objects.create(
            user=self.owner, quotation_number=number, quotation_date=date.today(),
            quotation_customer=self.cust, quotation_json=json.dumps(payload),
            status="APPROVED", created_from_cart=from_cart)

    def _convert(self, q):
        self.client.force_login(self.owner)
        return self.client.post(reverse("quotation_convert_to_invoice", args=[q.id]))

    def test_desktop_quotation_is_deleted_on_conversion(self):
        from .models import Quotation
        q = self._quotation(1, from_cart=False)
        r = self._convert(q)
        self.assertTrue(r.json()["success"], r.content)
        self.assertFalse(Quotation.objects.filter(pk=q.pk).exists())   # gone
        self.assertTrue(Invoice.objects.filter(pk=r.json()["invoice_id"]).exists())

    def test_mobile_order_survives_conversion_as_invoiced(self):
        from .models import Quotation
        q = self._quotation(2, from_cart=True)
        r = self._convert(q)
        self.assertTrue(r.json()["success"], r.content)
        q.refresh_from_db()                                            # still there
        self.assertEqual(q.status, "CONVERTED")
        self.assertEqual(q.converted_invoice_id, r.json()["invoice_id"])
        self.assertIsNotNone(q.converted_at)

    def test_converted_order_still_shows_in_customer_order_history(self):
        """The regression this guards: billing an order used to empty the customer's
        order list, because the row backing it was deleted."""
        from .models import Quotation
        q = self._quotation(3, from_cart=True)
        self._convert(q)
        rows = Quotation.objects.filter(user=self.owner, quotation_customer=self.cust,
                                        created_from_cart=True)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().get_status_display(), "Converted to Invoice")

    def test_a_converted_order_cannot_be_converted_twice(self):
        q = self._quotation(4, from_cart=True)
        self._convert(q)
        q.refresh_from_db()
        self.assertFalse(q.can_be_converted())
        r = self._convert(q)
        self.assertEqual(r.status_code, 400)

    def test_order_history_is_a_rolling_window(self):
        """A billed order shows as "Invoiced" straight away, then ages out with everything
        else — the customer's order list is the last 15 days, and the invoice is the
        permanent record."""
        from .models import Quotation
        from .cleanup import purge_quotations
        q = self._quotation(5, from_cart=True)
        r = self._convert(q)
        invoice_id = r.json()["invoice_id"]
        q.refresh_from_db()
        self.assertEqual(q.status, "CONVERTED")             # visible immediately...

        old = timezone.now() - timedelta(days=400)
        Quotation.objects.filter(pk=q.pk).update(quotation_date=old.date(), updated_at=old)
        purge_quotations(15)
        self.assertFalse(Quotation.objects.filter(pk=q.pk).exists())   # ...then ages out
        self.assertTrue(Invoice.objects.filter(pk=invoice_id).exists())  # invoice remains


class ConsoleAuthTests(TestCase):
    """The operator console's login is separate from the business login, in BOTH
    directions. That separation is the whole security model of this feature."""

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin, UserProfile
        cls.admin = PlatformAdmin(username="op_admin", full_name="Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()
        cls.biz = User.objects.create_user("biz_owner", password="Bizzz!pass99")
        UserProfile.objects.create(user=cls.biz, business_title="Shop")

    def _login(self, username="op_admin", password="Cons0le!pass9"):
        return self.client.post(reverse("console_login"),
                                {"username": username, "password": password})

    def test_console_requires_login(self):
        r = self.client.get(reverse("console_businesses"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/console/login", r["Location"])

    def test_admin_can_sign_in(self):
        r = self._login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse("console_businesses")).status_code, 200)

    def test_business_owner_cannot_sign_into_console(self):
        # Correct credentials for a BUSINESS login must not open the console.
        r = self._login("biz_owner", "Bizzz!pass99")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.get(reverse("console_businesses")).status_code, 302)

    def test_business_session_grants_no_console_access(self):
        """force_login sets request.user; the console must ignore it entirely."""
        self.client.force_login(self.biz)
        r = self.client.get(reverse("console_businesses"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/console/login", r["Location"])

    def test_console_session_grants_no_business_access(self):
        self._login()
        # The console login must not have authenticated request.user anywhere.
        r = self.client.get(reverse("invoices"))
        self.assertEqual(r.status_code, 302)          # bounced to the business login
        self.assertNotIn("/console/", r["Location"])

    def test_wrong_password_is_rejected(self):
        self.assertEqual(self._login("op_admin", "wrong").status_code, 401)

    def test_unknown_user_is_rejected(self):
        self.assertEqual(self._login("nobody", "whatever").status_code, 401)

    def test_revoked_admin_loses_access_mid_session(self):
        from .models import PlatformAdmin
        self._login()
        self.assertEqual(self.client.get(reverse("console_businesses")).status_code, 200)
        PlatformAdmin.objects.filter(pk=self.admin.pk).update(is_active=False)
        # Re-read on every request, so revocation is immediate — not at next login.
        self.assertEqual(self.client.get(reverse("console_businesses")).status_code, 302)

    def test_admin_is_not_an_auth_user_at_all(self):
        """The two populations are disjoint by construction, not by a filter."""
        self.assertFalse(User.objects.filter(username="op_admin").exists())

    def test_password_is_stored_hashed_not_plaintext(self):
        from .models import PlatformAdmin
        a = PlatformAdmin.objects.get(username="op_admin")
        self.assertNotEqual(a.password, "Cons0le!pass9")
        self.assertTrue(a.password.startswith("pbkdf2_"))
        self.assertTrue(a.check_password("Cons0le!pass9"))
        self.assertFalse(a.check_password("wrong"))

    def test_an_admin_and_a_business_may_share_a_username(self):
        """Different tables, different login screens — no collision."""
        from .models import PlatformAdmin, UserProfile
        u = User.objects.create_user("samename", password="Bizzz!pass99")
        UserProfile.objects.create(user=u, business_title="Same")
        a = PlatformAdmin(username="samename")
        a.set_password("Cons0le!pass9")
        a.save()          # must not raise
        self.assertEqual(self._login("samename", "Cons0le!pass9").status_code, 302)

    def test_logout_clears_the_session(self):
        self._login()
        self.client.get(reverse("console_logout"))
        self.assertEqual(self.client.get(reverse("console_businesses")).status_code, 302)

    def test_next_only_follows_console_paths(self):
        """An open redirect out of the console would be a phishing vector."""
        r = self.client.post(reverse("console_login") + "?next=https://evil.example/x",
                             {"username": "op_admin", "password": "Cons0le!pass9"})
        self.assertNotIn("evil.example", r["Location"])


class ConsoleBusinessTests(TestCase):
    """Creating, suspending and deleting businesses from the console."""

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin, UserProfile
        cls.admin = PlatformAdmin(username="op2", full_name="Op2")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()
        cls.biz = User.objects.create_user("shop_a", password="Bizzz!pass99")
        UserProfile.objects.create(user=cls.biz, business_title="SHOP A",
                                   business_gst="33AAAAA0000A1Z5")

    def setUp(self):
        self.client.post(reverse("console_login"),
                         {"username": "op2", "password": "Cons0le!pass9"})

    def test_list_shows_businesses_only(self):
        r = self.client.get(reverse("console_businesses"))
        # Assert on the row's link, not the label — the template upper-cases the username
        # for display and that styling choice should not be able to break this test.
        self.assertContains(r, reverse("console_business_detail", args=[self.biz.id]))
        self.assertContains(r, "SHOP A")                      # the business title
        # Admins aren't auth.Users, so they cannot appear as a row even by accident.
        self.assertNotContains(r, reverse("console_business_detail", args=[9999]))

    def test_create_business_makes_user_and_profile_together(self):
        from .models import UserProfile
        r = self.client.post(reverse("console_business_new"), {
            "username": "newshop", "password": "Fresh!pass2026",
            "business_title": "New Shop", "business_gst": "33BBBBB0000B1Z5",
        })
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="newshop")
        self.assertTrue(UserProfile.objects.filter(user=u).exists())   # never half-created
        self.assertEqual(UserProfile.objects.get(user=u).business_title, "NEW SHOP")

    def test_create_rejects_duplicate_username(self):
        r = self.client.post(reverse("console_business_new"), {
            "username": "shop_a", "password": "Fresh!pass2026", "business_title": "X"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.objects.filter(username="shop_a").count(), 1)

    def test_create_rejects_weak_password(self):
        r = self.client.post(reverse("console_business_new"), {
            "username": "weakshop", "password": "123", "business_title": "X"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(username="weakshop").exists())

    def test_suspend_blocks_business_login(self):
        self.client.post(reverse("console_business_toggle_active", args=[self.biz.id]))
        self.biz.refresh_from_db()
        self.assertFalse(self.biz.is_active)
        # Django's auth backend refuses an inactive user, so nothing else is needed.
        c2 = self.client_class()
        self.assertFalse(c2.login(username="shop_a", password="Bizzz!pass99"))

    def test_reset_password_changes_it(self):
        self.client.post(reverse("console_business_reset_password", args=[self.biz.id]),
                         {"password": "Rotated!pass77"})
        self.biz.refresh_from_db()
        self.assertTrue(self.biz.check_password("Rotated!pass77"))

    def test_purge_requires_typing_the_username(self):
        r = self.client.post(reverse("console_business_purge", args=[self.biz.id]),
                             {"confirm_username": "wrong"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.biz.pk).exists())

    def test_purge_removes_the_business_and_leaves_no_orphans(self):
        """The point of purge: SET_NULL means deleting the User alone would leave the
        rows behind with no owner."""
        from .models import UserProfile
        cust = Customer.objects.create(user=self.biz, customer_name="ACME")
        inv = Invoice.objects.create(user=self.biz, invoice_number=1,
                                     invoice_date=date(2026, 1, 1),
                                     invoice_customer=cust, invoice_json="{}")
        book = Book.objects.create(user=self.biz, customer=cust, current_balance=0)
        BookLog.objects.create(parent_book=book, change=10, change_type=0, date=timezone.now())

        self.client.post(reverse("console_business_purge", args=[self.biz.id]),
                         {"confirm_username": "shop_a"})

        self.assertFalse(User.objects.filter(pk=self.biz.pk).exists())
        self.assertFalse(UserProfile.objects.filter(user_id=self.biz.pk).exists())
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())      # gone, not orphaned
        self.assertFalse(Customer.objects.filter(pk=cust.pk).exists())
        self.assertFalse(Book.objects.filter(pk=book.pk).exists())
        self.assertEqual(BookLog.objects.count(), 0)
        self.assertEqual(Invoice.objects.filter(user__isnull=True).count(), 0)

    def test_purge_does_not_touch_another_business(self):
        from .models import UserProfile
        other = User.objects.create_user("shop_b", password="Other!pass99")
        UserProfile.objects.create(user=other, business_title="SHOP B")
        keep = Customer.objects.create(user=other, customer_name="KEEP")
        Customer.objects.create(user=self.biz, customer_name="GOES")

        self.client.post(reverse("console_business_purge", args=[self.biz.id]),
                         {"confirm_username": "shop_a"})

        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=keep.pk).exists())

    def test_purging_a_business_never_touches_an_admin(self):
        from .models import PlatformAdmin
        self.client.post(reverse("console_business_purge", args=[self.biz.id]),
                         {"confirm_username": "shop_a"})
        self.assertTrue(PlatformAdmin.objects.filter(username="op2").exists())


class PublicSignupRemovedTests(TestCase):
    """Self-service signup is gone, not merely disabled. Businesses are created by an
    operator in the console."""

    def test_no_signup_route_exists(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse("signup_view")

    def test_signup_url_404s(self):
        # Whatever the old path was, nothing answers there now.
        for path in ("/signup", "/signup/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
            self.assertEqual(self.client.post(path, {"username": "sneaky"}).status_code,
                             404, path)
        self.assertFalse(User.objects.filter(username="sneaky").exists())

    def test_signup_view_is_gone_from_the_module(self):
        from .views import auth
        self.assertFalse(hasattr(auth, "signup_view"))

    def test_login_page_offers_no_signup_link(self):
        html = self.client.get(reverse("login_view")).content.decode()
        self.assertNotIn("signUp(", html)
        self.assertNotIn("Create an account", html)

    def test_login_page_renders_with_admin_querystring(self):
        """The removed link lived behind ?admin — that branch must not have left a
        dangling {% url %} that raises at render time."""
        self.assertEqual(self.client.get(reverse("login_view") + "?admin=1").status_code, 200)


class CreatePlatformAdminCommandTests(TestCase):
    """The first admin has to come from the server, not from the console."""

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("create_platform_admin", *args, stdout=out)
        return out.getvalue()

    def test_generates_and_prints_a_password(self):
        from .models import PlatformAdmin
        out = self._run("firstop", "--name", "First Op")
        a = PlatformAdmin.objects.get(username="firstop")
        self.assertEqual(a.full_name, "First Op")
        # The generated password is printed once and must actually work.
        shown = [l.split("Password")[1].strip() for l in out.splitlines() if "Password " in l]
        self.assertEqual(len(shown), 1, out)
        self.assertTrue(a.check_password(shown[0]))
        self.assertNotEqual(a.password, shown[0])       # stored hashed

    def test_generated_passwords_are_unique_and_strong(self):
        from .management.commands.create_platform_admin import generate_password
        pws = {generate_password() for _ in range(50)}
        self.assertEqual(len(pws), 50)
        for pw in pws:
            self.assertGreaterEqual(len(pw), 18)
            self.assertTrue(any(c.isupper() for c in pw))
            self.assertTrue(any(c.islower() for c in pw))
            self.assertTrue(any(c.isdigit() for c in pw))
            # No look-alike characters — this gets typed off a terminal.
            self.assertFalse(set(pw) & set("0O1lI"))

    def test_creating_twice_is_refused(self):
        from django.core.management.base import CommandError
        self._run("dupop")
        with self.assertRaises(CommandError):
            self._run("dupop")

    def test_reset_password_issues_a_new_one(self):
        from .models import PlatformAdmin
        first = self._run("resetop")
        old_hash = PlatformAdmin.objects.get(username="resetop").password
        second = self._run("resetop", "--reset-password")
        new = PlatformAdmin.objects.get(username="resetop")
        self.assertNotEqual(new.password, old_hash)
        shown = [l.split("Password")[1].strip() for l in second.splitlines() if "Password " in l]
        self.assertTrue(new.check_password(shown[0]))

    def test_revoke_blocks_console_login(self):
        from .console_auth import authenticate_admin
        out = self._run("revokeop")
        pw = [l.split("Password")[1].strip() for l in out.splitlines() if "Password " in l][0]
        self.assertIsNotNone(authenticate_admin("revokeop", pw))
        self._run("revokeop", "--revoke")
        self.assertIsNone(authenticate_admin("revokeop", pw))
        self._run("revokeop", "--restore")
        self.assertIsNotNone(authenticate_admin("revokeop", pw))


class ConsoleChangePasswordTests(TestCase):
    """An admin changes their own console password from the UI."""

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="pwop", full_name="Pw Op")
        cls.admin.set_password("Origin4l!pass")
        cls.admin.save()

    def setUp(self):
        self.client.post(reverse("console_login"),
                         {"username": "pwop", "password": "Origin4l!pass"})

    def test_changes_the_password(self):
        from .models import PlatformAdmin
        r = self.client.post(reverse("console_change_password"), {
            "current_password": "Origin4l!pass",
            "new_password": "Rotated!pass77", "confirm_password": "Rotated!pass77"})
        self.assertEqual(r.status_code, 302)
        a = PlatformAdmin.objects.get(pk=self.admin.pk)
        self.assertTrue(a.check_password("Rotated!pass77"))
        self.assertFalse(a.check_password("Origin4l!pass"))

    def test_wrong_current_password_is_rejected(self):
        from .models import PlatformAdmin
        r = self.client.post(reverse("console_change_password"), {
            "current_password": "nope",
            "new_password": "Rotated!pass77", "confirm_password": "Rotated!pass77"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(PlatformAdmin.objects.get(pk=self.admin.pk)
                        .check_password("Origin4l!pass"))

    def test_mismatched_confirmation_is_rejected(self):
        r = self.client.post(reverse("console_change_password"), {
            "current_password": "Origin4l!pass",
            "new_password": "Rotated!pass77", "confirm_password": "Different!pass88"})
        self.assertEqual(r.status_code, 400)

    def test_weak_password_is_rejected(self):
        r = self.client.post(reverse("console_change_password"), {
            "current_password": "Origin4l!pass",
            "new_password": "12345678", "confirm_password": "12345678"})
        self.assertEqual(r.status_code, 400)

    def test_requires_console_login(self):
        self.client.get(reverse("console_logout"))
        r = self.client.get(reverse("console_change_password"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/console/login", r["Location"])


class ConsolePurgeCoverageTests(TestCase):
    """Guards the DERIVED ownership map in console_ops.

    The set of tables a business owns is worked out from the model graph, not listed by
    hand — so these tests are what makes adding a model safe. If a new model belongs to a
    business but is not reachable by the rule, one of these fails loudly instead of purge
    silently leaving its rows behind forever."""

    # Models that belong to the PLATFORM, not to any business. Anything else must be
    # reachable from a business, or the coverage test below fails.
    PLATFORM_MODELS = {"PlatformAdmin", "AppUser", "SyncUpSettings", "SyncUpJobRun"}

    def _app_models(self):
        from django.apps import apps
        return set(apps.get_app_config("gstbillingapp").get_models())

    def test_every_fk_to_user_is_classified(self):
        """A new FK to auth.User is either the tenancy column or a plain reference. It
        must be declared as one of them — guessing would either miss rows or delete
        another business's."""
        from .console_ops import _NOT_OWNERSHIP, _OWNERSHIP_FIELD_NAMES, user_fk_fields
        unclassified = [
            "%s.%s" % (m.__name__, f.name)
            for m, f in user_fk_fields()
            if f.name not in _OWNERSHIP_FIELD_NAMES
            and (m.__name__, f.name) not in _NOT_OWNERSHIP
        ]
        self.assertEqual(unclassified, [], (
            "These FKs to auth.User are unclassified: %s. Add the field name to "
            "_OWNERSHIP_FIELD_NAMES if it means 'belongs to this business', or to "
            "_NOT_OWNERSHIP if it is only a reference." % unclassified))

    def test_every_model_is_owned_or_platform_level(self):
        from .console_ops import owned_lookups
        owned = set(owned_lookups())
        stray = sorted(m.__name__ for m in self._app_models() - owned
                       if m.__name__ not in self.PLATFORM_MODELS)
        self.assertEqual(stray, [], (
            "These models belong to neither a business nor the platform: %s. If a "
            "business owns it, give it a `user`/`business` FK or a CASCADE FK to "
            "something owned. If the platform owns it, add it to PLATFORM_MODELS." % stray))

    def test_ownership_lookups_actually_resolve(self):
        """A derived lookup that does not resolve would raise only at purge time — on
        live data, mid-delete. Execute every one of them here instead."""
        from .console_ops import owned_querysets
        u = User.objects.create_user("lookupcheck", password="Xx!998877aa")
        for label, qs in owned_querysets(u):
            self.assertEqual(qs.count(), 0, label)      # must not raise

    def test_purge_empties_every_owned_table(self):
        from .models import UserProfile
        from .console_ops import owned_querysets, purge_business
        u = User.objects.create_user("fullpurge", password="Xx!998877aa")
        UserProfile.objects.create(user=u, business_title="Full")
        cust = Customer.objects.create(user=u, customer_name="ACME")
        Invoice.objects.create(user=u, invoice_number=1, invoice_date=date(2026, 1, 1),
                               invoice_customer=cust, invoice_json="{}")
        book = Book.objects.create(user=u, customer=cust, current_balance=0)
        BookLog.objects.create(parent_book=book, change=5, change_type=0, date=timezone.now())

        pk = u.pk
        purge_business(u)

        # Re-derive and query by the raw pk — the User row is gone, so nothing can be
        # left pointing at it anywhere.
        from .console_ops import owned_lookups
        for model, lookup in owned_lookups().items():
            self.assertEqual(model.objects.filter(**{lookup: pk}).count(), 0,
                             "%s still has rows after purge" % model.__name__)

    def test_purge_total_counts_rows_only(self):
        """Two things at once:

        * bool is a subclass of int, so a naive sum() over the result dict counted
          `committed: True` as a deleted row and over-reported by one;
        * the total covers UserProfile too — the old hand-written table list omitted it,
          so the preview under-reported by one in the other direction.
        """
        from .models import UserProfile
        from .console_ops import purge_business
        u = User.objects.create_user("counted", password="Xx!998877aa")
        UserProfile.objects.create(user=u, business_title="C")
        Customer.objects.create(user=u, customer_name="ONE")
        Customer.objects.create(user=u, customer_name="TWO")
        preview = purge_business(u, commit=False)
        self.assertEqual(preview["total"], 3)            # 2 customers + 1 profile
        self.assertEqual(preview["userprofile"], 1)
        self.assertEqual(purge_business(u)["total"], 3)  # same number when committed

    def test_converted_by_is_not_treated_as_ownership(self):
        """Quotation.converted_by points at a User but is a reference. If it were treated
        as ownership, purging business A would delete business B's quotations."""
        from .models import Quotation, UserProfile
        from .console_ops import purge_business
        a = User.objects.create_user("op_a", password="Xx!998877aa")
        b = User.objects.create_user("op_b", password="Xx!998877aa")
        UserProfile.objects.create(user=a, business_title="A")
        UserProfile.objects.create(user=b, business_title="B")
        # B owns the quotation; A merely converted it.
        q = Quotation.objects.create(user=b, quotation_number=1, quotation_date=date(2026, 1, 1),
                                     quotation_json="{}", converted_by=a)
        purge_business(a)
        self.assertTrue(Quotation.objects.filter(pk=q.pk).exists())


class PlatformAdminInitialsTests(TestCase):
    """The console avatar is always two letters — never one, never blank."""

    def _initials(self, full_name=None, username="someone"):
        from .models import PlatformAdmin
        return PlatformAdmin(username=username, full_name=full_name).initials

    def test_two_words_use_first_and_last(self):
        self.assertEqual(self._initials("Ganesh S"), "GS")
        self.assertEqual(self._initials("Ganesh Saravanan"), "GS")

    def test_three_words_use_first_and_last(self):
        self.assertEqual(self._initials("Anna Maria Rossi"), "AR")

    def test_single_word_uses_its_first_two_characters(self):
        self.assertEqual(self._initials("ag"), "AG")
        self.assertEqual(self._initials("ganesh"), "GA")

    def test_single_character_name_is_doubled(self):
        # Better a filled "XX" than a lonely half-empty letter.
        self.assertEqual(self._initials("x"), "XX")

    def test_falls_back_to_the_username(self):
        self.assertEqual(self._initials(None, username="goldmedal"), "GO")
        self.assertEqual(self._initials("", username="op two"), "OT")

    def test_never_returns_fewer_than_two_characters(self):
        for name in ["Ganesh S", "ag", "x", "  ", None, "", "A B C D"]:
            self.assertEqual(len(self._initials(name)), 2, repr(name))

    def test_always_upper_case(self):
        self.assertEqual(self._initials("ganesh saravanan"), "GS")


class FaviconTests(TestCase):
    """Every shell carries the brand icon, and /favicon.ico resolves at the root."""

    def test_favicon_files_exist(self):
        import os
        from django.conf import settings
        base = os.path.join(settings.BASE_DIR, "gstbillingapp", "static",
                            "gstbillingapp", "images")
        for name in ("favicon.svg", "favicon-32.png", "favicon.ico", "apple-touch-icon.png"):
            path = os.path.join(base, name)
            self.assertTrue(os.path.exists(path), name)
            self.assertGreater(os.path.getsize(path), 200, name)

    def test_root_favicon_ico_redirects_to_the_file(self):
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 301)
        self.assertIn("favicon.ico", r["Location"])

    def test_console_pages_link_the_icon(self):
        from .models import PlatformAdmin
        a = PlatformAdmin(username="favop", full_name="Fav Op")
        a.set_password("Cons0le!pass9")
        a.save()
        self.client.post(reverse("console_login"),
                         {"username": "favop", "password": "Cons0le!pass9"})
        html = self.client.get(reverse("console_businesses")).content.decode()
        self.assertIn('rel="icon"', html)
        self.assertIn("favicon.svg", html)
        self.assertIn("apple-touch-icon", html)

    def test_console_login_links_the_icon_too(self):
        html = self.client.get(reverse("console_login")).content.decode()
        self.assertIn("favicon.svg", html)

    def test_business_login_links_the_icon(self):
        html = self.client.get(reverse("login_view")).content.decode()
        self.assertIn("favicon.svg", html)


class TemplateCommentLeakTests(TestCase):
    """`{# ... #}` is SINGLE-LINE in Django. Spread it over two lines and it stops being
    a comment — the text renders into the page. That shipped once, visible at the top of
    every screen, so it is worth a test rather than a code review."""

    def test_no_multiline_hash_comments_in_any_template(self):
        import os
        from django.conf import settings
        root = os.path.join(settings.BASE_DIR, "gstbillingapp", "templates")
        offenders = []
        for dirpath, _, files in os.walk(root):
            for name in files:
                if not name.endswith(".html"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if "{#" in line and "#}" not in line:
                            offenders.append("%s:%d" % (
                                os.path.relpath(path, settings.BASE_DIR), lineno))
        self.assertEqual(offenders, [], (
            "Unterminated {# #} comment(s) at %s — these render as visible text. "
            "Use {%% comment %%}...{%% endcomment %%} for anything multi-line."
            % offenders))

    def test_rendered_shells_contain_no_raw_template_syntax(self):
        from .models import PlatformAdmin
        a = PlatformAdmin(username="leakop", full_name="Leak Op")
        a.set_password("Cons0le!pass9")
        a.save()
        self.client.post(reverse("console_login"),
                         {"username": "leakop", "password": "Cons0le!pass9"})
        for url in (reverse("login_view"), reverse("console_login"),
                    reverse("console_businesses"), reverse("console_admins")):
            html = self.client.get(url).content.decode()
            self.assertNotIn("{#", html, url)
            self.assertNotIn("{%", html, url)


class NotFoundPageTests(TestCase):
    """The branded 404 — shown for pages, never for machine-facing paths."""

    def test_missing_page_renders_the_branded_404(self):
        r = self.client.get("/definitely-not-a-page")
        self.assertEqual(r.status_code, 404)
        html = r.content.decode()
        self.assertIn("We couldn", html)                 # the headline
        self.assertIn("/definitely-not-a-page", html)    # shows what was missing
        self.assertIn("favicon.svg", html)

    def test_it_pulls_no_cdn_stylesheets(self):
        """The old page fetched Bootstrap + Bootstrap-Icons from two CDNs — exactly when
        the network is least likely to be working."""
        html = self.client.get("/nope").content.decode()
        self.assertNotIn("bootstrapcdn", html)
        self.assertNotIn("jsdelivr", html)

    def test_signed_out_visitor_is_offered_sign_in(self):
        html = self.client.get("/nope").content.decode()
        self.assertIn("Sign in", html)
        self.assertNotIn("Go to dashboard", html)

    def test_signed_in_user_is_offered_the_dashboard(self):
        from .models import UserProfile
        u = User.objects.create_user("e404", password="Xx!998877aa")
        UserProfile.objects.create(user=u, business_title="Shop")
        self.client.force_login(u)
        html = self.client.get("/nope").content.decode()
        self.assertIn("Go to dashboard", html)
        self.assertNotIn(">Sign in<", html)

    def test_console_404_offers_the_console_not_the_business_app(self):
        html = self.client.get("/console/no-such-screen").content.decode()
        self.assertIn("Back to console", html)
        self.assertNotIn("Go to dashboard", html)

    def test_mobile_404_offers_no_dead_link(self):
        """There is no /m/ root, so the mobile branch must not link to one."""
        html = self.client.get("/m/no-such-screen").content.decode()
        self.assertNotIn('href="/m/"', html)
        self.assertIn("Go back", html)

    # ---------------- machine-facing paths stay bare ----------------
    def test_cron_404_stays_bare(self):
        """The cron endpoints 404 to look like nothing is there — a branded page would
        announce the app and ship KBs to a cron service on every bad poll."""
        r = self.client.get("/cron/health")                  # no key configured
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"<!doctype html>", r.content.lower())
        self.assertEqual(r.content, b"")

    def test_api_404_stays_bare(self):
        r = self.client.get("/books/api/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"<!doctype html>", r.content.lower())

    def test_static_404_stays_bare(self):
        r = self.client.get("/static/gstbillingapp/nope.css")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"<!doctype html>", r.content.lower())


class SecurityLockdownTests(TestCase):
    """Endpoints that used to accept anonymous or cross-business requests.

    Each case pins one hole shut: an anonymous caller is sent to the login page, and a
    logged-in business cannot reach another business's records."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, ChequeLeaf, Product, Inventory, InventoryLog
        cls.a = User.objects.create_user("sec_a", password="x")
        cls.b = User.objects.create_user("sec_b", password="x")
        UserProfile.objects.create(user=cls.a, business_title="Shop A")
        UserProfile.objects.create(user=cls.b, business_title="Shop B")
        cls.cust_a = Customer.objects.create(user=cls.a, customer_name="A CUST", collection_day=1)
        cls.cust_b = Customer.objects.create(user=cls.b, customer_name="B CUST", collection_day=1,
                                             customer_place="OLD PLACE")
        cls.book_b = Book.objects.create(user=cls.b, customer=cls.cust_b, current_balance=-5)
        cls.log_b = BookLog.objects.create(parent_book=cls.book_b, change=-5, change_type=1,
                                           is_active=False)
        cls.leaf_b = ChequeLeaf.objects.create(user=cls.b, cheque_number="SEC-CHQ-B")
        cls.prod_b = Product.objects.create(user=cls.b, model_no="SEC-M", product_name="Thing")
        cls.inv_b = Inventory.objects.create(user=cls.b, product=cls.prod_b, current_stock=3)
        cls.ilog_b = InventoryLog.objects.create(user=cls.b, product=cls.prod_b, change=3)

    # -- anonymous callers are turned away -------------------------------------------
    def test_book_apis_require_login(self):
        for name, data in (("book_logs_api_active", {"booklog": self.log_b.id}),
                           ("book_logs_api_roundoff", {"book_id": self.book_b.id}),
                           ("book_logs_api_recalculate", {"book_id": self.book_b.id}),
                           ("book_logs_api_recalculate_all", {})):
            r = self.client.post(reverse(name), data)
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login", r["Location"], name)
        self.log_b.refresh_from_db()
        self.assertFalse(self.log_b.is_active)

    def test_book_logs_pending_requires_login(self):
        r = self.client.post(reverse("book_logs_pending"), {
            "booklog_id": self.log_b.id, "booklog_change": "1",
            "booklog_options": "1", "booklog_description": "x"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(BookLog.objects.filter(parent_book=self.book_b).count(), 1)

    def test_collection_day_update_requires_login(self):
        r = self.client.post(reverse("customer_collection_day_update"),
                             {"customer_id": self.cust_b.id, "collection_day": 4,
                              "customer_place": "HACKED"})
        self.assertEqual(r.status_code, 302)
        self.cust_b.refresh_from_db()
        self.assertEqual(self.cust_b.customer_place, "OLD PLACE")

    # -- a business cannot reach another business's records ----------------------------
    def test_book_api_cannot_touch_another_business(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(reverse("book_logs_api_active"),
                                          {"booklog": self.log_b.id}).status_code, 404)
        self.assertEqual(self.client.post(reverse("book_logs_api_roundoff"),
                                          {"book_id": self.book_b.id}).status_code, 404)
        self.assertEqual(self.client.post(reverse("book_logs_api_recalculate"),
                                          {"book_id": self.book_b.id}).status_code, 404)
        self.log_b.refresh_from_db()
        self.assertFalse(self.log_b.is_active)

    def test_state_changing_book_api_rejects_get(self):
        self.client.force_login(self.b)
        r = self.client.get(reverse("book_logs_api_active"), {"booklog": self.log_b.id})
        self.assertEqual(r.status_code, 405)
        self.log_b.refresh_from_db()
        self.assertFalse(self.log_b.is_active)

    def test_owner_can_still_use_book_api(self):
        self.client.force_login(self.b)
        r = self.client.post(reverse("book_logs_api_active"), {"booklog": self.log_b.id})
        self.assertEqual(r.status_code, 200)
        self.log_b.refresh_from_db()
        self.assertTrue(self.log_b.is_active)

    def test_collection_day_update_is_scoped(self):
        self.client.force_login(self.a)
        r = self.client.post(reverse("customer_collection_day_update"),
                             {"customer_id": self.cust_b.id, "collection_day": 4,
                              "customer_place": "HACKED"})
        self.assertEqual(r.json()["status"], "error")
        self.cust_b.refresh_from_db()
        self.assertEqual(self.cust_b.customer_place, "OLD PLACE")
        r = self.client.post(reverse("customer_collection_day_update"),
                             {"customer_id": self.cust_a.id, "collection_day": 3,
                              "customer_place": "Route 3"})
        self.assertEqual(r.json()["status"], "success")

    def test_cheque_leaf_is_scoped(self):
        from .models import ChequeLeaf
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(
            reverse("cheque_leaf_edit", args=[self.leaf_b.id])).status_code, 404)
        self.assertEqual(self.client.get(
            reverse("cheque_leaf_delete", args=[self.leaf_b.id])).status_code, 404)
        self.assertTrue(ChequeLeaf.objects.filter(pk=self.leaf_b.pk).exists())

    def test_inventory_log_delete_is_scoped(self):
        from .models import InventoryLog
        self.client.force_login(self.a)
        r = self.client.get(reverse("inventory_logs_del", args=[self.ilog_b.id]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(InventoryLog.objects.filter(pk=self.ilog_b.pk).exists())

    def test_inventory_log_delete_recomputes_the_right_row(self):
        self.client.force_login(self.b)
        r = self.client.get(reverse("inventory_logs_del", args=[self.ilog_b.id]))
        self.assertEqual(r.status_code, 302)
        self.inv_b.refresh_from_db()
        self.assertEqual(self.inv_b.current_stock, 0)

    # -- removed endpoints are gone ------------------------------------------------------
    def test_removed_endpoints_no_longer_exist(self):
        self.client.force_login(self.a)
        for path in ("/customers/api/location-mapper", "/customers/api/default_password",
                     "/customers/api/all_userid_set",
                     "/customers/%d/mobile-link" % self.cust_a.id):
            self.assertEqual(self.client.post(path).status_code, 404, path)

    # -- the mobile-access toggle --------------------------------------------------------
    def test_mobile_toggle_is_keyed_by_id_and_scoped(self):
        self.client.force_login(self.a)
        r = self.client.post(reverse("customer_is_mobile_user"), {"customer_id": self.cust_b.id})
        self.assertEqual(r.json()["status"], "error")
        self.cust_b.refresh_from_db()
        self.assertFalse(self.cust_b.is_mobile_user)
        r = self.client.post(reverse("customer_is_mobile_user"), {"customer_id": self.cust_a.id})
        self.assertEqual(r.json()["status"], "success")
        self.cust_a.refresh_from_db()
        self.assertTrue(self.cust_a.is_mobile_user)

    def test_mobile_toggle_rejects_get(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse("customer_is_mobile_user")).status_code, 405)


def _app_token(row, active=True):
    """The link a person gets — for whoever holds this row's mobile number (or email).

    One link per PERSON now: the same call works for a customer row and for an employee,
    because both are the same kind of thing once they carry a number."""
    from .identity import attach
    from .mobile_auth import mint_user_token
    from .models import AppUser
    person = row if isinstance(row, AppUser) else attach(row)
    assert person is not None, "%s has no usable mobile number or email" % (row,)
    if active:
        AppUser.objects.filter(pk=person.pk).update(login_status=AppUser.LOGIN_ACTIVE)
        person.refresh_from_db()
    return mint_user_token(person)


def _person_of(row):
    from .identity import attach
    return attach(row)


def _live_person(row):
    """The person holding this row's number, with their app login switched on."""
    from .models import AppUser
    person = _person_of(row)
    assert person is not None, "%s has no usable mobile number or email" % (row,)
    AppUser.objects.filter(pk=person.pk).update(login_status=AppUser.LOGIN_ACTIVE)
    person.refresh_from_db()
    return person


def _syncup_on(**fields):
    """Save SyncUp settings (as an admin would on Console -> Settings) for a test."""
    from .models import SyncUpSettings
    cfg = SyncUpSettings.load()
    values = {"api_base": "https://syncup.test", "partner_key": "key",
              "link_base": "https://gstsync.test"}
    values.update(fields)
    for name, value in values.items():
        setattr(cfg, name, value)
    cfg.save()
    return cfg


def _gstin(first14):
    """A GSTIN with a correct check character, so it counts as evidence."""
    from .gstin import gstin_check_char
    return first14 + gstin_check_char(first14)


def _businesses(*names):
    from .models import UserProfile
    out = []
    for n in names:
        u = User.objects.create_user("pt_" + n.lower(), password="Xx!998877aa")
        UserProfile.objects.create(user=u, business_title=n + " CO", business_brand=n)
        out.append(u)
    return out


class CustomerAppSwitchTests(TestCase):
    """The business side honours the console's customer-app switch, and every visibility
    change reaches SyncUp without ever blocking the business."""

    @classmethod
    def setUpTestData(cls):
        from .models import AppUser
        cls.owner, cls.other = _businesses("ALPHA", "BETA")
        cls.c = Customer.objects.create(user=cls.owner, customer_name="KMR",
                                        customer_phone="9000000001", is_mobile_user=True)
        cls.c2 = Customer.objects.create(user=cls.other, customer_name="KMR",
                                         customer_phone="9000000001", is_mobile_user=True)
        # One number, so one person — nobody mapped anything.
        cls.party = _person_of(cls.c)
        AppUser.objects.filter(pk=cls.party.pk).update(login_status=AppUser.LOGIN_ACTIVE,
                                                       syncup_active=True)
        cls.party.refresh_from_db()

    def setUp(self):
        self.client.force_login(self.owner)

    def _switch(self, on):
        from .models import UserProfile
        UserProfile.objects.filter(user=self.owner).update(customer_app_enabled=on)

    def _toggle(self, customer=None):
        return self.client.post(reverse("customer_is_mobile_user"),
                                {"customer_id": (customer or self.c).id}).json()

    def test_toggle_is_refused_while_the_app_is_off(self):
        self._switch(False)
        self.assertEqual(self._toggle()["status"], "error")
        self.c.refresh_from_db()
        self.assertTrue(self.c.is_mobile_user)

    def test_list_hides_the_toggle_while_the_app_is_off(self):
        marker = "IsMobileUser_Status(%d" % self.c.id
        self.assertContains(self.client.get(reverse("customers")), marker)
        self._switch(False)
        self.assertNotContains(self.client.get(reverse("customers")), marker)

    def test_edit_form_keeps_the_flag_while_the_app_is_off(self):
        """The toggle isn't on the form, so a save mustn't read it as switched off."""
        self._switch(False)
        url = reverse("customer_edit", args=[self.c.id])
        self.assertNotContains(self.client.get(url), 'name="is_mobile_user"')
        r = self.client.post(url, {"customer_name": "KMR", "customer_phone": "9000000001",
                                   "collection_day": 0})
        self.assertEqual(r.status_code, 302)
        self.c.refresh_from_db()
        self.assertTrue(self.c.is_mobile_user)

    def test_toggle_pushes_to_syncup_when_the_last_ledger_goes(self):
        # The push runs once the change commits (identity_hooks), so the test commits it.
        with mock.patch("gstbillingapp.syncup_client.set_account_active") as push:
            with self.captureOnCommitCallbacks(execute=True):
                self._toggle()                               # BETA still shows them
            push.assert_not_called()
            self.client.force_login(self.other)
            with self.captureOnCommitCallbacks(execute=True):
                self._toggle(self.c2)
        push.assert_called_once_with(self.party.external_id, False, timeout=2)

    def test_a_syncup_outage_never_blocks_the_business(self):
        from .syncup_client import SyncUpError
        Customer.objects.filter(pk=self.c2.pk).update(is_mobile_user=False)
        with mock.patch("gstbillingapp.syncup_client.set_account_active",
                        side_effect=SyncUpError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self._toggle()["status"], "success")
        self.party.refresh_from_db()
        self.assertIn("down", self.party.syncup_error)

    def test_deleting_the_last_shown_row_pushes_to_syncup(self):
        Customer.objects.filter(pk=self.c2.pk).update(is_mobile_user=False)
        with mock.patch("gstbillingapp.syncup_client.set_account_active") as push:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse("customer_delete"), {"customer_id": self.c.id})
        push.assert_called_once_with(self.party.external_id, False, timeout=2)


class SyncUpSettingsTests(TestCase):
    """SyncUp's address, key, public address and login domain live in the database and are
    edited on the console - never in settings.py."""

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="setop", full_name="Set Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()

    def setUp(self):
        self.client.post(reverse("console_login"),
                         {"username": "setop", "password": "Cons0le!pass9"})

    def _save(self, **fields):
        data = {"api_base": "https://syncup.test", "partner_key": "",
                "link_base": "https://gstsync.test", "timeout": "5"}
        data.update(fields)
        return self.client.post(reverse("console_syncup"), data)

    def _cfg(self):
        from .models import SyncUpSettings
        return SyncUpSettings.load()

    def test_requires_console_login(self):
        self.client.get(reverse("console_logout"))
        for r in (self.client.get(reverse("console_syncup")),
                  self.client.post(reverse("console_syncup_test"))):
            self.assertEqual(r.status_code, 302)
            self.assertIn("/console/login", r["Location"])

    def test_defaults_before_anything_is_saved(self):
        from .syncup_client import is_configured
        r = self.client.get(reverse("console_syncup"))
        self.assertContains(r, "Not set up")
        self.assertFalse(is_configured())

    def test_settings_is_in_the_console_nav(self):
        self.assertContains(self.client.get(reverse("console_businesses")),
                            'href="%s"' % reverse("console_syncup"))

    def test_saving_stores_and_normalises(self):
        r = self._save(api_base="https://syncup.test/partner/v1/", partner_key="sk_live_ABCD1234")
        self.assertRedirects(r, reverse("console_syncup"))
        cfg = self._cfg()
        self.assertEqual((cfg.api_base, cfg.partner_key, cfg.link_base, cfg.updated_by),
                         ("https://syncup.test", "sk_live_ABCD1234", "https://gstsync.test",
                          self.admin))

    def test_the_partner_key_is_write_only(self):
        self._save(partner_key="sk_live_ABCD1234")
        page = self.client.get(reverse("console_syncup"))
        self.assertNotContains(page, "sk_live_ABCD1234")
        self.assertContains(page, "1234")                        # only a hint
        self._save()                                              # blank keeps it
        self.assertEqual(self._cfg().partner_key, "sk_live_ABCD1234")
        self._save(clear_key="1")
        self.assertEqual(self._cfg().partner_key, "")

    def test_bad_values_are_refused_and_nothing_is_saved(self):
        from .models import SyncUpSettings
        for fields in ({"link_base": "http://gstsync.test"},      # SyncUp needs https links
                       {"api_base": "http://syncup.example.com"},  # key in the clear
                       {"api_base": "syncup.test"},
                       {"timeout": "0"}):
            self.assertEqual(self._save(**fields).status_code, 400, fields)
        self.assertFalse(SyncUpSettings.objects.exists())

    def test_plain_http_is_allowed_for_a_local_syncup(self):
        self._save(api_base="http://127.0.0.1:8001")
        self.assertEqual(self._cfg().api_base, "http://127.0.0.1:8001")

    def test_the_client_uses_the_saved_settings(self):
        import io
        from .syncup_client import set_account_active
        _syncup_on(timeout=7)
        seen = {}

        def fake_urlopen(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header("Authorization"), timeout=timeout)
            return io.BytesIO(b'{"user": {"id": "1"}}')

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(set_account_active("party-1", True), {"id": "1"})
        self.assertEqual(seen, {"url": "https://syncup.test/partner/v1/users/external/party-1",
                                "auth": "Bearer key", "timeout": 7})

    def test_check_connection_reads_syncups_answer(self):
        from .syncup_client import SyncUpError, check_connection
        _syncup_on()
        for exc, ok in ((SyncUpError("x", 404, {"success": False}), True),    # key accepted
                        (SyncUpError("x", 401, {"success": False}), False),   # key rejected
                        (SyncUpError("x", 404, None), False),     # something else answered
                        (SyncUpError("unreachable"), False)):
            with mock.patch("gstbillingapp.syncup_client._request", side_effect=exc):
                self.assertEqual(check_connection()[0], ok, exc.status)

    def test_the_test_button_reports_the_result(self):
        _syncup_on()
        with mock.patch("gstbillingapp.views.console_settings.check_connection",
                        return_value=(False, "SyncUp rejected the partner key.")):
            r = self.client.post(reverse("console_syncup_test"), follow=True)
        self.assertContains(r, "SyncUp rejected the partner key.")


def _employee(business, name="RAVI", **fields):
    from .models import Employee
    return Employee.objects.create(business=business, name=name, **fields)


class SyncUpSpeedTests(TestCase):
    """Every action is one Partner API call, a business never waits more than
    QUICK_TIMEOUT on SyncUp, and /cron/syncup catches up anything that fell behind."""

    def setUp(self):
        _syncup_on(timeout=5)

    @staticmethod
    def _urlopen(reply, seen):
        import io

        def fake(req, timeout):
            seen.append({"method": req.get_method(), "timeout": timeout,
                         "body": json.loads(req.data.decode()) if req.data else None})
            return io.BytesIO(json.dumps(reply).encode())
        return fake

    def test_issuing_sends_the_account_and_its_link_in_one_call(self):
        from .syncup_client import upsert_account
        link = "https://gstsync.test/m/customer/?t=abc"
        seen = []
        reply = {"success": True, "user": {"id": "1"}, "links": [{"id": "9", "url": link}]}
        with mock.patch("urllib.request.urlopen", self._urlopen(reply, seen)):
            upsert_account("user-1", name="KMR", phone="9876500001",
                           password="Abcd1234xy", app_link=link)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["method"], "PUT")
        self.assertEqual(seen[0]["body"]["links"], [
            {"external_id": "gstsync", "title": "GSTSync", "url": link, "icon": "home"}])

    def test_a_syncup_that_drops_the_link_is_an_error(self):
        """An older SyncUp ignores `links`: say so, rather than leave a login with no link."""
        from .syncup_client import SyncUpError, upsert_account
        with mock.patch("urllib.request.urlopen",
                        self._urlopen({"success": True, "user": {"id": "1"}}, [])):
            with self.assertRaises(SyncUpError):
                upsert_account("user-1", name="KMR", phone="9876500001",
                               password="Abcd1234xy", app_link="https://gstsync.test/m/customer/?t=abc")

    def test_business_side_pushes_wait_at_most_the_quick_timeout(self):
        from .syncup_client import QUICK_TIMEOUT, set_account_active
        seen = []
        with mock.patch("urllib.request.urlopen", self._urlopen({"user": {}}, seen)):
            set_account_active("party-1", False, timeout=QUICK_TIMEOUT)     # a business toggle
            set_account_active("party-1", False)                            # a console action
        self.assertEqual([s["timeout"] for s in seen], [QUICK_TIMEOUT, 5])

    def test_a_toggle_uses_the_quick_timeout(self):
        from .models import AppUser
        from .appusers import refresh_login
        a, = _businesses("ALPHA")
        c = Customer.objects.create(user=a, customer_name="KMR", customer_phone="9876500031",
                                    is_mobile_user=False)
        person = _person_of(c)
        AppUser.objects.filter(pk=person.pk).update(login_status=AppUser.LOGIN_ACTIVE,
                                                    syncup_active=True)
        person.refresh_from_db()
        party = person
        with mock.patch("gstbillingapp.syncup_client.set_account_active") as push:
            self.assertEqual(refresh_login(party), "pushed")
        push.assert_called_once_with(party.external_id, False, timeout=2)

    def test_the_connection_check_reports_the_round_trip(self):
        from .syncup_client import SyncUpError, check_connection
        with mock.patch("gstbillingapp.syncup_client._request",
                        side_effect=SyncUpError("x", 404, {"success": False})):
            ok, message = check_connection()
        self.assertTrue(ok)
        self.assertRegex(message, r"\(\d+ ms\)")

    @override_settings(CRON_KEY="k")
    def test_cron_catches_up_logins_that_fell_behind(self):
        from .models import AppUser
        a, = _businesses("ALPHA")
        c = Customer.objects.create(user=a, customer_name="KMR", customer_phone="9876500041",
                                    is_mobile_user=True)
        party = _person_of(c)
        AppUser.objects.filter(pk=party.pk).update(login_status=AppUser.LOGIN_ACTIVE,
                                                   syncup_active=True, syncup_error="timed out")
        party.refresh_from_db()
        staff = _employee(a, "GANESH", phone="9000000009")
        AppUser.objects.filter(pk=_person_of(staff).pk).update(
            login_status=AppUser.LOGIN_ACTIVE, syncup_active=True)        # already in step
        with mock.patch("gstbillingapp.syncup_client.set_account_active") as push:
            r = self.client.get("/cron/syncup", {"key": "k"})
        body = r.json()
        self.assertEqual((body["logins"]["pushed"], body["logins"]["unchanged"]), (1, 1))
        push.assert_called_once_with(party.external_id, True, timeout=2)
        party.refresh_from_db()
        self.assertEqual(party.syncup_error, "")
        self.assertEqual(self.client.get("/cron/syncup", {"key": "wrong"}).status_code, 404)

    @override_settings(CRON_KEY="k")
    def test_cron_skips_until_syncup_is_set_up(self):
        _syncup_on(api_base="")
        self.assertEqual(self.client.get("/cron/syncup", {"key": "k"}).json().get("skipped"),
                         "not_configured")


class SyncUpErrorMessageTests(TestCase):
    """When SyncUp itself crashes, the console says what broke instead of a bare 500."""

    def _crash(self, body):
        import io
        import urllib.error

        def fake(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", {},
                                         io.BytesIO(body.encode()))
        return fake

    def test_a_syncup_crash_names_the_error_from_its_debug_page(self):
        from .syncup_client import SyncUpError, set_account_active
        _syncup_on()
        page = ("<html><head><title>OperationalError at /partner/v1/users/external/party-3"
                "</title></head><body>no such column</body></html>")
        with mock.patch("urllib.request.urlopen", self._crash(page)):
            with self.assertRaises(SyncUpError) as ctx:
                set_account_active("party-3", True)
        message = str(ctx.exception)
        self.assertIn("OperationalError at /partner/v1/users/external/party-3", message)
        self.assertIn("error log", message)
        self.assertEqual(ctx.exception.status, 500)

    def test_a_plain_crash_still_reads_sensibly(self):
        from .syncup_client import SyncUpError, set_account_active
        _syncup_on()
        with mock.patch("urllib.request.urlopen", self._crash("")):
            with self.assertRaises(SyncUpError) as ctx:
                set_account_active("party-3", True)
        self.assertIn("SyncUp hit an error on its side (500): Internal Server Error", str(ctx.exception))


class GooglePlayTests(TestCase):
    """The SyncUp app's Google Play listing: one URL on the console, shown wherever it's set,
    and never half-shown when it isn't."""

    PLAY = "https://play.google.com/store/apps/details?id=com.agani.syncup"

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="playop", full_name="Play Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()
        cls.a, = _businesses("ALPHA")

    def _play(self, **fields):
        return _syncup_on(play_url=self.PLAY, **fields)

    def _console(self):
        self.client.post(reverse("console_login"),
                         {"username": "playop", "password": "Cons0le!pass9"})

    def _save(self, **fields):
        data = {"api_base": "", "partner_key": "", "link_base": "", "timeout": "5",
                "play_url": "", "customer_share_text": "",
                "share_text": ""}
        data.update(fields)
        return self.client.post(reverse("console_syncup"), data)

    # ---- the listing ----------------------------------------------------------------
    def test_play_links_are_recognised_and_made_canonical(self):
        from .syncup_app import parse_play_url
        want = (self.PLAY, "com.agani.syncup")
        for raw in ("https://play.google.com/store/apps/details?id=com.agani.syncup&hl=en_IN&gl=US",
                    "  https://play.google.com/store/apps/details/?id=com.agani.syncup  ",
                    "market://details?id=com.agani.syncup",
                    "com.agani.syncup"):
            self.assertEqual(parse_play_url(raw), want, raw)
        for bad in ("https://example.com/store/apps/details?id=com.agani.syncup",
                    "https://play.google.com/store/apps/details", "not a link", "syncup",
                    "javascript:alert(1)"):
            self.assertEqual(parse_play_url(bad), ("", ""), bad)

    def test_nothing_until_a_url_is_set_then_each_place_is_tagged(self):
        from .syncup_app import listing
        self.assertIsNone(listing())
        self._play()
        app = listing()
        self.assertEqual(app["package"], "com.agani.syncup")
        self.assertEqual(app["staff"],
                         self.PLAY + "&referrer=utm_source%3Dgstsync%26utm_medium%3Dstaff")

    def test_share_texts_fill_in_and_survive_stray_braces(self):
        from .syncup_app import customer_text, share_text
        cfg = self._play()
        self.assertIn("Hello KMR, see your ALPHA ledger",
                      customer_text(cfg, customer="KMR", business="ALPHA", link="L"))
        self.assertEqual(share_text(cfg, business="ALPHA", link="L"),
                         "Get the SyncUp app for ALPHA: L")
        cfg.customer_share_text = "Hi {customer} {oops} } { {link}"
        self.assertEqual(customer_text(cfg, customer="KMR", business="B", link="L"),
                         "Hi KMR {oops} } { L")

    # ---- console --------------------------------------------------------------------
    def test_console_saves_a_canonical_play_link(self):
        from .models import SyncUpSettings
        self._console()
        r = self._save(play_url=self.PLAY + "&hl=en", play_on_landing="1",
                       share_text="Get {business}: {link}")
        self.assertRedirects(r, reverse("console_syncup"))
        cfg = SyncUpSettings.load()
        self.assertEqual((cfg.play_url, cfg.play_on_landing, cfg.share_text),
                         (self.PLAY, True, "Get {business}: {link}"))
        self.assertContains(self.client.get(reverse("console_syncup")), "com.agani.syncup")

    def test_console_refuses_a_link_that_isnt_google_play(self):
        from .models import SyncUpSettings
        self._console()
        self.assertEqual(self._save(play_url="https://example.com/app").status_code, 400)
        self.assertFalse(SyncUpSettings.objects.exists())

    # ---- where it shows -------------------------------------------------------------
    def test_public_landing_page_only_when_set_and_switched_on(self):
        self.assertNotContains(self.client.get("/"), "Google Play")
        self._play()
        r = self.client.get("/")
        self.assertContains(r, "Get SyncUp on Google Play")
        self.assertContains(r, "utm_medium%3Dlanding")
        self._play(play_on_landing=False)
        self.assertNotContains(self.client.get("/"), "Google Play")

    def test_business_dashboard_and_profile_offer_the_app(self):
        self.client.force_login(self.a)
        self.assertNotContains(self.client.get("/"), "SyncUp on Google Play")
        self.assertNotContains(self.client.get(reverse("user_profile")), 'class="papp"')
        self._play()
        home = self.client.get("/")
        self.assertContains(home, "SyncUp on Google Play")
        self.assertContains(home, "https://wa.me/?text=Get%20the%20SyncUp%20app%20for%20ALPHA")
        profile = self.client.get(reverse("user_profile"))
        self.assertContains(profile, 'class="papp"')      # the block beside Bank & payments
        self.assertContains(profile, "utm_medium%3Dbusiness")

    def test_staff_can_invite_only_customers_shown_in_the_app(self):
        self._play()
        emp = _employee(self.a, "GANESH", phone="9000000003")
        shown = Customer.objects.create(user=self.a, customer_name="KMR",
                                        customer_phone="9000000001", is_mobile_user=True)
        hidden = Customer.objects.create(user=self.a, customer_name="LONE",
                                         customer_phone="9000000002", is_mobile_user=False)
        self.client.get("/m/employee/", {"t": _app_token(emp)})
        r = self.client.get(reverse("m_employee_customer", args=[shown.id]))
        self.assertContains(r, 'onclick="shareApp()"')
        self.assertContains(r, "utm_medium%3Dstaff")
        self.assertNotContains(self.client.get(reverse("m_employee_customer", args=[hidden.id])),
                               'onclick="shareApp()"')


class PasskeyTests(TestCase):
    """Business passkeys: set on the console, stored only as a digest, never hard-coded, and
    guarded against guessing."""

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="keyop", full_name="Key Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()
        cls.a, cls.b = _businesses("ALPHA", "BETA")

    def setUp(self):
        from django.core.cache import cache
        cache.clear()                         # the attempt limit lives in the cache

    def _console(self):
        self.client.post(reverse("console_login"),
                         {"username": "keyop", "password": "Cons0le!pass9"})

    def _sign_in(self, passkey, client=None):
        return (client or self.client).post(reverse("passkey_auth"),
                                            data=json.dumps({"passkey": passkey}),
                                            content_type="application/json")

    def test_the_old_hard_coded_passkeys_are_gone_for_good(self):
        from .passkeys import problem
        for old in ("11111", "22222", "33333", "44444", "55555"):
            self.assertEqual(self._sign_in(old).status_code, 400, old)
        self.assertIn("published", problem("97911"))

    def test_generate_shows_it_once_and_it_signs_in(self):
        from django.forms.models import model_to_dict
        from django.test import Client
        from .models import BusinessPasskey
        self._console()
        r = self.client.post(reverse("console_business_passkey_generate", args=[self.a.id]))
        self.assertIn("no-store", r["Cache-Control"])
        passkey = r.context["passkey"]
        self.assertRegex(passkey, r"^[A-Z0-9]{5}$")
        record = BusinessPasskey.objects.get(user=self.a)
        self.assertNotIn(passkey, repr(model_to_dict(record)))        # only the digest is kept
        self.assertEqual(record.set_by, self.admin)
        self.assertNotContains(self.client.get(reverse("console_business_detail", args=[self.a.id])),
                               'data-passkey="%s"' % passkey)
        phone = Client()
        self.assertEqual(self._sign_in(passkey.lower(), phone).status_code, 200)   # any case
        self.assertEqual(int(phone.session["_auth_user_id"]), self.a.id)
        record.refresh_from_db()
        self.assertIsNotNone(record.last_used_at)

    def test_weak_leaked_and_taken_passkeys_are_refused(self):
        from .models import BusinessPasskey
        from .passkeys import set_passkey
        set_passkey(self.b, "K7M2Q")
        self._console()
        url = reverse("console_business_passkey_set", args=[self.a.id])
        for bad in ("AAAAA", "12345", "54321", "ABCDE", "11111", "K7M2", "K7M2Q9", "K7M2Q"):
            self.client.post(url, {"passkey": bad})
            self.assertFalse(BusinessPasskey.objects.filter(user=self.a).exists(), bad)
        ok = self.client.post(url, {"passkey": "r8t3w"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.context["passkey"], "R8T3W")

    def test_turning_it_off_stops_it(self):
        from django.test import Client
        from .passkeys import set_passkey
        set_passkey(self.a, "R8T3W")
        self._console()
        self.client.post(reverse("console_business_passkey_off", args=[self.a.id]))
        self.assertEqual(self._sign_in("R8T3W", Client()).status_code, 400)

    def test_a_suspended_business_cant_sign_in(self):
        from .passkeys import set_passkey
        set_passkey(self.a, "R8T3W")
        User.objects.filter(pk=self.a.pk).update(is_active=False)
        self.assertEqual(self._sign_in("R8T3W").status_code, 400)

    def test_wrong_tries_are_limited_per_device(self):
        from .passkeys import set_passkey
        set_passkey(self.a, "R8T3W")
        for _ in range(5):
            self.assertEqual(self._sign_in("ZZZZ9").status_code, 400)
        self.assertEqual(self._sign_in("R8T3W").status_code, 429)   # even the right one, for now

    def test_one_answer_for_every_failure(self):
        from .passkeys import set_passkey
        set_passkey(self.a, "R8T3W")
        User.objects.filter(pk=self.a.pk).update(is_active=False)
        answers = {self._sign_in(p).json()["error"] for p in ("R8T3W", "ZZZZ9", "")}
        self.assertEqual(answers, {"That passkey isn't right."})

    def test_csrf_is_enforced_and_only_post(self):
        from django.test import Client
        from .passkeys import set_passkey
        set_passkey(self.a, "R8T3W")
        self.assertEqual(self._sign_in("R8T3W", Client(enforce_csrf_checks=True)).status_code, 403)
        self.assertEqual(self.client.get(reverse("passkey_auth")).status_code, 405)

    def test_console_shows_passkey_status(self):
        from .passkeys import set_passkey
        set_passkey(self.a, "R8T3W", admin=self.admin)
        self._console()
        detail = self.client.get(reverse("console_business_detail", args=[self.a.id]))
        self.assertContains(detail, "not used yet")
        self.assertContains(self.client.get(reverse("console_businesses")), 'data-l="Passkey"')

    def test_setting_needs_the_console(self):
        r = self.client.post(reverse("console_business_passkey_generate", args=[self.a.id]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/console/login", r["Location"])

    def test_generated_passkeys_pass_the_rules_and_skip_look_alikes(self):
        from .passkeys import generate, problem
        for _ in range(40):
            p = generate()
            self.assertEqual(problem(p), "")
            self.assertFalse(set(p) & set("01OIL"), p)


def _local(day, hour, minute=0):
    import datetime as _dt
    return timezone.make_aware(_dt.datetime.combine(day, _dt.time(hour, minute)))


class SyncUpMessageTests(TestCase):
    """SyncUp messages: queued (never sent inline, except an approval's quick try), only when
    the console has switched them on, only to the right people, never at night."""

    ALL = {"c_bill", "c_payment", "c_order", "c_overdue", "e_payment", "e_morning",
           "a_approval", "a_order", "a_evening"}

    @classmethod
    def setUpTestData(cls):
        from .models import AppUser
        cls.a, = _businesses("ALPHA")
        cls.cust = Customer.objects.create(user=cls.a, customer_name="KMR",
                                           customer_phone="9876511111", is_mobile_user=True)
        cls.book = Book.objects.create(user=cls.a, customer=cls.cust, current_balance=0)
        cls.staff = _employee(cls.a, "RIZWAN", phone="9876522222")
        cls.boss = _employee(cls.a, "GANESH", phone="9876533333")
        cls.boss.postings.filter(is_home=True).update(is_admin=True)
        # Every one of them is whoever holds their number, with a live login.
        cls.party, cls.staff_user, cls.boss_user = (_live_person(r) for r in
                                                    (cls.cust, cls.staff, cls.boss))
        cls.c_ext = cls.party.external_id
        cls.s_ext, cls.b_ext = cls.staff_user.external_id, cls.boss_user.external_id

    def setUp(self):
        from .syncup_messages import set_events
        _syncup_on(messages_enabled=True)
        set_events(self.a, self.ALL)
        self.today = timezone.localdate()
        self.clock = mock.patch("gstbillingapp.syncup_messages._now",
                                return_value=_local(self.today, 12)).start()
        self.bulk = mock.patch("gstbillingapp.syncup_client.notify_bulk", side_effect=lambda msgs, timeout=None: [
            {"external_id": m["external_id"], "delivered": 1} for m in msgs]).start()
        self.action = mock.patch("gstbillingapp.syncup_client.create_action", return_value={
            "success": True, "request_id": "req-1", "delivered": 1}).start()
        self.addCleanup(mock.patch.stopall)

    # ---- helpers ----
    def _msgs(self, **kw):
        from .models import SyncUpMessage
        return list(SyncUpMessage.objects.filter(**kw).order_by("id"))

    def _bill(self, total=48900):
        with self.captureOnCommitCallbacks(execute=True):
            return Invoice.objects.create(
                user=self.a, invoice_number=7, invoice_date=self.today, invoice_customer=self.cust,
                invoice_json=json.dumps({"invoice_total_amt_with_gst": total}))

    def _log(self, change, change_type=0, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return BookLog.objects.create(parent_book=self.book, change_type=change_type,
                                          change=change, **kw)

    def _as(self, emp):
        self.client.get("/m/employee/", {"t": _app_token(emp)})

    def _staff_pays(self, amount=400):
        self._as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("m_employee_record_payment", args=[self.cust.id]),
                             data=json.dumps({"amount": amount}), content_type="application/json")
        return BookLog.objects.get(parent_book=self.book, change_type=0, is_active=False)

    def _act(self, log, action):
        self._as(self.boss)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("m_employee_approval_act", args=[log.id]),
                                    data=json.dumps({"action": action}),
                                    content_type="application/json")

    # ---- switches and people ----
    def test_nothing_is_queued_until_switched_on(self):
        from .syncup_messages import set_events
        _syncup_on(messages_enabled=False)
        self._bill()
        self.assertEqual(self._msgs(), [])
        _syncup_on(messages_enabled=True)
        set_events(self.a, self.ALL - {"c_bill"})
        self._bill()
        self.assertEqual(self._msgs(), [])

    def test_a_bill_tells_the_customer_once(self):
        inv = self._bill()
        m, = self._msgs()
        self.assertEqual((m.event, m.external_id, m.title), ("c_bill", self.c_ext, "ALPHA · Bill #7"))
        self.assertIn("₹48,900", m.body)
        self.assertEqual(m.url, "https://gstsync.test/m/customer/invoice/%d?acct=%d"
                         % (inv.id, self.cust.id))
        with self.captureOnCommitCallbacks(execute=True):
            inv.save()                                           # an edit doesn't notify again
        self.assertEqual(len(self._msgs()), 1)
        self.bulk.assert_not_called()                            # queued, not sent inline

    def test_a_row_not_shown_in_the_app_gets_nothing(self):
        Customer.objects.filter(pk=self.cust.pk).update(is_mobile_user=False)
        self.cust.refresh_from_db()
        self._bill()
        self.assertEqual(self._msgs(), [])

    def test_a_desktop_payment_tells_the_customer_the_new_balance(self):
        self._log(-1000, change_type=1)
        self._log(400)
        m, = self._msgs()
        self.assertEqual(m.title, "ALPHA · Payment received ₹400")
        self.assertEqual(m.body, "Balance: ₹600 due")
        self.assertTrue(m.url.endswith("/m/customer/books?acct=%d" % self.cust.id))

    # ---- approvals ----
    def test_staff_payment_asks_only_admins_straight_away(self):
        self._staff_pays(400)
        m, = self._msgs(event="a_approval")
        self.assertEqual((m.external_id, m.kind), (self.b_ext, "notify"))
        self.assertEqual(m.title, "Approve ₹400 from KMR?")
        self.assertIn("recorded by RIZWAN", m.body)
        self.bulk.assert_called_once()                            # the immediate try
        self.assertEqual(self.bulk.call_args.kwargs["timeout"], 2)
        self.assertIsNotNone(self._msgs(event="a_approval")[0].sent_at)

    def test_approving_tells_the_customer_and_the_employee(self):
        log = self._staff_pays(400)
        self.assertTrue(self._act(log, "approve").json()["approved"])
        self.assertEqual([(m.event, m.external_id) for m in self._msgs(event__in=["c_payment", "e_payment"])],
                         [("c_payment", self.c_ext), ("e_payment", self.s_ext)])
        self.assertEqual(self._msgs(event="e_payment")[0].title, "₹400 from KMR approved")

    def test_rejecting_tells_the_employee(self):
        log = self._staff_pays(400)
        self.assertTrue(self._act(log, "reject").json()["rejected"])
        m, = self._msgs(event="e_payment")
        self.assertEqual((m.external_id, m.title), (self.s_ext, "₹400 from KMR rejected"))
        self.assertEqual(self._msgs(event="c_payment"), [])

    def test_approve_buttons_go_out_as_a_prompt(self):
        from .syncup_messages import set_events
        set_events(self.a, self.ALL | {"a_approval_prompt"})
        self._staff_pays(400)
        m, = self._msgs(event="a_approval")
        self.assertEqual((m.kind, m.request_id), ("approve", "req-1"))
        ext, payload = self.action.call_args.args
        self.assertEqual(ext, self.b_ext)
        self.assertEqual((payload["type"], payload["callback_url"], payload["ttl_seconds"]),
                         ("approve", "https://gstsync.test/syncup/callback", 3600))

    def _prompted(self):
        from .syncup_messages import set_events
        set_events(self.a, self.ALL | {"a_approval_prompt"})
        _syncup_on(messages_enabled=True, signing_secret="s3cret")
        return self._staff_pays(400)

    def _callback(self, value, secret="s3cret", request_id="req-1"):
        import hashlib
        import hmac
        body = json.dumps({"request_id": request_id, "type": "approve", "status": "completed",
                           "value": value, "user": {"id": "9", "external_id": self.b_ext},
                           "approved": value == "approved"}).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/syncup/callback", data=body, content_type="application/json",
                                    HTTP_X_SYNCUP_SIGNATURE=sig)

    def test_approve_from_the_notification(self):
        log = self._prompted()
        r = self._callback("approved")
        self.assertEqual(r.json()["result"], "approved")
        log.refresh_from_db()
        self.assertTrue(log.is_active)
        self.book.refresh_from_db()
        self.assertAlmostEqual(self.book.current_balance, 400)
        self.assertEqual(len(self._msgs(event="e_payment")), 1)
        self.assertEqual(self._callback("rejected").json()["result"], "ignored")   # replay
        self.assertTrue(BookLog.objects.filter(pk=log.pk, is_active=True).exists())

    def test_reject_from_the_notification(self):
        log = self._prompted()
        self.assertEqual(self._callback("rejected").json()["result"], "rejected")
        self.assertFalse(BookLog.objects.filter(pk=log.pk).exists())

    def test_a_forged_or_unconfigured_callback_is_refused(self):
        log = self._prompted()
        self.assertEqual(self._callback("approved", secret="guess").status_code, 403)
        _syncup_on(signing_secret="")
        self.assertEqual(self._callback("approved").status_code, 404)
        log.refresh_from_db()
        self.assertFalse(log.is_active)

    def test_someone_no_longer_admin_cannot_decide(self):
        log = self._prompted()
        self.boss.postings.update(is_admin=False)
        self.assertEqual(self._callback("approved").json()["result"], "not an admin any more")
        log.refresh_from_db()
        self.assertFalse(log.is_active)                           # still in Approvals

    def test_the_cron_picks_up_an_answer_whose_callback_was_lost(self):
        from .syncup_messages import reconcile
        log = self._prompted()
        with mock.patch("gstbillingapp.syncup_client.action_status",
                        return_value={"status": "completed", "value": "approved"}):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(reconcile(), 1)
        log.refresh_from_db()
        self.assertTrue(log.is_active)

    def test_a_payment_handled_in_the_app_skips_the_prompt(self):
        from .syncup_messages import flush
        from .syncup_client import SyncUpError
        from .models import SyncUpMessage
        self.action.side_effect = SyncUpError("down")             # the quick try fails
        log = self._prompted()
        self._act(log, "approve")
        self.action.reset_mock()
        flush()
        self.action.assert_not_called()
        self.assertEqual(SyncUpMessage.objects.get(event="a_approval").answer, "moot")

    # ---- orders ----
    def test_app_orders_tell_admins_then_the_customer(self):
        from .models import Quotation
        with self.captureOnCommitCallbacks(execute=True):
            q = Quotation.objects.create(user=self.a, quotation_number=812, quotation_date=self.today,
                                         quotation_customer=self.cust, created_from_cart=True,
                                         quotation_json=json.dumps({"invoice_total_amt_with_gst": 28440}),
                                         status="DRAFT")
        self.assertEqual(self._msgs(), [])
        with self.captureOnCommitCallbacks(execute=True):
            q.status = "PENDING"
            q.save(update_fields=["status"])
        m, = self._msgs(event="a_order")
        self.assertEqual((m.external_id, m.title), (self.b_ext, "New order from KMR · ₹28,440"))
        with self.captureOnCommitCallbacks(execute=True):
            q.status = "APPROVED"
            q.save()
        m, = self._msgs(event="c_order")
        self.assertEqual((m.external_id, m.title), (self.c_ext, "ALPHA · Order QT-812 approved"))

    # ---- sending ----
    def test_nothing_goes_out_at_night(self):
        from .syncup_messages import flush
        self.clock.return_value = _local(self.today, 22, 30)
        self._bill()
        m, = self._msgs()
        self.assertEqual(timezone.localtime(m.send_after),
                         _local(self.today + timedelta(days=1), 8))
        self.assertEqual(flush()["sent"], 0)
        self.bulk.assert_not_called()
        self.clock.return_value = _local(self.today + timedelta(days=1), 8, 5)
        self.assertEqual(flush()["sent"], 1)

    def test_the_queue_goes_25_per_call_and_keeps_what_failed(self):
        from .syncup_messages import MAX_ATTEMPTS, flush, queue
        from .syncup_client import SyncUpError
        for i in range(30):
            queue(business=self.a, event="c_bill", external_id="party-%d" % i, title="t",
                  dedupe="t:%d" % i)
        self.bulk.side_effect = lambda msgs, timeout=None: (
            [{"error": "User not found"}] + [{"delivered": 1}] * (len(msgs) - 1))
        self.assertEqual(flush(), {"sent": 28, "failed": 2})
        self.assertEqual([len(c.args[0]) for c in self.bulk.call_args_list], [25, 5])

        queue(business=self.a, event="c_bill", external_id=self.c_ext, title="t", dedupe="late")
        self.bulk.side_effect = SyncUpError("SyncUp is unreachable")
        for _ in range(MAX_ATTEMPTS - 1):
            flush()
        m, = self._msgs(dedupe_key="late")
        self.assertEqual((m.attempts, m.failed, m.sent_at), (MAX_ATTEMPTS - 1, False, None))
        flush()
        self.assertTrue(self._msgs(dedupe_key="late")[0].failed)

    # ---- schedules ----
    def _owing(self, amount=1000, billed=None):
        from .models import Book
        billed = billed or self.today - timedelta(days=40)
        with self.captureOnCommitCallbacks(execute=True):
            BookLog.objects.create(parent_book=self.book, change_type=1, change=-amount,
                                   date=_local(billed, 11))
        Book.objects.filter(pk=self.book.pk).update(current_balance=-amount)

    def test_monday_morning_lists_and_overdue_reminders_run_once(self):
        from .syncup_messages import run_schedules
        monday = self.today - timedelta(days=self.today.weekday())
        Customer.objects.filter(pk=self.cust.pk).update(collection_day=1)   # Monday
        self._owing(billed=monday - timedelta(days=40))
        out = run_schedules(_local(monday, 10, 30))
        self.assertEqual((out["morning"], out["overdue"]), (2, 1))
        self.assertEqual(sorted(m.external_id for m in self._msgs(event="e_morning")),
                         sorted([self.s_ext, self.b_ext]))
        self.assertEqual(self._msgs(event="e_morning")[0].title, "Today at ALPHA: 1 to collect")
        m, = self._msgs(event="c_overdue")
        self.assertEqual((m.external_id, m.title), (self.c_ext, "₹1,000 due at ALPHA"))
        self.assertIn("40 days", m.body)
        self.assertEqual(run_schedules(_local(monday, 11)), {})             # once per period

    def test_the_evening_summary_goes_to_admins(self):
        from .syncup_messages import run_schedules
        self._log(250)
        out = run_schedules(_local(self.today, 19, 30))
        self.assertEqual(out["evening"], 1)
        m, = self._msgs(event="a_evening")
        self.assertEqual(m.external_id, self.b_ext)
        self.assertIn("collected ₹250", m.body)

    def test_the_tile_shows_whats_due_and_only_changes_when_it_does(self):
        from .syncup_messages import refresh_tiles, run_schedules
        from .models import AppUser
        _syncup_on(messages_enabled=True, tile_due=True)
        self._owing(1000)
        with mock.patch("gstbillingapp.syncup_client.update_app_link") as tile:
            self.assertEqual(run_schedules(_local(self.today, 7, 30))["tiles"], 1)
            self.assertEqual(tile.call_args.kwargs["description"], "₹1,000 due")
            self.assertEqual(refresh_tiles(), 0)                 # unchanged: no call
            self.assertEqual(tile.call_count, 1)
            _syncup_on(tile_due=False)
            run_schedules(_local(self.today, 13))
            self.assertEqual(tile.call_args.kwargs["description"], "")
        self.assertEqual(AppUser.objects.get(pk=self.party.pk).tile_text, "")

    # ---- balance confirmation ----
    def test_balance_confirmation_is_asked_and_answered(self):
        from .models import BalanceConfirmation
        from .syncup_messages import request_balance_confirmations
        self._owing(1000)
        self.assertEqual(request_balance_confirmations(self.a, self.today), 1)
        bc = BalanceConfirmation.objects.get()
        self.assertEqual(bc.balance, -1000)
        m, = self._msgs(event="c_confirm")
        self.assertTrue(m.url.endswith("/m/customer/confirm/%d?acct=%d" % (bc.id, self.cust.id)))
        self.client.get("/m/customer/", {"t": _app_token(self.party)})
        url = reverse("m_customer_confirm", args=[bc.id]) + "?acct=%d" % self.cust.id
        self.assertContains(self.client.get(url), "I confirm this balance")
        self.assertContains(self.client.post(url), "You confirmed this balance")
        bc.refresh_from_db()
        self.assertIsNotNone(bc.confirmed_at)

    def test_a_confirmation_is_only_open_to_its_customer(self):
        from .models import BalanceConfirmation
        bc = BalanceConfirmation.objects.create(customer=self.cust, balance=-5, as_of=self.today)
        other = Customer.objects.create(user=self.a, customer_name="OTHER",
                                        customer_phone="9876500071", is_mobile_user=True)
        self.client.get("/m/customer/", {"t": _app_token(other)})
        self.assertEqual(self.client.get(reverse("m_customer_confirm", args=[bc.id])).status_code, 404)

    # ---- cron and console ----
    @override_settings(CRON_KEY="k")
    def test_the_cron_sends_the_queue(self):
        self._bill()
        with mock.patch("gstbillingapp.syncup_client.set_account_active"):   # login catch-up
            body = self.client.get("/cron/syncup", {"key": "k"}).json()
        self.assertEqual(body["messages"]["sent"], 1)
        self.bulk.assert_called_once()


class ConsoleMessageScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="msgop", full_name="Msg Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()
        cls.a, = _businesses("ALPHA")

    def setUp(self):
        self.client.post(reverse("console_login"), {"username": "msgop", "password": "Cons0le!pass9"})

    def test_settings_hold_the_switches_and_a_write_only_secret(self):
        from .models import SyncUpSettings
        _syncup_on()
        form = {"api_base": "https://syncup.test", "link_base": "https://gstsync.test",
                "timeout": "5", "messages_enabled": "1",
                "tile_due": "1", "signing_secret": "s3cret-value"}
        self.client.post(reverse("console_syncup"), form)
        cfg = SyncUpSettings.load()
        self.assertEqual((cfg.messages_enabled, cfg.tile_due, cfg.signing_secret),
                         (True, True, "s3cret-value"))
        page = self.client.get(reverse("console_syncup"))
        self.assertNotContains(page, "s3cret-value")
        self.assertContains(page, "https://gstsync.test/syncup/callback")
        self.client.post(reverse("console_syncup"), dict(form, signing_secret=""))
        self.assertEqual(SyncUpSettings.load().signing_secret, "s3cret-value")   # blank keeps it

    def test_business_page_switches_each_message(self):
        from .syncup_messages import events_for
        page = self.client.get(reverse("console_business_detail", args=[self.a.id]))
        self.assertContains(page, "SyncUp messages")
        self.assertContains(page, "Send SyncUp messages")                        # not ready yet
        self.client.post(reverse("console_business_messages", args=[self.a.id]),
                         {"events": ["c_bill", "a_approval_prompt", "nonsense"]})
        self.assertEqual(events_for(self.a), {"c_bill", "a_approval", "a_approval_prompt"})

    def test_balance_confirmation_needs_messages_on(self):
        r = self.client.post(reverse("console_business_confirm_balances", args=[self.a.id]),
                             {"as_of": timezone.localdate().isoformat()}, follow=True)
        self.assertContains(r, "Turn on SyncUp messages")


class TelegramReportTests(TestCase):
    """Telegram reports: the console decides whether a business may send and to which groups;
    the business decides which reports and when, on each report's own page."""

    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = _businesses("ALPHA", "BETA")
        cls.cust = Customer.objects.create(user=cls.a, customer_name="KMR",
                                           customer_phone="9876543210", collection_day=1,
                                           customer_place="SALEM")
        cls.book = Book.objects.create(user=cls.a, customer=cls.cust, current_balance=-1000)

    def setUp(self):
        from .models import BusinessTelegram, TelegramChat
        _syncup_on(telegram_enabled=True)
        BusinessTelegram.objects.update_or_create(user=self.a, defaults={"enabled": True})
        self.chat = TelegramChat.objects.create(business=self.a, chat_id="-1001234567890",
                                                label="Owner group")
        self.bulk = mock.patch("gstbillingapp.syncup_client.telegram_bulk", side_effect=lambda msgs, timeout=None: [
            {"chat_id": m["chat_id"], "message_id": "11"} for m in msgs]).start()
        self.one = mock.patch("gstbillingapp.syncup_client.telegram_send",
                              return_value={"success": True, "message_id": "11"}).start()
        self.addCleanup(mock.patch.stopall)

    # ---- helpers ----
    def _owing(self, days_old=100, amount=1000):
        when = timezone.now() - timedelta(days=days_old)
        BookLog.objects.create(parent_book=self.book, change_type=1, change=-amount, date=when)

    def _login(self, user=None):
        self.client.force_login(user or self.a)

    def _console(self):
        from .models import PlatformAdmin
        admin = PlatformAdmin(username="tgop", full_name="TG Op")
        admin.set_password("Cons0le!pass9")
        admin.save()
        self.client.post(reverse("console_login"), {"username": "tgop",
                                                    "password": "Cons0le!pass9"})
        return admin

    def _settings(self, report="overdue"):
        return self.client.get(reverse("telegram_report_settings", args=[report])).json()

    def _save(self, rows, report="overdue"):
        return self.client.post(reverse("telegram_report_settings", args=[report]),
                                data=json.dumps({"rows": rows}), content_type="application/json")

    def _msgs(self, event=None):
        """This report's queued messages. Signing in queues a login alert of its own
        (telegram_alerts), which is not what these tests are about."""
        from .models import SyncUpMessage
        qs = SyncUpMessage.objects.filter(kind="telegram").exclude(event="login")
        return list(qs.filter(event=event) if event else qs.order_by("id"))

    # ---- the reports themselves ----
    def test_the_reports_read_like_the_ones_the_group_already_gets(self):
        from .telegram_reports import build
        self._owing()
        text, count = build("overdue", self.a, {"days": 90})
        self.assertEqual(count, 1)
        for bit in ("📋  *OVERDUE REPORT*", "🏢  *ALPHA CO*", "KMR", "9876543210",
                    "⚠️  Overdue Customers: *1*", "SyncUp"):
            self.assertIn(bit, text)

        text, count = build("collection", self.a, {})
        self.assertIn("COLLECTION ROUTE", text)
        # Only counts today's route — the customer collects on Mondays.
        self.assertEqual(count, 1 if timezone.localdate().weekday() == 0 else 0)

        from .models import ChequeLeaf
        ChequeLeaf.objects.create(user=self.a, cheque_number="000123", bank="HDFC",
                                  payee_name="RAJ", amount=5000, status="ISSUED",
                                  clearance_date=timezone.localdate() + timedelta(days=1))
        text, count = build("cheque", self.a, {})
        self.assertEqual(count, 1)
        self.assertIn("Cheque Clearance Reminder", text)
        self.assertIn("000123", text)

    def test_a_long_report_is_split_not_lost(self):
        from .telegram_reports import MAX_TEXT, split_parts
        parts = split_parts("\n".join("line %d" % i for i in range(3000)))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= MAX_TEXT + 40 for p in parts))
        self.assertIn("_Part 1 of %d_" % len(parts), parts[0])

    # ---- the popup ----
    def test_the_popup_says_when_telegram_is_not_set_up(self):
        from .models import BusinessTelegram
        self._login(self.b)                                    # no chat ids, not enabled
        state = self._settings()
        self.assertFalse(state["available"])
        self.assertIn("isn't switched on", state["reason"])
        BusinessTelegram.objects.update_or_create(user=self.b, defaults={"enabled": True})
        self.assertIn("No Telegram group", self._settings()["reason"])
        self._login()
        self.assertTrue(self._settings()["available"])

    def test_saving_times_and_groups(self):
        from .models import TelegramReport
        self._login()
        r = self._save([{"enabled": True, "send_at": "09:00", "days": 90, "chats": [self.chat.id]},
                        {"enabled": True, "send_at": "09:05", "days": 120, "chats": [self.chat.id]}])
        self.assertEqual(r.status_code, 200)
        rows = TelegramReport.objects.filter(business=self.a, report="overdue")
        self.assertEqual([(str(x.send_at)[:5], x.days) for x in rows.order_by("send_at")],
                         [("09:00", 90), ("09:05", 120)])
        self.assertEqual([c.id for c in rows.first().chats.all()], [self.chat.id])
        # Saving fewer rows removes the extra one.
        self._save([{"enabled": False, "send_at": "10:30", "days": 90, "chats": []}])
        self.assertEqual(rows.count(), 1)

    def test_a_bad_time_or_another_business_chat_is_refused(self):
        from .models import TelegramChat, TelegramReport
        theirs = TelegramChat.objects.create(business=self.b, chat_id="-100999", label="Theirs")
        self._login()
        r = self._save([{"enabled": True, "send_at": "nine", "days": 90, "chats": []}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("HH:MM", r.json()["message"])
        self._save([{"enabled": True, "send_at": "09:00", "days": 90, "chats": [theirs.id]}])
        row = TelegramReport.objects.get(business=self.a)
        self.assertEqual(list(row.chats.all()), [])            # not ours to send to
        self.assertEqual(self._save([{"enabled": True, "send_at": "09:00", "days": 7,
                                      "chats": []}]).status_code, 400)

    def test_the_popup_is_only_the_signed_in_business(self):
        url = reverse("telegram_report_settings", args=["overdue"])
        self.assertIn("/login", self.client.get(url)["Location"])
        self._login()
        self.assertEqual(self.client.get(reverse("telegram_report_settings",
                                                 args=["nonsense"])).status_code, 404)

    def test_send_now_posts_the_report(self):
        self._owing()
        self._login()
        r = self.client.post(reverse("telegram_report_send", args=["overdue"]),
                             data=json.dumps({"days": 90, "chats": [self.chat.id]}),
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.bulk.assert_called_once()
        sent = self.bulk.call_args.args[0]
        self.assertEqual(sent[0]["chat_id"], "-1001234567890")
        self.assertEqual(sent[0]["parse_mode"], "MarkdownV2")
        self.assertIn("OVERDUE REPORT", sent[0]["text"])
        self.assertIsNotNone(self._msgs()[0].sent_at)

    def test_each_row_sends_its_own_days(self):
        """Two rows of one report (90 and 120 days) each send THEIR report — pressing Send
        now on the second must not re-send the first."""
        self._owing(days_old=100)                    # overdue by 100 days: in 90, not in 120
        self._login()
        url = reverse("telegram_report_send", args=["overdue"])
        for days, customers in ((90, 1), (120, 0)):
            r = self.client.post(url, data=json.dumps({"days": days, "chats": [self.chat.id]}),
                                 content_type="application/json")
            self.assertTrue(r.json()["ok"])
            self.assertIn("(%d days)" % days, r.json()["message"])
            self.assertIn("%d customer" % customers, r.json()["message"])
        self.assertEqual(self.bulk.call_count, 2)
        first, second = [c.args[0][0]["text"] for c in self.bulk.call_args_list]
        self.assertIn("⏳ 90 Days", first)
        self.assertIn("KMR", first)
        self.assertIn("⏳ 120 Days", second)          # the second row really sent 120
        self.assertIn("No overdue customers", second)

    def test_two_manual_sends_in_the_same_second_both_go(self):
        from .models import SyncUpMessage
        self._owing()
        self._login()
        url = reverse("telegram_report_send", args=["overdue"])
        for days in (90, 120):
            self.client.post(url, data=json.dumps({"days": days, "chats": [self.chat.id]}),
                             content_type="application/json")
        self.assertEqual(SyncUpMessage.objects.filter(event="overdue").count(), 2)

    # ---- the schedule ----
    def _schedule(self, at="09:00", report="overdue", days=90):
        from .models import TelegramReport
        row = TelegramReport.objects.create(business=self.a, report=report,
                                            send_at=datetime.time(*[int(x) for x in at.split(":")]),
                                            params={"days": days} if days else {})
        row.chats.set([self.chat])
        return row

    def test_it_goes_once_at_the_time_that_was_set(self):
        from .telegram_reports import run_due
        self._owing()
        row = self._schedule("09:00")
        today = timezone.localdate()
        self.assertEqual(run_due(_local(today, 8, 50)), 0)          # not yet
        self.assertEqual(run_due(_local(today, 9, 5)), 1)           # first run after 9:00
        self.assertEqual(run_due(_local(today, 9, 15)), 0)          # and only once
        row.refresh_from_db()
        self.assertEqual(row.last_sent_on, today)
        self.assertIn("Queued", row.last_status)
        m, = self._msgs()
        self.assertEqual((m.external_id, m.event), ("-1001234567890", "overdue"))
        self.assertIn("OVERDUE REPORT", m.text)

    def test_a_missed_report_waits_for_tomorrow_rather_than_arriving_late(self):
        from .telegram_reports import run_due
        self._owing()
        self._schedule("03:00")
        self.assertEqual(run_due(_local(timezone.localdate(), 9, 0)), 0)
        self.assertEqual(self._msgs(), [])

    def test_an_empty_report_is_not_sent(self):
        from .telegram_reports import run_due
        row = self._schedule("09:00")                               # nothing overdue at all
        self.assertEqual(run_due(_local(timezone.localdate(), 9, 5)), 0)
        row.refresh_from_db()
        self.assertEqual(row.last_status, "Nothing to report")

    def test_nothing_goes_out_while_a_switch_is_off(self):
        from .models import BusinessTelegram, TelegramChat
        from .telegram_reports import run_due
        self._owing()
        self._schedule("09:00")
        at = _local(timezone.localdate(), 9, 5)
        _syncup_on(telegram_enabled=False)                          # the platform switch
        self.assertEqual(run_due(at), 0)
        _syncup_on(telegram_enabled=True)
        BusinessTelegram.objects.filter(user=self.a).update(enabled=False)   # the business switch
        self.assertEqual(run_due(at), 0)
        BusinessTelegram.objects.filter(user=self.a).update(enabled=True)
        TelegramChat.objects.filter(pk=self.chat.pk).update(is_active=False)  # the chat id
        self.assertEqual(run_due(at), 0)
        self.assertEqual(self._msgs(), [])

    def test_the_cron_sends_what_is_due(self):
        from .models import TelegramChat
        self._owing()
        self._schedule("00:01")                 # already due, but only within the catch-up window
        from .telegram_reports import CATCH_UP
        with override_settings(CRON_KEY="k"), \
             mock.patch("gstbillingapp.telegram_reports.CATCH_UP", timedelta(days=1)), \
             mock.patch("gstbillingapp.syncup_client.set_account_active"):
            body = self.client.get("/cron/syncup", {"key": "k"}).json()
        self.assertEqual(body["telegram"], 1)
        self.assertEqual(body["messages"]["sent"], 1)
        self.bulk.assert_called_once()
        self.assertIsNotNone(TelegramChat.objects.get(pk=self.chat.pk).last_ok_at)

    def test_a_chat_telegram_refuses_is_not_retried(self):
        from .models import SyncUpMessage, TelegramChat
        from .telegram_reports import queue_report
        from .syncup_messages import flush
        self._owing()
        self.bulk.side_effect = lambda msgs, timeout=None: [
            {"chat_id": m["chat_id"], "error": "chat not found"} for m in msgs]
        queue_report(self.a, "overdue", {"days": 90}, [self.chat])
        flush()
        m = SyncUpMessage.objects.get(event="overdue")
        self.assertTrue(m.failed)
        self.assertIn("chat not found", TelegramChat.objects.get(pk=self.chat.pk).last_error)
        self.bulk.reset_mock()
        flush()
        self.bulk.assert_not_called()

    def test_reports_ignore_the_quiet_hours(self):
        from .telegram_reports import queue_report
        with mock.patch("gstbillingapp.syncup_messages._now",
                        return_value=_local(timezone.localdate(), 22, 30)):
            self._owing()
            queue_report(self.a, "overdue", {"days": 90}, [self.chat])
        m, = self._msgs()
        self.assertEqual(timezone.localtime(m.send_after).hour, 22)

    # ---- the console side ----
    def test_console_adds_checks_and_tests_a_chat_id(self):
        from .models import TelegramChat
        self._console()
        url = reverse("console_business_telegram_chat_add", args=[self.b.id])
        self.client.post(url, {"chat_id": "not-an-id", "label": "Nope"})
        self.assertFalse(TelegramChat.objects.filter(business=self.b).exists())
        self.client.post(url, {"chat_id": "-1009876543210", "label": "Beta group"})
        chat = TelegramChat.objects.get(business=self.b)
        self.assertEqual(chat.label, "Beta group")
        r = self.client.post(url, {"chat_id": "-1009876543210"}, follow=True)
        self.assertContains(r, "already on this business")
        self.client.post(reverse("console_business_telegram_chat_test",
                                 args=[self.b.id, chat.id]))
        self.one.assert_called_once()
        chat.refresh_from_db()
        self.assertIsNotNone(chat.last_ok_at)

    def test_console_switch_and_removal(self):
        from .models import TelegramChat
        from .telegram_reports import business_enabled
        self._console()
        self.client.post(reverse("console_business_telegram", args=[self.b.id]))
        self.assertTrue(business_enabled(self.b))
        self.client.post(reverse("console_business_telegram", args=[self.b.id]))
        self.assertFalse(business_enabled(self.b))
        self.client.post(reverse("console_business_telegram_chat_delete",
                                 args=[self.a.id, self.chat.id]))
        self.assertFalse(TelegramChat.objects.filter(pk=self.chat.pk).exists())

    def test_the_console_needs_a_console_login(self):
        r = self.client.post(reverse("console_business_telegram", args=[self.a.id]))
        self.assertIn("/console/login", r["Location"])

    def test_the_business_page_shows_what_is_scheduled(self):
        self._schedule("09:00")
        self._console()
        page = self.client.get(reverse("console_business_detail", args=[self.a.id]))
        self.assertContains(page, "Telegram reports")
        self.assertContains(page, "Owner group")
        self.assertContains(page, "Overdue report")

    def test_the_button_is_on_all_three_report_pages(self):
        self._login()
        for name in ("overdue_report", "cheque_leafs", "customers_collection_calendar"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, 'onclick="tgOpen()"', msg_prefix=name)
            self.assertContains(r, "/telegram/report/", msg_prefix=name)

    # ---- re-using one group across an owner's businesses ----
    def test_a_group_can_be_picked_instead_of_typed_again(self):
        from .models import TelegramChat
        from .views.console import reusable_chats
        self._console()
        # BETA has none of its own yet, so ALPHA's group is on offer…
        offered = reusable_chats(self.b)
        self.assertEqual([(r["chat_id"], r["label"]) for r in offered],
                         [(self.chat.chat_id, "Owner group")])
        self.assertIn("ALPHA", offered[0]["used_by"])
        self.client.post(reverse("console_business_telegram_chat_reuse", args=[self.b.id]),
                         {"chat_id": self.chat.chat_id})
        copy = TelegramChat.objects.get(business=self.b)
        self.assertEqual((copy.chat_id, copy.label), (self.chat.chat_id, "Owner group"))
        # …and once taken it is no longer offered to BETA.
        self.assertEqual(reusable_chats(self.b), [])

    def test_the_copy_lives_its_own_life(self):
        from .models import TelegramChat
        self._console()
        self.client.post(reverse("console_business_telegram_chat_reuse", args=[self.b.id]),
                         {"chat_id": self.chat.chat_id, "label": "Shared with BETA"})
        copy = TelegramChat.objects.get(business=self.b)
        self.assertEqual(copy.label, "Shared with BETA")        # its own label
        self.client.post(reverse("console_business_telegram_chat_toggle",
                                 args=[self.b.id, copy.id]))
        self.chat.refresh_from_db()
        self.assertTrue(self.chat.is_active)                    # ALPHA's is untouched
        self.client.post(reverse("console_business_telegram_chat_delete",
                                 args=[self.a.id, self.chat.id]))
        self.assertTrue(TelegramChat.objects.filter(pk=copy.pk).exists())

    def test_only_a_group_we_already_hold_can_be_picked(self):
        from .models import TelegramChat
        self._console()
        r = self.client.post(reverse("console_business_telegram_chat_reuse", args=[self.b.id]),
                             {"chat_id": "-100555000"}, follow=True)
        self.assertContains(r, "Pick one of the groups we already have")
        self.assertFalse(TelegramChat.objects.filter(business=self.b).exists())
        self.client.post(reverse("console_business_telegram_chat_reuse", args=[self.b.id]),
                         {"chat_id": self.chat.chat_id})
        again = self.client.post(reverse("console_business_telegram_chat_reuse",
                                         args=[self.b.id]),
                                 {"chat_id": self.chat.chat_id}, follow=True)
        self.assertContains(again, "already on this business")
        self.assertEqual(TelegramChat.objects.filter(business=self.b).count(), 1)

    def test_a_shared_group_can_tell_the_businesses_apart(self):
        from .telegram_reports import build
        text, _ = build("collection", self.a, {})
        self.assertIn("COLLECTION ROUTE", text)
        self.assertIn("ALPHA", text)                            # whose route this is

    # ---- what the old SyncUp job used ----
    def test_the_open_report_endpoints_are_gone(self):
        for url in ("/api/reports/overdue", "/api/cheque_leaf_reminder",
                    "/customers/api/collection-day/show?markdown=true&user_id=1"):
            self.assertEqual(self.client.get(url).status_code, 404, url)


class TelegramLoginAlertTests(TestCase):
    """The owner hears when their customer or employee opens the app — once per visit,
    only where it was asked for, and never in the way of the page itself."""

    @classmethod
    def setUpTestData(cls):
        from .models import AppUser
        cls.a, cls.b = _businesses("ALPHA", "BETA")
        # One number at both businesses — that is what makes them one person.
        cls.cust = Customer.objects.create(user=cls.a, customer_name="KMR", customer_place="SALEM",
                                           customer_phone="9876544444", is_mobile_user=True)
        cls.cust_b = Customer.objects.create(user=cls.b, customer_name="KMR TRADERS",
                                             customer_phone="9876544444", is_mobile_user=True)
        cls.emp = _employee(cls.a, "RIZWAN", phone="9876555555")
        cls.party, cls.emp_user = _live_person(cls.cust), _live_person(cls.emp)

    def setUp(self):
        from .models import BusinessTelegram, TelegramChat
        _syncup_on(telegram_enabled=True)
        self.bulk = self._relay(side_effect=lambda msgs, timeout=None, longer=True: [
            {"chat_id": m["chat_id"], "message_id": "7"} for m in msgs])
        self.addCleanup(mock.patch.stopall)
        for biz in (self.a, self.b):
            BusinessTelegram.objects.update_or_create(
                user=biz, defaults={"enabled": True, "login_alerts": True})
            TelegramChat.objects.create(business=biz, chat_id="-100%d" % biz.id,
                                        label="%s group" % biz.username)

    def _msgs(self):
        from .models import SyncUpMessage
        return list(SyncUpMessage.objects.filter(event="login").order_by("id"))

    @property
    def AppUser(self):
        from .models import AppUser
        return AppUser

    def _relay(self, **kwargs):
        """Stand in for SyncUp's relay — an alert tries to send the moment it is made."""
        return mock.patch("gstbillingapp.syncup_client.telegram_bulk", **kwargs).start()

    def _open_customer(self):
        return self.client.get("/m/customer/", {"t": _app_token(self.party)},
                               HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14) Chrome/128")

    def _open_employee(self):
        return self.client.get("/m/employee/", {"t": _app_token(self.emp)})

    def test_a_customer_opening_the_app_tells_every_business_they_can_see(self):
        self._open_customer()
        msgs = self._msgs()
        self.assertEqual(sorted(m.external_id for m in msgs), ["-100%d" % self.a.id,
                                                               "-100%d" % self.b.id])
        text = msgs[0].text
        for bit in ("Mobile Login", "KMR", "Customer", "1 Times", "Android · Chrome", "SyncUp"):
            self.assertIn(bit, text)
        self.assertEqual(self.AppUser.objects.get(pk=self.party.pk).app_opens, 1)
        self.assertIsNotNone(self.AppUser.objects.get(pk=self.party.pk).last_open_at)

    def test_an_employee_opening_the_app_tells_their_business(self):
        from .models import AppUser
        self._open_employee()
        m, = self._msgs()
        self.assertEqual(m.external_id, "-100%d" % self.a.id)
        self.assertIn("Employee", m.text)
        self.assertIn("RIZWAN", m.text)
        self.assertEqual(AppUser.objects.get(pk=self.emp_user.pk).app_opens, 1)

    def test_the_rest_of_the_visit_is_quiet(self):
        self._open_customer()
        self.client.get(reverse("m_customer_books"))
        self.client.get(reverse("m_customer_profile"))
        self.assertEqual(len(self._msgs()), 2)          # the two businesses, once each

    def test_opening_the_app_again_later_is_a_second_login(self):
        """9 am, close the app, open it again at 11 am — two alerts, because tapping the
        tile brings the link with it."""
        from .telegram_alerts import SESSION_KEY
        self._open_customer()
        session = self.client.session
        session[SESSION_KEY] = session[SESSION_KEY] - 2 * 3600      # two hours later
        session.save()
        self._open_customer()
        self.assertEqual(len(self._msgs()), 4)                      # two businesses, twice
        self.assertEqual(self.AppUser.objects.get(pk=self.party.pk).app_opens, 2)
        self.assertIn("2 Times", self._msgs()[-1].text)

    def test_a_double_tap_on_the_tile_is_one_login(self):
        self._open_customer()
        self._open_customer()
        self.assertEqual(len(self._msgs()), 2)

    def test_coming_back_later_is_a_new_login(self):
        from .telegram_alerts import SESSION_KEY, SESSION_GAP
        self._open_customer()
        session = self.client.session
        session[SESSION_KEY] = session[SESSION_KEY] - SESSION_GAP - 60
        session.save()
        self.client.get(reverse("m_customer_home"))
        self.assertEqual(len(self._msgs()), 4)
        self.assertEqual(self.AppUser.objects.get(pk=self.party.pk).app_opens, 2)
        self.assertIn("2 Times", self._msgs()[-1].text)

    def test_a_business_with_telegram_off_hears_nothing(self):
        from .models import BusinessTelegram
        BusinessTelegram.objects.all().update(enabled=False)
        self._open_customer()
        self.assertEqual(self._msgs(), [])
        self.client.cookies.clear()
        self._open_employee()
        self.assertEqual(self._msgs(), [])

    def test_login_notifications_must_be_allowed_on_the_console(self):
        from .models import BusinessTelegram
        BusinessTelegram.objects.all().update(login_alerts=False)   # Telegram still on
        self._open_customer()
        self.assertEqual(self._msgs(), [])

    def test_the_business_chooses_desktop_or_mobile(self):
        from .models import BusinessTelegram
        BusinessTelegram.objects.filter(user=self.a).update(notify_mobile=False)
        self._open_customer()
        self.assertEqual([m.external_id for m in self._msgs()], ["-100%d" % self.b.id])
        BusinessTelegram.objects.filter(user=self.a).update(notify_desktop=False)
        self.a.set_password("Xx!998877aa")
        self.a.save()
        self.client.post(reverse("login_view"), {"username": self.a.username,
                                                 "password": "Xx!998877aa"})
        self.assertEqual(len(self._msgs()), 1)                      # still just BETA's

    def test_the_business_chooses_which_group_hears_it(self):
        from .models import BusinessTelegram, TelegramChat
        second = TelegramChat.objects.create(business=self.a, chat_id="-100999",
                                             label="Second group")
        row = BusinessTelegram.objects.get(user=self.a)
        row.alert_chats.set([second])
        self._open_customer()
        alpha = [m.external_id for m in self._msgs() if m.business_id == self.a.id]
        self.assertEqual(alpha, ["-100999"])

    def test_the_profile_page_shows_it_only_when_allowed(self):
        from .models import BusinessTelegram
        self.a.set_password("Xx!998877aa")
        self.a.save()
        self.client.force_login(self.a)
        page = self.client.get(reverse("user_profile"))
        self.assertContains(page, "Login notifications")
        from .models import TelegramChat
        mine = TelegramChat.objects.get(business=self.a)
        self.assertContains(page, mine.label)               # its own group, by name
        self.assertNotContains(page, mine.chat_id)          # never the raw id
        BusinessTelegram.objects.filter(user=self.a).update(login_alerts=False)
        self.assertNotContains(self.client.get(reverse("user_profile")),
                               "Login notifications")

    def test_the_business_saves_its_own_choice(self):
        from .models import BusinessTelegram, TelegramChat
        second = TelegramChat.objects.create(business=self.a, chat_id="-100999", label="Second")
        theirs = TelegramChat.objects.create(business=self.b, chat_id="-100888", label="Theirs")
        self.client.force_login(self.a)
        self.client.post(reverse("telegram_login_alerts"),
                         {"mobile": "1", "chats": [str(second.id), str(theirs.id)]})
        row = BusinessTelegram.objects.get(user=self.a)
        self.assertEqual((row.notify_desktop, row.notify_mobile), (False, True))
        # Another business's group is not theirs to pick.
        self.assertEqual([c.id for c in row.alert_chats.all()], [second.id])

    def test_ticking_every_group_keeps_following_the_list(self):
        from .models import BusinessTelegram, TelegramChat
        self.client.force_login(self.a)
        mine = TelegramChat.objects.filter(business=self.a)
        self.client.post(reverse("telegram_login_alerts"),
                         {"mobile": "1", "desktop": "1",
                          "chats": [str(c.id) for c in mine]})
        row = BusinessTelegram.objects.get(user=self.a)
        self.assertEqual(list(row.alert_chats.all()), [])       # "all" is stored as none…
        later = TelegramChat.objects.create(business=self.a, chat_id="-100777", label="Later")
        self.client.cookies.clear()
        self._open_customer()
        self.assertIn(later.chat_id, [m.external_id for m in self._msgs()])   # …so a new one counts

    def test_a_business_cannot_save_what_was_never_allowed(self):
        from .models import BusinessTelegram
        BusinessTelegram.objects.filter(user=self.a).update(login_alerts=False)
        self.client.force_login(self.a)
        r = self.client.post(reverse("telegram_login_alerts"), {"desktop": "1"})
        self.assertEqual(r.status_code, 400)

    def test_the_owner_signing_in_on_the_desktop_is_announced(self):
        self.a.set_password("Xx!998877aa")
        self.a.save()
        r = self.client.post(reverse("login_view"),
                             {"username": self.a.username, "password": "Xx!998877aa"},
                             HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/128")
        self.assertIn(r.status_code, (200, 302))
        msgs = self._msgs()
        self.assertEqual([m.external_id for m in msgs], ["-100%d" % self.a.id])
        for bit in ("Desktop Login", "ALPHA", "Owner", "Windows · Chrome"):
            self.assertIn(bit, msgs[0].text)
        self.assertNotIn("Times", msgs[0].text)         # no count for the owner

    def test_a_passkey_sign_in_is_announced_too(self):
        from django.core.cache import cache
        from .passkeys import set_passkey
        # The wrong-passkey limiter is per device and lives in the cache, which the test
        # client shares across tests — start this one with a clean slate.
        cache.clear()
        set_passkey(self.a, "R8T3W")
        r = self.client.post(reverse("passkey_auth"), data=json.dumps({"passkey": "R8T3W"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([m.external_id for m in self._msgs()], ["-100%d" % self.a.id])

    def test_the_console_is_never_announced(self):
        from .models import PlatformAdmin
        admin = PlatformAdmin(username="quietop", full_name="Quiet Op")
        admin.set_password("Cons0le!pass9")
        admin.save()
        self.client.post(reverse("console_login"), {"username": "quietop",
                                                    "password": "Cons0le!pass9"})
        self.assertEqual(self._msgs(), [])

    def test_the_count_is_kept_even_when_nobody_is_listening(self):
        from .models import AppUser, BusinessTelegram
        BusinessTelegram.objects.all().update(enabled=False)
        self._open_customer()
        self.assertEqual(self._msgs(), [])
        self.assertEqual(self.AppUser.objects.get(pk=self.party.pk).app_opens, 1)

    def test_a_broken_alert_never_blocks_the_page(self):
        with mock.patch("gstbillingapp.telegram_alerts.note_app_open",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(self._open_customer().status_code, 302)
            self.assertEqual(self.client.get(reverse("m_customer_home")).status_code, 200)

    def test_it_goes_out_at_once_not_at_the_next_cron_run(self):
        from .models import SyncUpMessage
        from .telegram_alerts import INSTANT_TIMEOUT
        self._open_customer()
        self.bulk.assert_called_once()                      # sent while they signed in
        self.assertEqual(self.bulk.call_args.kwargs["timeout"], INSTANT_TIMEOUT)
        self.assertFalse(self.bulk.call_args.kwargs["longer"])   # a cap, not an extension
        self.assertEqual(self.bulk.call_args.args[0][0]["parse_mode"], "MarkdownV2")
        self.assertFalse(SyncUpMessage.objects.filter(event="login",
                                                      sent_at__isnull=True).exists())

    def test_a_failed_instant_try_is_left_for_the_cron(self):
        from .models import SyncUpMessage
        from .syncup_client import SyncUpError
        from .syncup_messages import flush
        self.bulk.side_effect = SyncUpError("SyncUp is unreachable")
        self._open_customer()
        waiting = SyncUpMessage.objects.filter(event="login", sent_at__isnull=True, failed=False)
        self.assertEqual(waiting.count(), 2)                # still queued, one try spent
        self.assertEqual(waiting.first().attempts, 1)
        self.bulk.side_effect = lambda msgs, timeout=None, longer=True: [
            {"chat_id": m["chat_id"], "message_id": "7"} for m in msgs]
        self.assertEqual(flush()["sent"], 2)                # the cron gets it out

    def test_signing_in_is_never_held_up_by_a_broken_relay(self):
        self.bulk.side_effect = RuntimeError("relay exploded")
        self.assertEqual(self._open_customer().status_code, 302)
        self.assertEqual(len(self._msgs()), 2)              # queued, to go with the cron

    def test_each_kind_of_sign_in_is_named_for_what_it_was(self):
        from .models import SyncUpMessage
        self._open_customer()
        for m in self._msgs():
            self.assertIn("📱 Mobile Login", m.text)
            self.assertEqual(m.title, "Mobile login")
        self.a.set_password("Xx!998877aa")
        self.a.save()
        self.client.cookies.clear()
        self.client.post(reverse("login_view"), {"username": self.a.username,
                                                 "password": "Xx!998877aa"})
        owner = SyncUpMessage.objects.filter(event="login", title="Desktop login")
        self.assertEqual(owner.count(), 1)
        self.assertIn("🖥️ Desktop Login", owner.first().text)
        self.assertNotIn("Mobile", owner.first().text)

    def test_a_login_alert_names_the_business_it_belongs_to(self):
        """One group can serve several businesses, so "KMR opened the app" has to say where."""
        self._open_customer()
        for m in self._msgs():
            mine, other = ("ALPHA", "BETA") if m.business_id == self.a.id else ("BETA", "ALPHA")
            self.assertIn("🏢 %s" % mine, m.text)
            # Separate groups: an owner never learns where else this person buys.
            self.assertNotIn(other, m.text)

    def _share_one_group(self):
        """BETA reports to ALPHA's group too (the console's re-use picker)."""
        from .models import TelegramChat
        TelegramChat.objects.filter(business=self.b).update(chat_id="-100%d" % self.a.id)

    def test_several_businesses_in_one_group_are_one_message(self):
        self._share_one_group()
        self._open_customer()
        m, = self._msgs()                                   # not one per business
        self.assertIn("2 Businesses", m.text)
        self.assertIn("ALPHA", m.text)
        self.assertIn("BETA", m.text)
        self.assertEqual(sorted(m.data["businesses"]), sorted([self.a.id, self.b.id]))
        self.bulk.assert_called_once()                      # and sent once, at once

    def test_an_employee_posted_to_several_businesses_is_one_message(self):
        from .models import EmployeePosting
        EmployeePosting.objects.create(employee=self.emp, business=self.b, is_active=True)
        self._share_one_group()
        self._open_employee()
        m, = self._msgs()
        for bit in ("Mobile Login", "RIZWAN", "Employee", "2 Businesses", "ALPHA", "BETA"):
            self.assertIn(bit, m.text)

    def test_a_shared_message_credits_every_business_it_spoke_for(self):
        from .models import TelegramChat
        self._share_one_group()
        self._open_customer()
        rows = TelegramChat.objects.filter(chat_id="-100%d" % self.a.id)
        self.assertEqual(rows.count(), 2)
        self.assertTrue(all(r.last_ok_at for r in rows))    # both businesses see it went

    def test_a_business_that_chose_another_group_is_not_listed(self):
        from .models import BusinessTelegram, TelegramChat
        self._share_one_group()
        own = TelegramChat.objects.create(business=self.b, chat_id="-100424242", label="BETA only")
        BusinessTelegram.objects.get(user=self.b).alert_chats.set([own])
        self._open_customer()
        shared = [m for m in self._msgs() if m.external_id == "-100%d" % self.a.id]
        self.assertEqual(len(shared), 1)
        self.assertNotIn("BETA", shared[0].text)            # BETA sends its logins elsewhere
        beta_only, = [m for m in self._msgs() if m.external_id == "-100424242"]
        self.assertNotIn("ALPHA", beta_only.text)

    def test_the_owners_own_alert_does_not_repeat_the_name(self):
        from .telegram_alerts import message
        text = message("ALPHA", "owner", None, timezone.localtime(), "Windows · Chrome",
                       at="ALPHA")
        self.assertNotIn("🏢", text)

    def test_a_late_alert_still_says_when_they_logged_in(self):
        from .telegram_alerts import message
        when = timezone.localtime().replace(hour=22, minute=5)
        text = message("KMR", "customer", 3, when, "iPhone · Safari")
        self.assertIn("10:05 PM", text)
        self.assertIn("3 Times", text)

    def test_the_device_is_named_when_the_browser_says_so(self):
        from .telegram_alerts import device_name
        self.assertEqual(device_name("Mozilla/5.0 (Linux; Android 14) Chrome/128"),
                         "Android · Chrome")
        self.assertEqual(device_name("Mozilla/5.0 (iPhone) Version/17 Safari/605"),
                         "iPhone · Safari")
        self.assertEqual(device_name(""), "")

    def test_the_console_allows_or_stops_login_notifications(self):
        from .models import BusinessTelegram, PlatformAdmin
        admin = PlatformAdmin(username="alertop", full_name="Alert Op")
        admin.set_password("Cons0le!pass9")
        admin.save()
        self.client.post(reverse("console_login"), {"username": "alertop",
                                                    "password": "Cons0le!pass9"})
        page = self.client.get(reverse("console_business_detail", args=[self.a.id]))
        self.assertContains(page, "Login notifications")
        self.client.post(reverse("console_business_telegram_logins", args=[self.a.id]), {})
        self.assertFalse(BusinessTelegram.objects.get(user=self.a).login_alerts)
        self.client.post(reverse("console_business_telegram_logins", args=[self.a.id]),
                         {"login_alerts": "1"})
        self.assertTrue(BusinessTelegram.objects.get(user=self.a).login_alerts)


class SurveyTests(TestCase):
    """Customer surveys: builder, lifecycle, scoping, results, and mobile answering."""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile, Employee, EmployeePosting
        cls.owner = User.objects.create_user(username="surveyowner", password="x")
        UserProfile.objects.create(user=cls.owner, business_title="Survey Co")
        cls.customer = Customer.objects.create(
            user=cls.owner, customer_name="Gamma Store", customer_phone="9000000001",
            is_mobile_user=True)
        cls.emp = Employee.objects.create(business=cls.owner, name="Field Rep", email="fr@syncup.local")
        cls.posting, _ = EmployeePosting.objects.get_or_create(
            employee=cls.emp, business=cls.owner, defaults={"is_admin": True, "is_home": True})

    def setUp(self):
        self.client.force_login(self.owner)

    # ---- builder ----
    def test_builder_creates_survey_with_questions(self):
        qs = json.dumps([
            {"text": "Do you have a PC?", "type": "bool", "required": True, "options": []},
            {"text": "Which software?", "type": "single", "required": False, "options": ["Tally", "Busy"]},
        ])
        r = self.client.post("/surveys/new", {"title": "IT survey", "description": "d", "questions_json": qs})
        self.assertEqual(r.status_code, 302)
        from .models import Survey
        s = Survey.objects.get(user=self.owner, title="IT survey")
        self.assertEqual(s.questions.count(), 2)
        single = s.questions.get(type="single")
        self.assertEqual([o["id"] for o in single.options], ["o1", "o2"])

    def test_choice_needs_two_options(self):
        qs = json.dumps([{"text": "Pick", "type": "single", "required": True, "options": ["only one"]}])
        r = self.client.post("/surveys/new", {"title": "Bad", "questions_json": qs})
        self.assertEqual(r.status_code, 400)
        from .models import Survey
        self.assertFalse(Survey.objects.filter(title="Bad").exists())

    # ---- lifecycle ----
    def test_activate_requires_questions(self):
        from .models import Survey, SurveyQuestion
        s = Survey.objects.create(user=self.owner, title="Empty")
        self.client.post("/surveys/%d/activate" % s.id)
        s.refresh_from_db()
        self.assertEqual(s.status, "draft")
        SurveyQuestion.objects.create(survey=s, order=0, text="q", type="bool")
        self.client.post("/surveys/%d/activate" % s.id)
        s.refresh_from_db()
        self.assertEqual(s.status, "active")

    def test_structure_locks_after_response(self):
        from .models import Survey, SurveyQuestion, SurveyResponse
        s = Survey.objects.create(user=self.owner, title="Locked", status="active")
        SurveyQuestion.objects.create(survey=s, order=0, text="q1", type="bool")
        SurveyResponse.objects.create(survey=s, customer=self.customer, source="customer")
        qs = json.dumps([{"text": "NEW", "type": "bool", "required": True, "options": []},
                         {"text": "q2", "type": "bool", "required": False, "options": []}])
        self.client.post("/surveys/%d/edit" % s.id, {"title": "Renamed", "questions_json": qs})
        s.refresh_from_db()
        self.assertEqual(s.title, "Renamed")            # meta editable
        self.assertEqual(s.questions.count(), 1)         # structure frozen
        self.assertEqual(s.questions.first().text, "q1")

    # ---- scoping ----
    def test_other_business_cannot_access(self):
        from .models import Survey
        s = Survey.objects.create(user=self.owner, title="Mine")
        other = User.objects.create_user("intruder", password="x")
        self.client.force_login(other)
        self.assertEqual(self.client.get("/surveys/%d/edit" % s.id).status_code, 404)
        self.assertEqual(self.client.get("/surveys/%d/results" % s.id).status_code, 404)

    # ---- save helper ----
    def test_one_response_per_customer_and_required(self):
        from .models import Survey, SurveyQuestion
        from .views.surveys import save_survey_response
        s = Survey.objects.create(user=self.owner, title="Once", status="active")
        q = SurveyQuestion.objects.create(survey=s, order=0, text="PC?", type="bool", required=True)
        ok, _ = save_survey_response(s, self.customer, "customer", None, {str(q.id): True})
        self.assertTrue(ok)
        ok2, _ = save_survey_response(s, self.customer, "customer", None, {str(q.id): False})
        self.assertTrue(ok2)
        self.assertEqual(s.responses.count(), 1)                       # upsert, not duplicate
        self.assertFalse(s.responses.first().answers.first().value["bool"])
        bad, err = save_survey_response(s, self.customer, "customer", None, {})
        self.assertFalse(bad)
        self.assertIn("PC?", err)

    # ---- mobile ----
    def test_mobile_customer_answers(self):
        from .models import Survey, SurveyQuestion, SurveyResponse
        s = Survey.objects.create(user=self.owner, title="M", status="active")
        q = SurveyQuestion.objects.create(survey=s, order=0, text="PC?", type="bool", required=True)
        cl = Client()
        cl.get("/m/customer/", {"t": _app_token(self.customer)})
        r = cl.post("/m/customer/survey/%d" % s.id,
                    data=json.dumps({"answers": {str(q.id): True}}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        resp = SurveyResponse.objects.get(survey=s, customer=self.customer)
        self.assertEqual(resp.source, "customer")
        bad = cl.post("/m/customer/survey/%d" % s.id,
                      data=json.dumps({"answers": {}}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_mobile_employee_answers_for_customer(self):
        from .models import Survey, SurveyQuestion, SurveyResponse
        s = Survey.objects.create(user=self.owner, title="E", status="active")
        q = SurveyQuestion.objects.create(survey=s, order=0, text="PC?", type="bool", required=True)
        cl = Client()
        cl.get("/m/employee/", {"t": _app_token(self.emp)})
        r = cl.post("/m/employee/customer/%d/survey/%d" % (self.customer.id, s.id),
                    data=json.dumps({"answers": {str(q.id): False}}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        resp = SurveyResponse.objects.get(survey=s, customer=self.customer)
        self.assertEqual(resp.source, "employee")
        self.assertEqual(resp.answered_by_employee_id, self.posting.id)

    # ---- results / export ----
    def test_results_and_export(self):
        from .models import Survey, SurveyQuestion, SurveyResponse, SurveyAnswer
        s = Survey.objects.create(user=self.owner, title="R", status="active")
        q = SurveyQuestion.objects.create(survey=s, order=0, text="PC?", type="bool")
        resp = SurveyResponse.objects.create(survey=s, customer=self.customer, source="customer")
        SurveyAnswer.objects.create(response=resp, question=q, value={"bool": True})
        rr = self.client.get("/surveys/%d/results" % s.id)
        self.assertEqual(rr.status_code, 200)
        self.assertContains(rr, "Answers summary")
        ex = self.client.get("/surveys/%d/export" % s.id)
        self.assertEqual(ex.status_code, 200)
        self.assertEqual(ex["Content-Type"], "text/csv")

    def test_owner_desktop_records_response(self):
        from .models import Survey, SurveyQuestion, SurveyResponse
        s = Survey.objects.create(user=self.owner, title="Desk", status="active")
        q = SurveyQuestion.objects.create(survey=s, order=0, text="PC?", type="bool", required=True)
        page = self.client.get("/surveys/%d/respond?customer=%d" % (s.id, self.customer.id))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "PC?")
        r = self.client.post("/surveys/%d/respond" % s.id,
                             {"customer": self.customer.id, "q%d" % q.id: "true"})
        self.assertEqual(r.status_code, 302)
        resp = SurveyResponse.objects.get(survey=s, customer=self.customer)
        self.assertEqual(resp.source, "owner")
        self.assertTrue(resp.answers.first().value["bool"])


class IdentityTests(TestCase):
    """A person IS their mobile number. Nobody maps anyone: the same number in two businesses
    is one person, and changing a number moves the row to whoever holds the new one."""

    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = _businesses("ALPHA", "BETA")

    def _cust(self, business, name, phone="", email=None, **kw):
        return Customer.objects.create(user=business, customer_name=name, customer_phone=phone,
                                       customer_email=email, is_mobile_user=True, **kw)

    # ---- what counts as a number ----
    def test_only_a_ten_digit_indian_mobile_is_an_identity(self):
        from .identity import clean_mobile
        for good, want in (("9876543210", "9876543210"), ("+91 98765 43210", "9876543210"),
                           ("09876543210", "9876543210"), ("919876543210", "9876543210")):
            self.assertEqual(clean_mobile(good), want, good)
        for bad in ("0424-2412345",                      # landline
                    "9876543210 / 9123456789",           # two numbers
                    "1234567890", "98765", "", None, "abcd"):
            self.assertEqual(clean_mobile(bad), "", repr(bad))

    def test_the_form_refuses_anything_else(self):
        from .forms import CustomerForm
        form = CustomerForm({"customer_name": "KMR", "customer_phone": "0424-2412345",
                             "collection_day": 0}, user=self.a)
        self.assertFalse(form.is_valid())
        self.assertIn("10-digit Indian mobile", str(form.errors["customer_phone"]))
        ok = CustomerForm({"customer_name": "KMR", "customer_phone": "+91 98765 43210",
                           "collection_day": 0}, user=self.a)
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(ok.cleaned_data["customer_phone"], "9876543210")   # stored bare

    # ---- the join ----
    def test_one_number_in_two_businesses_is_one_person(self):
        ca = self._cust(self.a, "KMR", "9876543210")
        cb = self._cust(self.b, "KMR TRADERS", "9876543210")
        self.assertEqual(_person_of(ca), _person_of(cb))
        self.assertEqual(sorted(r.id for r in appusers.visible_rows(_person_of(ca))),
                         sorted([ca.id, cb.id]))

    def test_different_numbers_are_different_people(self):
        ca = self._cust(self.a, "KMR", "9876543210")
        cb = self._cust(self.b, "KMR", "9876500000")
        self.assertNotEqual(_person_of(ca), _person_of(cb))

    def test_an_email_joins_when_there_is_no_number(self):
        from .identity import attach
        ea = Employee.objects.create(business=self.a, name="RAVI", email="ravi@shop.test")
        eb = Employee.objects.create(business=self.b, name="RAVI K", email="RAVI@shop.test")
        self.assertEqual(attach(ea), attach(eb))

    def test_a_row_with_no_number_belongs_to_nobody(self):
        c = self._cust(self.a, "WALK IN")
        self.assertIsNone(_person_of(c))

    def test_changing_the_number_moves_the_row(self):
        from .models import AppUser
        c = self._cust(self.a, "KMR", "9876543210")
        first = _person_of(c)
        with self.captureOnCommitCallbacks(execute=True):
            c.customer_phone = "9876500002"
            c.save()
        c.refresh_from_db()
        second = c.app_user
        self.assertNotEqual(first, second)
        self.assertEqual(second.mobile, "9876500002")
        # The person they left held nothing else and no login, so they are gone.
        self.assertFalse(AppUser.objects.filter(pk=first.pk).exists())

    # ---- one identifier, one customer per business ----
    def test_a_second_customer_cannot_take_the_same_number(self):
        from .forms import CustomerForm
        self._cust(self.a, "KMR", "9876543210")
        form = CustomerForm({"customer_name": "OTHER", "customer_phone": "9876543210",
                             "collection_day": 0}, user=self.a)
        self.assertFalse(form.is_valid())
        self.assertIn("One mobile number belongs to one customer", str(form.errors))
        # …but the same number at ANOTHER business is fine — that is the join.
        self.assertTrue(CustomerForm({"customer_name": "KMR", "customer_phone": "9876543210",
                                      "collection_day": 0}, user=self.b).is_valid())

    def test_two_customers_of_one_business_cannot_share_a_number(self):
        """One number is one person, so inside a business it can only be one customer."""
        from .forms import CustomerForm
        self._cust(self.a, "KMR", "9876543210")
        form = CustomerForm({"customer_name": "KMR SECOND SHOP", "customer_phone": "9876543210",
                             "collection_day": 0}, user=self.a)
        self.assertFalse(form.is_valid())
        self.assertIn("One mobile number belongs to one customer", str(form.errors))


class AppLoginTests(TestCase):
    """The login SyncUp performs: the person's own number, never an address we invented."""

    @classmethod
    def setUpTestData(cls):
        cls.a, = _businesses("ALPHA")
        cls.cust = Customer.objects.create(user=cls.a, customer_name="KMR",
                                           customer_phone="9876543210", is_mobile_user=True)

    def setUp(self):
        _syncup_on()
        self.upsert = mock.patch("gstbillingapp.syncup_client.upsert_account").start()
        self.push = mock.patch("gstbillingapp.syncup_client.set_account_active").start()
        self.addCleanup(mock.patch.stopall)

    def test_a_customer_with_a_number_gets_their_login_by_itself(self):
        """Nobody issues anything: adding the customer opens the app for them."""
        from .models import AppUser
        with self.captureOnCommitCallbacks(execute=True):
            c = Customer.objects.create(user=self.a, customer_name="RAJ",
                                        customer_phone="9876500081", is_mobile_user=True)
        person = AppUser.objects.get(mobile="9876500081")
        self.assertEqual(person.login_status, "active")
        kwargs = self.upsert.call_args.kwargs
        self.assertEqual(kwargs["phone"], "9876500081")
        self.assertEqual(kwargs["password"], "9876500081")      # their number IS the password
        link, = kwargs["links"]                                 # a customer: one tile
        self.assertEqual(link["external_id"], "gstsync")
        self.assertTrue(link["url"].startswith("https://gstsync.test/m/customer/?t="))
        self.assertEqual(c.app_user, person)

    def test_a_password_they_have_changed_is_never_overwritten(self):
        """The password is sent once, when the account is made."""
        person = _person_of(self.cust)
        appusers.ensure_login(person)
        self.upsert.reset_mock()
        person.refresh_from_db()
        self.assertIsNone(appusers.ensure_login(person))        # already open
        self.upsert.assert_not_called()

    def test_no_number_means_no_login(self):
        with self.captureOnCommitCallbacks(execute=True):
            Customer.objects.create(user=self.a, customer_name="WALK IN", is_mobile_user=True)
        self.upsert.assert_not_called()

    def test_a_hidden_ledger_opens_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            Customer.objects.create(user=self.a, customer_name="QUIET",
                                    customer_phone="9876500082", is_mobile_user=False)
        self.upsert.assert_not_called()

    def test_another_business_typing_the_same_number_joins_them_later(self):
        """Business A has X. Tomorrow business B puts X's number on its own customer Y —
        from then on SyncUp sees one person with both ledgers."""
        from .models import AppUser
        b, = _businesses("BETA")
        with self.captureOnCommitCallbacks(execute=True):
            y = Customer.objects.create(user=b, customer_name="Y", customer_phone="9876500083",
                                        is_mobile_user=True)
        x_person, y_person = _person_of(self.cust), _person_of(y)
        self.assertNotEqual(x_person, y_person)
        with self.captureOnCommitCallbacks(execute=True):
            y.customer_phone = self.cust.customer_phone      # B corrects the number
            y.save()
        y.refresh_from_db()
        self.assertEqual(y.app_user, x_person)               # one person now
        self.assertEqual(sorted(r.id for r in appusers.visible_rows(x_person)),
                         sorted([self.cust.id, y.id]))
        # The person Y used to be has nothing left, so their login is switched off.
        self.assertFalse(appusers.can_use_app(AppUser.objects.get(pk=y_person.pk)))
        self.assertIn(mock.call(y_person.external_id, False, timeout=2), self.push.call_args_list)

    def test_syncup_is_told_their_own_number(self):
        person = _person_of(self.cust)
        password = appusers.issue_login(person)
        self.assertEqual(self.upsert.call_args.args, (person.external_id,))
        kwargs = self.upsert.call_args.kwargs
        self.assertEqual(kwargs["phone"], "9876543210")
        self.assertNotIn("email", kwargs)                 # nothing invented
        self.assertEqual(kwargs["password"], password)
        link, = kwargs["links"]
        self.assertTrue(link["url"].startswith("https://gstsync.test/m/customer/?t="))
        person.refresh_from_db()
        self.assertEqual(person.login_status, "active")

    def test_an_email_only_person_signs_in_with_it(self):
        emp = Employee.objects.create(business=self.a, name="RAVI", email="ravi@shop.test")
        person = _person_of(emp)
        appusers.issue_login(person)
        self.assertEqual(self.upsert.call_args.kwargs["email"], "ravi@shop.test")
        self.assertNotIn("phone", self.upsert.call_args.kwargs)

    def test_nothing_to_open_blocks_the_login(self):
        Customer.objects.filter(pk=self.cust.pk).update(is_mobile_user=False)
        person = _person_of(self.cust)
        with self.assertRaises(appusers.LoginBlocked):
            appusers.issue_login(person)

    def test_deactivating_kills_the_link_at_once(self):
        person = _person_of(self.cust)
        appusers.issue_login(person)
        token = self.upsert.call_args.kwargs["links"][0]["url"].split("?t=", 1)[1]
        self.assertEqual(self.client.get("/m/", {"t": token}).status_code, 302)
        self.client.cookies.clear()
        appusers.deactivate_login(person)
        self.assertEqual(self.client.get("/m/", {"t": token}).status_code, 403)

    # ---- one number, two sides ----
    def test_a_customer_who_is_also_staff_gets_a_tile_for_each(self):
        """One number is one person — but two sides, so two tiles rather than one that has to
        guess which they meant."""
        emp = Employee.objects.create(business=self.a, name="KMR", phone="9876543210")
        person = _person_of(emp)                          # the customer row's number
        appusers.issue_login(person)
        links = {l["external_id"]: l for l in self.upsert.call_args.kwargs["links"]}
        self.assertEqual(set(links), {"gstsync", "gstsync-staff"})
        self.assertTrue(links["gstsync"]["url"].startswith("https://gstsync.test/m/customer/?t="))
        self.assertTrue(links["gstsync-staff"]["url"].startswith("https://gstsync.test/m/employee/?t="))
        token = links["gstsync"]["url"].split("?t=", 1)[1]        # either tile opens its side
        self.assertEqual(self.client.get("/m/customer/", {"t": token}).status_code, 302)
        self.assertEqual(self.client.get(reverse("m_employee_home")).status_code, 200)

    def test_gaining_the_staff_side_adds_its_tile(self):
        """Only a customer until today, when a business makes them staff on the same number."""
        person = _person_of(self.cust)
        appusers.ensure_login(person)
        person.refresh_from_db()
        self.assertEqual(person.link_keys, "gstsync")
        self.upsert.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            Employee.objects.create(business=self.a, name="KMR", phone="9876543210")
        person.refresh_from_db()
        self.assertEqual(person.link_keys, "gstsync,gstsync-staff")
        self.assertEqual({l["external_id"] for l in self.upsert.call_args.kwargs["links"]},
                         {"gstsync", "gstsync-staff"})

    def test_an_unchanged_set_of_tiles_costs_no_call(self):
        person = _person_of(self.cust)
        appusers.ensure_login(person)
        person.refresh_from_db()
        self.upsert.reset_mock()
        self.assertFalse(appusers.sync_links(person))
        self.upsert.assert_not_called()

    def test_a_tile_goes_when_that_side_does(self):
        """They stop being staff: that tile is taken away, their ledger tile stays."""
        emp = Employee.objects.create(business=self.a, name="KMR", phone="9876543210")
        person = _person_of(emp)
        appusers.ensure_login(person)
        person.refresh_from_db()
        with mock.patch("gstbillingapp.syncup_client.list_links",
                        return_value=[{"id": 7, "external_id": "gstsync-staff"},
                                      {"id": 8, "external_id": "gstsync"}]),              mock.patch("gstbillingapp.syncup_client.delete_link") as drop:
            emp.delete()
            appusers.sync_links(AppUserModel.objects.get(pk=person.pk))
        drop.assert_called_once_with(7)                   # only the staff tile
        self.assertEqual(AppUserModel.objects.get(pk=person.pk).link_keys, "gstsync")


class ConnectionStatusTests(TestCase):
    """SyncUp answers every upsert with the state of OUR connection. A number that already
    belonged to a SyncUp account stays that person's: our tiles appear only once they switch
    this business on. Showing them "Open" when they are not would send a business chasing a
    tile that was never going to appear."""

    @classmethod
    def setUpTestData(cls):
        cls.a, = _businesses("ALPHA")
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="connop", full_name="Conn Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()

    def setUp(self):
        _syncup_on()
        self.upsert = mock.patch("gstbillingapp.syncup_client.upsert_account").start()
        self.push = mock.patch("gstbillingapp.syncup_client.set_account_active").start()
        self.upsert.return_value = {"status": "enabled"}
        self.push.return_value = {"status": "enabled"}
        self.addCleanup(mock.patch.stopall)

    def _add(self, phone, name="KMR"):
        with self.captureOnCommitCallbacks(execute=True):
            return Customer.objects.create(user=self.a, customer_name=name,
                                           customer_phone=phone, is_mobile_user=True)

    def test_a_number_already_on_syncup_waits_for_its_owner(self):
        from .models import AppUser
        self.upsert.return_value = {"status": "not_enabled", "pending": ["connection"]}
        self._add("9876500091")
        person = AppUser.objects.get(mobile="9876500091")
        self.assertEqual(person.connection, "not_enabled")
        self.assertEqual(person.login_status, "active")     # the account exists on our side

    def test_an_ordinary_new_number_is_simply_enabled(self):
        from .models import AppUser
        self._add("9876500092")
        self.assertEqual(AppUser.objects.get(mobile="9876500092").connection, "enabled")

    def test_switching_us_off_in_their_app_is_recorded(self):
        from .models import AppUser
        c = self._add("9876500093")
        person = _person_of(c)
        self.push.return_value = {"status": "disabled"}
        AppUser.objects.filter(pk=person.pk).update(syncup_active=False)
        appusers.refresh_login(AppUser.objects.get(pk=person.pk))
        self.assertEqual(AppUser.objects.get(pk=person.pk).connection, "disabled")

    def test_an_answer_without_a_status_leaves_what_we_knew(self):
        from .models import AppUser
        self.upsert.return_value = {"status": "not_enabled"}
        c = self._add("9876500094")
        self.upsert.return_value = {}                        # older SyncUp, no field
        appusers.issue_login(_person_of(c))
        self.assertEqual(AppUser.objects.get(mobile="9876500094").connection, "not_enabled")

    def test_the_console_says_whose_turn_it_is(self):
        self.upsert.return_value = {"status": "not_enabled"}
        self._add("9876500095", name="WAITING SHOP")
        self.client.post(reverse("console_login"),
                         {"username": "connop", "password": "Cons0le!pass9"})
        r = self.client.get(reverse("console_customers"))
        self.assertContains(r, "Their turn")
        self.assertNotContains(r, "Open</span>")
        person = _person_of(Customer.objects.get(customer_phone="9876500095"))
        r = self.client.get(reverse("console_person", args=[person.id]))
        self.assertContains(r, "The account stays theirs")


class SyncUpPacingTests(TestCase):
    """SyncUp allows 120 calls a minute. A business importing its customer list must not turn
    that limit into a column of failures."""

    @classmethod
    def setUpTestData(cls):
        cls.a, = _businesses("ALPHA")

    def setUp(self):
        _syncup_on()
        self.upsert = mock.patch("gstbillingapp.syncup_client.upsert_account").start()
        self.push = mock.patch("gstbillingapp.syncup_client.set_account_active").start()
        self.upsert.return_value = {"status": "enabled"}
        self.push.return_value = {"status": "enabled"}
        self.addCleanup(mock.patch.stopall)

    def _people(self, n):
        from .models import AppUser
        for i in range(n):
            Customer.objects.create(user=self.a, customer_name="C%d" % i,
                                    customer_phone="98765%05d" % i, is_mobile_user=True)
        AppUser.objects.update(login_status=AppUser.LOGIN_NONE)

    def test_too_many_stops_the_run_instead_of_failing_everybody(self):
        from .models import AppUser
        self._people(5)
        self.upsert.side_effect = syncup_client.SyncUpError("too many requests", status=429)
        counts = appusers.retry_pending()
        self.assertEqual(counts["busy"], 1)                  # asked once, then stopped
        self.assertEqual(self.upsert.call_count, 1)
        self.assertEqual(counts["left"], 5)                  # all still waiting, none "failed"
        self.assertEqual(counts["failed"], 0)
        self.assertEqual(AppUser.objects.filter(login_status=AppUser.LOGIN_NONE).count(), 5)

    def test_an_ordinary_failure_does_not_stop_the_others(self):
        self._people(3)
        self.upsert.side_effect = [syncup_client.SyncUpError("bad request", status=400),
                                   {"status": "enabled"}, {"status": "enabled"}]
        counts = appusers.retry_pending()
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["created"], 2)

    def test_one_run_opens_no_more_than_the_cap(self):
        self._people(4)
        with mock.patch.object(appusers, "PER_RUN", 2):
            counts = appusers.retry_pending()
        self.assertEqual(counts["created"], 2)
        self.assertEqual(counts["left"], 2)                  # the next run takes these


class NumberChangedTests(TestCase):
    """A corrected number must not cost somebody their app account."""

    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = _businesses("ALPHA", "BETA")

    def setUp(self):
        _syncup_on()
        self.upsert = mock.patch("gstbillingapp.syncup_client.upsert_account").start()
        self.push = mock.patch("gstbillingapp.syncup_client.set_account_active").start()
        self.upsert.return_value = {"status": "enabled"}
        self.push.return_value = {"status": "enabled"}
        self.addCleanup(mock.patch.stopall)

    def _customer(self, business, phone, name="KMR"):
        with self.captureOnCommitCallbacks(execute=True):
            return Customer.objects.create(user=business, customer_name=name,
                                           customer_phone=phone, is_mobile_user=True)

    def test_a_typo_fixed_keeps_the_same_account(self):
        from .models import AppUser
        c = self._customer(self.a, "9876500011")
        person = _person_of(c)
        with self.captureOnCommitCallbacks(execute=True):
            c.customer_phone = "9876500012"
            c.save()
        c.refresh_from_db()
        self.assertEqual(c.app_user_id, person.id)           # the same person, re-numbered
        self.assertEqual(AppUser.objects.count(), 1)
        moved = AppUser.objects.get(pk=person.pk)
        self.assertEqual(moved.mobile, "9876500012")
        self.assertEqual(moved.login_status, "active")
        sent = self.upsert.call_args.kwargs                  # SyncUp told, password untouched
        self.assertEqual(sent["phone"], "9876500012")
        self.assertNotIn("password", sent)

    def test_a_number_handed_to_someone_else_makes_a_second_person(self):
        """Two businesses share the person, so one of them changing a number is a different
        person now — not a correction."""
        from .models import AppUser
        ca = self._customer(self.a, "9876500021")
        self._customer(self.b, "9876500021", name="KMR TRADERS")
        with self.captureOnCommitCallbacks(execute=True):
            ca.customer_phone = "9876500022"
            ca.save()
        self.assertEqual(AppUser.objects.count(), 2)
        ca.refresh_from_db()
        self.assertEqual(ca.app_user.mobile, "9876500022")
        self.assertTrue(AppUser.objects.filter(mobile="9876500021").exists())

    def test_moving_onto_a_number_someone_already_has_joins_them(self):
        from .models import AppUser
        self._customer(self.b, "9876500031", name="RAJ")
        ca = self._customer(self.a, "9876500032")
        with self.captureOnCommitCallbacks(execute=True):
            ca.customer_phone = "9876500031"
            ca.save()
        ca.refresh_from_db()
        self.assertEqual(ca.app_user.mobile, "9876500031")   # same person as BETA's RAJ
        # The number they left keeps its account — it is somebody's app access, and the
        # external id has to stay addressable — but it no longer opens anything.
        self.assertFalse(AppUser.objects.get(mobile="9876500032").syncup_active)

    def test_syncup_refusing_the_new_number_is_shown_not_lost(self):
        from .models import AppUser
        c = self._customer(self.a, "9876500041")
        self.upsert.side_effect = syncup_client.SyncUpError(
            "that number belongs to another account", status=409)
        with self.captureOnCommitCallbacks(execute=True):
            c.customer_phone = "9876500042"
            c.save()
        person = AppUser.objects.get(mobile="9876500042")
        self.assertIn("another account", person.syncup_error)


    def test_a_refused_sign_in_change_is_tried_again_by_the_cron(self):
        from .models import AppUser
        c = self._customer(self.a, "9876500045")
        self.upsert.side_effect = syncup_client.SyncUpError("SyncUp is unreachable")
        with self.captureOnCommitCallbacks(execute=True):
            c.customer_phone = "9876500046"
            c.save()
        self.assertTrue(AppUser.objects.get(mobile="9876500046").identity_pending)
        self.upsert.side_effect = None                       # SyncUp is back
        self.upsert.return_value = {"status": "enabled"}
        appusers.retry_pending()
        person = AppUser.objects.get(mobile="9876500046")
        self.assertFalse(person.identity_pending)
        self.assertEqual(person.syncup_error, "")
        self.assertEqual(self.upsert.call_args.kwargs["phone"], "9876500046")


class BackfillTests(TestCase):
    """A database that existed before identity.py has rows pointing at nobody. Until they are
    walked once, every console people screen is empty and nobody can open the app."""

    @classmethod
    def setUpTestData(cls):
        cls.a, = _businesses("ALPHA")

    def setUp(self):
        _syncup_on()
        self.upsert = mock.patch("gstbillingapp.syncup_client.upsert_account").start()
        self.push = mock.patch("gstbillingapp.syncup_client.set_account_active").start()
        self.upsert.return_value = {"status": "enabled"}
        self.push.return_value = {"status": "enabled"}
        self.addCleanup(mock.patch.stopall)

    def _orphans(self):
        """Rows as a pre-identity database holds them: saved, then unlinked behind the hooks."""
        c = Customer.objects.create(user=self.a, customer_name="OLD SHOP",
                                    customer_phone="9876500061", is_mobile_user=True)
        e = Employee.objects.create(business=self.a, name="OLD REP", phone="9876500062")
        Customer.objects.create(user=self.a, customer_name="LANDLINE",
                                customer_phone="0424-2412345", is_mobile_user=True)
        from .models import AppUser
        Customer.objects.update(app_user=None)
        Employee.objects.update(app_user=None)
        AppUser.objects.all().delete()
        return c, e

    def test_the_command_links_every_row_that_has_a_number(self):
        from django.core.management import call_command
        from .models import AppUser
        self._orphans()
        call_command("link_people", verbosity=0)
        self.assertEqual(AppUser.objects.count(), 2)         # the landline is nobody
        self.assertTrue(Customer.objects.get(customer_name="OLD SHOP").app_user_id)
        self.assertTrue(Employee.objects.get(name="OLD REP").app_user_id)

    def test_a_dry_run_changes_nothing(self):
        from django.core.management import call_command
        from .models import AppUser
        self._orphans()
        call_command("link_people", "--dry-run", verbosity=0)
        self.assertEqual(AppUser.objects.count(), 0)

    def test_running_it_twice_is_harmless(self):
        from django.core.management import call_command
        from .models import AppUser
        self._orphans()
        call_command("link_people", verbosity=0)
        call_command("link_people", "--all", verbosity=0)
        self.assertEqual(AppUser.objects.count(), 2)

    def test_the_cron_picks_up_rows_nobody_walked(self):
        from .models import AppUser
        self._orphans()
        appusers.retry_pending()
        self.assertEqual(AppUser.objects.count(), 2)
        self.assertEqual(AppUser.objects.get(mobile="9876500061").login_status, "active")


class StaffAppSwitchTests(TestCase):
    """Employment and app access are two questions, as they are for a customer."""

    @classmethod
    def setUpTestData(cls):
        cls.a, = _businesses("ALPHA")

    def setUp(self):
        _syncup_on()
        self.upsert = mock.patch("gstbillingapp.syncup_client.upsert_account").start()
        self.push = mock.patch("gstbillingapp.syncup_client.set_account_active").start()
        self.upsert.return_value = {"status": "enabled"}
        self.push.return_value = {"status": "enabled"}
        self.addCleanup(mock.patch.stopall)

    def test_staff_app_is_on_by_default(self):
        with self.captureOnCommitCallbacks(execute=True):
            e = Employee.objects.create(business=self.a, name="RIZWAN", phone="9876500051")
        person = _person_of(e)
        self.assertTrue(appusers.is_staff(person))
        self.assertEqual([l["external_id"] for l in appusers.desired_links(person)],
                         ["gstsync-staff"])

    def test_switching_the_app_off_keeps_the_employee(self):
        with self.captureOnCommitCallbacks(execute=True):
            e = Employee.objects.create(business=self.a, name="RIZWAN", phone="9876500052")
        with self.captureOnCommitCallbacks(execute=True):
            e.is_mobile_user = False
            e.save()
        person = _person_of(e)
        self.assertFalse(appusers.is_staff(person))          # no staff tile
        self.assertFalse(appusers.can_use_app(person))       # nothing to open
        e.refresh_from_db()
        self.assertTrue(e.is_active)                         # still works here

    def test_a_customer_who_is_also_staff_keeps_their_customer_tile(self):
        with self.captureOnCommitCallbacks(execute=True):
            Customer.objects.create(user=self.a, customer_name="RIZWAN",
                                    customer_phone="9876500053", is_mobile_user=True)
            e = Employee.objects.create(business=self.a, name="RIZWAN", phone="9876500053",
                                        is_mobile_user=False)
        person = _person_of(e)
        self.assertEqual([l["external_id"] for l in appusers.desired_links(person)],
                         ["gstsync"])
        self.assertTrue(appusers.can_use_app(person))


class ConsolePeopleTests(TestCase):
    """The console: people, their login, and the rows a number can't speak for."""

    @classmethod
    def setUpTestData(cls):
        from .models import PlatformAdmin
        cls.admin = PlatformAdmin(username="peopleop", full_name="People Op")
        cls.admin.set_password("Cons0le!pass9")
        cls.admin.save()
        cls.a, cls.b = _businesses("ALPHA", "BETA")
        cls.ca = Customer.objects.create(user=cls.a, customer_name="KMR",
                                         customer_phone="9876543210", is_mobile_user=True)
        cls.cb = Customer.objects.create(user=cls.b, customer_name="KMR TRADERS",
                                         customer_phone="9876543210", is_mobile_user=True)
        cls.emp = Employee.objects.create(business=cls.a, name="RIZWAN", phone="9876500004")

    def setUp(self):
        _syncup_on()
        self.client.post(reverse("console_login"),
                         {"username": "peopleop", "password": "Cons0le!pass9"})

    def test_the_customers_screen_lists_people_not_rows(self):
        r = self.client.get(reverse("console_customers"))
        self.assertContains(r, "KMR")
        self.assertContains(r, "9876543210")
        self.assertContains(r, "ALPHA, BETA")            # one person, both businesses
        self.assertNotContains(r, "RIZWAN")              # staff live on their own screen

    def test_the_employees_screen_lists_staff(self):
        r = self.client.get(reverse("console_employees"))
        self.assertContains(r, "RIZWAN")
        self.assertNotContains(r, "KMR TRADERS")

    def test_the_person_page_shows_every_ledger(self):
        person = _person_of(self.ca)
        r = self.client.get(reverse("console_person", args=[person.id]))
        for bit in ("KMR", "ALPHA", "BETA", "App login"):
            self.assertContains(r, bit)

    def test_the_problems_page_shows_what_a_number_cannot_answer(self):
        Customer.objects.create(user=self.a, customer_name="LANDLINE",
                                customer_phone="0424-2412345", is_mobile_user=True)
        r = self.client.get(reverse("console_problems"))
        self.assertContains(r, "LANDLINE")
        self.assertContains(r, "Not a 10-digit Indian mobile")
        self.assertContains(r, "9876543210")             # the join, listed but not a fault

    def test_a_shared_number_shows_what_each_business_calls_them(self):
        """A number in three businesses is only readable with the three shop names beside it:
        the same number under three spellings is how you tell a real join from a typo."""
        r = self.client.get(reverse("console_problems"))
        self.assertContains(r, "KMR TRADERS")                # BETA's name for them
        self.assertContains(r, "ALPHA")
        self.assertContains(r, "BETA")

    def test_one_name_everywhere_is_said_once(self):
        Customer.objects.create(user=self.b, customer_name="SAME SHOP",
                                customer_phone="9876500077", is_mobile_user=True)
        Customer.objects.create(user=self.a, customer_name="SAME SHOP",
                                customer_phone="9876500077", is_mobile_user=True)
        r = self.client.get(reverse("console_problems"))
        self.assertContains(r, "the same name everywhere")

    def test_the_console_needs_a_console_login(self):
        self.client.get(reverse("console_logout"))
        for url in (reverse("console_customers"), reverse("console_employees"),
                    reverse("console_customer_rows"), reverse("console_problems")):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/console/login", r["Location"])
