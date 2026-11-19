/**
 * Cadastro/edição da solicitação de crédito (vendas/templates/cliente/form_cliente.html).
 *
 * Antes eram ~980 linhas inline. Valores do Django chegam por
 * #formClienteDados (data-attributes); nada de template tag aqui.
 *   data-produtos / data-parcelamentos / data-marcas → JSON
 *   data-produto-salvo-id / data-parcelas-salvas / data-parcelas-do-formulario
 *
 * Confirmações usam window.ipixConfirm (modal padrão), sem confirm nativo.
 */
var FORM_CLIENTE_DADOS = (function () {
  'use strict';
  var el = document.getElementById('formClienteDados');
  var d = el ? el.dataset : {};
  return {
    produtos: d.produtos || '[]',
    parcelamentos: d.parcelamentos || '[]',
    marcas: d.marcas || '[]',
    produtoSalvoId: d.produtoSalvoId || '',
    parcelasSalvas: d.parcelasSalvas || '',
    parcelasDoFormulario: d.parcelasDoFormulario || '',
  };
})();

$('.tel').mask('00 00000-0000');
$('.cpf').mask('000.000.000-00');
$('.rg').mask('00000000');
$('.cep').mask('00000000');

// Máscara para campo de renda - apenas números inteiros
$('#id_total_renda').on('input', function() {
  // Remove qualquer caractere que não seja número
  this.value = this.value.replace(/[^0-9]/g, '');
});

// Previne entrada de caracteres não numéricos
$('#id_total_renda').on('keypress', function(e) {
  // Permite apenas números (0-9), backspace, delete, tab, escape, enter
  if (!/[0-9]/.test(String.fromCharCode(e.which)) && 
      !(e.which === 8 || e.which === 9 || e.which === 27 || e.which === 13 || 
        (e.which === 46 && e.shiftKey === false))) {
    e.preventDefault();
  }
});

