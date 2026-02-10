# Customer Order Edit Feature - Quick Reference

## 🎯 Overview
Customers can now edit their DRAFT orders by adding or removing products. Once an order is APPROVED or CONVERTED, editing is disabled.

---

## ✨ Features Added

### 1. **Edit Order View** (`customer_edit_order`)
- Displays product catalog with existing quantities pre-filled
- Only accessible for DRAFT status orders
- Shows search functionality
- Real-time cart update

### 2. **Update Order API** (`customer_update_order`)
- Updates quotation JSON with new items
- Recalculates totals (GST, CGST, SGST)
- Sends notification to business owner
- Prevents editing non-DRAFT orders

### 3. **Edit Restrictions**
- ✅ DRAFT orders: Full edit access
- ❌ APPROVED orders: Read-only
- ❌ CONVERTED orders: Read-only

---

## 🔗 New Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/mobile/v1/customer/order/<id>/edit` | GET | Show edit form |
| `/mobile/v1/customer/order/<id>/update` | POST | Save changes |

---

## 🎨 UI Updates

### Orders List Page:
- Added **"Edit"** button (yellow) for DRAFT orders
- Only visible when `status == 'DRAFT'`

### Order Detail Page:
- Added **"Edit Order"** button (blue) 
- Only visible when `can_edit == True`

### Order Edit Page:
- Product catalog with existing quantities
- Search functionality
- Real-time cart summary
- **Cancel** button (returns to detail)
- **Update Order** button (saves changes)

---

## 🔄 Workflow

```
Customer views order list
    ↓
Clicks "Edit" on DRAFT order
    ↓
Sees product catalog with current quantities
    ↓
Adds/removes products
    ↓
Clicks "Update Order"
    ↓
Confirmation prompt
    ↓
Order updated + notification sent
    ↓
Redirects to order detail
```

---

## 🔐 Security Features

1. **Status Validation**: Server-side check for DRAFT status
2. **Customer Ownership**: Validates customer owns the order
3. **Created By Customer**: Only customer-created orders can be edited
4. **CSRF Protection**: All POST requests protected
5. **Error Handling**: User-friendly error messages

---

## 📊 Data Flow

### Edit Order Request:
```python
GET /customer/order/123/edit?cid=<encoded>
```

### Update Order Request:
```javascript
POST /customer/order/123/update
Body: {
    cid: "GS-1-C-5",
    order_items: [
        {product_id: 10, quantity: 5, rate: 1180.00},
        {product_id: 15, quantity: 2, rate: 590.00}
    ]
}
```

### Response:
```json
{
    "success": true,
    "message": "Order #123 updated successfully!",
    "quotation_id": 123,
    "quotation_number": 123
}
```

---

## 🔔 Notifications

When order is updated:
```
Title: "Order Updated by [Customer Name]"
Message: "Order #123 updated to ₹5,900.00"
Link: "/quotation/123/"
Type: ORDER
```

---

## 🎯 User Experience

### Before Update:
- Order shows old items and total
- Status: DRAFT
- "Edit" button visible

### After Update:
- Order shows new items and total
- Status: Still DRAFT (approval needed)
- "Edit" button still visible
- Business receives notification

### After Approval:
- Order shows final items
- Status: APPROVED
- "Edit" button hidden
- No further changes allowed

---

## 🐛 Error Handling

| Scenario | Error Message |
|----------|---------------|
| Order not DRAFT | "Order cannot be edited. Only DRAFT orders can be modified." |
| No items in cart | "Please add at least one item to the order" |
| Invalid customer | "Invalid customer code" |
| Product not found | "Product not found" |

---

## 💡 Tips for Testing

1. **Create a DRAFT order** as customer
2. **Click "Edit"** from orders list or detail page
3. **Add/remove products** and verify cart updates
4. **Click "Update Order"** and confirm
5. **Verify notification** sent to business owner
6. **Check order detail** shows updated items
7. **Approve order** as business owner
8. **Verify "Edit" button** disappears

---

## 📱 Mobile UI Elements

### Edit Button Styles:
- **DRAFT orders**: Yellow warning button `btn-warning`
- **Confirmation**: Browser native confirm dialog
- **Loading state**: Spinner icon during save

### Cart Summary (Fixed Bottom):
- Left side: Cancel button (grey)
- Right side: Update Order button (green)
- Shows item count and total
- Disabled when cart is empty

---

## 🚀 Future Enhancements

- [ ] Order deletion (DRAFT only)
- [ ] Order duplication
- [ ] Minimum order value validation
- [ ] Product availability check
- [ ] Inline quantity edit on detail page
- [ ] Order notes/comments
- [ ] Track edit history

---

## 📋 Testing Checklist

- [ ] Can edit DRAFT order
- [ ] Cannot edit APPROVED order
- [ ] Cannot edit CONVERTED order
- [ ] Existing quantities pre-filled
- [ ] Can add new products
- [ ] Can remove products (set to 0)
- [ ] Cart updates in real-time
- [ ] Totals calculated correctly
- [ ] Notification sent on update
- [ ] Order detail shows changes
- [ ] Edit button visibility correct
- [ ] Cancel button works
- [ ] Confirmation dialog appears
- [ ] Error handling works

---

**Implementation Complete! ✅**

Customers can now freely edit their DRAFT orders, and the system automatically restricts editing once orders are approved or converted.
