/**
 * Caixa de entrada do CRM (crm/templates/crm/caixa.html).
 *
 * - Formulários [data-crm-acao] vão por fetch; o servidor responde JSON
 *   ({ok, mensagem, erro, texto, avisos, redirecionar}) e a tela recarrega só os trechos.
 * - Trechos [data-crm-parte] chegam prontos do Django (HTML já escapado no servidor).
 * - Tempo real: evento "crm:evento" (disparado por notificacoes.js a partir do
 *   WebSocket) e, de reserva, recarga periódica com a aba visível.
 * - Sem JS tudo continua funcionando por POST comum (com mensagem no topo).
 */
(function () {
  'use strict';

  var raiz = document.getElementById('crmCaixa');
  if (!raiz) {
    return;
  }

  var INTERVALO_MS = 20000;
  var DIGITANDO_MS = 15000;
  var ESPERA_EVENTO_MS = 400;
  var PERTO_DO_FIM_PX = 160;
  var ALTURA_MAX_TEXTO_PX = 160;
  var PARTES = ['cabecalho', 'mensagens', 'compositor', 'painel'];
  var CHAVE_MENU = 'crm:menu-recolhido';
  var CHAVE_PAINEL = 'crm:painel-recolhido';

  var conversaId = raiz.getAttribute('data-conversa') || '';
  var urlLista = raiz.getAttribute('data-url-lista');
  var urlParte = raiz.getAttribute('data-url-parte') || '';
  var filtros = raiz.getAttribute('data-filtros') || '';
  var carregando = {};
  var repetir = {};
  var ultimoHtml = {};
  var mensagensPendentes = null;
  var temBusca = /(^|&)q=/.test(filtros);
  var ultimoDigitando = 0;
  var timerEvento = null;
  var eventoDaConversa = false;
  var partesPendentes = [];

  function nada() {}

  function avisar(texto, variante) {
    if (window.ipixToast) {
      window.ipixToast(texto, variante || 'info');
    }
  }

  function tokenCsrf() {
    var partes = (document.cookie || '').split(';');
    for (var i = 0; i < partes.length; i++) {
      var item = partes[i].trim();
      if (item.indexOf('csrftoken=') === 0) {
        return decodeURIComponent(item.substring('csrftoken='.length));
      }
    }
    var campo = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return campo ? campo.value : '';
  }

  function cabecalhos() {
    return { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': tokenCsrf() };
  }

  function buscarHtml(url) {
    return fetch(url, { credentials: 'same-origin', headers: cabecalhos() }).then(function (resposta) {
      if (!resposta.ok) {
        throw new Error('HTTP ' + resposta.status);
      }
      return resposta.text();
    });
  }

  function erroPorStatus(status) {
    if (status === 403) {
      return 'Sem permissão para isso, ou a sessão expirou. Recarregue a página.';
    }
    if (status === 404) {
      return 'Não encontrado: a conversa ou a mensagem pode ter mudado. Recarregue a página.';
    }
    if (status === 413) {
      return 'O arquivo é grande demais para o servidor.';
    }
    if (status >= 500) {
      return 'Erro no servidor. Tente de novo em instantes.';
    }
    return 'Não foi possível concluir. Se a sessão expirou, recarregue a página.';
  }

  function postar(url, dados) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: cabecalhos(), body: dados || new FormData() })
      .then(function (resposta) {
        return resposta.json().catch(function () {
          return { ok: false, erro: erroPorStatus(resposta.status) };
        });
      });
  }

  // ── Mensagens e rolagem ─────────────────────────────────────────────────
  function elMensagens() {
    return document.getElementById('crmMensagens');
  }

  function pertoDoFim(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < PERTO_DO_FIM_PX;
  }

  function rolarParaFim() {
    var el = elMensagens();
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }

  function maiorIdMensagem(raizBusca) {
    var maior = 0;
    raizBusca.querySelectorAll('[data-mensagem-id]').forEach(function (el) {
      maior = Math.max(maior, parseInt(el.getAttribute('data-mensagem-id'), 10) || 0);
    });
    return maior;
  }

  /** O HTML recebido traz mensagem que ainda não está na tela? */
  function temMensagemNova(el, html) {
    var modelo = document.createElement('template');
    modelo.innerHTML = html;
    return maiorIdMensagem(modelo.content) > maiorIdMensagem(el);
  }

  function mostrarNovas(mostrar) {
    var botao = document.querySelector('[data-crm-novas]');
    if (botao) {
      botao.classList.toggle('d-none', !mostrar);
    }
  }

  // ── Trechos ─────────────────────────────────────────────────────────────
  function compositorOcupado(considerarFoco) {
    var form = document.querySelector('[data-crm-compositor]');
    if (!form) {
      return false;
    }
    var texto = form.querySelector('[data-crm-texto]');
    var anexo = form.querySelector('[data-crm-anexo]');
    var resposta = form.querySelector('[data-crm-responde-a]');
    return Boolean((texto && texto.value.trim()) || (anexo && anexo.files.length) || (resposta && resposta.value)
      || (considerarFoco && form.contains(document.activeElement)));
  }

  /** Algum rascunho no painel (nota, apelido, busca) que a recarga apagaria. */
  function painelEmUso(el) {
    var campos = el.querySelectorAll('textarea, input[type="text"], input[type="search"]');
    for (var i = 0; i < campos.length; i++) {
      if (campos[i].value !== campos[i].defaultValue) {
        return true;
      }
    }
    return false;
  }

  function midiaTocando(el) {
    var midias = el.querySelectorAll('audio, video');
    for (var i = 0; i < midias.length; i++) {
      if (!midias[i].paused) {
        return true;
      }
    }
    return false;
  }

  function podeAtualizar(nome, el, forcar) {
    if (nome === 'compositor') {
      return !compositorOcupado(!forcar);
    }
    if (nome === 'painel') {
      return !painelEmUso(el);
    }
    return true;
  }

  /** Lendo mensagens antigas ou ouvindo um áudio: não arrasta a tela; avisa se chegou algo novo. */
  function mensagensOcupadas(el, forcar) {
    return !forcar && (!pertoDoFim(el) || midiaTocando(el));
  }

  function aplicarParte(nome, el, html) {
    if (html === ultimoHtml[nome]) {
      return;  // nada mudou: não mexe no DOM (não interrompe nada nem pisca)
    }
    ultimoHtml[nome] = html;
    el.innerHTML = html;
    if (nome === 'mensagens') {
      rolarParaFim();
      mostrarNovas(false);
    }
    if (nome === 'compositor') {
      ajustarAltura(el.querySelector('[data-crm-texto]'));
    }
    if (nome === 'cabecalho') {
      marcarBotoesPainel();
    }
  }

  // --- Recolher o menu do sistema e o painel do cliente (preferência guardada no navegador) ---

  function lerPreferencia(chave) {
    try {
      return window.localStorage.getItem(chave) === '1';
    } catch (erro) {
      return false;
    }
  }

  function gravarPreferencia(chave, ligado) {
    try {
      window.localStorage.setItem(chave, ligado ? '1' : '0');
    } catch (erro) {
      nada();
    }
  }

  function menuRecolhido() {
    return document.documentElement.classList.contains('layout-menu-collapsed');
  }

  function marcarBotaoMenu(recolhido) {
    var botao = document.querySelector('[data-crm-recolher-menu]');
    if (!botao) {
      return;
    }
    botao.setAttribute('aria-pressed', recolhido ? 'true' : 'false');
    var rotulo = botao.querySelector('[data-crm-rotulo]');
    if (rotulo) {
      rotulo.textContent = recolhido ? 'Abrir menu' : 'Recolher menu';
    }
  }

  function recolherMenu(recolher, animar) {
    if (window.Helpers && typeof window.Helpers.setCollapsed === 'function') {
      window.Helpers.setCollapsed(recolher, animar);
    } else {
      document.documentElement.classList.toggle('layout-menu-collapsed', recolher);
    }
    marcarBotaoMenu(recolher);
  }

  function marcarBotoesPainel() {
    var recolhido = raiz.classList.contains('crm-caixa--sem-painel');
    document.querySelectorAll('[data-crm-recolher-painel]').forEach(function (botao) {
      botao.setAttribute('aria-pressed', recolhido ? 'true' : 'false');
    });
  }

  function recolherPainel(recolher) {
    raiz.classList.toggle('crm-caixa--sem-painel', recolher);
    marcarBotoesPainel();
  }

  // --- Emojis: entram onde está o cursor do campo de mensagem ---

  function inserirEmoji(emoji) {
    var campo = document.querySelector('[data-crm-texto]');
    if (!campo) {
      return;
    }
    var inicio = campo.selectionStart == null ? campo.value.length : campo.selectionStart;
    var fim = campo.selectionEnd == null ? inicio : campo.selectionEnd;
    campo.value = campo.value.slice(0, inicio) + emoji + campo.value.slice(fim);
    var posicao = inicio + emoji.length;
    campo.focus();
    campo.setSelectionRange(posicao, posicao);
    ajustarAltura(campo);
  }

  function atualizarParte(nome, forcar) {
    var el = document.querySelector('[data-crm-parte="' + nome + '"]');
    if (!el || !urlParte) {
      return;
    }
    if (carregando[nome]) {
      // A resposta em voo pode ser anterior à ação; repete ao terminar.
      repetir[nome] = repetir[nome] || Boolean(forcar);
      return;
    }
    if (!podeAtualizar(nome, el, forcar)) {
      return;
    }
    carregando[nome] = true;
    var url = urlParte.replace('__parte__', nome) + (filtros ? '?' + filtros : '');
    buscarHtml(url)
      .then(function (html) {
        if (nome === 'mensagens' && mensagensOcupadas(el, forcar)) {
          if (temMensagemNova(el, html)) {
            mensagensPendentes = html;
            mostrarNovas(true);
          }
          return;
        }
        // Reavalia: o usuário pode ter começado a digitar enquanto a resposta vinha.
        if (podeAtualizar(nome, el, forcar)) {
          mensagensPendentes = nome === 'mensagens' ? null : mensagensPendentes;
          aplicarParte(nome, el, html);
        }
      })
      .catch(nada)
      .then(function () {
        carregando[nome] = false;
        if (nome in repetir) {
          var novamente = repetir[nome];
          delete repetir[nome];
          atualizarParte(nome, novamente);
        }
      });
  }

  function atualizarConversa(forcar, partes) {
    if (!conversaId) {
      return;
    }
    (partes || PARTES).forEach(function (nome) {
      atualizarParte(nome, forcar);
    });
  }

  function atualizarLista(automatica) {
    var el = document.getElementById('crmLista');
    // Com busca por texto, só recarrega quando o usuário pede (a busca varre as mensagens).
    if (!el || carregando.lista || (automatica && temBusca)) {
      return;
    }
    var ativo = document.activeElement;
    if (el.querySelector('.collapse.show') || (ativo && el.contains(ativo) && ativo.matches('input, select'))) {
      return;
    }
    carregando.lista = true;
    var itens = el.querySelector('.crm-lista__itens');
    var rolagem = itens ? itens.scrollTop : 0;
    var parametros = filtros + (conversaId ? (filtros ? '&' : '') + 'atual=' + encodeURIComponent(conversaId) : '');
    buscarHtml(urlLista + (parametros ? '?' + parametros : ''))
      .then(function (html) {
        el.innerHTML = html;
        var novos = el.querySelector('.crm-lista__itens');
        if (novos) {
          novos.scrollTop = rolagem;
        }
      })
      .catch(nada)
      .then(function () {
        carregando.lista = false;
      });
  }

  /** Junta eventos em rajada numa recarga só (com a união das partes pedidas). */
  function agendarAtualizacao(daConversa, partes) {
    if (daConversa) {
      eventoDaConversa = true;
      (partes || PARTES).forEach(function (nome) {
        if (partesPendentes.indexOf(nome) < 0) {
          partesPendentes.push(nome);
        }
      });
    }
    if (timerEvento) {
      return;
    }
    timerEvento = window.setTimeout(function () {
      var conversa = eventoDaConversa;
      var partesDaVez = partesPendentes;
      timerEvento = null;
      eventoDaConversa = false;
      partesPendentes = [];
      atualizarLista(true);
      if (conversa) {
        atualizarConversa(false, partesDaVez);
      }
    }, ESPERA_EVENTO_MS);
  }

  // ── Compositor ──────────────────────────────────────────────────────────
  function ajustarAltura(campo) {
    if (!campo) {
      return;
    }
    campo.style.height = 'auto';
    campo.style.height = Math.min(campo.scrollHeight, ALTURA_MAX_TEXTO_PX) + 'px';
  }

  /** Limpa o que foi enviado; o texto só se ninguém o alterou durante o envio. */
  function limparCompositor(form, textoEnviado) {
    var campo = form.querySelector('[data-crm-texto]');
    var anexo = form.querySelector('[data-crm-anexo]');
    if (campo.value === textoEnviado) {
      campo.value = '';
    }
    anexo.value = '';
    definirResposta(form, '', '');
    mostrarAnexo(anexo);
    ajustarAltura(campo);
  }

  function definirResposta(form, id, texto) {
    if (!form) {
      return;
    }
    form.querySelector('[data-crm-responde-a]').value = id;
    form.querySelector('[data-crm-texto-resposta]').textContent = texto;
    form.querySelector('[data-crm-barra-resposta]').classList.toggle('d-none', !id);
  }

  function mostrarAnexo(campo) {
    if (!campo) {
      return;
    }
    var form = campo.form;
    var arquivo = campo.files && campo.files[0];
    form.querySelector('[data-crm-nome-anexo]').textContent = arquivo ? arquivo.name : '';
    form.querySelector('[data-crm-barra-anexo]').classList.toggle('d-none', !arquivo);
  }

  function avisarDigitando(form) {
    var agora = Date.now();
    if (agora - ultimoDigitando < DIGITANDO_MS) {
      return;
    }
    ultimoDigitando = agora;
    postar(form.getAttribute('data-url-digitando')).catch(nada);
  }

  function usarTextoPronto(texto) {
    var campo = document.querySelector('[data-crm-texto]');
    if (campo) {
      campo.value = campo.value.trim() ? campo.value.replace(/\s*$/, '\n\n') + texto : texto;
      ajustarAltura(campo);
      campo.focus();
      avisar('Texto pronto no campo de mensagem. Revise antes de enviar.', 'info');
      return;
    }
    if (navigator.clipboard) {
      navigator.clipboard.writeText(texto)
        .then(function () { avisar('Texto copiado. Assuma a conversa para enviar.', 'info'); })
        .catch(function () { avisar('Assuma a conversa para enviar o texto.', 'warning'); });
    }
  }

  // ── Ações ───────────────────────────────────────────────────────────────
  function fecharModal(form) {
    var modal = form.closest('.modal');
    if (modal && window.bootstrap) {
      window.bootstrap.Modal.getOrCreateInstance(modal).hide();
      form.reset();
    }
  }

  function destinoInterno(url) {
    return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/';
  }

  function tratarResposta(form, resposta, textoEnviado) {
    if (!resposta.ok) {
      avisar(resposta.erro || 'Não foi possível concluir.', 'danger');
      return;
    }
    if (destinoInterno(resposta.redirecionar)) {
      window.location.assign(resposta.redirecionar);
      return;
    }
    if (form.hasAttribute('data-crm-texto-pronto')) {
      usarTextoPronto(resposta.texto || '');
      return;
    }
    if (resposta.mensagem) {
      avisar(resposta.mensagem, 'success');
    }
    fecharModal(form);
    if (form.hasAttribute('data-crm-limpar')) {
      form.reset();  // sem rascunho, o painel pode recarregar com o resultado
    }
    if (form.hasAttribute('data-crm-compositor')) {
      limparCompositor(form, textoEnviado);
    }
    atualizarLista();
    atualizarConversa(true);
  }

  function enviarFormulario(form, botao) {
    var ehCompositor = form.hasAttribute('data-crm-compositor');
    // Trava por formulário: Enter repetido ou segurado não manda a mensagem duas vezes.
    if (form.dataset.crmEnviando === '1' || (ehCompositor && !compositorOcupado(false))) {
      return;
    }
    var dados = new FormData(form);
    if (botao && botao.name) {
      dados.set(botao.name, botao.value);
    }
    var campoTexto = form.querySelector('[data-crm-texto]');
    var textoEnviado = campoTexto ? campoTexto.value : '';
    var botoes = form.querySelectorAll('button[type="submit"]');
    form.dataset.crmEnviando = '1';
    botoes.forEach(function (b) { b.disabled = true; });
    postar(form.action, dados)
      .then(function (resposta) { tratarResposta(form, resposta, textoEnviado); })
      .catch(function () { avisar('Falha de conexão. Tente de novo.', 'danger'); })
      .then(function () {
        delete form.dataset.crmEnviando;
        botoes.forEach(function (b) { b.disabled = false; });
      });
  }

  function buscarCliente(form) {
    var destino = form.parentElement.querySelector('[data-crm-busca-resultado]');
    var consulta = new URLSearchParams(new FormData(form)).toString();
    buscarHtml(form.action + '?' + consulta)
      .then(function (html) { destino.innerHTML = html; })
      .catch(function () { avisar('Não foi possível buscar agora.', 'danger'); });
  }

  function carregarAntigas(botao) {
    var bloco = botao.closest('[data-crm-antigas-bloco]');
    var lista = elMensagens();
    botao.disabled = true;
    buscarHtml(botao.getAttribute('data-url'))
      .then(function (html) {
        var alturaAntes = lista.scrollHeight;
        var topoAntes = lista.scrollTop;
        var temporario = document.createElement('div');
        temporario.innerHTML = html;
        var fragmento = document.createDocumentFragment();
        while (temporario.firstChild) {
          fragmento.appendChild(temporario.firstChild);
        }
        bloco.replaceWith(fragmento);
        lista.scrollTop = topoAntes + (lista.scrollHeight - alturaAntes);
      })
      .catch(function () {
        botao.disabled = false;
        avisar('Não foi possível carregar as mensagens anteriores.', 'danger');
      });
  }

  function aplicarRespostaRapida(url) {
    postar(url)
      .then(function (resposta) {
        if (!resposta.ok) {
          avisar(resposta.erro || 'Resposta rápida indisponível.', 'danger');
          return;
        }
        usarTextoPronto(resposta.texto || '');
        (resposta.avisos || []).forEach(function (aviso) { avisar(aviso, 'warning'); });
      })
      .catch(function () { avisar('Falha de conexão. Tente de novo.', 'danger'); });
  }

  // ── Eventos ─────────────────────────────────────────────────────────────
  // Registrado depois do confirm-action.js: formulários com data-confirm-message
  // chegam aqui só depois de confirmados (o primeiro envio vem com defaultPrevented).
  document.addEventListener('submit', function (evento) {
    var form = evento.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (form.matches('[data-crm-busca]')) {
      evento.preventDefault();
      buscarCliente(form);
      return;
    }
    if (!form.matches('[data-crm-acao]') || evento.defaultPrevented) {
      return;
    }
    evento.preventDefault();
    delete form.dataset.confirmado;
    enviarFormulario(form, evento.submitter);
  });

  document.addEventListener('click', function (evento) {
    var alvo = evento.target;
    var emoji = alvo.closest('[data-crm-emoji]');
    if (emoji) {
      inserirEmoji(emoji.getAttribute('data-crm-emoji'));
      return;
    }
    var mais = alvo.closest('[data-crm-mais-reacoes]');
    if (mais) {
      var todas = mais.closest('form').querySelector('[data-crm-todas-reacoes]');
      var abrir = todas.classList.contains('d-none');
      todas.classList.toggle('d-none', !abrir);
      mais.setAttribute('aria-expanded', abrir ? 'true' : 'false');
      return;
    }
    if (alvo.closest('[data-crm-recolher-menu]')) {
      var recolherMenuAgora = !menuRecolhido();
      recolherMenu(recolherMenuAgora, true);
      gravarPreferencia(CHAVE_MENU, recolherMenuAgora);
      return;
    }
    if (alvo.closest('[data-crm-recolher-painel]')) {
      var recolherPainelAgora = !raiz.classList.contains('crm-caixa--sem-painel');
      recolherPainel(recolherPainelAgora);
      gravarPreferencia(CHAVE_PAINEL, recolherPainelAgora);
      return;
    }
    var rapida = alvo.closest('[data-crm-resposta-rapida]');
    if (rapida) {
      evento.preventDefault();
      aplicarRespostaRapida(rapida.getAttribute('data-crm-resposta-rapida'));
      return;
    }
    var responder = alvo.closest('[data-crm-responder]');
    if (responder) {
      var form = document.querySelector('[data-crm-compositor]');
      definirResposta(form, responder.getAttribute('data-crm-responder'), responder.getAttribute('data-texto'));
      if (form) {
        form.querySelector('[data-crm-texto]').focus();
      }
      return;
    }
    if (alvo.closest('[data-crm-cancelar-resposta]')) {
      definirResposta(alvo.closest('form'), '', '');
      return;
    }
    if (alvo.closest('[data-crm-cancelar-anexo]')) {
      var campo = alvo.closest('form').querySelector('[data-crm-anexo]');
      campo.value = '';
      mostrarAnexo(campo);
      return;
    }
    var antigas = alvo.closest('[data-crm-antigas]');
    if (antigas) {
      carregarAntigas(antigas);
      return;
    }
    if (alvo.closest('[data-crm-novas]')) {
      var el = document.querySelector('[data-crm-parte="mensagens"]');
      if (mensagensPendentes && el) {
        var html = mensagensPendentes;
        mensagensPendentes = null;
        aplicarParte('mensagens', el, html);
      } else {
        atualizarParte('mensagens', true);
      }
    }
  });

  document.addEventListener('keydown', function (evento) {
    if (!evento.target.matches('[data-crm-texto]')) {
      return;
    }
    if (evento.key === 'Enter' && !evento.shiftKey && !evento.isComposing) {
      evento.preventDefault();
      evento.target.form.requestSubmit();
    }
  });

  document.addEventListener('input', function (evento) {
    if (evento.target.matches('[data-crm-texto]')) {
      ajustarAltura(evento.target);
      avisarDigitando(evento.target.form);
    }
  });

  document.addEventListener('change', function (evento) {
    var campo = evento.target;
    if (campo.matches('[data-crm-anexo]')) {
      mostrarAnexo(campo);
    } else if (campo.matches('[data-crm-auto]') && campo.form) {
      campo.form.requestSubmit();
    }
  });

  var mensagens = elMensagens();
  if (mensagens) {
    mensagens.addEventListener('scroll', function () {
      if (!pertoDoFim(mensagens)) {
        return;
      }
      mostrarNovas(false);
      if (mensagensPendentes && !midiaTocando(mensagens)) {
        var html = mensagensPendentes;
        mensagensPendentes = null;
        aplicarParte('mensagens', mensagens, html);
      }
    });
  }

  // Com a aba escondida, não recarrega as mensagens: abrir as mensagens marca a conversa
  // como lida e manda o recibo (tiques azuis) ao cliente.
  document.addEventListener('crm:evento', function (evento) {
    var dados = evento.detail || {};
    var daConversa = Boolean(conversaId) && String(dados.conversa_id) === conversaId;
    agendarAtualizacao(daConversa, document.hidden ? ['cabecalho'] : null);
  });

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) {
      agendarAtualizacao(true);
    }
  });

  window.setInterval(function () {
    if (!document.hidden) {
      agendarAtualizacao(true, ['cabecalho', 'mensagens', 'compositor']);
    }
  }, INTERVALO_MS);

  if (lerPreferencia(CHAVE_MENU)) {
    recolherMenu(true, false);
  }
  recolherPainel(lerPreferencia(CHAVE_PAINEL));
  rolarParaFim();
  // As imagens terminam de carregar depois: desce de novo para a última mensagem.
  window.addEventListener('load', rolarParaFim);
  ajustarAltura(document.querySelector('[data-crm-texto]'));
})();
