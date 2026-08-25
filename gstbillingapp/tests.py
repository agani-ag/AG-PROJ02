import json
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from .models import Customer, Book, BookLog, Invoice, ChequeLeaf


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
        # Regular employee: only today's tally, no business financials.
        self._emp()
        r = self.client.get(reverse("m_employee_home"))
        self.assertNotContains(r, "Overall Summary")
        self.assertNotContains(r, "Payment Collection")
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
