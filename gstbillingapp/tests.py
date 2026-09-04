import json
from datetime import date, timedelta

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from .models import Customer, Book, BookLog, Invoice, ChequeLeaf


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
        from .mobile_auth import mint_customer_token
        token = mint_customer_token(self.customer)
        resp = self.client.get("/m/customer/", {"t": token})           # token → session
        self.assertEqual(resp.status_code, 302)                        # redirects to clean URL
        resp2 = self.client.get("/m/customer/")                        # rides the session
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "BETA STORE")                       # name (upper-cased on save)
        self.assertContains(resp2, "1,500")                            # outstanding shown (Indian format)

    def test_auth_survives_session_wipe(self):
        # The magic-link identity lives in its own m_auth cookie, so a desktop logout
        # (which flushes the shared Django session) must NOT sign the phone out.
        from .mobile_auth import mint_customer_token, _COOKIE
        self.client.get("/m/customer/", {"t": mint_customer_token(self.customer)})
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
        from .mobile_auth import mint_customer_token
        self.client.get("/m/customer/", {"t": mint_customer_token(self.customer)})  # customer session
        self.assertEqual(self.client.get("/m/employee/").status_code, 403)          # role-gated

    def test_employee_token_grants_access(self):
        from .mobile_auth import mint_employee_token
        token = mint_employee_token(self.emp)
        self.client.get("/m/employee/", {"t": token})
        resp = self.client.get("/m/employee/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ACME DISTRIBUTORS")

    def test_token_tamper_fails_verification(self):
        from .mobile_auth import mint_customer_token, verify_mobile_token
        token = mint_customer_token(self.customer)
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
            customer_userid="gs1c1", collection_day=1, is_mobile_user=True,
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
        from .mobile_auth import mint_customer_token
        self.client.get("/m/customer/", {"t": mint_customer_token(self.cust)})

    def _emp(self):
        from .mobile_auth import mint_employee_token
        self.client.get("/m/employee/", {"t": mint_employee_token(self.emp)})

    def test_customer_screens_render(self):
        self._cust()
        for name, args in [("m_customer_home", []), ("m_customer_books", []),
                           ("m_customer_invoices", []), ("m_customer_invoice", [self.inv.id]),
                           ("m_customer_orders", []), ("m_customer_profile", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_customer_cannot_open_foreign_invoice(self):
        from .mobile_auth import mint_customer_token
        other = Customer.objects.create(user=self.owner, customer_name="Other", customer_userid="gs1c2", is_mobile_user=True)
        self.client.get("/m/customer/", {"t": mint_customer_token(other)})
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
        from .mobile_auth import mint_customer_token
        self.client.get("/m/customer/", {"t": mint_customer_token(self.cust)})

    def _emp_session(self):
        from .mobile_auth import mint_employee_token
        self.client.get("/m/employee/", {"t": mint_employee_token(self.emp)})

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
        from .models import Employee
        emp = Employee.objects.create(business=self.owner, name="Ravi")
        d = self.client.get(reverse("employee_mobile_link", args=[emp.id])).json()
        self.assertTrue(d["ok"]); self.assertIn("/m/employee/?t=", d["url"])
        cust = Customer.objects.create(user=self.owner, customer_name="C")
        d2 = self.client.get(reverse("customer_mobile_link", args=[cust.id])).json()
        self.assertIn("/m/customer/?t=", d2["url"])

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

    def test_revoke_bumps_version(self):
        from .models import Employee
        emp = Employee.objects.create(business=self.owner, name="Ravi")
        home = emp.postings.get(is_home=True)
        v0 = emp.token_version
        self.client.post(reverse("employee_revoke", args=[home.id]))
        emp.refresh_from_db()
        self.assertEqual(emp.token_version, v0 + 1)


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
        # Same real customer across two shops — linked by matching GSTIN.
        cls.ca = Customer.objects.create(user=cls.a, customer_name="Ram", customer_gst="29ABCDE1234F1Z5", is_mobile_user=True)
        cls.cb = Customer.objects.create(user=cls.b, customer_name="Ram", customer_gst="29ABCDE1234F1Z5", is_mobile_user=True)
        Book.objects.create(user=cls.a, customer=cls.ca, current_balance=-100)
        Book.objects.create(user=cls.b, customer=cls.cb, current_balance=-250)
        from .models import EmployeePosting
        cls.emp = Employee.objects.create(business=cls.a, name="Rep")   # home posting @ A
        EmployeePosting.objects.create(employee=cls.emp, business=cls.b, is_active=True)  # shared @ B

    def test_customer_consolidated_total(self):
        from .mobile_auth import mint_customer_token
        self.client.get("/m/customer/", {"t": mint_customer_token(self.ca)})
        r = self.client.get("/m/customer/")
        self.assertContains(r, "350")            # 100 + 250 across the group
        self.assertContains(r, "SHOP A")         # business titles upper-cased on save
        self.assertContains(r, "SHOP B")

    def test_customer_switch_scopes_ledger(self):
        from .mobile_auth import mint_customer_token
        self.client.get("/m/customer/", {"t": mint_customer_token(self.ca)})
        r = self.client.get("/m/customer/books", {"biz": self.b.id})   # switch to Shop B
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "250")            # B's due

    def test_employee_coverage_and_switch(self):
        from .mobile_auth import mint_employee_token
        self.client.get("/m/employee/", {"t": mint_employee_token(self.emp)})
        self.assertEqual(self.client.get("/m/employee/customers", {"biz": self.b.id}).status_code, 200)

    def test_employee_invalid_biz_falls_back(self):
        from .mobile_auth import mint_employee_token
        stranger = User.objects.create_user("bizC", password="x")
        from .models import UserProfile
        UserProfile.objects.create(user=stranger, business_title="Shop C", business_gst="OTHERGST")
        self.client.get("/m/employee/", {"t": mint_employee_token(self.emp)})
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
        from .mobile_auth import mint_customer_token
        return self.client.get("/m/customer/", {"t": mint_customer_token(cust)})

    def test_toggle_off_denies_access(self):
        c = Customer.objects.create(user=self.owner, customer_name="Off", is_mobile_user=False)
        r = self._open(c)
        self.assertEqual(r.status_code, 403)                 # inactive for mobile → denied
        self.assertContains(r, "Mobile access turned off", status_code=403)   # deactivation message
        self.assertContains(r, "contact the business owner", status_code=403)

    def test_invalid_token_shows_session_expired(self):
        r = self.client.get("/m/customer/", {"t": "not.a.valid.token"})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Session expired", status_code=403)   # not the deactivation message

    def test_toggle_on_grants_access(self):
        c = Customer.objects.create(user=self.owner, customer_name="On", is_mobile_user=True)
        self.assertEqual(self._open(c).status_code, 302)     # token accepted → redirect to clean URL

    def test_toggle_is_per_business(self):
        from .models import UserProfile
        from .mobile_auth import _accessible
        b = User.objects.create_user("tog_b", password="x")
        UserProfile.objects.create(user=b, business_title="Tog B")
        # Same person across two shops (matched by GST): active here, inactive at B.
        ca = Customer.objects.create(user=self.owner, customer_name="Ram",
                                     customer_gst="27AAAAA0000A1Z5", is_mobile_user=True)
        Customer.objects.create(user=b, customer_name="Ram",
                                customer_gst="27AAAAA0000A1Z5", is_mobile_user=False)
        businesses, _ = _accessible({"role": "customer", "primary": ca})
        ids = [x.id for x in businesses]
        self.assertIn(self.owner.id, ids)        # active business is accessible
        self.assertNotIn(b.id, ids)              # business with the toggle off is dropped


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
        from .mobile_auth import mint_employee_token
        self.client.get("/m/employee/", {"t": mint_employee_token(self.emp)})

    def _staff(self):
        from .mobile_auth import mint_employee_token
        self.client.get("/m/employee/", {"t": mint_employee_token(self.emp2)})

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
