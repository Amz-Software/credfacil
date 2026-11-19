/**
 * Comportamentos globais do layout (templates/base.html).
 * Antes ficavam em <script> inline no fim da página.
 */
(function () {
  'use strict';

  function definirBotoes(desabilitado) {
    document.querySelectorAll('button').forEach(function (botao) {
      botao.disabled = desabilitado;
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    // Garante que os dropdowns do Bootstrap funcionem em toda página.
    if (window.bootstrap && window.bootstrap.Dropdown) {
      document.querySelectorAll('[data-bs-toggle="dropdown"]').forEach(function (el) {
        try {
          window.bootstrap.Dropdown.getOrCreateInstance(el);
        } catch (e) { /* elemento sem menu associado */ }
      });
    }

    // Sempre habilita os botões ao carregar (ex.: volta com erros de validação).
    definirBotoes(false);

    // Voltar pelo histórico (bfcache) não recarrega a página.
    window.addEventListener('pageshow', function (evento) {
      if (evento.persisted) {
        definirBotoes(false);
      }
    });

    // Bloqueia cliques repetidos durante requisições AJAX e navegação.
    document.addEventListener('ajaxStart', function () { definirBotoes(true); });
    document.addEventListener('ajaxStop', function () { definirBotoes(false); });
    window.addEventListener('beforeunload', function () { definirBotoes(true); });
  });
})();
