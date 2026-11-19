/**
 * Edição de venda — compartilhado por venda/venda_edit.html e
 * venda/venda_edit_especial.html.
 *
 * - Tooltips da página.
 * - Linhas de produto (.produto-form): select2 de produto/IMEI, preço vindo
 *   de /info-products/, total com desconto e autorização de gerente quando
 *   o desconto passa de LIMITE_DESCONTO_PCT (#descontoModal).
 * - Linhas de pagamento (.pagamento-form): habilita parcelas conforme o tipo
 *   (/info-payment/) e calcula o valor da parcela.
 *
 * Erros de API viram toasts (window.ipixToast) — sem alert().
 * Depende de jQuery, jquery.mask e select2 (carregados pela página).
 */
(function () {
  'use strict';

  var LIMITE_DESCONTO_PCT = 15;

  function avisar(mensagem, variante) {
    if (window.ipixToast) {
      window.ipixToast(mensagem, variante || 'danger');
    }
  }

  function csrfToken() {
    var campo = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (campo && campo.value) {
      return campo.value;
    }
    return window.getCookie ? window.getCookie('csrftoken') || '' : '';
  }

  function obterJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (resposta) {
      if (!resposta.ok) {
        throw new Error('HTTP ' + resposta.status);
      }
      return resposta.json();
    });
  }

  /** Valor numérico de um campo com máscara de dinheiro (000.000,00). */
  function obterValorSemMascara(campo) {
    var $campo = window.jQuery(campo);
    var valor = typeof $campo.cleanVal === 'function' ? $campo.cleanVal() : String(campo.value || '').replace(/\D/g, '');
    if (valor === '') return undefined;
    return parseInt(valor, 10) / 100;
  }

  /* ---------------------------------------------------------------------
     Autorização de desconto acima do limite
     --------------------------------------------------------------------- */
  function abrirModalParaValidacao() {
    var modalEl = document.getElementById('descontoModal');
    if (!modalEl || !window.bootstrap) {
      return Promise.resolve(false);
    }
    var descontoModal = window.bootstrap.Modal.getOrCreateInstance(modalEl, { keyboard: false, backdrop: 'static' });
    var usuario = document.getElementById('username');
    var senha = document.getElementById('password');

    function limparCampos() {
      usuario.value = '';
      senha.value = '';
    }

    return new Promise(function (resolve) {
      document.getElementById('confirmarDesconto').onclick = function () {
        fetch('/autorizacao/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
          body: JSON.stringify({ username: usuario.value, password: senha.value }),
        })
          .then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
              if (!resposta.ok) {
                throw new Error(dados.message || 'Erro desconhecido');
              }
              return dados;
            });
          })
          .then(function (dados) {
            if (dados.success) {
              descontoModal.hide();
              limparCampos();
              resolve(true);
            } else {
              avisar('Autorização negada: ' + (dados.message || 'verifique usuário e senha.'), 'danger');
            }
          })
          .catch(function (erro) {
            avisar('Não foi possível validar a autorização: ' + erro.message, 'danger');
          });
      };

      document.getElementById('cancelarDesconto').onclick = function () {
        descontoModal.hide();
        limparCampos();
        resolve(false);
      };

      descontoModal.show();
    });
  }

  /* ---------------------------------------------------------------------
     Linha de produto
     --------------------------------------------------------------------- */
  function configurarProdutoForm(form) {
    var $ = window.jQuery;
    var produtoSelect = form.querySelector('select[name$="-produto"]');
    var imeiField = form.querySelector('select[name$="-imei"]');
    var valorField = form.querySelector('input[name$="-valor_unitario"]');
    var quantidadeField = form.querySelector('input[name$="-quantidade"]');
    var valorTotalField = form.querySelector('input[name$="-valor_total"]');
    var valorDescontoField = form.querySelector('input[name$="-valor_desconto"]');

    if (!produtoSelect || !imeiField || !valorField || !quantidadeField || !valorTotalField || !valorDescontoField) return;

    // Só zera o desconto de linhas novas: na edição o valor salvo é mantido.
    if (!valorDescontoField.value) {
      valorDescontoField.value = '0.00';
    }

    if ($(imeiField).data('select2')) {
      $(imeiField).select2('destroy');
    }
    imeiField.required = false;
    quantidadeField.readOnly = false;

    function verificarProduto() {
      var produtoId = produtoSelect.value;
      if (!produtoId) {
        quantidadeField.readOnly = true;
        return;
      }
      obterJson('/produto/details/' + encodeURIComponent(produtoId) + '/')
        .then(function (data) {
          if (data.serializado) {
            quantidadeField.value = 1;
            quantidadeField.readOnly = true;
          } else {
            imeiField.value = '';
            imeiField.disabled = true;
            imeiField.required = false;
            quantidadeField.readOnly = false;
          }
        })
        .catch(function () { /* mantém o formulário como está */ });
    }

    function atualizarValorTotal() {
      var valorUnitario = obterValorSemMascara(valorField) || 0;
      var quantidade = parseInt(quantidadeField.value, 10) || 0;
      var valorDesconto = obterValorSemMascara(valorDescontoField) || 0;
      var valorTotalSemDesconto = valorUnitario * quantidade;
      var valorTotal = valorTotalSemDesconto - valorDesconto;
      var porcentagemDesconto = valorTotalSemDesconto ? (valorDesconto / valorTotalSemDesconto) * 100 : 0;

      if (porcentagemDesconto > LIMITE_DESCONTO_PCT) {
        // Reverte o desconto até o gerente autorizar.
        valorTotalField.value = valorTotalSemDesconto.toFixed(2);
        abrirModalParaValidacao().then(function (autorizado) {
          if (autorizado) {
            valorTotalField.value = valorTotal.toFixed(2);
          } else {
            valorDescontoField.value = '0.00';
            valorTotalField.value = valorTotalSemDesconto.toFixed(2);
          }
        });
        return;
      }
      valorTotalField.value = valorTotal.toFixed(2);
    }

    function buscarPreco(produtoId, imei) {
      var url = '/info-products/?product_id=' + encodeURIComponent(produtoId);
      if (imei) {
        url += '&imei=' + encodeURIComponent(imei);
      }
      return obterJson(url).then(function (info) {
        if (info.status === 'success') {
          valorField.value = info.price;
          atualizarValorTotal();
          return true;
        }
        avisar(info.message || 'Não foi possível obter o preço do produto.', 'warning');
        valorField.value = '';
        return false;
      }).catch(function () {
        avisar('Não foi possível obter o preço do produto.', 'danger');
        return false;
      });
    }

    function configurarSelectImei(produtoId) {
      $(imeiField).select2({
        ajax: {
          url: '/info-products/imei/' + encodeURIComponent(produtoId) + '/',
          dataType: 'json',
          delay: 250,
          data: function (params) {
            return { term: params.term, produto_id: produtoId };
          },
          processResults: function (data) {
            return { results: data.results };
          },
          cache: true,
        },
        placeholder: 'Selecione o IMEI',
        allowClear: true,
      });

      $(imeiField).on('select2:select', function (e) {
        var imeiValue = e.params.data.id;
        if (!imeiValue) return;
        buscarPreco(produtoId, imeiValue).then(function (ok) {
          if (!ok) {
            $(imeiField).val(null).trigger('change');
          }
        });
      });
    }

    verificarProduto();
    atualizarValorTotal();

    if ($(produtoSelect).data('select2')) {
      $(produtoSelect).select2('destroy');
    }
    $(produtoSelect).select2({ placeholder: 'Selecione um produto', allowClear: true, width: '100%' });

    $(produtoSelect).on('select2:select', function (e) {
      var produtoId = e.params.data.id;
      valorField.value = '';
      quantidadeField.value = '';
      valorTotalField.value = '';
      imeiField.value = '';
      imeiField.disabled = true;
      imeiField.required = false;
      quantidadeField.readOnly = true;
      if (!produtoId) return;

      obterJson('/produto/details/' + encodeURIComponent(produtoId) + '/')
        .then(function (data) {
          if (data.serializado) {
            imeiField.disabled = false;
            imeiField.required = true;
            quantidadeField.value = 1;
            quantidadeField.readOnly = true;
            configurarSelectImei(produtoId);
          } else {
            imeiField.disabled = true;
            imeiField.required = false;
            quantidadeField.readOnly = false;
            $(imeiField).val(null).trigger('change');
            buscarPreco(produtoId);
          }
        })
        .catch(function () {
          avisar('Não foi possível carregar o produto selecionado.', 'danger');
        });
    });

    $(imeiField).on('select2:select', function (e) {
      var imeiId = e.params.data.id;
      var produtoId = produtoSelect.value;
      if (!produtoId || !imeiId) return;
      obterJson('/produto/details/' + encodeURIComponent(produtoId) + '/')
        .then(function (data) {
          if (data.serializado) {
            quantidadeField.value = 1;
            quantidadeField.readOnly = true;
          } else {
            quantidadeField.readOnly = false;
            imeiField.disabled = true;
            $(imeiField).val(null).trigger('change');
          }
        })
        .catch(function () { /* sem alteração */ });
    });

    quantidadeField.addEventListener('input', function () {
      verificarProduto();
      atualizarValorTotal();
    });
    valorField.addEventListener('input', atualizarValorTotal);
    valorDescontoField.addEventListener('input', atualizarValorTotal);
  }

  /* ---------------------------------------------------------------------
     Linha de pagamento
     --------------------------------------------------------------------- */
  function configurarPagamentoForm(form) {
    var tipoPagamentoSelect = form.querySelector('select[name$="-tipo_pagamento"]');
    var parcelasField = form.querySelector('input[name$="-parcelas"]');
    var valorField = form.querySelector('input[name$="-valor"]');
    var valorParcelaField = form.querySelector('input[name$="-valor_parcela"]');

    if (!tipoPagamentoSelect || !parcelasField || !valorField || !valorParcelaField) return;

    function atualizarValorParcela() {
      var valor = obterValorSemMascara(valorField) || 0;
      var parcelas = parseInt(parcelasField.value, 10) || 1;
      valorParcelaField.value = (valor / parcelas).toFixed(2);
    }

    function atualizarParcelas() {
      var paymentId = tipoPagamentoSelect.value;
      if (!paymentId) {
        parcelasField.disabled = true;
        parcelasField.value = 1;
        atualizarValorParcela();
        return;
      }
      obterJson('/info-payment/?payment_id=' + encodeURIComponent(paymentId))
        .then(function (data) {
          if (data.status !== 'success') {
            avisar('Erro ao buscar informações do tipo de pagamento.', 'danger');
            return;
          }
          if (data.parcela) {
            parcelasField.disabled = false;
            parcelasField.value = parcelasField.value || 1;
          } else {
            parcelasField.disabled = true;
            parcelasField.value = 1;
          }
          atualizarValorParcela();
        })
        .catch(function () {
          avisar('Erro ao buscar informações do tipo de pagamento.', 'danger');
        });
    }

    parcelasField.addEventListener('input', atualizarValorParcela);
    valorField.addEventListener('input', atualizarValorParcela);
    tipoPagamentoSelect.addEventListener('change', atualizarParcelas);
    atualizarParcelas();
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (window.bootstrap && window.bootstrap.Tooltip) {
      document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
        window.bootstrap.Tooltip.getOrCreateInstance(el);
      });
    }

    if (!window.jQuery) return;
    if (typeof window.jQuery.fn.mask === 'function') {
      window.jQuery('.money').mask('000.000.000,00', { reverse: true });
    }
    if (typeof window.jQuery.fn.select2 === 'function') {
      document.querySelectorAll('.produto-form').forEach(configurarProdutoForm);
    }
    document.querySelectorAll('.pagamento-form').forEach(configurarPagamentoForm);
  });
})();