$(function(){
  var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
  var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl)
  });

  // Progress tracking
  function updateProgress() {
    let completedSteps = 0;
    let totalSteps = 3;
    
    // Check produto step (agora é o primeiro)
    let produtoComplete = checkProdutoComplete();
    if (produtoComplete) {
      $('#step-produto-number').removeClass('active').addClass('completed success');
      $('#step-produto-text').addClass('completed');
      completedSteps++;
    } else {
      $('#step-produto-number').removeClass('completed success').addClass('active');
      $('#step-produto-text').removeClass('completed');
    }
    
    // Check dados step (agora é o segundo)
    let dadosComplete = checkDadosComplete();
    if (dadosComplete) {
      $('#step-dados-number').removeClass('active').addClass('completed success');
      $('#step-dados-text').addClass('completed');
      completedSteps++;
    } else {
      $('#step-dados-number').removeClass('completed success').addClass('active');
      $('#step-dados-text').removeClass('completed');
    }
    
    // Check comprovantes step (agora é o terceiro)
    let comprovantesComplete = checkComprovantesComplete();
    if (comprovantesComplete) {
      $('#step-comprovantes-number').removeClass('active').addClass('completed success');
      $('#step-comprovantes-text').addClass('completed');
      completedSteps++;
    } else {
      $('#step-comprovantes-number').removeClass('completed success').addClass('active');
      $('#step-comprovantes-text').removeClass('completed');
    }
    
    // Update submit button
    if (completedSteps === totalSteps) {
      $('#submitBtn').removeClass('btn-primary').addClass('btn-success');
      $('#submitBtn').html('<i class="bx bx-check me-1"></i> Formulário Completo - Salvar');
    } else {
      $('#submitBtn').removeClass('btn-success').addClass('btn-primary');
      $('#submitBtn').html('<i class="bx bx-save me-1"></i> Salvar');
    }
  }
  
  function checkDadosComplete() {
    let requiredFields = [
      '#id_nome',
      '#id_cpf',
      '#id_nascimento',
      '#id_telefone',
      '#id_rg',
      '#id_cep',
      '#id_profissao',
      '#id_quantidade_dependentes',
      '#id_recebe_auxilio',
      '#id_total_renda',
    ];
    
    let complete = true;
    requiredFields.forEach(field => {
      let value = $(field).val();
      if (!value || value.trim() === '') {
        complete = false;
        return false;
      }
      
      if (field === '#id_quantidade_dependentes') {
        const num = parseInt(value, 10);
        if (isNaN(num) || num < 0) {
          complete = false;
          return false;
        }
      }

      if (field === '#id_email') {
        // Email validation for completion check
        if (!value.includes('@')) {
          complete = false;
          return false;
        } else {
          const parts = value.split('@');
          if (parts.length !== 2 || parts[0].length === 0 || parts[1].length === 0) {
            complete = false;
            return false;
          } else if (!/[a-zA-Z]/.test(parts[0]) || !/[a-zA-Z]/.test(parts[1])) {
            complete = false;
            return false;
          }
        }
      }
      
      if (field === '#id_telefone') {
        // Phone validation - check if it has between 10 and 11 digits
        const digitsOnly = value.replace(/\D/g, '');
        if (digitsOnly.length < 10 || digitsOnly.length > 11) {
          complete = false;
          return false;
        }
      }
      
      if (field === '#id_rg') {
        // RG validation - check if it has between 7 and 12 digits
        const digitsOnly = value.replace(/\D/g, '');
        if (digitsOnly.length < 7 || digitsOnly.length > 12) {
          complete = false;
          return false;
        }
      }
      
      if (field === '#id_nascimento') {
        // Validação de idade: mínimo 22 anos
        if (value) {
          const birthDate = new Date(value);
          const today = new Date();
          let age = today.getFullYear() - birthDate.getFullYear();
          const monthDiff = today.getMonth() - birthDate.getMonth();
          
          // Adjust age if birthday hasn't occurred this year
          if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
            age--;
          }
          
          if (age < 22) {
            complete = false;
            return false;
          }
        }
      }
      
      if (field === '#id_cep') {
        // CEP validation - check if it has exactly 8 digits
        const digitsOnly = value.replace(/\D/g, '');
        if (digitsOnly.length !== 8) {
          complete = false;
          return false;
        }
      }
      
      if (field === '#id_total_renda') {
        // Renda validation - must be a positive integer with minimum value
        const rendaValue = parseInt(value, 10);
        if (isNaN(rendaValue) || rendaValue <= 0) {
          complete = false;
          return false;
        } else if (rendaValue < 1000) {
          complete = false;
          return false;
        }
      }
    });
    
    
    // Additional validation for duplicate phones
    if (complete) {
      const telefone = ($('#id_telefone').val() || '').replace(/\D/g, '');
      const telefone_secundario = ($('#id_telefone_secundario').val() || '').replace(/\D/g, '');
      
      if (telefone && telefone_secundario && telefone === telefone_secundario) {
        complete = false;
      }
    }
    
    return complete;
  }
  
  function checkComprovantesComplete() {
    let requiredFields = [
      '#id_documento_identificacao_frente',
      '#id_documento_identificacao_verso',
      '#id_comprovante_residencia',
      '#id_foto_cliente'
    ];
    
    let complete = true;
    requiredFields.forEach(field => {
      let value = $(field).val();
      if (!value || value.trim() === '') {
        complete = false;
        return false;
      }
    });
    
    return complete;
  }
  
  function checkProdutoComplete() {
    let requiredFields = [
      '#id_produto',
      '#id_numero_parcelas',
      '#id_data_pagamento'
    ];

    // Se o campo observacao existir no DOM (aparece apenas em edição), adiciona à validação
    if ($('#id_observacao').length) {
      requiredFields.push('#id_observacao');
    }

    let complete = true;
    requiredFields.forEach(field => {
      let value = $(field).val();
      if (!value || value.trim() === '') {
        complete = false;
        return false;
      }
    });

    return complete;
  }
  
  // Real-time validation
  function validateField(field) {
    let value = $(field).val();
    let fieldId = $(field).attr('id');
    let isValid = true;
    let message = 'Campo preenchido corretamente';
    
    // Check if field is empty
    if (!value || value.trim() === '') {
      isValid = false;
      message = 'Este campo é obrigatório';
    } else {
      // Specific validations
      if (fieldId === 'id_cpf') {
        // CPF validation (basic)
        const cpfRegex = /^\d{3}\.\d{3}\.\d{3}-\d{2}$/;
        if (!cpfRegex.test(value)) {
          isValid = false;
          message = 'Digite um CPF válido (000.000.000-00)';
        }
      } else if (fieldId === 'id_telefone') {
        // Phone validation - check if it has between 10 and 11 digits
        const digitsOnly = value.replace(/\D/g, '');
        if (digitsOnly.length < 10 || digitsOnly.length > 11) {
          isValid = false;
          message = 'Telefone deve ter entre 10 e 11 dígitos';
        }
      } else if (fieldId === 'id_rg') {
        // RG validation - check if it has between 7 and 12 digits
        const digitsOnly = value.replace(/\D/g, '');
        if (digitsOnly.length < 7 || digitsOnly.length > 12) {
          isValid = false;
          message = 'RG deve ter entre 7 e 12 dígitos';
        }
      } else if (fieldId === 'id_nascimento') {
        // Validação de idade: mínimo 22 anos
        if (value) {
          const birthDate = new Date(value);
          const today = new Date();
          let age = today.getFullYear() - birthDate.getFullYear();
          const monthDiff = today.getMonth() - birthDate.getMonth();
          
          // Adjust age if birthday hasn't occurred this year
          if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
            age--;
          }
          // Atualiza badge de idade
          const idadeBadge = document.getElementById('idadeDisplay');
          if (idadeBadge) idadeBadge.textContent = age + ' anos';

          if (age < 22) {
            isValid = false;
            message = 'Cliente deve ter pelo menos 22 anos';
          }
        }
      } else if (fieldId === 'id_cep') {
        // CEP validation - check if it has exactly 8 digits
        const digitsOnly = value.replace(/\D/g, '');
        if (digitsOnly.length !== 8) {
          isValid = false;
          message = 'CEP deve ter exatamente 8 dígitos';
        }
      } else if (fieldId === 'id_total_renda') {
        // Renda validation - must be a positive integer
        const rendaValue = parseInt(value, 10);
        if (isNaN(rendaValue) || rendaValue <= 0) {
          isValid = false;
          message = 'Renda deve ser um número inteiro positivo';
        } else if (rendaValue < 1000) {
          isValid = false;
          message = 'Renda deve ser pelo menos R$ 1.000,00';
        }
      }
    }
    
    if (isValid) {
      $(field).removeClass('is-invalid').addClass('is-valid');
      $(field).siblings('.validation-feedback').removeClass('invalid-feedback').addClass('valid-feedback').text(message);
    } else {
      $(field).removeClass('is-valid').addClass('is-invalid');
      $(field).siblings('.validation-feedback').removeClass('valid-feedback').addClass('invalid-feedback').text(message);
    }
    
    updateProgress();
  }
  
  // Add validation feedback elements (exclui o textarea de nova observação na aba Histórico)
  $('input[required], select[required], textarea[required]').not('#novaObservacaoTexto').each(function() {
    if (!$(this).siblings('.validation-feedback').length) {
      $(this).after('<div class="validation-feedback"></div>');
    }
  });
  
  // Debug: Check if email field exists
  
  // Add validation feedback for email field specifically
  if ($('#id_email').length && !$('#id_email').siblings('.validation-feedback').length) {
    $('#id_email').after('<div class="validation-feedback"></div>');
  }

  if ($('#id_telefone_secundario').length && !$('#id_telefone_secundario').siblings('.validation-feedback').length) {
    $('#id_telefone_secundario').after('<div class="validation-feedback"></div>');
  }
  
  // Bind validation events (exclui o textarea de nova observação na aba Histórico)
  $('input, select, textarea').not('#novaObservacaoTexto').on('blur change', function() {
    if ($(this).prop('required')) {
      validateField(this);
    }
  });
  
  // Special validation for email field
  $('#id_email').on('blur change', function() {
    validateField(this);
  });
  
  // Validation for duplicate phones
  function validateDuplicatePhones() {
    const telefone = ($('#id_telefone').val() || '').replace(/\D/g, '');
    const telefone_secundario = ($('#id_telefone_secundario').val() || '').replace(/\D/g, '');
    
    if (telefone_secundario && (telefone_secundario.length < 10 || telefone_secundario.length > 11)) {
      $('#id_telefone_secundario').removeClass('is-valid').addClass('is-invalid');
      $('#id_telefone_secundario').siblings('.validation-feedback').removeClass('valid-feedback').addClass('invalid-feedback').text('Telefone secundário deve ter entre 10 e 11 dígitos');
      return false;
    } else if (telefone && telefone_secundario && telefone === telefone_secundario) {
      $('#id_telefone_secundario').removeClass('is-valid').addClass('is-invalid');
      $('#id_telefone_secundario').siblings('.validation-feedback').removeClass('valid-feedback').addClass('invalid-feedback').text('Telefone secundário não pode ser igual ao telefone principal');
      return false;
    } else if (telefone_secundario) {
      $('#id_telefone_secundario').removeClass('is-invalid').addClass('is-valid');
      $('#id_telefone_secundario').siblings('.validation-feedback').removeClass('invalid-feedback').addClass('valid-feedback').text('Telefone secundário válido');
    } else {
      $('#id_telefone_secundario').removeClass('is-invalid is-valid');
      $('#id_telefone_secundario').siblings('.validation-feedback').text('');
    }
    return true;
  }
  
  // Bind validation for duplicate phones
  $('#id_telefone, #id_telefone_secundario').on('blur change', function() {
    validateDuplicatePhones();
  });
  
  // Tab switching with progress update
  $('.nav-link').on('click', function() {
    setTimeout(updateProgress, 100);
  });
  
  // Atualiza a idade ao alterar a data de nascimento
  function updateIdade() {
    const value = $('#id_nascimento').val();
    const badge = $('#idadeDisplay');
    if (!badge.length) return;
    if (!value) { badge.text('—'); return; }
    const birthDate = new Date(value);
    const today = new Date();
    let age = today.getFullYear() - birthDate.getFullYear();
    const monthDiff = today.getMonth() - birthDate.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    badge.text(age + ' anos');
  }
  $('#id_nascimento').on('change', function(){ updateIdade(); });
  // Inicializa badge de idade no carregamento
  updateIdade();
  
  // ==================== CARDS DE PRODUTO ====================
  let produtos = [];
  try {
    produtos = JSON.parse(FORM_CLIENTE_DADOS.produtos);
  } catch (e) {
  }

  let parcelamentos = [];
  try {
    parcelamentos = JSON.parse(FORM_CLIENTE_DADOS.parcelamentos);
  } catch (e) {
  }

  let marcas = [];
  try {
    marcas = JSON.parse(FORM_CLIENTE_DADOS.marcas);
  } catch (e) {
  }

  let marcasInicializadas = false;
  let optionsProdutoOriginais = [];

  function initMarcas() {
    if (!marcas || marcas.length === 0) {
      // Fallback caso não tenha marcas, exibe os campos de produto normalmente
      $('#div-campos-produto').show();
      return;
    }

    const container = $('#marcas-container');
    container.empty();
    $('#secao-marcas').show();

    // Salvar as opções originais do form select
    const $selectProduto = $('#id_produto');
    if (optionsProdutoOriginais.length === 0) {
       $selectProduto.find('option').each(function() {
           optionsProdutoOriginais.push({
               value: $(this).val(),
               text: $(this).text()
           });
       });
    }

    marcas.forEach(marca => {
      let card = $('<div>')
        .addClass('marca-card')
        .css('--marca-cor', marca.cor || '#007bff')
        .css('--marca-cor-light', (marca.cor || '#007bff') + '15')
        .attr('data-id', marca.id)
        .on('click', function() {
          $('.marca-card').removeClass('active');
          $(this).addClass('active');
          selecionarMarca(marca.id);
        });
        
      let icone = $('<i>').addClass(marca.icone || 'bx bx-mobile');
      let text = $('<span>').text(marca.nome);
      
      card.append(icone).append(text);
      container.append(card);
    });

    // Caso já haja um produto selecionado via backend (edição)
    const valAtual = $selectProduto.val();
    if (valAtual) {
       const p = produtos.find(x => x.id == valAtual);
       if (p && p.marca_id) {
           $(`.marca-card[data-id="${p.marca_id}"]`).addClass('active');
           selecionarMarca(p.marca_id, true);
       } else {
           $('#div-campos-produto').show();
       }
    }
  }

  function selecionarMarca(marcaId, preserveSelect) {
    const $selectProduto = $('#id_produto');
    const valAtual = $selectProduto.val();
    
    // Pega todos os produtos dessa marca para usar como filter das options
    const produtosAtivos = produtos.filter(p => !marcaId || p.marca_id == marcaId);
    const activeIds = produtosAtivos.map(p => p.id.toString());
    
    $selectProduto.empty();
    $selectProduto.append('<option value="">---------</option>');
    
    optionsProdutoOriginais.forEach(opt => {
        if (!opt.value || activeIds.includes(opt.value)) {
            if (opt.value) { // ignora empty text default fallback repetido
                $selectProduto.append($('<option>').val(opt.value).text(opt.text));
            }
        }
    });
    
    // Se preserva e se o novo select ainda contém a options mantida
    if (preserveSelect && $selectProduto.find(`option[value="${valAtual}"]`).length > 0) {
        $selectProduto.val(valAtual);
    } else {
        $selectProduto.val('').trigger('change');
        if ($selectProduto.hasClass('select2-hidden-accessible')) {
            $selectProduto.trigger('change.select2');
        }
    }

    $('#div-campos-produto').slideDown(300);
  }

  let currentEntradaMinima = 0;

  function formatBRL(v) {
    return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  }

  function validaEntrada() {
    const val = parseFloat($('#id_entrada_informada').val());
    const alert = $('#entrada-minima-alert');
    if (!isNaN(val) && val < currentEntradaMinima) {
      alert.show();
    } else {
      alert.hide();
    }
  }

  function toggleIphoneFields(isIphone) {
    if (isIphone) {
      $('#iphone-alert').show();
      $('.icloud-field').show();
    } else {
      $('#iphone-alert').hide();
      $('.icloud-field').hide();
    }
  }

  function getParcelamentosDaMarca(marcaId) {
    const resultado = parcelamentos.filter(p => p.marca_id == marcaId);
    return resultado;
  }

  // Estado da proposta como está salvo no banco — usado para restaurar o
  // parcelamento na abertura da tela sem atrapalhar trocas feitas na mão.
  const PRODUTO_SALVO_ID = FORM_CLIENTE_DADOS.produtoSalvoId;
  const PARCELAS_SALVAS = FORM_CLIENTE_DADOS.parcelasSalvas;

  function atualizaOpcoesParcelamento(produto) {
    const select = $('#id_numero_parcelas');
    
    let valorAtual = select.val();
    // Na inicialização, resgata o valor preenchido via back-end caso as opções estejam vazias
    if (!select.data('initialized')) {
        let initial = FORM_CLIENTE_DADOS.parcelasSalvas;
        if (!initial || initial === 'None') {
            initial = FORM_CLIENTE_DADOS.parcelasDoFormulario;
        }
        if (initial && initial !== 'None') {
            valorAtual = initial;
        }
        select.data('initialized', true);
    }
    
    select.empty();
    select.append('<option value="">---------</option>');

    // Mantém o valor já salvo como option válida mesmo quando ele não
    // existe mais na tabela de parcelamentos da marca. Sem isso o select
    // ficava vazio, o POST não enviava numero_parcelas e o backend
    // devolvia "Este campo é obrigatório" ao salvar/aprovar.
    // Só preserva enquanto o produto continua sendo o da proposta salva —
    // ao trocar de produto/marca a lista deve ser recomeçada do zero.
    function preservarValorAtual(motivo) {
      if (!valorAtual) return;
      if (!produto || String(produto.id) !== String(PRODUTO_SALVO_ID)) return;
      if (valorAtual !== PARCELAS_SALVAS) return;
      if (select.find('option[value="' + valorAtual + '"]').length === 0) {
        select.append(
          $('<option>').val(valorAtual).text(valorAtual + 'x (parcelamento não cadastrado)')
        );
      }
      select.val(valorAtual);
    }

    if (!produto || !produto.marca_id) {
      if (produto) {
        select.append('<option value="" disabled>Produto sem marca — configure a marca do produto</option>');
        preservarValorAtual('produto sem marca');
      } else {
      }
      return;
    }

    const parcs = getParcelamentosDaMarca(produto.marca_id);
    if (parcs.length === 0) {
      select.append('<option value="" disabled>Nenhum parcelamento cadastrado para esta marca</option>');
      preservarValorAtual('marca sem parcelamentos');
      return;
    }

    parcs.forEach(p => {
      const opt = $('<option>').val(p.qtd_vezes).text(p.qtd_vezes + 'x');
      select.append(opt);
    });


    // Reseleciona se ainda disponível; se não estiver, preserva mesmo assim
    if (valorAtual && select.find('option[value="' + valorAtual + '"]').length) {
      select.val(valorAtual);
    } else {
      preservarValorAtual('parcelamento não cadastrado para esta marca');
    }
  }

  function atualizaInfo() {
    const prodId = $('#id_produto').val();
    const numParcelas = $('#id_numero_parcelas').val();

    // Se não tem produto, zera tudo e oculta campos iPhone
    if (!prodId) {
      toggleIphoneFields(false);
      $('#wrapper-entrada-informada').hide();
      $('#id_entrada_informada').val('');
      $('#info-entrada').text('—');
      $('#info-total').text('—');
      $('#info-parcela').text('—');
      $('#info-parcela-label').text('Parcelas');
      $('#card-preco-venda').hide();
      $('#info-preco-venda').text('—');
      return;
    }

    const produto = produtos.find(p => p.id == prodId) || {};
    const isIphone = !!produto.is_iphone;

    // Controla visibilidade dos campos exclusivos de iPhone
    toggleIphoneFields(isIphone);

    // --- Lógica unificada para todos os produtos ---
    const valorBase = produto.valor || 0;
    const entradaMinima = produto.entrada || 0;
    currentEntradaMinima = entradaMinima;

    $('#wrapper-entrada-informada').show();
    // Atualiza hint de entrada mínima
    $('#entrada-minima-hint').text('Entrada mínima: ' + formatBRL(entradaMinima));
    validaEntrada();

    // Entrada: usa campo digitado para qualquer produto; se vazio ou menor, usa a mínima ou proíbe
    let entradaUsada = entradaMinima;
    
    const rawEntrada = $('#id_entrada_informada').val().trim();
    const entradaDigitada = parseFloat(rawEntrada);
    const campoVazio = rawEntrada === '' || isNaN(entradaDigitada);

    if (!campoVazio) {
      if (entradaDigitada < entradaMinima) {
        $('#info-entrada').text(formatBRL(entradaDigitada));
        $('#info-total').text('—');
        $('#info-parcela-label').text('Parcelas');
        $('#info-parcela').text('—');
        $('#card-preco-venda').show();
        $('#info-preco-venda').text(formatBRL(valorBase));
        return;
      }
      entradaUsada = entradaDigitada;
    }

    $('#info-entrada').text(formatBRL(entradaUsada));
    $('#card-preco-venda').show();
    $('#info-preco-venda').text(formatBRL(valorBase));

    if (!numParcelas) {
      $('#info-total').text('—');
      $('#info-parcela-label').text('Parcelas');
      $('#info-parcela').text('—');
      return;
    }

    // Busca juros na tabela de parcelamentos vinculados à marca do produto
    const marcaParcs = getParcelamentosDaMarca(produto.marca_id);
    const parc = marcaParcs.find(p => p.qtd_vezes == parseInt(numParcelas, 10));
    if (!parc) {
      $('#info-total').text('Parcelamento ' + numParcelas + 'x não cadastrado para esta marca');
      $('#info-parcela-label').text('Parcelas');
      $('#info-parcela').text('—');
      return;
    }

    const valorFinanciado = valorBase - entradaUsada;
    const juros = valorFinanciado * parc.porcentagem_juros / 100;
    const total = valorFinanciado + juros;
    const parcela = total / parseInt(numParcelas, 10);

    $('#info-total').text(formatBRL(total));
    $('#info-parcela-label').text('Parcela (' + numParcelas + 'x)');
    $('#info-parcela').text(formatBRL(parcela));

    updateProgress();
  }

  // ==================== LISTENERS DE PRODUTO ====================
  // Função centralizada para reagir à mudança de produto
  function onProdutoChange(prodId) {
    const produto = prodId ? (produtos.find(p => p.id == prodId) || null) : null;
    if (prodId && !produto) {
    } else if (produto) {
    }
    atualizaOpcoesParcelamento(produto);
    atualizaInfo();
  }

  // Escuta evento nativo 'change' (funciona com Select2 na maioria dos casos)
  $(document).on('change', '#id_produto', function() {
    onProdutoChange($(this).val());
  });

  // Escuta evento Select2 'select2:select' como fallback robusto para django-select2
  $(document).on('select2:select', '#id_produto', function(e) {
    const selectedId = e.params && e.params.data ? e.params.data.id : $(this).val();
    onProdutoChange(selectedId);
  });

  // Escuta 'select2:unselect' / 'select2:clear' para quando o produto é removido
  $(document).on('select2:unselect select2:clear', '#id_produto', function() {
    onProdutoChange(null);
  });

  $(document).on('change', '#id_numero_parcelas', function() {
    atualizaInfo();
  });

  // Recalcula entrada ao digitar valor de entrada (iPhone)
  $('#id_entrada_informada').on('input', function() {
    atualizaInfo();
    validaEntrada();
  });

  // Inicializa cards ao carregar a página (600ms para garantir init do Select2)
  setTimeout(function() {
    initMarcas(); // Construir grid de marcas antes e captar options do Select2
    
    const prodId = $('#id_produto').val();
    if (prodId) {
      onProdutoChange(prodId);
    } else {
      atualizaInfo();
    }
  }, 600);
  
  // Form submission enhancement - simplified
  $('#clienteForm').on('submit', function(e) {
    // Bloqueia envio se a data de pagamento resultar em primeira parcela indisponível
    const dataInput = document.getElementById('id_data_pagamento');
    if (dataInput && dataInput.value) {
      const dia = parseInt(dataInput.value, 10);
      if (!calcularMelhorData(dia, 30) || dia === diaExcluido()) {
        e.preventDefault();
        const previsaoDiv = document.getElementById('vencimento-previsao-analise');
        if (previsaoDiv) {
          previsaoDiv.textContent = 'Vencimento da primeira parcela indisponível';
          previsaoDiv.className = 'form-text text-danger fw-semibold';
        }
        $('[data-bs-target="#tab-analise"]').tab('show');
        return;
      }
    }

    // Allow form submission without blocking
    // Just show a warning if there are validation errors
    let incompleteSteps = [];
    
    if (!checkDadosComplete()) {
      incompleteSteps.push('Dados do Cliente');
    }
    if (!checkComprovantesComplete()) {
      incompleteSteps.push('Comprovantes');
    }
    if (!checkProdutoComplete()) {
      incompleteSteps.push('Produto e Condições');
    }
    
    if (incompleteSteps.length > 0 && this.dataset.confirmadoIncompleto !== '1') {
      e.preventDefault();
      const form = this;
      const submitter = e.originalEvent && e.originalEvent.submitter;
      window.ipixConfirm({
        title: 'Seções incompletas',
        message: 'Estas seções podem estar incompletas: ' + incompleteSteps.join(', ') + '. Deseja salvar mesmo assim?',
        label: 'Salvar mesmo assim',
        variant: 'warning',
      }).then(function (confirmado) {
        if (confirmado) {
          form.dataset.confirmadoIncompleto = '1';
          if (form.requestSubmit) {
            form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
          } else {
            form.submit();
          }
          return;
        }
        // Leva o usuário para a primeira aba incompleta
        if (!checkDadosComplete()) {
          $('[data-bs-target="#tab-dados"]').tab('show');
        } else if (!checkComprovantesComplete()) {
          $('[data-bs-target="#tab-comprovantes"]').tab('show');
        } else if (!checkProdutoComplete()) {
          $('[data-bs-target="#tab-analise"]').tab('show');
        }
      });
    }
  });
  
  // Auto-save indicator
  let autoSaveTimer;
  $('input, select, textarea').on('input change', function() {
    clearTimeout(autoSaveTimer);
    $('#submitBtn').html('<i class="bx bx-time me-1"></i> Salvando...');
    
    autoSaveTimer = setTimeout(function() {
      $('#submitBtn').html('<i class="bx bx-save me-1"></i> Salvar');
    }, 1000);
  });
});

