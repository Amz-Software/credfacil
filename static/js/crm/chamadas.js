/**
 * Ligações pelo WhatsApp no navegador (crm/templates/crm/parciais/chamada_widget.html).
 *
 * Recebida: evento "crm:evento" (tipo chamada_tocando) → toca para todos → quem clica em
 * Atender cria a resposta WebRTC para a oferta da Meta e manda ao servidor; o microfone só
 * abre depois que o servidor confirma (a Meta pede o áudio só após o accept).
 * Feita: botão [data-ligar] da conversa → oferta WebRTC → servidor pede à Meta → a resposta
 * do cliente chega pelo webhook e é buscada aqui. Sem permissão, oferece "Pedir permissão".
 */
(function () {
  'use strict';

  var raiz = document.getElementById('crmLigacao');
  if (!raiz || !window.RTCPeerConnection || !navigator.mediaDevices) {
    return;
  }

  var SERVIDORES_ICE = [{ urls: 'stun:stun.l.google.com:19302' }];
  var ESPERA_ICE_MS = 2500;
  var INTERVALO_CONSULTA_MS = 1500;
  var LIMITE_CHAMANDO_MS = 70000;
  var FINAIS = ['ENCERRADA', 'PERDIDA', 'RECUSADA', 'FALHOU'];

  var el = {
    nome: raiz.querySelector('[data-ligacao-nome]'),
    situacao: raiz.querySelector('[data-ligacao-situacao]'),
    tempo: raiz.querySelector('[data-ligacao-tempo]'),
    atender: raiz.querySelector('[data-ligacao-atender]'),
    ignorar: raiz.querySelector('[data-ligacao-ignorar]'),
    permissao: raiz.querySelector('[data-ligacao-permissao]'),
    mudo: raiz.querySelector('[data-ligacao-mudo]'),
    desligar: raiz.querySelector('[data-ligacao-desligar]'),
    abrir: raiz.querySelector('[data-ligacao-abrir]'),
    audio: raiz.querySelector('[data-ligacao-audio]')
  };
  var toque = new Audio(raiz.getAttribute('data-som'));
  toque.loop = true;

  var tocando = null;      // ligação recebida esperando resposta: {id, nome, ...}
  var atual = null;        // ligação em curso: {id, direcao, pc, stream, inicio, relogio, consulta}
  var ignoradas = {};
  var pedirPermissaoUrl = '';

  // --- infraestrutura ---------------------------------------------------------------------------

  function url(nome, id) {
    return raiz.getAttribute('data-url-' + nome).replace('/0/', '/' + id + '/');
  }

  function csrf() {
    var achado = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return achado ? decodeURIComponent(achado[1]) : '';
  }

  function avisar(texto, variante) {
    if (window.ipixToast) {
      window.ipixToast(texto, variante || 'danger');
    }
  }

  function postar(endereco, corpo) {
    return fetch(endereco, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(corpo || {})
    }).then(function (resposta) {
      return resposta.json().catch(function () { return {}; }).then(function (dados) {
        if (!resposta.ok) {
          var erro = new Error(dados.detail || dados.erro || 'Não foi possível concluir. Tente de novo.');
          erro.motivo = dados.motivo || '';
          throw erro;
        }
        return dados;
      });
    });
  }

  function buscar(endereco) {
    return fetch(endereco, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(function (resposta) {
        if (!resposta.ok) {
          throw new Error('Não foi possível consultar a ligação.');
        }
        return resposta.json();
      });
  }

  // --- tela -------------------------------------------------------------------------------------

  function mostrarBotoes(visiveis) {
    ['atender', 'ignorar', 'permissao', 'mudo', 'desligar'].forEach(function (nome) {
      el[nome].classList.toggle('d-none', visiveis.indexOf(nome) < 0);
    });
  }

  function exibir(dados, situacao, botoes) {
    el.nome.textContent = dados.nome || dados.telefone || 'Cliente';
    el.situacao.textContent = situacao;
    el.abrir.href = url('conversa', dados.conversa_id);
    mostrarBotoes(botoes);
    raiz.classList.remove('d-none');
  }

  function esconder() {
    raiz.classList.add('d-none');
    el.tempo.classList.add('d-none');
    pararToque();
  }

  function tocarSom() {
    toque.currentTime = 0;
    toque.play().catch(function () { /* o navegador bloqueia som sem interação: fica só o aviso */ });
  }

  function pararToque() {
    toque.pause();
  }

  function iniciarRelogio() {
    atual.inicio = Date.now();
    el.tempo.classList.remove('d-none');
    atual.relogio = window.setInterval(function () {
      var segundos = Math.floor((Date.now() - atual.inicio) / 1000);
      var minutos = Math.floor(segundos / 60);
      el.tempo.textContent = String(minutos).padStart(2, '0') + ':' + String(segundos % 60).padStart(2, '0');
    }, 1000);
  }

  // --- WebRTC -----------------------------------------------------------------------------------

  function abrirMicrofone() {
    return navigator.mediaDevices.getUserMedia({ audio: true, video: false }).catch(function () {
      throw new Error('Libere o microfone do navegador para falar na ligação.');
    });
  }

  function novaConexao(stream) {
    var pc = new RTCPeerConnection({ iceServers: SERVIDORES_ICE });
    stream.getTracks().forEach(function (faixa) { pc.addTrack(faixa, stream); });
    pc.ontrack = function (evento) { el.audio.srcObject = evento.streams[0]; };
    pc.onconnectionstatechange = function () {
      if (atual && atual.pc === pc && pc.connectionState === 'failed') {
        desligar('O áudio da ligação caiu.');
      }
    };
    return pc;
  }

  function esperarIce(pc) {
    return new Promise(function (pronto) {
      if (pc.iceGatheringState === 'complete') {
        pronto();
        return;
      }
      var limite = window.setTimeout(pronto, ESPERA_ICE_MS);
      pc.addEventListener('icegatheringstatechange', function () {
        if (pc.iceGatheringState === 'complete') {
          window.clearTimeout(limite);
          pronto();
        }
      });
    });
  }

  function microfone(ligado) {
    if (atual && atual.stream) {
      atual.stream.getAudioTracks().forEach(function (faixa) { faixa.enabled = ligado; });
    }
  }

  function limpar() {
    if (!atual) {
      return;
    }
    window.clearInterval(atual.relogio);
    window.clearInterval(atual.consulta);
    if (atual.pc) {
      atual.pc.close();
    }
    if (atual.stream) {
      atual.stream.getTracks().forEach(function (faixa) { faixa.stop(); });
    }
    el.audio.srcObject = null;
    atual = null;
  }

  function finalizar(mensagem, variante) {
    limpar();
    esconder();
    if (mensagem) {
      avisar(mensagem, variante || 'info');
    }
  }

  // --- ligação recebida -------------------------------------------------------------------------

  function receber(dados) {
    if (atual || ignoradas[dados.id] || dados.status !== 'TOCANDO') {
      return;
    }
    tocando = dados;
    exibir(dados, 'Ligação pelo WhatsApp…', ['atender', 'ignorar']);
    tocarSom();
  }

  function atenderLigacao() {
    var chamada = tocando;
    if (!chamada) {
      return;
    }
    pararToque();
    el.situacao.textContent = 'Conectando…';
    mostrarBotoes([]);
    var sessao = { id: chamada.id, direcao: 'ENTRADA' };
    atual = sessao;
    abrirMicrofone().then(function (stream) {
      sessao.stream = stream;
      return buscar(url('chamada', chamada.id));
    }).then(function (dados) {
      if (!dados.sdp_oferta) {
        throw new Error('Essa ligação já foi atendida ou terminou.');
      }
      sessao.pc = novaConexao(sessao.stream);
      microfone(false);  // só abre depois do accept da Meta
      return sessao.pc.setRemoteDescription({ type: 'offer', sdp: dados.sdp_oferta });
    }).then(function () {
      return sessao.pc.createAnswer();
    }).then(function (resposta) {
      return sessao.pc.setLocalDescription(resposta);
    }).then(function () {
      return esperarIce(sessao.pc);
    }).then(function () {
      return postar(url('atender', chamada.id), { sdp: sessao.pc.localDescription.sdp });
    }).then(function () {
      tocando = null;
      microfone(true);
      exibir(chamada, 'Em ligação', ['mudo', 'desligar']);
      iniciarRelogio();
    }).catch(function (erro) {
      tocando = null;
      finalizar(erro.message, 'danger');
    });
  }

  function ignorar() {
    if (tocando) {
      ignoradas[tocando.id] = true;
      tocando = null;
    }
    esconder();
  }

  // --- ligação feita pela equipe ----------------------------------------------------------------

  function ligar(botao) {
    if (atual || tocando) {
      avisar('Termine a ligação atual antes de fazer outra.');
      return;
    }
    var dadosTela = { nome: botao.getAttribute('data-nome'), conversa_id: botao.getAttribute('data-conversa') };
    pedirPermissaoUrl = botao.getAttribute('data-pedir-permissao');
    var sessao = { id: null, direcao: 'SAIDA' };
    atual = sessao;
    exibir(dadosTela, 'Preparando a ligação…', ['desligar']);
    abrirMicrofone().then(function (stream) {
      sessao.stream = stream;
      sessao.pc = novaConexao(stream);
      return sessao.pc.createOffer({ offerToReceiveAudio: true });
    }).then(function (oferta) {
      return sessao.pc.setLocalDescription(oferta);
    }).then(function () {
      return esperarIce(sessao.pc);
    }).then(function () {
      return postar(botao.getAttribute('data-ligar'), { sdp: sessao.pc.localDescription.sdp });
    }).then(function (dados) {
      sessao.id = dados.id;
      sessao.criada = Date.now();
      exibir(dados, 'Chamando…', ['desligar']);
      sessao.consulta = window.setInterval(acompanharSaida, INTERVALO_CONSULTA_MS);
    }).catch(function (erro) {
      limpar();
      if (erro.motivo === 'SEM_PERMISSAO') {
        exibir(dadosTela, erro.message, ['permissao', 'ignorar']);
        return;
      }
      finalizar(erro.message, 'danger');
    });
  }

  function acompanharSaida() {
    var sessao = atual;
    if (!sessao || !sessao.id || sessao.direcao !== 'SAIDA') {
      return;
    }
    buscar(url('chamada', sessao.id)).then(function (dados) {
      if (atual !== sessao) {
        return;
      }
      if (FINAIS.indexOf(dados.status) >= 0) {
        finalizar(dados.status === 'ENCERRADA' ? 'Ligação encerrada.' : 'Ligação ' + dados.status_display.toLowerCase() + '.');
        return;
      }
      if (dados.sdp_resposta && !sessao.respondida) {
        sessao.respondida = true;
        sessao.pc.setRemoteDescription({ type: 'answer', sdp: dados.sdp_resposta }).catch(function () {
          desligar('Não foi possível conectar o áudio.');
        });
      }
      if (dados.status === 'EM_ANDAMENTO' && !sessao.inicio) {
        exibir(dados, 'Em ligação', ['mudo', 'desligar']);
        iniciarRelogio();
      } else if (!sessao.inicio && Date.now() - sessao.criada > LIMITE_CHAMANDO_MS) {
        desligar('O cliente não atendeu.');
      }
    }).catch(function () { /* tenta de novo na próxima consulta */ });
  }

  function pedirPermissao() {
    if (!pedirPermissaoUrl) {
      return;
    }
    el.permissao.disabled = true;
    postar(pedirPermissaoUrl, {}).then(function (dados) {
      finalizar(dados.mensagem || 'Pedido de permissão enviado.', 'success');
    }).catch(function (erro) {
      finalizar(erro.message, 'danger');
    }).then(function () {
      el.permissao.disabled = false;
    });
  }

  // --- comum ------------------------------------------------------------------------------------

  function desligar(mensagem) {
    var sessao = atual;
    if (sessao && sessao.id) {
      postar(url('encerrar', sessao.id), {}).catch(function () { /* o webhook fecha do mesmo jeito */ });
    }
    finalizar(mensagem || 'Ligação encerrada.');
  }

  function alternarMudo() {
    if (!atual || !atual.stream) {
      return;
    }
    var silenciado = el.mudo.getAttribute('aria-pressed') !== 'true';
    microfone(!silenciado);
    el.mudo.setAttribute('aria-pressed', silenciado ? 'true' : 'false');
    el.mudo.querySelector('i').className = silenciado ? 'bx bx-microphone-off' : 'bx bx-microphone';
  }

  function aoEvento(evento) {
    var dados = evento.detail || {};
    if (!dados.chamada_id) {
      return;
    }
    if (atual && atual.id === dados.chamada_id) {
      if (atual.direcao === 'SAIDA') {
        acompanharSaida();
      } else if (FINAIS.indexOf(dados.chamada_status) >= 0) {
        finalizar('Ligação encerrada.');
      }
      return;
    }
    if (tocando && tocando.id === dados.chamada_id && dados.chamada_status !== 'TOCANDO') {
      tocando = null;
      esconder();  // outra pessoa atendeu ou o cliente desistiu
      return;
    }
    if (dados.tipo === 'chamada_tocando') {
      buscar(url('chamada', dados.chamada_id)).then(receber).catch(function () {});
    }
  }

  el.atender.addEventListener('click', atenderLigacao);
  el.ignorar.addEventListener('click', ignorar);
  el.permissao.addEventListener('click', pedirPermissao);
  el.mudo.addEventListener('click', alternarMudo);
  el.desligar.addEventListener('click', function () { desligar(); });
  document.addEventListener('crm:evento', aoEvento);
  document.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-ligar]');
    if (botao) {
      evento.preventDefault();
      ligar(botao);
    }
  });

  // Ao abrir a página, já mostra uma ligação que esteja tocando.
  buscar(raiz.getAttribute('data-url-tocando')).then(function (dados) {
    (dados.chamadas || []).some(function (chamada) {
      receber(chamada);
      return Boolean(tocando);
    });
  }).catch(function () {});
})();
