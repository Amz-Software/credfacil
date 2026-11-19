/**
 * Notificações em tempo real do backoffice (WebSocket /ws/notifications/).
 *
 * Antes ficava inline em templates/base.html. Valores do Django chegam por
 * data-attributes no próprio <script>:
 *   data-sons-url        → prefixo dos arquivos de som (static/sounds/)
 *   data-pode-ver-modal  → "1" quando o usuário pode ver o modal central
 *                           de nova proposta (ANALISTA / ADMINISTRADOR)
 *
 * Todo texto vindo do servidor (nome do cliente, descrição, URL) entra no DOM
 * via textContent / atributos (nunca como HTML cru) para evitar XSS armazenado.
 */
(function () {
  'use strict';

  var scriptEl = document.currentScript;
  var SONS_URL = (scriptEl && scriptEl.getAttribute('data-sons-url')) || '/static/sounds/';
  var PODE_VER_MODAL = !!(scriptEl && scriptEl.getAttribute('data-pode-ver-modal') === '1');
  var WS_ESPERA_MAXIMA_MS = 30000;
  var EVENTOS_MODAL = ['proposta_criada', 'pre_analise_criada', 'instalacao_aguardando_confirmacao'];
  var SONS_POR_TIPO = {
    analise_credito_cliente: 'notification.mp3',
    entrada_estoque: 'notification-alert.mp3',
  };

  var wsTentativas = 0;
  var modalProposta = null;

  function getCookie(name) {
    if (!document.cookie) {
      return null;
    }
    var prefixo = name + '=';
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
      var cookie = cookies[i].trim();
      if (cookie.indexOf(prefixo) === 0) {
        return decodeURIComponent(cookie.substring(prefixo.length));
      }
    }
    return null;
  }

  /** Aceita apenas URLs relativas ou do mesmo host (evita javascript: etc.). */
  function urlSegura(url) {
    if (!url) {
      return '#';
    }
    try {
      var destino = new URL(url, window.location.origin);
      if (destino.protocol !== 'http:' && destino.protocol !== 'https:') {
        return '#';
      }
      return destino.origin === window.location.origin ? destino.pathname + destino.search + destino.hash : '#';
    } catch (e) {
      return '#';
    }
  }

  function marcarComoLida(notificationId, targetUrl) {
    var destino = urlSegura(targetUrl);
    var id = encodeURIComponent(String(notificationId));
    fetch('/notificacao/marcar-como-lida/' + id + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') || '' },
      credentials: 'same-origin',
    })
      .catch(function () { /* segue para o destino mesmo se falhar */ })
      .then(function () {
        window.location.href = destino;
      });
  }

  function tocarSom(tipo) {
    var arquivo = SONS_POR_TIPO[tipo] || 'notification.mp3';
    try {
      var audio = new Audio(SONS_URL + arquivo);
      audio.volume = 1.0;
      // O navegador bloqueia som antes de qualquer interação; ignorar.
      audio.play().catch(function () {});
    } catch (e) { /* sem suporte a áudio */ }
  }

  function incrementarBadge() {
    var ancora = document.getElementById('notificacaoDropdown');
    if (!ancora) {
      return;
    }
    var contador = ancora.querySelector('[data-notificacoes-contador]');
    if (contador) {
      var atual = parseInt(contador.textContent, 10) || 0;
      contador.textContent = String(atual + 1);
      return;
    }
    var badge = document.createElement('span');
    badge.className = 'position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger';
    var numero = document.createElement('span');
    numero.setAttribute('data-notificacoes-contador', '');
    numero.textContent = '1';
    badge.appendChild(numero);
    var oculto = document.createElement('span');
    oculto.className = 'visually-hidden';
    oculto.textContent = ' notificações não lidas';
    badge.appendChild(oculto);
    ancora.appendChild(badge);
  }

  function criarSpan(classe, texto) {
    var el = document.createElement('span');
    el.className = classe;
    el.textContent = texto == null ? '' : String(texto);
    return el;
  }

  function criarItemNotificacao(data) {
    var li = document.createElement('li');
    li.className = 'mb-1';

    var link = document.createElement('a');
    link.className = 'dropdown-item d-flex flex-column small text-wrap text-break notificacao-nova';
    link.href = urlSegura(data.target_url);
    link.setAttribute('data-notificacao-id', String(data.notification_id || ''));
    link.setAttribute('data-notificacao-url', link.getAttribute('href'));

    link.appendChild(criarSpan('fw-semibold text-body text-wrap text-break', data.verb));
    link.appendChild(criarSpan('text-muted text-wrap text-break', data.description));
    var hora = document.createElement('small');
    hora.className = 'text-muted mt-1';
    hora.textContent = data.timestamp == null ? '' : String(data.timestamp);
    link.appendChild(hora);

    li.appendChild(link);
    return li;
  }

  function inserirNoDropdown(data) {
    var ancora = document.getElementById('notificacaoDropdown');
    var dropdownLi = ancora ? ancora.closest('li.dropdown') : null;
    var menu = dropdownLi ? dropdownLi.querySelector('.dropdown-menu') : null;
    if (!menu) {
      return;
    }

    var vazio = menu.querySelector('[data-notificacoes-vazio]');
    if (vazio) {
      vazio.remove();
    }

    var item = criarItemNotificacao(data);
    var header = menu.querySelector('.dropdown-header');
    var depoisDoHeader = header ? header.nextElementSibling : null;
    if (depoisDoHeader) {
      menu.insertBefore(item, depoisDoHeader);
    } else {
      menu.appendChild(item);
    }
    menu.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function mostrarModalProposta(data) {
    var el = document.getElementById('modalNovaProposta');
    if (!el || !window.bootstrap || !window.bootstrap.Modal) {
      return;
    }

    var titulo = 'Nova proposta recebida';
    var rotuloLink = 'Ver proposta';
    if (data.event === 'instalacao_aguardando_confirmacao') {
      titulo = 'Instalação aguardando confirmação';
      rotuloLink = 'Ver solicitação';
    } else if (data.event === 'pre_analise_criada') {
      titulo = 'Nova análise rápida';
      rotuloLink = 'Ver análise';
    }

    var tituloEl = document.getElementById('modalNovaPropostaTitulo');
    var verbEl = document.getElementById('modalNovaPropostaVerb');
    var descEl = document.getElementById('modalNovaPropostaDescription');
    var linkEl = document.getElementById('modalNovaPropostaLink');

    if (tituloEl) tituloEl.textContent = titulo;
    if (verbEl) verbEl.textContent = data.verb || 'Uma nova proposta foi criada.';
    if (descEl) descEl.textContent = data.description || '';
    if (linkEl) {
      var destino = urlSegura(data.target_url);
      linkEl.textContent = rotuloLink;
      linkEl.href = destino;
      linkEl.classList.toggle('d-none', destino === '#');
    }

    modalProposta = window.bootstrap.Modal.getOrCreateInstance(el);
    modalProposta.show();
  }

  function tratarMensagemWs(evento) {
    var data;
    try {
      data = JSON.parse(evento.data);
    } catch (e) {
      return;
    }
    if (!data || typeof data !== 'object') {
      return;
    }

    // Eventos do CRM só avisam a caixa de entrada que algo mudou (sem som nem sino).
    if (data.event === 'crm.evento') {
      document.dispatchEvent(new CustomEvent('crm:evento', { detail: data }));
      return;
    }

    if (PODE_VER_MODAL && EVENTOS_MODAL.indexOf(data.event) >= 0) {
      mostrarModalProposta(data);
    }

    tocarSom(data.type_notification);
    incrementarBadge();
    inserirNoDropdown(data);
  }

  // Reconecta sozinho quando o servidor reinicia (deploy, reciclagem de
  // worker): sem isso o analista deixava de receber o modal até dar F5.
  function conectarWs() {
    var esquema = window.location.protocol === 'https:' ? 'wss' : 'ws';
    var socket;
    try {
      socket = new WebSocket(esquema + '://' + window.location.host + '/ws/notifications/');
    } catch (e) {
      return;
    }

    socket.onopen = function () {
      wsTentativas = 0;
    };

    socket.onclose = function () {
      var espera = Math.min(WS_ESPERA_MAXIMA_MS, 1000 * Math.pow(2, wsTentativas));
      wsTentativas += 1;
      setTimeout(conectarWs, espera);
    };

    socket.onmessage = tratarMensagemWs;
  }

  // Clique em qualquer notificação (lista renderizada pelo Django ou recebida
  // pelo WebSocket) marca como lida antes de navegar.
  document.addEventListener('click', function (evento) {
    var link = evento.target.closest('[data-notificacao-id]');
    if (!link) {
      return;
    }
    evento.preventDefault();
    marcarComoLida(link.getAttribute('data-notificacao-id'), link.getAttribute('data-notificacao-url'));
  });

  // Mantidos no escopo global por compatibilidade com scripts de página.
  window.getCookie = window.getCookie || getCookie;
  window.marcarComoLida = marcarComoLida;
  window.mostrarModalProposta = mostrarModalProposta;

  conectarWs();
})();
