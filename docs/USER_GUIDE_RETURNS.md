# 🚀 Quick Start Guide - Invoice Return System

## 📋 NEW FEATURES ADDED

### 1. **Return Invoices** 🔄
**Purpose:** When customers return products

**Access:** 
- Navbar: **Invoices** → **Return Invoices**
- Direct: http://127.0.0.1:8000/returns/
- From Invoice: Click **"Create Return"** button on any invoice

**Key Features:**
- Link to parent invoice
- Track available vs returned quantities
- Auto-restore inventory
- Auto-credit customer balance
- Print credit notes

---

### 2. **Customer Payments** 💰
**Purpose:** Record customer payments

**Access:**
- Navbar: **Customers** → **Payments**
- Direct: http://127.0.0.1:8000/customers/payments/

**Key Features:**
- Multiple payment modes (Cash, Cheque, UPI, Online, Card)
- Reference number tracking
- Auto-update customer balance
- Notes field

---

### 3. **Customer Discounts** 🏷️
**Purpose:** Give discounts/credit notes

**Access:**
- Navbar: **Customers** → **Discounts**
- Direct: http://127.0.0.1:8000/customers/discounts/

**Key Features:**
- Multiple discount types
- Mandatory reason
- Auto-update customer balance
- Notes field

---

## 🎯 USAGE EXAMPLES

### **Scenario 1: Customer Returns Defective Product**
```
1. Customer bought 10 items in Invoice #123
2. Returns 3 defective items

Steps:
→ Open Invoice #123
→ Click "Create Return"
→ Select 3 items, mark as "Defective/Damaged"
→ Add reason: "Product not working"
→ Submit

Result:
✅ Inventory +3 items
✅ Customer balance credited ₹(price × 3)
✅ BookLog created (type=3: Returned Items)
✅ InventoryLog created (type=3: Return)
```

---

### **Scenario 2: Customer Makes Payment**
```
1. Customer owes ₹10,000
2. Pays ₹5,000 via UPI

Steps:
→ Customers → Payments → Add Payment
→ Select customer
→ Amount: 5000
→ Payment Mode: UPI
→ Reference: UPI TXN ID
→ Submit

Result:
✅ Customer balance reduced by ₹5,000
✅ Now owes ₹5,000
✅ BookLog created (type=0: Paid)
```

---

### **Scenario 3: Give Settlement Discount**
```
1. Customer owes ₹8,000
2. Give ₹1,000 discount for early settlement

Steps:
→ Customers → Discounts → Add Discount
→ Select customer
→ Amount: 1000
→ Type: Settlement Discount
→ Reason: "Early payment settlement"
→ Submit

Result:
✅ Customer balance reduced by ₹1,000
✅ Now owes ₹7,000
✅ BookLog created (type=4: Other)
```

---

## 📊 CUSTOMER BALANCE TRACKING

### **How Balances Work:**
- **Negative Balance** = Customer owes you money (debt)
- **Positive Balance** = Customer has credit/overpaid
- **Zero Balance** = All cleared

### **Transactions Effect on Balance:**
```
Invoice Sale:     Balance -= invoice_amount  (increases debt)
Return:           Balance += return_amount   (reduces debt)
Payment:          Balance += payment_amount  (reduces debt)
Discount:         Balance += discount_amount (reduces debt)
```

### **Example Flow:**
```
Start:           Balance = 0
Invoice ₹10,000: Balance = -10,000 (owes ₹10,000)
Payment ₹5,000:  Balance = -5,000  (owes ₹5,000)
Return ₹2,000:   Balance = -3,000  (owes ₹3,000)
Discount ₹1,000: Balance = -2,000  (owes ₹2,000)
Payment ₹2,000:  Balance = 0       (cleared)
```

---

## 🔍 NAVIGATION GUIDE

### **Updated Navbar:**
```
Invoices ▼
  ├─ New Invoice
  ├─ All Invoices
  ├─ Non-GST Invoices
  └─ Return Invoices ← NEW

Customers ▼
  ├─ All Customers
  ├─ Add Customer
  └─ Transactions:
      ├─ Payments ← NEW
      └─ Discounts ← NEW
```

---

## 📱 IMPORTANT URLS

### **Return Invoices:**
- List: `/returns/`
- Create: `/returns/create/<invoice_id>/`
- View: `/returns/<return_id>/`
- Print: `/returns/<return_id>/print/`

### **Payments:**
- List: `/customers/payments/`
- Add: `/customers/payments/add/`
- For specific customer: `/customers/payments/add/<customer_id>/`

### **Discounts:**
- List: `/customers/discounts/`
- Add: `/customers/discounts/add/`
- For specific customer: `/customers/discounts/add/<customer_id>/`

---

## ⚠️ IMPORTANT NOTES

### **Return Invoice:**
- Can only return up to available quantity
- Cannot return more than purchased
- Return date must be after invoice date
- Auto-updates inventory and customer book

### **Payments:**
- Amount must be positive
- Multiple payment modes available
- Optional reference number for tracking

### **Discounts:**
- Reason is mandatory
- Multiple discount types available
- Use "Credit Note" type for formal credit notes

---

## 🐛 TROUBLESHOOTING

### **Problem: Cannot create return**
**Solution:** Check if items were already fully returned. View original invoice to see available quantities.

### **Problem: Balance not updating**
**Solution:** Check `inventory_reflected` and `books_reflected` flags in return invoice detail. Both should be True.

### **Problem: Payment not appearing**
**Solution:** Check customer's book logs at Books → Select Customer → View Logs. Look for type=0 (Paid).

---

## 📞 SUPPORT

For issues or questions about the return system:
1. Check [INVOICE_RETURN_SYSTEM_ANALYSIS.md](INVOICE_RETURN_SYSTEM_ANALYSIS.md) for detailed technical docs
2. Check [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for complete implementation details
3. Review BookLog and InventoryLog entries in admin panel for debugging

---

**Last Updated:** December 12, 2025  
**Version:** 1.0  
**Status:** Production Ready ✅