// Retorna a melhor data de primeiro vencimento dentro de maxDias, ou null se indisponível
function calcularMelhorData(diaEscolhido, maxDias) {
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const ano = hoje.getFullYear();
  const mes = hoje.getMonth() + 1;
  let melhorData = null;
  let maiorDiferenca = -1;
  for (let i = 0; i < 3; i++) {
    let novoMes = mes + i;
    let novoAno = ano + Math.floor((novoMes - 1) / 12);
    novoMes = ((novoMes - 1) % 12) + 1;
    let ultimoDiaMes = new Date(novoAno, novoMes, 0).getDate();
    let diaReal = Math.min(diaEscolhido, ultimoDiaMes);
    let dataCandidata = new Date(novoAno, novoMes - 1, diaReal);
    let diasAteParcela = Math.round((dataCandidata - hoje) / (1000 * 60 * 60 * 24));
    if (diasAteParcela > 0 && diasAteParcela <= maxDias) {
      if (diasAteParcela > maiorDiferenca) {
        melhorData = dataCandidata;
        maiorDiferenca = diasAteParcela;
      }
    }
  }
  return melhorData;
}

// Retorna o dia (1, 10 ou 20) cuja próxima ocorrência futura é a mais próxima de hoje.
// Essa opção fica desabilitada pois o prazo seria muito curto para o cliente.
function diaExcluido() {
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const ano = hoje.getFullYear();
  const mes = hoje.getMonth() + 1;
  const DIAS = [1, 10, 20];
  let menorDias = Infinity;
  let excluido = null;
  for (const dia of DIAS) {
    for (let i = 0; i < 3; i++) {
      let novoMes = mes + i;
      let novoAno = ano + Math.floor((novoMes - 1) / 12);
      novoMes = ((novoMes - 1) % 12) + 1;
      let ultimoDiaMes = new Date(novoAno, novoMes, 0).getDate();
      let diaReal = Math.min(dia, ultimoDiaMes);
      let dataCandidata = new Date(novoAno, novoMes - 1, diaReal);
      let diasAte = Math.round((dataCandidata - hoje) / (1000 * 60 * 60 * 24));
      if (diasAte > 0) {
        if (diasAte < menorDias) {
          menorDias = diasAte;
          excluido = dia;
        }
        break; // próxima ocorrência encontrada para este dia
      }
    }
  }
  return excluido;
}

