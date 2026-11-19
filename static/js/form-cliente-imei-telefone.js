/**
 * Edição de IMEI/telefone da solicitação
 * (vendas/templates/cliente/form_cliente_imei_telefone.html).
 *
 * Dados do Django chegam em #clienteFormDados:
 *   data-produtos            → JSON com produtos (valor, entrada, marca_id)
 *   data-parcelamentos       → JSON com Parcelamento por marca
 *   data-entrada-informada   → entrada digitada pelo operador (pode vir vazia)
 *
 * Mostra entrada/total/parcela com o mesmo cálculo de gerar_venda (juros do
 * Parcelamento da marca) e trata o botão "Aprovar" (salva antes de aprovar).
 */
(function () {
  'use strict';

  function lerJson(texto) {
    if (!texto) return [];
    try {
      var valor = JSON.parse(texto);
      return Array.isArray(valor) ? valor : [];
    } catch (e) {
      return [];
    }
  }

  function formatBRL(v) {
    return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  }

  function iniciarResumoDeValores(dados) {
    var $ = window.jQuery;
    var produtos = lerJson(dados.getAttribute('data-produtos'));
    var parcelamentos = lerJson(dados.getAttribute('data-parcelamentos'));
    var entradaInformada = parseFloat(dados.getAttribute('data-entrada-informada'));

    function atualizaInfo() {
      var prodId = $('#id_produto').val();
      var np = $('#id_numero_parcelas').val();

      if (!prodId) {
        $('#info-entrada, #info-total, #info-parcela').text('—');
        return;
      }

      var p = produtos.find(function (x) { return String(x.id) === String(prodId); }) || {};
      var valorBase = p.valor || 0;
      var entrada = !isNaN(entradaInformada) ? entradaInformada : (p.entrada || 0);
      $('#info-entrada').text(formatBRL(entrada));

      var parcelas = parseInt(np, 10);
      if (!np || isNaN(parcelas)) {
        $('#info-total').text('—');
        $('#info-parcela').text('—');
        return;
      }

      var parc = parcelamentos.find(function (x) {
        return String(x.marca_id) === String(p.marca_id) && x.qtd_vezes === parcelas;
      });
      if (!parc) {
        $('#info-total').text('Parcelamento ' + np + 'x não cadastrado para esta marca');
        $('#info-parcela').text('—');
        return;
      }

      var valorFinanciado = Math.max(valorBase - entrada, 0);
      var total = valorFinanciado + (valorFinanciado * parc.porcentagem_juros / 100);
      $('#info-total').text(formatBRL(total));
      $('#info-parcela').text(np + '× de ' + formatBRL(total / parcelas));
    }

    $('#id_produto').on('change select2:select', atualizaInfo);
    $('#id_numero_parcelas').on('change', atualizaInfo);
    atualizaInfo();
  }

  // Aprovar: salva o formulário e o servidor aprova logo depois
  // (campo oculto aprovar_apos_salvar).
  function iniciarAprovar() {
    var aprovarBtn = document.getElementById('aprovarBtn');
    var form = document.getElementById('clienteForm');
    if (!aprovarBtn || !form) return;

    aprovarBtn.addEventListener('click', function (e) {
      e.preventDefault();
      form.querySelectorAll('input[name="aprovar_apos_salvar"]').forEach(function (input) {
        input.remove();
      });
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = 'aprovar_apos_salvar';
      hidden.value = aprovarBtn.getAttribute('data-url');
      form.appendChild(hidden);

      if (form.requestSubmit) {
        form.requestSubmit();
      } else if (form.checkValidity()) {
        form.submit();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var dados = document.getElementById('clienteFormDados');
    if (dados && window.jQuery) {
      iniciarResumoDeValores(dados);
    }
    iniciarAprovar();
  });
})();
