// Utils mínimos: sem framework, sem CDN.
(function () {
  'use strict';

  // Confirmção para ações destrutivas / de execução.
  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    var msg = form.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) ev.preventDefault();
  });

  // Auto-submit ao alterar filtros.
  document.querySelectorAll('[data-auto-submit]').forEach(function (el) {
    el.addEventListener('change', function () { el.form.submit(); });
  });

  // Polling do log só enquanto a coleta está rodando (evita RAM/CPU no Pi).
  var box = document.getElementById('live-log');
  if (box && box.dataset.running === '1') {
    var every = window.setInterval(function () {
      fetch('/sistema/log', { credentials: 'same-origin' })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          var fresh = doc.getElementById('live-log');
          if (fresh) box.innerHTML = fresh.innerHTML;
          if (box.dataset.running !== '1') window.clearInterval(every);
        })
        .catch(function () {});
    }, 7000);
  }
})();
