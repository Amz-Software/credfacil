/**
 * Solicitações de Crédito: filtro de lojas, cartões de status (clique filtra e
 * os números se atualizam a cada 15 s), cronômetros e modal do QR code.
 * Valores do servidor: #kpi-row (data-current-status, data-kpis-url) e o
 * json_script #statusChoices.
 */
(function () {
  'use strict';

  var INTERVALO_KPIS_MS = 15000;
  var INTERVALO_CRONOMETRO_MS = 1000;
  var FEEDBACK_COPIA_MS = 2000;
  var STATUS_FINAIS = ['A', 'R', 'C'];

  function iniciarFiltroDeLojas() {
    if (!(window.jQuery && jQuery.fn.select2)) return;
    var select = jQuery('.select2-lojas');
    select.select2({ placeholder: select.data('placeholder'), width: '100%', allowClear: true });
  }

  function iniciarCartoesDeStatus() {
    var linha = document.getElementById('kpi-row');
    if (!linha) return;
    var statusAtual = linha.dataset.currentStatus || '';
    var cartoes = document.querySelectorAll('.kpi-card');

    cartoes.forEach(function (cartao) {
      cartao.classList.toggle('border-primary', cartao.dataset.status === statusAtual);
      cartao.addEventListener('click', function () {
        var url = new URL(window.location);
        if (url.searchParams.get('status') === cartao.dataset.status) {
          url.searchParams.delete('status'); // clicar de novo limpa o filtro
        } else {
          url.searchParams.set('status', cartao.dataset.status);
        }
        window.location = url.toString();
      });
    });

    var elementoStatus = document.getElementById('statusChoices');
    var urlKpis = linha.dataset.kpisUrl;
    if (!elementoStatus || !urlKpis) return;
    var statusChoices = JSON.parse(elementoStatus.textContent);

    function atualizar() {
      fetch(urlKpis, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (dados) {
          statusChoices.forEach(function (par) {
            var el = document.getElementById('kpi-' + par[0]);
            if (el) el.textContent = dados[par[0]] || 0;
          });
        })
        .catch(function () { /* mantém os números atuais até a próxima tentativa */ });
    }
    atualizar();
    setInterval(atualizar, INTERVALO_KPIS_MS);
  }

  function formatarDuracao(ms) {
    var total = Math.max(0, Math.floor(ms / 1000));
    var dias = Math.floor(total / 86400);
    var hh = String(Math.floor((total % 86400) / 3600)).padStart(2, '0');
    var mm = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
    var ss = String(total % 60).padStart(2, '0');
    return (dias > 0 ? dias + 'd ' : '') + hh + ':' + mm + ':' + ss;
  }

  function atualizarCronometros() {
    var agora = Date.now();
    document.querySelectorAll('.cronometro').forEach(function (el) {
      var inicio = el.getAttribute('data-start');
      var fim = el.getAttribute('data-end');
      if (!inicio) { el.textContent = '—'; return; }
      var comeco = new Date(inicio).getTime();
      var terminou = STATUS_FINAIS.indexOf(el.getAttribute('data-status')) >= 0 && fim;
      el.textContent = formatarDuracao((terminou ? new Date(fim).getTime() : agora) - comeco);
    });
  }

  function iniciarTooltips() {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
      new bootstrap.Tooltip(el, { html: true, sanitize: false });
    });
  }

  function iniciarModaisDeQrCode() {
    document.querySelectorAll('[id^="installModal"]').forEach(function (modal) {
      var qr = modal.querySelector('.qr-image');
      modal.addEventListener('show.bs.modal', function () {
        modal.querySelector('.modal-content').classList.add('modal-opening');
        if (qr) setTimeout(function () { qr.classList.add('qr-image--pulsando'); }, 300);
      });
      modal.addEventListener('hidden.bs.modal', function () {
        modal.querySelector('.modal-content').classList.remove('modal-opening');
        if (qr) qr.classList.remove('qr-image--pulsando');
      });
    });

    document.querySelectorAll('.code-display').forEach(function (caixa) {
      if (caixa.querySelector('.toggle-password')) return; // senha: não copia
      var texto = caixa.querySelector('span');
      if (!texto) return;
      caixa.classList.add('code-display--copiavel');
      caixa.title = 'Clique para copiar o código';
      caixa.addEventListener('click', function () {
        var codigo = texto.textContent;
        if (!navigator.clipboard || codigo === 'Código não disponível') return;
        navigator.clipboard.writeText(codigo).then(function () {
          texto.textContent = 'Código copiado!';
          caixa.classList.add('code-display--copiado');
          setTimeout(function () {
            texto.textContent = codigo;
            caixa.classList.remove('code-display--copiado');
          }, FEEDBACK_COPIA_MS);
        });
      });
    });
  }

  function iniciar() {
    iniciarFiltroDeLojas();
    iniciarCartoesDeStatus();
    atualizarCronometros();
    setInterval(atualizarCronometros, INTERVALO_CRONOMETRO_MS);
    iniciarTooltips();
    iniciarModaisDeQrCode();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