// Previsão de vencimento na aba Produto
function calcularPrevisaoVencimentoAnalise() {
  const dataInput = document.getElementById('id_data_pagamento');
  const previsaoDiv = document.getElementById('vencimento-previsao-analise');
  if (!dataInput || !previsaoDiv) return;

  const MAX_DIAS = 30;
  const excluido = diaExcluido();

  // Desabilita: o dia mais próximo (muito curto) e qualquer opção acima de 30 dias
  Array.from(dataInput.options).forEach(function(option) {
    if (!option.value) return;
    const dia = parseInt(option.value, 10);
    const melhor = calcularMelhorData(dia, MAX_DIAS);
    option.disabled = !melhor || dia === excluido;
  });

  // Se a opção atual ficou desabilitada, limpa a seleção
  if (dataInput.value && dataInput.options[dataInput.selectedIndex] && dataInput.options[dataInput.selectedIndex].disabled) {
    dataInput.value = '';
  }

  const diaEscolhido = parseInt(dataInput.value, 10);
  if (isNaN(diaEscolhido)) {
    previsaoDiv.textContent = '';
    previsaoDiv.className = 'form-text text-primary';
    return;
  }

  const melhorData = calcularMelhorData(diaEscolhido, MAX_DIAS);
  if (melhorData && diaEscolhido !== excluido) {
    const diaStr = melhorData.getDate().toString().padStart(2, '0');
    const mesStr = (melhorData.getMonth() + 1).toString().padStart(2, '0');
    const anoStr = melhorData.getFullYear();
    previsaoDiv.textContent = 'Primeiro vencimento: ' + diaStr + '/' + mesStr + '/' + anoStr;
    previsaoDiv.className = 'form-text text-primary';
  } else {
    previsaoDiv.textContent = 'Vencimento da primeira parcela indisponível';
    previsaoDiv.className = 'form-text text-danger fw-semibold';
  }
}

