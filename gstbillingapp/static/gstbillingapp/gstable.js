/* =====================================================================
   gstable.js — tiny vanilla table enhancer (replaces jQuery DataTables)
   Client-side search + sortable columns + pagination + CSV/print export.
   Zero dependencies. Works on any <table> whose rows live in <tbody>.

   Usage:
     var t = GSTable.enhance('#my-table', {
        pageSize: 25,
        search: true,            // build a search box (or pass searchInput)
        searchInput: '#mySearch',// use an existing input instead
        sort: true,              // click-to-sort headers (data-nosort to skip a th)
        exportCsv: true, print: true,
        exportName: 'book-logs',
        printTitle: 'Book logs', printSubtitle: '...'
     });
     t.getVisibleRows();  // rows matching the current search (all pages)
     t.exportCSV(); t.print(); t.refresh();

   A cell may carry data-order="<number>" for correct numeric sorting
   (mirrors DataTables' data-order), otherwise text is compared.
   ===================================================================== */
(function (w) {
  'use strict';

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function text(node) { return (node.textContent || '').trim(); }
  function cellSortVal(td) {
    if (td.hasAttribute('data-order')) {
      var n = parseFloat(td.getAttribute('data-order'));
      if (!isNaN(n)) return n;
    }
    var t = text(td);
    var num = parseFloat(t.replace(/[^0-9.\-]/g, ''));
    // only treat as numeric if the cell is essentially a number
    if (t !== '' && !isNaN(num) && /^[₹$\s]*-?[0-9,.]+%?$/.test(t)) return num;
    return t.toLowerCase();
  }

  function enhance(target, opts) {
    var table = typeof target === 'string' ? document.querySelector(target) : target;
    if (!table) return null;
    opts = opts || {};
    var pageSize = opts.pageSize || 25;
    var tbody = table.tBodies[0];
    if (!tbody) return null;
    var allRows = Array.prototype.slice.call(tbody.rows);
    var filtered = allRows.slice();
    var page = 1;
    var sortCol = -1, sortDir = 1;

    // ---- toolbar (search + export/print) --------------------------------
    var searchInput = null;
    var toolbar = null;
    if (opts.searchInput) {
      searchInput = typeof opts.searchInput === 'string'
        ? document.querySelector(opts.searchInput) : opts.searchInput;
    }
    var needToolbar = (opts.search !== false && !searchInput) || opts.exportCsv || opts.print;
    if (needToolbar) {
      toolbar = el('div', 'gstable-bar');
      if (opts.search !== false && !searchInput) {
        var box = el('div', 'search');
        box.innerHTML = '<i class="fas fa-search"></i>';
        searchInput = el('input');
        searchInput.type = 'search';
        searchInput.placeholder = opts.searchPlaceholder || 'Search…';
        box.appendChild(searchInput);
        toolbar.appendChild(box);
      }
      var spacer = el('div', 'gstable-bar-sp'); toolbar.appendChild(spacer);
      if (opts.exportCsv) {
        var bCsv = el('button', 'gbtn', '<i class="fas fa-file-csv"></i> Excel/CSV');
        bCsv.type = 'button';
        bCsv.addEventListener('click', function () { api.exportCSV(); });
        toolbar.appendChild(bCsv);
      }
      if (opts.print) {
        var bPr = el('button', 'gbtn', '<i class="fas fa-print"></i> Print');
        bPr.type = 'button';
        bPr.addEventListener('click', function () { api.print(); });
        toolbar.appendChild(bPr);
      }
      // place the toolbar just above the table's card/element
      var host = table.closest('.tablecard') || table;
      host.parentNode.insertBefore(toolbar, host);
    }

    // ---- footer (info + pager) ------------------------------------------
    var foot = el('div', 'gstable-foot');
    var info = el('div', 'gstable-info');
    var pager = el('div', 'gstable-pager');
    foot.appendChild(info); foot.appendChild(pager);
    var footHost = table.closest('.tablecard') || table;
    footHost.parentNode.insertBefore(foot, footHost.nextSibling);

    // ---- sortable headers ------------------------------------------------
    if (opts.sort !== false) {
      var heads = table.tHead ? table.tHead.rows[table.tHead.rows.length - 1].cells : [];
      Array.prototype.forEach.call(heads, function (th, i) {
        if (th.hasAttribute('data-nosort')) return;
        th.classList.add('gstable-sortable');
        th.addEventListener('click', function () {
          if (sortCol === i) sortDir = -sortDir; else { sortCol = i; sortDir = 1; }
          Array.prototype.forEach.call(heads, function (h) { h.removeAttribute('data-sortdir'); });
          th.setAttribute('data-sortdir', sortDir > 0 ? 'asc' : 'desc');
          doSort(); page = 1; render();
        });
      });
    }

    function doSort() {
      if (sortCol < 0) return;
      filtered.sort(function (a, b) {
        var av = cellSortVal(a.cells[sortCol]), bv = cellSortVal(b.cells[sortCol]);
        if (av < bv) return -1 * sortDir;
        if (av > bv) return 1 * sortDir;
        return 0;
      });
    }

    function applyFilter() {
      var q = (searchInput && searchInput.value || '').trim().toLowerCase();
      if (!q) { filtered = allRows.slice(); }
      else {
        filtered = allRows.filter(function (r) { return text(r).toLowerCase().indexOf(q) !== -1; });
      }
      doSort();
    }

    function render() {
      var total = filtered.length;
      var pages = Math.max(1, Math.ceil(total / pageSize));
      if (page > pages) page = pages;
      var start = (page - 1) * pageSize;
      var end = Math.min(start + pageSize, total);
      // hide all, show current page slice
      allRows.forEach(function (r) { r.style.display = 'none'; });
      for (var i = start; i < end; i++) filtered[i].style.display = '';
      // reorder DOM to reflect sort within the visible slice
      for (var j = start; j < end; j++) tbody.appendChild(filtered[j]);
      // info
      info.textContent = total ? ('Showing ' + (start + 1) + '–' + end + ' of ' + total) : 'No records';
      // pager
      pager.innerHTML = '';
      if (pages > 1) {
        var mk = function (label, target, disabled, active) {
          var b = el('button', 'gstable-pg' + (active ? ' active' : ''), label);
          b.type = 'button';
          if (disabled) b.disabled = true;
          else b.addEventListener('click', function () { page = target; render(); });
          pager.appendChild(b);
        };
        mk('‹', page - 1, page === 1);
        var from = Math.max(1, page - 2), to = Math.min(pages, from + 4);
        from = Math.max(1, to - 4);
        if (from > 1) { mk('1', 1, false, page === 1); if (from > 2) pager.appendChild(el('span', 'gstable-gap', '…')); }
        for (var p = from; p <= to; p++) mk(String(p), p, false, p === page);
        if (to < pages) { if (to < pages - 1) pager.appendChild(el('span', 'gstable-gap', '…')); mk(String(pages), pages, false, page === pages); }
        mk('›', page + 1, page === pages);
      }
    }

    if (searchInput) {
      searchInput.addEventListener('input', function () { applyFilter(); page = 1; render(); });
    }

    // ---- export / print --------------------------------------------------
    // columns whose header th carries data-noexport are dropped from CSV/print
    function exportCols() {
      var keep = [];
      if (table.tHead) {
        var hr = table.tHead.rows[table.tHead.rows.length - 1];
        Array.prototype.forEach.call(hr.cells, function (th, i) {
          if (!th.hasAttribute('data-noexport')) keep.push(i);
        });
      }
      return keep;
    }
    function headerLabels() {
      var cols = exportCols(), out = [];
      if (table.tHead) {
        var hr = table.tHead.rows[table.tHead.rows.length - 1];
        cols.forEach(function (i) { if (hr.cells[i]) out.push(text(hr.cells[i])); });
      }
      return out;
    }
    function rowValues(r) {
      return exportCols().map(function (i) { return r.cells[i] ? text(r.cells[i]) : ''; });
    }
    var api = {
      getVisibleRows: function () { return filtered.slice(); },
      refresh: function () { allRows = Array.prototype.slice.call(tbody.rows); applyFilter(); render(); },
      exportCSV: function () {
        var rows = [headerLabels()].concat(filtered.map(rowValues));
        var csv = rows.map(function (r) {
          return r.map(function (c) {
            c = (c == null ? '' : String(c));
            return /[",\n]/.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c;
          }).join(',');
        }).join('\r\n');
        var blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (opts.exportName || 'export') + '.csv';
        document.body.appendChild(a); a.click();
        setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(a.href); }, 100);
      },
      print: function () {
        var win = window.open('', '_blank');
        if (!win) { alert('Please allow pop-ups to print.'); return; }
        var heads = headerLabels();
        var body = filtered.map(function (r, i) {
          return '<tr><td style="text-align:center">' + (i + 1) + '</td>' +
            rowValues(r).map(function (c) { return '<td>' + (c || '') + '</td>'; }).join('') + '</tr>';
        }).join('') || '<tr><td colspan="' + (heads.length + 1) + '" style="text-align:center;color:#666;padding:16px">No records.</td></tr>';
        var doc = '<html><head><title>' + (opts.printTitle || 'Print') + '</title><style>' +
          'body{font-family:Arial,Helvetica,sans-serif;margin:16px;color:#111}' +
          'h2{margin:0}p.sub{margin:4px 0 12px;color:#666;font-size:13px}' +
          'table{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}' +
          'th,td{border:1px solid #ddd;padding:8px;text-align:left}thead th{background:#343a40;color:#fff}' +
          '@media print{@page{size:A4 landscape;margin:8mm}}</style></head><body>' +
          (opts.printHeadHtml ||
            ('<h2>' + (opts.printTitle || '') + '</h2>' +
             (opts.printSubtitle ? '<p class="sub">' + opts.printSubtitle + '</p>' : ''))) +
          '<table><thead><tr><th style="text-align:center">S.No</th>' +
          heads.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
          '</tr></thead><tbody>' + body + '</tbody></table></body></html>';
        win.document.open(); win.document.write(doc); win.document.close(); win.focus();
        setTimeout(function () { win.print(); win.close(); }, 300);
      }
    };

    applyFilter(); render();
    return api;
  }

  w.GSTable = { enhance: enhance };
})(window);
