/**
 * Detalhe de Contas a Receber
 * (financeiro/templates/contas_a_receber/contas_a_receber_detail.html).
 *
 * - [data-auto-submit]: envia o formulário ao mudar (situações, % desconto).
 *   Se o campo tiver data-confirmar-ligar / data-confirmar-desligar, pede
 *   confirmação no modal padrão antes; ao cancelar, volta o switch.
 * - Cor dos status personalizados ([data-status-color], vem do banco).
 * - "Adicionar Parcela": clona a última linha do formset e redistribui o saldo.
 * - "Gerar PDF": html2pdf do bloco #report-content (data-arquivo no botão).
 */
(function () {
  'use strict';

  function avisar(mensagem, variante) {
    if (window.ipixToast) {
      window.ipixToast(mensagem, variante || 'warning');
    }
  }

  function confirmar(opcoes) {
    if (window.ipixConfirm) {
      return window.ipixConfirm(opcoes);
    }
    return Promise.resolve(true);
  }

  /* ---------------------------------------------------------------------
     Envio automático com confirmação para situações destrutivas
     --------------------------------------------------------------------- */
  function iniciarAutoSubmit() {
    document.addEventListener('change', function (evento) {
      var campo = evento.target;
      if (!campo || !campo.matches('[data-auto-submit]') || !campo.form) {
        return;
      }
      var ligando = campo.type === 'checkbox' ? campo.checked : true;
      var mensagem = campo.getAttribute(ligando ? 'data-confirmar-ligar' : 'data-confirmar-desligar');
      if (!mensagem) {
        campo.form.submit();
        return;
      }
      confirmar({
        title: campo.getAttribute('data-confirmar-titulo') || 'Confirmar alteração',
        message: mensagem,
        label: ligando ? 'Sim, marcar' : 'Sim, desmarcar',
        variant: ligando ? 'danger' : 'primary',
      }).then(function (ok) {
        if (ok) {
          campo.form.submit();
        } else if (campo.type === 'checkbox') {
          campo.checked = !campo.checked;
        }
      });
    });
  }

  function aplicarCoresDeStatus() {
    document.querySelectorAll('[data-status-color]').forEach(function (el) {
      var cor = el.getAttribute('data-status-color');
      if (cor && /^#[0-9a-f]{3,8}$/i.test(cor)) {
        el.style.backgroundColor = cor;
      }
    });
  }

  /* ---------------------------------------------------------------------
     Adicionar parcela extra no formset
     --------------------------------------------------------------------- */
  function addOneMonthISO(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return iso;
    var y = parseInt(m[1], 10);
    var mo = parseInt(m[2], 10);
    var d = parseInt(m[3], 10);
    var alvo = new Date(y, mo, d); // mês +1 porque Date é 0-indexed
    // Ajusta se "estourou" o mês (ex: 31/jan + 1 = 03/mar)
    if (alvo.getMonth() !== mo % 12) {
      alvo.setDate(0);
    }
    return alvo.getFullYear() + '-' +
      String(alvo.getMonth() + 1).padStart(2, '0') + '-' +
      String(alvo.getDate()).padStart(2, '0');
  }

  function iniciarAdicionarParcela() {
    var btn = document.getElementById('btn-add-parcela');
    if (!btn) return;

    var dataEl = document.getElementById('parcelas-data');
    var table = document.getElementById('parcelas-table');
    if (!dataEl || !table) return;
    var tbody = table.querySelector('tbody');
    var totalCell = document.getElementById('total-valor-original-cell');
    var counterEl = document.getElementById('parcelas-extras-count');

    var pagamentoValor = parseFloat(dataEl.dataset.pagamentoValor) || 0;
    var totalPagoEfetivo = parseFloat(dataEl.dataset.totalPagoEfetivo) || 0;
    var maxExtras = parseInt(dataEl.dataset.maxExtras, 10) || 4;
    var parcelasAdicionadas = 0;

    var totalForms = document.querySelector('input[name$="-TOTAL_FORMS"]');
    if (!totalForms) return;
    var prefix = totalForms.name.replace(/-TOTAL_FORMS$/, '');
    var totalFormsInput = document.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');

    function isPendentRow(tr) {
      if (tr.dataset.delete === '1') return false;
      var pagoCb = tr.querySelector('input[type="checkbox"][name$="-pago"]');
      return !(pagoCb && pagoCb.checked);
    }

    function getMaxNumero() {
      var max = 0;
      tbody.querySelectorAll('input[name$="-numero_parcela"]').forEach(function (i) {
        var v = parseInt(i.value, 10);
        if (!isNaN(v) && v > max) max = v;
      });
      return max;
    }

    function getLastVencimento() {
      var lastDate = null;
      var lastNumero = -1;
      tbody.querySelectorAll('tr').forEach(function (tr) {
        var numEl = tr.querySelector('input[name$="-numero_parcela"]');
        var dateEl = tr.querySelector('input[name$="-data_vencimento"]');
        if (!numEl || !dateEl || !dateEl.value) return;
        var num = parseInt(numEl.value, 10) || 0;
        if (num >= lastNumero) {
          lastNumero = num;
          lastDate = dateEl.value;
        }
      });
      return lastDate;
    }

    function atualizarTotal() {
      var total = 0;
      tbody.querySelectorAll('input[name$="-valor"]').forEach(function (i) {
        total += parseFloat(i.value) || 0;
      });
      if (totalCell) totalCell.textContent = 'R$ ' + total.toFixed(2);
    }

    function recalcular() {
      var saldo = Math.max(pagamentoValor - totalPagoEfetivo, 0);
      var pendentes = [];
      tbody.querySelectorAll('tr').forEach(function (tr) {
        if (!isPendentRow(tr)) return;
        var valorInput = tr.querySelector('input[name$="-valor"]');
        if (valorInput) pendentes.push(valorInput);
      });
      if (pendentes.length === 0) return;
      var baseCents = Math.floor((saldo * 100) / pendentes.length);
      var diffCents = Math.round(saldo * 100) - baseCents * pendentes.length;
      pendentes.forEach(function (input, idx) {
        var cents = baseCents + (idx === pendentes.length - 1 ? diffCents : 0);
        input.value = (cents / 100).toFixed(2);
      });
      atualizarTotal();
    }

    function renumerarFormset() {
      var rows = tbody.querySelectorAll('tr');
      rows.forEach(function (tr, idx) {
        tr.querySelectorAll('input, select, textarea').forEach(function (el) {
          if (el.name) el.name = el.name.replace(/-(\d+)-/, '-' + idx + '-');
          if (el.id) el.id = el.id.replace(/-(\d+)-/, '-' + idx + '-');
        });
      });
      totalFormsInput.value = String(rows.length);
    }

    function atualizarContador() {
      if (counterEl) counterEl.textContent = parcelasAdicionadas + '/' + maxExtras;
    }

    function addRemoveButton(row) {
      var alvo = row.querySelector('td:last-child');
      if (!alvo) return;
      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-danger ms-2 btn-remove-extra';
      removeBtn.title = 'Remover esta parcela adicionada';
      removeBtn.setAttribute('aria-label', 'Remover esta parcela adicionada');
      var icone = document.createElement('i');
      icone.className = 'bx bx-trash';
      removeBtn.appendChild(icone);
      removeBtn.addEventListener('click', function () {
        row.remove();
        renumerarFormset();
        parcelasAdicionadas = Math.max(0, parcelasAdicionadas - 1);
        atualizarContador();
        btn.disabled = false;
        recalcular();
      });
      alvo.appendChild(removeBtn);
    }

    function prepararNovaLinha(newRow, newIndex) {
      newRow.classList.remove('table-success');
      newRow.classList.add('table-warning');
      newRow.dataset.pago = '0';
      newRow.dataset.delete = '0';

      var re = new RegExp('^' + prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '-\\d+-');
      newRow.querySelectorAll('input, select, textarea').forEach(function (el) {
        if (el.name) el.name = el.name.replace(re, prefix + '-' + newIndex + '-');
        if (el.id) el.id = el.id.replace(/-\d+-/, '-' + newIndex + '-');
        // Mantém pagamento_efetuado desabilitado (regra original do form)
        if (el.name && el.name.endsWith('-pagamento_efetuado')) {
          if (el.type === 'checkbox') el.checked = false;
          return;
        }
        el.disabled = false;
        el.removeAttribute('disabled');
      });
      newRow.querySelectorAll('input').forEach(function (el) {
        if (!el.name) return;
        if (el.name.endsWith('-id')) el.value = '';
        if (el.name.endsWith('-valor_pago')) el.value = '';
        if (el.name.endsWith('-data_pagamento')) el.value = '';
        if (el.type === 'checkbox') el.checked = false;
      });

      var numInput = newRow.querySelector('input[name$="-numero_parcela"]');
      if (numInput) {
        numInput.value = String(getMaxNumero() + 1);
        numInput.removeAttribute('readonly');
      }

      var dateInput = newRow.querySelector('input[name$="-data_vencimento"]');
      if (dateInput) {
        var last = getLastVencimento();
        if (last) dateInput.value = addOneMonthISO(last);
        dateInput.removeAttribute('readonly');
        dateInput.type = 'date';
      }

      var valorInput = newRow.querySelector('input[name$="-valor"]');
      if (valorInput) {
        valorInput.removeAttribute('readonly');
        valorInput.removeAttribute('disabled');
        valorInput.type = 'number';
        valorInput.step = '0.01';
        valorInput.min = '0';
        valorInput.value = '0.00';
      }

      newRow.querySelectorAll('.btn-remove-extra').forEach(function (b) { b.remove(); });

      // A parcela nova ainda não existe no banco: o botão de comprovante clonado
      // apontaria para o modal da parcela anterior.
      newRow.querySelectorAll('.cr-comprovante-btn').forEach(function (b) {
        var celula = b.closest('td');
        b.remove();
        if (celula) {
          var aviso = document.createElement('span');
          aviso.className = 'text-muted small';
          aviso.textContent = 'Salve a parcela primeiro';
          celula.replaceChildren(aviso);
        }
      });
    }

    btn.addEventListener('click', function () {
      if (parcelasAdicionadas >= maxExtras) {
        avisar('Limite de ' + maxExtras + ' parcelas extras atingido.', 'warning');
        return;
      }
      var lastRow = tbody.querySelector('tr:last-child');
      if (!lastRow) return;

      var newRow = lastRow.cloneNode(true);
      var newIndex = parseInt(totalFormsInput.value, 10);
      prepararNovaLinha(newRow, newIndex);

      tbody.appendChild(newRow);
      totalFormsInput.value = String(newIndex + 1);
      parcelasAdicionadas++;
      atualizarContador();
      if (parcelasAdicionadas >= maxExtras) btn.disabled = true;

      addRemoveButton(newRow);
      recalcular();
    });

    // Recalcula ao alternar pago/DELETE em qualquer linha (saldo distribuído)
    tbody.addEventListener('change', function (e) {
      var t = e.target;
      if (!t || !t.name || parcelasAdicionadas === 0) return;
      if (t.name.endsWith('-pago') || t.name.endsWith('-DELETE')) {
        recalcular();
      }
    });
  }

  /* ---------------------------------------------------------------------
     PDF
     --------------------------------------------------------------------- */
  function iniciarPdf() {
    var botao = document.getElementById('download-pdf');
    if (!botao) return;
    botao.addEventListener('click', function () {
      var el = document.getElementById('report-content');
      if (!el || typeof window.html2pdf !== 'function') {
        avisar('Não foi possível gerar o PDF agora. Tente novamente.', 'danger');
        return;
      }
      el.style.display = 'block';
      el.style.position = 'static';
      window.html2pdf().set({
        margin: [10, 10, 10, 10],
        filename: botao.getAttribute('data-arquivo') || 'conta.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 3 },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      }).from(el).save().finally(function () {
        el.style.display = '';
        el.style.position = '';
      });
    });
  }

  iniciarAutoSubmit();
  document.addEventListener('DOMContentLoaded', function () {
    aplicarCoresDeStatus();
    iniciarAdicionarParcela();
    iniciarPdf();
  });
})();
