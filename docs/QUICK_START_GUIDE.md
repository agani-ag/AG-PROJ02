# 🚀 Quick Start Guide - GST Filing & Auditing System

## Prerequisites Checklist
- [ ] Python 3.8+ installed
- [ ] Django project environment ready
- [ ] Database configured (SQLite3)
- [ ] Required Python packages installed

---

## Step-by-Step Setup

### 1️⃣ Activate Virtual Environment
```bash
# Windows PowerShell
venv\Scripts\activate

# Or Windows CMD
venv\Scripts\activate.bat

# Linux/Mac
source venv/bin/activate
```

### 2️⃣ Install Dependencies (if needed)
```bash
pip install -r requirements.txt
```

### 3️⃣ Run Database Migrations ⚠️ **CRITICAL**
```bash
# Generate migration files for new GST models
python manage.py makemigrations gstbillingapp

# Apply migrations to database
python manage.py migrate
```

**Expected Output:**
```
Migrations for 'gstbillingapp':
  gstbillingapp\migrations\0004_auto_XXXXXX.py
    - Create model PurchaseInvoice
    - Create model GSTReturn
    - Create model GSTRReconciliation
    - Create model AuditLog
```

### 4️⃣ Create Superuser (if not done)
```bash
python manage.py createsuperuser
```

### 5️⃣ Start Development Server
```bash
python manage.py runserver
```

**Server will run at:** `http://127.0.0.1:8000/`

---

## 🎯 Quick Feature Access

### Main URLs:
| Feature | URL | Description |
|---------|-----|-------------|
| GST Dashboard | `/gst/dashboard/` | Overview & quick links |
| Purchase Invoices | `/purchase-invoices/` | Manage purchase invoices |
| GSTR-1 Report | `/gst/gstr1/?month=1&year=2024` | Outward supplies |
| GSTR-3B Report | `/gst/gstr3b/?month=1&year=2024` | Monthly return |
| GSTR-9 Report | `/gst/gstr9/?year=2024` | Annual return |
| Reconciliation | `/gst/reconciliation/` | GSTR-2A/2B matching |
| Audit Logs | `/audit/logs/` | Compliance trail |
| Compliance Tracker | `/gst/compliance/` | Deadline alerts |
| Analytics | `/gst/analytics/` | Charts & insights |
| ITC Ledger | `/purchase-invoices/itc-ledger/` | Input tax credit |

---

## 📝 Initial Setup Tasks

### 1. Add Purchase Invoices
1. Navigate to: `http://127.0.0.1:8000/purchase-invoices/add/`
2. Fill in vendor details (GSTIN, name)
3. Enter invoice details (number, date, amounts)
4. Check "ITC Claimed" if applicable
5. Save

### 2. Generate GSTR-1 (Outward Supplies)
1. Navigate to: `http://127.0.0.1:8000/gst/gstr1/`
2. Select month and year
3. Click "Generate Report"
4. Review B2B, B2C, and HSN sections
5. Export JSON if needed

### 3. Generate GSTR-3B (Monthly Return)
1. Navigate to: `http://127.0.0.1:8000/gst/gstr3b/`
2. Select month and year
3. System auto-calculates:
   - Output tax (from sales invoices)
   - ITC available (from purchase invoices)
   - Net tax payable
4. Export JSON for filing

### 4. Reconcile with GSTR-2A
1. Download GSTR-2A CSV from GST Portal:
   - Login to https://www.gst.gov.in/
   - Go to Services → Returns → GSTR-2A
   - Select period and download CSV
2. Navigate to: `http://127.0.0.1:8000/gst/reconciliation/upload/`
3. Select period and upload CSV
4. System will auto-match invoices
5. Review mismatches and take action

### 5. Check Compliance Status
1. Navigate to: `http://127.0.0.1:8000/gst/compliance/`
2. View upcoming deadlines
3. Check filing status
4. Monitor late fees (if any)

---

## 🔧 Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'django'"
**Solution:**
```bash
# Ensure virtual environment is activated
venv\Scripts\activate

# Reinstall Django
pip install django
```

### Issue: "OperationalError: no such table"
**Solution:**
```bash
# Run migrations
python manage.py migrate
```

### Issue: "CSRF verification failed"
**Solution:**
- Ensure `{% csrf_token %}` is present in all forms
- Check Django CSRF middleware is enabled in settings.py

### Issue: Charts not displaying in Analytics
**Solution:**
- Check browser console for JavaScript errors
- Verify Chart.js CDN is loading
- Ensure data arrays are properly formatted in view

### Issue: Upload GSTR-2A CSV fails
**Solution:**
- Verify CSV format matches GST Portal format
- Check column headers are correct
- Ensure date format is DD-MM-YYYY
- Validate GSTIN format (15 characters)

---

## 📊 Sample Data for Testing

### Sample Purchase Invoice:
```
Vendor GSTIN: 27AABCU9603R1ZX
Vendor Name: ABC Suppliers Pvt Ltd
Invoice Number: INV/2024/001
Invoice Date: 01-01-2024
Taxable Amount: 10000.00
CGST: 900.00 (9%)
SGST: 900.00 (9%)
IGST: 0.00
ITC Eligible: Yes
ITC Claimed: Yes
```

