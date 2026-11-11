/**
 * Confirmação padrão para ações que alteram dados.
 *
 * Qualquer elemento com data-post-url abre o modal #confirmActionModal
 * (templates/components/confirm_modal.html) e, ao confirmar, envia um POST
 * com CSRF para a URL informada.
 *
 * Atributos opcionais: data-confirm-title, data-confirm-message,
 * data-confirm-label e data-confirm-variant (danger | warning | primary).
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

  function readOptions(trigger) {
    var variant = trigger.getAttribute('data-confirm-variant');
    return {
      url: trigger.getAttribute('data-post-url'),
      title: trigger.getAttribute('data-confirm-title') || DEFAULTS.title,
      message: trigger.getAttribute('data-confirm-message') || DEFAULTS.message,
      label: trigger.getAttribute('data-confirm-label') || DEFAULTS.label,
      variant: VARIANTS.indexOf(variant) >= 0 ? variant : DEFAULTS.variant,
    };
  }

  function openConfirm(options) {
    var modalEl = document.getElementById('confirmActionModal');
    var form = document.getElementById('confirmActionForm');
    var submit = document.getElementById('confirmActionSubmit');
    if (!modalEl || !form || !submit || !window.bootstrap) {
      return;
    }

    document.getElementById('confirmActionTitle').textContent = options.title;
    document.getElementById('confirmActionMessage').textContent = options.message;
    submit.textContent = options.label;
    submit.className = 'btn btn-' + options.variant;
    submit.disabled = false;
    form.setAttribute('action', options.url);

    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
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
    if (event.target.id !== 'confirmActionForm') {
      return;
    }
    // Evita envio duplo por clique repetido.
    document.getElementById('confirmActionSubmit').disabled = true;
  });
})();
