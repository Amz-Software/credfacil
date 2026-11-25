/**
 * Aviso de nova versão (templates/base.html, core/versao.py).
 *
 * A página guarda a versão com que foi aberta (data-versao). A cada minuto, com a aba
 * visível, pergunta a versão no ar (/versao/). Se mudou (houve deploy), mostra o aviso
 * com "Atualizar" (recarrega a página). "Lembrar depois" esconde até sair outra versão.
 * Falha de rede ou servidor reiniciando no meio do deploy: tenta de novo na próxima vez.
 */
(function () {
  'use strict';

  var aviso = document.getElementById('avisoNovaVersao');
  if (!aviso || !window.fetch) {
    return;
  }

  var INTERVALO_MS = 60000;
  var versaoDaPagina = aviso.getAttribute('data-versao');
  var url = aviso.getAttribute('data-url');
  var versaoAdiada = null;

  function mostrar(versao) {
    if (versao === versaoAdiada) {
      return;
    }
    aviso.setAttribute('data-nova', versao);
    aviso.classList.remove('d-none');
  }

  function verificar() {
    if (document.hidden) {
      return;
    }
    fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(function (resposta) { return resposta.ok ? resposta.json() : null; })
      .then(function (dados) {
        if (dados && dados.versao && dados.versao !== versaoDaPagina) {
          mostrar(dados.versao);
        }
      })
      .catch(function () { /* sem rede ou deploy em andamento: tenta na próxima */ });
  }

  aviso.addEventListener('click', function (evento) {
    if (evento.target.closest('[data-versao-atualizar]')) {
      window.location.reload();
      return;
    }
    if (evento.target.closest('[data-versao-depois]')) {
      versaoAdiada = aviso.getAttribute('data-nova');
      aviso.classList.add('d-none');
    }
  });

  document.addEventListener('visibilitychange', verificar);
  window.setInterval(verificar, INTERVALO_MS);
})();