### Sample GSTR-2A CSV Row:
```
GSTIN of Supplier,Trade/Legal name,Invoice Number,Invoice Date,Taxable Value,Central Tax,State/UT Tax,Integrated Tax
27AABCU9603R1ZX,ABC Suppliers Pvt Ltd,INV/2024/001,01-01-2024,10000.00,900.00,900.00,0.00
```

---

## 🎓 Common Workflows

### Monthly Workflow:
1. **By 10th:** Add all sales invoices for previous month
2. **By 11th:** Generate and file GSTR-1
3. **By 15th:** Add all purchase invoices
4. **By 18th:** Download GSTR-2A and reconcile
5. **By 20th:** Generate and file GSTR-3B
6. **By 25th:** Review audit logs and compliance status

### Quarterly Workflow:
1. Review 3-month data in analytics
2. Check state-wise sales distribution
3. Reconcile all GSTR-2A for the quarter
4. Verify ITC claims
5. Prepare for annual return

### Annual Workflow:
1. **By November:** Start GSTR-9 preparation
2. **By December 15:** Complete data verification
3. **By December 31:** Generate and file GSTR-9
4. **If turnover > ₹5 crore:** File GSTR-9C with CA certificate

---

## 📱 Navigation Menu (Add to navbar.html)

```html
<!-- GST Menu -->
<li class="nav-item dropdown">
    <a class="nav-link dropdown-toggle" href="#" id="gstMenu" role="button" data-toggle="dropdown">
        GST
    </a>
    <div class="dropdown-menu">
        <a class="dropdown-item" href="{% url 'gst_dashboard' %}">📊 Dashboard</a>
        <div class="dropdown-divider"></div>
        <h6 class="dropdown-header">Returns</h6>
        <a class="dropdown-item" href="{% url 'gstr1_report' %}">GSTR-1</a>
        <a class="dropdown-item" href="{% url 'gstr3b_report' %}">GSTR-3B</a>
        <a class="dropdown-item" href="{% url 'gstr9_report' %}">GSTR-9</a>
        <div class="dropdown-divider"></div>
        <h6 class="dropdown-header">Purchases</h6>
        <a class="dropdown-item" href="{% url 'purchase_invoice_list' %}">Purchase Invoices</a>
        <a class="dropdown-item" href="{% url 'itc_ledger' %}">ITC Ledger</a>
        <div class="dropdown-divider"></div>
        <h6 class="dropdown-header">Compliance</h6>
        <a class="dropdown-item" href="{% url 'gstr2_reconciliation' %}">Reconciliation</a>
        <a class="dropdown-item" href="{% url 'compliance_tracker' %}">Compliance Tracker</a>
        <a class="dropdown-item" href="{% url 'audit_log_viewer' %}">Audit Logs</a>
        <a class="dropdown-item" href="{% url 'gst_analytics' %}">Analytics</a>
    </div>
</li>
```

---

## 📞 Quick Reference

### GST Rate Structure:
- 0% - Essential goods (grains, milk)
- 5% - Household necessities
- 12% - Processed foods
- 18% - Most goods & services (standard rate)
- 28% - Luxury items

### State Codes (Sample):
- 01 - Jammu and Kashmir
- 02 - Himachal Pradesh
- 07 - Delhi
- 09 - Uttar Pradesh
- 27 - Maharashtra
- 29 - Karnataka
- 33 - Tamil Nadu

### Filing Deadlines:
- GSTR-1: 11th of next month
- GSTR-3B: 20th of next month
- GSTR-9: 31st December (annual)

### Late Fees:
- GSTR-1: ₹200/day (max ₹10,000)
- GSTR-3B: ₹50/day (with tax) or ₹20/day (nil return)
- GSTR-9: ₹200/day (max 0.25% of turnover)

---

## ✅ Verification Checklist

After setup, verify:
- [ ] All migrations applied successfully
- [ ] Can access GST dashboard
- [ ] Can add purchase invoice
- [ ] GSTR-1 report generates
- [ ] GSTR-3B report generates
- [ ] CSV upload works
- [ ] Audit logs are created
- [ ] Charts display in analytics
- [ ] Navigation menu updated

---

## 🆘 Support

### Common GST Portal Links:
- **Main Portal:** https://www.gst.gov.in/
- **GSTR-1:** https://services.gst.gov.in/services/login
- **GSTR-2A:** Services → Returns → GSTR-2A
- **E-Invoice:** https://einvoice1.gst.gov.in/
- **E-Way Bill:** https://ewaybillgst.gov.in/

### Documentation:
- Django: https://docs.djangoproject.com/
- Chart.js: https://www.chartjs.org/docs/
- Bootstrap: https://getbootstrap.com/docs/4.4/

---

## 🎉 You're Ready!

Your GST Filing & Auditing system is now ready to use. Start by:
1. ✅ Running migrations
2. ✅ Adding sample data
3. ✅ Testing report generation
4. ✅ Exploring analytics

**Happy GST Compliance! 🚀**
