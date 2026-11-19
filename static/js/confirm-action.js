/**
 * Confirmação padrão para ações que alteram dados (substitui confirm()).
 *
 * Usa o modal #confirmActionModal (templates/components/confirm_modal.html).
 * Três formas de uso:
 *
 * 1. Elemento com data-post-url: ao confirmar, envia um POST (com CSRF)
 *    para a URL informada.
 * 2. <form data-confirm-message="...">: o envio do formulário só acontece
 *    depois da confirmação (mantém método, campos e botão clicado).
 * 3. JS: window.ipixConfirm({message, title, label, variant}) devolve uma
 *    Promise<boolean>.
 *
 * Atributos opcionais: data-confirm-title, data-confirm-message,
 * data-confirm-label e data-confirm-variant (danger | warning | primary | success).
 */
(function () {
  'use strict';

  var DEFAULTS = {
    title: 'Confirmar ação',
    message: 'Tem certeza que deseja continuar?',
    label: 'Confirmar',
    variant: 'primary',
  };
  var VARIANTS = ['primary', 'danger', 'warning', 'success'];

  // Ação pendente quando a confirmação não é um POST direto (formulário/JS).
  var pendente = null;

  function normalizar(options) {
    var opts = options || {};
    return {
      url: opts.url || null,
      title: opts.title || DEFAULTS.title,
      message: opts.message || DEFAULTS.message,
      label: opts.label || DEFAULTS.label,
      variant: VARIANTS.indexOf(opts.variant) >= 0 ? opts.variant : DEFAULTS.variant,
    };
  }

  function readOptions(trigger) {
    return normalizar({
      url: trigger.getAttribute('data-post-url'),
      title: trigger.getAttribute('data-confirm-title'),
      message: trigger.getAttribute('data-confirm-message'),
      label: trigger.getAttribute('data-confirm-label'),
      variant: trigger.getAttribute('data-confirm-variant'),
    });
  }

  function elementos() {
    return {
      modal: document.getElementById('confirmActionModal'),
      form: document.getElementById('confirmActionForm'),
      submit: document.getElementById('confirmActionSubmit'),
    };
  }

  function openConfirm(options, aoConfirmar) {
    var el = elementos();
    if (!el.modal || !el.form || !el.submit || !window.bootstrap) {
      // Sem modal disponível: não bloqueia a ação silenciosamente.
      if (aoConfirmar) {
        aoConfirmar(window.confirm(options.message));
      }
      return;
    }

    document.getElementById('confirmActionTitle').textContent = options.title;
    document.getElementById('confirmActionMessage').textContent = options.message;
    el.submit.textContent = options.label;
    el.submit.className = 'btn btn-' + options.variant;
    el.submit.disabled = false;

    if (aoConfirmar) {
      pendente = aoConfirmar;
      el.form.removeAttribute('action');
    } else {
      pendente = null;
      el.form.setAttribute('action', options.url);
    }

    window.bootstrap.Modal.getOrCreateInstance(el.modal).show();
  }

  function ipixConfirm(options) {
    return new Promise(function (resolve) {
      openConfirm(normalizar(options), resolve);
    });
  }

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-post-url]');
    if (!trigger) {
      return;
    }
    event.preventDefault();
    openConfirm(readOptions(trigger));
  });

  document.addEventListener('submit', function (event) {
    var form = event.target;

    if (form.id === 'confirmActionForm') {
      if (pendente) {
        event.preventDefault();
        var acao = pendente;
        pendente = null;
        window.bootstrap.Modal.getOrCreateInstance(elementos().modal).hide();
        acao(true);
        return;
      }
      // Evita envio duplo por clique repetido.
      document.getElementById('confirmActionSubmit').disabled = true;
      return;
    }

    if (!form.hasAttribute('data-confirm-message') || form.dataset.confirmado === '1') {
      return;
    }
    event.preventDefault();
    var submitter = event.submitter || null;
    openConfirm(readOptions(form), function (confirmado) {
      if (!confirmado) {
        return;
      }
      form.dataset.confirmado = '1';
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      } else {
        form.submit();
      }
    });
  });

  // Fechar o modal sem confirmar descarta a ação pendente.
  document.addEventListener('hidden.bs.modal', function (event) {
    if (event.target.id !== 'confirmActionModal' || !pendente) {
      return;
    }
    var acao = pendente;
    pendente = null;
    acao(false);
  });

  window.ipixConfirm = ipixConfirm;
})();
