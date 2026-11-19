/**
 * Toasts do backoffice.
 *
 * - Mostra os toasts renderizados pelo Django (mensagens de `messages`) que
 *   estão em #ipixToastContainer com [data-ipix-toast].
 * - Expõe window.ipixToast(mensagem, variante) para feedback em scripts de
 *   página (substitui alert()). Variantes: success | danger | warning | info.
 *
 * A mensagem entra via textContent (nunca innerHTML).
 */
(function () {
  'use strict';

  var VARIANTES = ['success', 'danger', 'warning', 'info', 'primary', 'secondary'];
  var PERSISTENTES = ['danger', 'warning'];
  var ATRASO_MS = 6000;

  function container() {
    var el = document.getElementById('ipixToastContainer');
    if (el) {
      return el;
    }
    el = document.createElement('div');
    el.id = 'ipixToastContainer';
    el.className = 'toast-container ipix-toast-container position-fixed top-0 end-0 p-3';
    el.setAttribute('aria-live', 'polite');
    el.setAttribute('aria-atomic', 'false');
    document.body.appendChild(el);
    return el;
  }

  function mostrar(toastEl) {
    if (!window.bootstrap || !window.bootstrap.Toast) {
      toastEl.classList.add('show');
      return;
    }
    var toast = window.bootstrap.Toast.getOrCreateInstance(toastEl);
    toastEl.addEventListener('hidden.bs.toast', function () {
      toastEl.remove();
    });
    toast.show();
  }

  function ipixToast(mensagem, variante) {
    var tipo = VARIANTES.indexOf(variante) >= 0 ? variante : 'info';
    var persistente = PERSISTENTES.indexOf(tipo) >= 0;

    var toastEl = document.createElement('div');
    toastEl.className = 'toast align-items-center border-0 text-bg-' + tipo;
    toastEl.setAttribute('role', persistente ? 'alert' : 'status');
    toastEl.setAttribute('aria-live', persistente ? 'assertive' : 'polite');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.setAttribute('data-bs-autohide', persistente ? 'false' : 'true');
    toastEl.setAttribute('data-bs-delay', String(ATRASO_MS));

    var linha = document.createElement('div');
    linha.className = 'd-flex';

    var corpo = document.createElement('div');
    corpo.className = 'toast-body';
    corpo.textContent = mensagem == null ? '' : String(mensagem);

    var fechar = document.createElement('button');
    fechar.type = 'button';
    fechar.className = 'btn-close me-2 m-auto' + (tipo === 'warning' ? '' : ' btn-close-white');
    fechar.setAttribute('data-bs-dismiss', 'toast');
    fechar.setAttribute('aria-label', 'Fechar');

    linha.appendChild(corpo);
    linha.appendChild(fechar);
    toastEl.appendChild(linha);
    container().appendChild(toastEl);
    mostrar(toastEl);
    return toastEl;
  }

  function iniciar() {
    document.querySelectorAll('#ipixToastContainer [data-ipix-toast]').forEach(mostrar);
  }

  window.ipixToast = ipixToast;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
