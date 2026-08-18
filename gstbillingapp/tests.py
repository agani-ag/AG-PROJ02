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
        )
        Book.objects.create(user=cls.owner, customer=cls.customer, current_balance=-1500)
        cls.emp = Employee.objects.create(business=cls.owner, name="Rep One", email="rep1@syncup.local")

    def test_customer_token_grants_access_and_shows_dues(self):
        from .mobile_auth import mint_customer_token
        token = mint_customer_token(self.customer)
        resp = self.client.get("/m/customer/", {"t": token})           # token → session
        self.assertEqual(resp.status_code, 302)                        # redirects to clean URL
        resp2 = self.client.get("/m/customer/")                        # rides the session
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "BETA STORE")                       # name (upper-cased on save)
        self.assertContains(resp2, "1500")                             # outstanding shown

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
            customer_userid="gs1c1", collection_day=1,
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
        other = Customer.objects.create(user=self.owner, customer_name="Other", customer_userid="gs1c2")
        self.client.get("/m/customer/", {"t": mint_customer_token(other)})
        self.assertEqual(self.client.get(reverse("m_customer_invoice", args=[self.inv.id])).status_code, 404)

    def test_employee_screens_render(self):
        self._emp()
        for name, args in [("m_employee_home", []), ("m_employee_customers", []),
                           ("m_employee_customer", [self.cust.id]), ("m_employee_invoices", []),
                           ("m_employee_collections", []), ("m_employee_orders", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_record_payment_updates_balance(self):
        self._emp()
        r = self.client.post(reverse("m_employee_record_payment", args=[self.cust.id]),
                             data=json.dumps({"amount": 200, "note": "part"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.book.refresh_from_db()
        self.assertAlmostEqual(self.book.current_balance, -300.0)  # owed 500, paid 200

    def test_employee_customer_scoped(self):
        # employee of one business can't open another business's customer
        stranger = User.objects.create_user("own3", password="x")
        foreign = Customer.objects.create(user=stranger, customer_name="Foreign")
        self._emp()
        self.assertEqual(self.client.get(reverse("m_employee_customer", args=[foreign.id])).status_code, 404)


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

    def test_revoke_bumps_version(self):
        from .models import Employee
        emp = Employee.objects.create(business=self.owner, name="Ravi")
        v0 = emp.token_version
        self.client.post(reverse("employee_revoke", args=[emp.id]))
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
        cls.ca = Customer.objects.create(user=cls.a, customer_name="Ram", customer_gst="29ABCDE1234F1Z5")
        cls.cb = Customer.objects.create(user=cls.b, customer_name="Ram", customer_gst="29ABCDE1234F1Z5")
        Book.objects.create(user=cls.a, customer=cls.ca, current_balance=-100)
        Book.objects.create(user=cls.b, customer=cls.cb, current_balance=-250)
        cls.emp = Employee.objects.create(business=cls.a, name="Rep")
        cls.emp.businesses.set([cls.a, cls.b])

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
