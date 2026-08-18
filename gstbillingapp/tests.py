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
        # 1000 purchased, only 300 settled → oldest purchase (40d) is still open.
        self.assertEqual(self._get()['oldest_unpaid_days'], 40)

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
