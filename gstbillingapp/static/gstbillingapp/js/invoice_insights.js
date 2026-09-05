/* =====================================================================
   invoice_insights.js — business-smart insights for the invoice &
   quotation creators (shared). Vanilla JS, no jQuery.
     Group A: know-your-customer panel (balance, dues, credit, usual items)
     Group B: per-line checks (qty, stock, below-cost, last-price)
     Group C: today's tally (only if #today-summary-strip exists)
   All selectors are optional — the script no-ops for any panel a page omits,
   so the same file drives invoice_create, quotation_create & quotation_edit.
   ===================================================================== */
(function () {
    var productsMap = {};      // MODEL_NO -> product (incl. current_stock, product_purchase_rate)
    var customerInsights = null;
    var activeRowNo = null;    // only THIS row's detail is shown, so the list can't grow

    function $id(id) { return document.getElementById(id); }
    function show(el) { if (el) el.style.display = ''; }
    function hide(el) { if (el) el.style.display = 'none'; }
    function rowIndexOf(tr) { return tr ? Array.prototype.indexOf.call(tr.parentNode.children, tr) : -1; }
    function fmt(n) {
        return (Number(n) || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // ---- Group C: today's tally + this-month GST (only if the strip is present) ----
    function loadTodaySummary() {
        if (!$id('today-summary-strip')) return;
        fetch('/api/today-summary/').then(function (r) { return r.json(); }).then(function (d) {
            if (!d || !d.ok) return;
            var strip = $id('today-summary-strip');
            if (strip) strip.innerHTML =
                '<span class="badge badge-info">Today: ' + d.invoice_count + ' invoice(s)</span>' +
                '<span class="badge badge-secondary">Sales &#8377;' + fmt(d.sales_total) + '</span>' +
                '<span class="badge badge-success">Collected &#8377;' + fmt(d.collections_total) + '</span>' +
                '<span class="badge badge-warning">GST ' + d.gst_month_label + ' &#8377;' + fmt(d.gst_month) + '</span>';
        }).catch(function () {});
    }

    // ---- product catalogue (adds stock + purchase cost for Group B) ----
    function loadProducts() {
        fetch('/productsjson').then(function (r) { return r.json(); }).then(function (rows) {
            (rows || []).forEach(function (p) {
                if (p.model_no) productsMap[String(p.model_no).toUpperCase()] = p;
            });
            recomputeItemAlerts();
        }).catch(function () {});
    }

    // ---- Group A: know-your-customer panel ----
    function loadCustomerInsights() {
        var cidInput = $id('customer-id-input');
        var cid = cidInput ? cidInput.value : '';
        if (!cid) { hide($id('customer-insights-panel')); customerInsights = null; recomputeItemAlerts(); return; }
        fetch('/api/customer-insights/?customer=' + encodeURIComponent(cid)).then(function (r) { return r.json(); }).then(function (d) {
            if (!d || !d.ok) { hide($id('customer-insights-panel')); return; }
            customerInsights = d;
            renderCustomerPanel(d);
            recomputeItemAlerts();
        }).catch(function () {});
    }

    function renderCustomerPanel(d) {
        if (!$id('customer-insights-panel')) return;
        var bal = $id('ci-balance');
        if (bal) {
            bal.classList.remove('badge-danger', 'badge-success', 'badge-secondary');
            bal.classList.add(d.status === 'owes' ? 'badge-danger' : (d.status === 'advance' ? 'badge-success' : 'badge-secondary'));
            bal.textContent = d.balance_label;
        }

        var aging = $id('ci-aging');
        if (d.oldest_unpaid_days !== null && d.oldest_unpaid_days !== undefined) {
            if (aging) { show(aging); aging.textContent = 'Oldest due: ' + d.oldest_unpaid_days + ' days'; }
        } else hide(aging);

        var cheque = $id('ci-cheque');
        if (d.bounced_cheques > 0) { if (cheque) { show(cheque); cheque.textContent = '⚑ ' + d.bounced_cheques + ' bounced cheque(s)'; } }
        else hide(cheque);

        var coll = $id('ci-collection'); if (coll) coll.textContent = 'Collections: ' + d.collection_day;
        var lastpay = $id('ci-lastpay'); if (lastpay) lastpay.textContent = d.last_payment ? ('Last paid ₹' + fmt(d.last_payment.amount) + ' on ' + d.last_payment.date) : '';
        var lastorder = $id('ci-lastorder'); if (lastorder) lastorder.textContent = d.last_order ? ('· Last order ' + d.last_order.days_ago + 'd ago (₹' + fmt(d.last_order.amount) + ')') : '';

        renderCreditBadge();
        renderUsualChips(d.usual_items);

        var border = d.status === 'owes' ? '#dc3545' : (d.status === 'advance' ? '#28a745' : '#6c757d');
        var panel = $id('customer-insights-panel');
        if (panel) { panel.style.borderLeftColor = border; show(panel); }
    }

    // Credit headroom depends on the live invoice total, so it re-renders on grid changes too.
    function renderCreditBadge() {
        var c = $id('ci-credit');
        if (!c) return;
        if (!customerInsights || customerInsights.credit_limit === null || customerInsights.credit_limit === undefined) { hide(c); return; }
        var totalInput = document.querySelector('input[name=invoice-total-amt-with-gst]');
        var invoiceTotal = totalInput ? (parseFloat(totalInput.value) || 0) : 0;
        var projected = customerInsights.outstanding + invoiceTotal;
        c.classList.remove('badge-danger', 'badge-success');
        if (projected > customerInsights.credit_limit) {
            c.classList.add('badge-danger'); c.textContent = '⚠ Over credit limit by ₹' + fmt(projected - customerInsights.credit_limit);
        } else {
            c.classList.add('badge-success'); c.textContent = 'Credit left ₹' + fmt(customerInsights.credit_limit - projected);
        }
        show(c);
    }

    function renderUsualChips(items) {
        if (!items || !items.length) { hide($id('ci-usual')); return; }
        var box = $id('ci-usual-chips');
        if (box) {
            box.innerHTML = '';
            items.forEach(function (it) {
                var a = document.createElement('a');
                a.href = '#'; a.className = 'badge badge-light border'; a.style.margin = '1px';
                a.textContent = '+ ' + it.model_no;
                a.addEventListener('click', function (e) { e.preventDefault(); fillUsualItem(it); });
                box.appendChild(a);
            });
        }
        show($id('ci-usual'));
    }

    function fillUsualItem(it) {
        var p = productsMap[String(it.model_no).toUpperCase()];
        if (!p) return;
        var rows = document.querySelectorAll('#invoice-form-items-table-body > tr');
        var row = null;
        rows.forEach(function (tr) {
            var mi = tr.querySelector('input[name=invoice-model-no]');
            if (!row && !(mi && mi.value)) row = tr;
        });
        if (!row) { add_invoice_item_row(); var all = document.querySelectorAll('#invoice-form-items-table-body > tr'); row = all[all.length - 1]; }
        function setv(name, val) { var el = row.querySelector('input[name=' + name + ']'); if (el) el.value = val; }
        setv('invoice-model-no', p.model_no);
        setv('invoice-product', p.product_name || '');
        setv('invoice-hsn', p.product_hsn || '');
        setv('invoice-rate-with-gst', p.product_rate_with_gst || 0);
        setv('invoice-gst-percentage', p.product_gst_percentage || 0);
        setv('invoice-discount', p.product_discount || 0);
        setv('invoice-qty', it.last_qty || 1);
        activeRowNo = rowIndexOf(row) + 1;
        if (typeof initialize_auto_calculation === 'function') initialize_auto_calculation();
        recomputeItemAlerts(); renderCreditBadge();
    }

    // ---- Group B: per-line qty / stock / margin / last-price checks ----
    function _val(r, name) { var el = r.querySelector('input[name=' + name + ']'); return el ? el.value : ''; }
    function evaluateRow(r) {
        var res = { severity: null, messages: [] };
        var model = (_val(r, 'invoice-model-no') || '').trim().toUpperCase();
        if (!model) return res;
        var qty = parseFloat(_val(r, 'invoice-qty')) || 0;
        var rate = parseFloat(_val(r, 'invoice-rate-with-gst')) || 0;
        var disc = parseFloat(_val(r, 'invoice-discount')) || 0;
        var p = productsMap[model];

        // Quantity must be positive — warn (but the row can still be saved).
        if (qty <= 0) {
            res.messages.push({ level: 'warning', text: model + ': quantity is ' + qty + ' — enter a valid quantity.' });
            if (res.severity !== 'danger') res.severity = 'warning';
        }
        if (p && p.current_stock !== null && p.current_stock !== undefined && qty > p.current_stock) {
            res.messages.push({ level: 'warning', text: model + ': qty ' + qty + ' exceeds stock (' + p.current_stock + ' left).' });
            if (res.severity !== 'danger') res.severity = 'warning';
        }
        if (p && p.product_purchase_rate > 0) {
            var eff = rate - (rate * disc / 100);
            if (eff > 0 && eff < p.product_purchase_rate) {
                res.messages.push({ level: 'danger', text: model + ': selling ₹' + fmt(eff) + ' below cost ₹' + fmt(p.product_purchase_rate) + '.' });
                res.severity = 'danger';
            }
        }
        if (customerInsights && customerInsights.product_last_prices && (model in customerInsights.product_last_prices)) {
            var lp = customerInsights.product_last_prices[model];
            if (Math.abs(lp - rate) > 0.01)
                res.messages.push({ level: 'info', text: model + ': last billed to this customer at ₹' + fmt(lp) + ' (now ₹' + fmt(rate) + ').' });
        }
        return res;
    }

    function recomputeItemAlerts() {
        var activeHtml = [];
        var dangerCount = 0, warnCount = 0;
        document.querySelectorAll('#invoice-form-items-table-body > tr').forEach(function (r, i) {
            var rowNo = i + 1;
            var res = evaluateRow(r);

            r.classList.remove('item-row-danger', 'item-row-warning');
            if (res.severity === 'danger') { r.classList.add('item-row-danger'); dangerCount++; }
            else if (res.severity === 'warning') { r.classList.add('item-row-warning'); warnCount++; }
            var warnMsgs = res.messages.filter(function (m) { return m.level !== 'info'; });
            r.setAttribute('title', warnMsgs.map(function (m) { return m.text; }).join('  '));

            if (rowNo === activeRowNo)
                res.messages.forEach(function (m) {
                    activeHtml.push('<div class="alert alert-' + m.level + ' py-1 px-2 mb-1 small">Row ' + rowNo + ' &mdash; ' + m.text + '</div>');
                });
        });

        var summary = '';
        if (dangerCount + warnCount > 0)
            summary = '<div class="small text-muted mb-1">'
                + (dangerCount ? '<span class="badge badge-danger">' + dangerCount + '</span> below-cost ' : '')
                + (warnCount ? '<span class="badge badge-warning">' + warnCount + '</span> to review ' : '')
                + 'row(s) flagged — highlighted in the grid; hover a row for details.</div>';
        var alerts = $id('item-alerts');
        if (alerts) alerts.innerHTML = summary + activeHtml.join('');
    }

    // expose for callers that want to force a refresh (e.g. row delete in main.js)
    window.recomputeItemAlerts = recomputeItemAlerts;

    document.addEventListener('DOMContentLoaded', function () {
        loadTodaySummary();
        loadProducts();

        document.addEventListener('click', function (e) {
            if (e.target.closest && e.target.closest('.customer-search-result')) setTimeout(loadCustomerInsights, 40);
        });
        var nameInput = $id('customer-name-input');
        if (nameInput) nameInput.addEventListener('input', function () {
            if (!this.value) { hide($id('customer-insights-panel')); customerInsights = null; recomputeItemAlerts(); }
        });

        var tbody = $id('invoice-form-items-table-body');
        if (tbody) ['focusin', 'input', 'change'].forEach(function (evt) {
            tbody.addEventListener(evt, function (e) {
                if (e.target && e.target.matches && e.target.matches('input')) {
                    activeRowNo = rowIndexOf(e.target.closest('tr')) + 1;
                    setTimeout(function () { recomputeItemAlerts(); renderCreditBadge(); }, 0);
                }
            });
        });
        var addrow = $id('invoice-form-addrow');
        if (addrow) addrow.addEventListener('click', function () { setTimeout(recomputeItemAlerts, 0); });
        document.addEventListener('click', function (e) {
            if (e.target.closest && e.target.closest('.product-search-result')) setTimeout(function () { recomputeItemAlerts(); renderCreditBadge(); }, 40);
        });

        // On quotation_edit the rows are pre-filled — run once so existing rows get checked.
        setTimeout(recomputeItemAlerts, 60);
        // If a customer is already selected (edit pages), load their insights on open.
        var cidInit = $id('customer-id-input');
        if (cidInit && cidInit.value) setTimeout(loadCustomerInsights, 80);
    });
})();
