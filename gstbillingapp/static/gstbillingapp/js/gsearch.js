/* Live search for server-rendered list toolbars.
 *
 * Every list page filters server-side on ?q=, but most toolbars have no Apply button,
 * so typing did nothing until you happened to press Enter — which read as "search is
 * broken". This makes any GET <form> that contains an <input name="q"> submit itself a
 * short debounce after typing (and immediately on Enter), then restores focus + caret
 * after the reload so typing stays seamless.
 *
 * Scope: only GET forms with a name="q" input. Client-side search widgets (the .gstable
 * enhancer, the Customer Analysis / Business Cockpit inputs) use their own inputs that are
 * NOT name="q" in a GET form, so they are left completely untouched. Opt a form out with
 * data-no-autosearch.
 */
(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var forms = document.querySelectorAll('form');
    for (var i = 0; i < forms.length; i++) {
      (function (form) {
        var method = (form.getAttribute('method') || 'get').toLowerCase();
        if (method !== 'get') return;                       // never auto-submit POST forms
        if (form.hasAttribute('data-no-autosearch')) return;
        var input = form.querySelector('input[name="q"]');
        if (!input) return;

        var timer = null;
        function submitNow() {
          if (form.requestSubmit) form.requestSubmit();
          else form.submit();
        }

        input.addEventListener('input', function (e) {
          if (e && e.isComposing) return;                   // don't fire mid IME composition
          clearTimeout(timer);
          timer = setTimeout(submitNow, 450);
        });
        // Enter should submit immediately (native), so just cancel the pending debounce.
        input.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') clearTimeout(timer);
        });

        // After a search-triggered reload the box already has a value — refocus it and
        // put the caret at the end so the user can keep typing without re-clicking.
        if (input.value) {
          try {
            input.focus({ preventScroll: true });
            var v = input.value;
            input.value = '';
            input.value = v;                                // moves caret to end
          } catch (_) {}
        }
      })(forms[i]);
    }
  });
})();
