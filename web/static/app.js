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

  // Limite rígido de 30 termos por caixa de texto (colagem inclusive).
  document.querySelectorAll('textarea[data-limit]').forEach(function (ta) {
    if (!ta.value.trim()) return;
    var max = parseInt(ta.getAttribute('data-limit'), 10) || 30;
    var path = ta.getAttribute('data-path');
    var counter = path && document.querySelector('.counter[data-for="' + path + '"]');
    function enforce() {
      var lines = ta.value.split('\n');
      var seen = Object.create(null);
      var kept = [];
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        if (!line) continue;
        var key = line.toLowerCase();
        if (seen[key]) continue;
        seen[key] = true;
        kept.push(line);
      }
      if (kept.length > max) kept = kept.slice(0, max);
      var next = kept.join('\n');
      if (ta.value !== next) ta.value = next;
      if (counter) counter.textContent = kept.length + ' de ' + max + ' termos · um por linha · o 31º é descartado';
    }
    ta.addEventListener('input', enforce);
    ta.addEventListener('paste', function () { window.setTimeout(enforce, 0); });
    enforce();
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
