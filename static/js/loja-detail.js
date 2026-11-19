/**
 * Detalhe da loja: texto do contrato, aba ativa lembrada por loja
 * (sessionStorage), envio do repasse com Enter e limpar filtro de datas.
 * O id da loja vem de #lojaTabs[data-loja-id].
 */
(function () {
  'use strict';

  function iniciarContrato() {
    var div = document.getElementById('texto_contrato');
    if (div && typeof formatarTexto === 'function') {
      formatarTexto(div.getAttribute('data-texto'), div);
    }
  }

  function iniciarAbas() {
    var abas = document.getElementById('lojaTabs');
    if (!abas) return;
    var chave = 'lojaDetailActiveTab_' + (abas.dataset.lojaId || '');

    var salva = null;
    try { salva = sessionStorage.getItem(chave); } catch (e) { /* armazenamento indisponível */ }
    if (salva) {
      var botao = abas.querySelector('button[data-bs-target="' + salva + '"]');
      if (botao) new bootstrap.Tab(botao).show();
    }

    function lembrar(alvo) {
      try { sessionStorage.setItem(chave, alvo); } catch (e) { /* armazenamento indisponível */ }
    }

    abas.querySelectorAll('button[data-bs-toggle="tab"]').forEach(function (btn) {
      btn.addEventListener('shown.bs.tab', function (e) { lembrar(e.target.getAttribute('data-bs-target')); });
    });

    var form = document.querySelector('#offcanvasRepasse form');
    if (!form) return;
    form.addEventListener('submit', function () {
      var ativa = abas.querySelector('button.active');
      if (ativa) lembrar(ativa.getAttribute('data-bs-target'));
    });
    // Enter envia o repasse a partir da observação (Shift+Enter quebra linha)
    var observacao = form.querySelector('textarea[name="observacao"]');
    if (observacao) {
      observacao.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' || e.shiftKey) return;
        e.preventDefault();
        if (typeof form.requestSubmit === 'function') form.requestSubmit(); else form.submit();
      });
    }
  }

  function iniciarLimparFiltro() {
    var limpar = document.getElementById('limparFiltro');
    if (!limpar) return;
    limpar.addEventListener('click', function () {
      ['data_inicio', 'data_fim'].forEach(function (id) {
        var campo = document.getElementById(id);
        if (campo) campo.value = '';
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    iniciarContrato();
    iniciarAbas();
    iniciarLimparFiltro();
  });
})();