document.addEventListener('DOMContentLoaded', function() {
  const dataInput = document.getElementById('id_data_pagamento');
  const parcelasInput = document.getElementById('id_numero_parcelas');
  if (dataInput && parcelasInput) {
    dataInput.addEventListener('change', calcularPrevisaoVencimentoAnalise);
    parcelasInput.addEventListener('change', calcularPrevisaoVencimentoAnalise);
    calcularPrevisaoVencimentoAnalise();
  }
  
  // Botão Aprovar - salvar formulário antes de redirecionar
  const aprovarBtn = document.getElementById('aprovarBtn');
  if (aprovarBtn) {
    aprovarBtn.addEventListener('click', function(e) {
      e.preventDefault();
      const form = document.getElementById('clienteForm');
      const aprovarUrl = this.getAttribute('data-url');
      
      form.querySelectorAll('input[name="aprovar_apos_salvar"]').forEach(function(input) {
        input.remove();
      });

      // Cria um campo hidden para identificar que é uma aprovação
      const hiddenField = document.createElement('input');
      hiddenField.type = 'hidden';
      hiddenField.name = 'aprovar_apos_salvar';
      hiddenField.value = aprovarUrl;
      form.appendChild(hiddenField);
      
      // Usa o fluxo normal de submit para manter validações e handlers ativos.
      if (form.requestSubmit) {
        form.requestSubmit();
      } else {
        const submitEvent = new Event('submit', { bubbles: true, cancelable: true });
        if (form.dispatchEvent(submitEvent) && form.checkValidity()) {
          form.submit();
        }
      }
    });
  }
});
