/**
 * Gráfico "Balanço de Parcelas" da página inicial.
 * Dados: atributo data-dados do canvas #parcelasChart ({labels, data} em %).
 * Cores: tokens --ipix-* do tema, relidos ao trocar claro/escuro.
 */
(function () {
  'use strict';

  function token(nome, padrao) {
    var valor = getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
    return valor || padrao;
  }

  function lerDados(canvas) {
    try {
      return JSON.parse(canvas.dataset.dados || '{}');
    } catch (erro) {
      return {};
    }
  }

  function opcoes() {
    var texto = token('--ipix-heading', '#384551');
    var eixo = token('--ipix-muted', '#8592A3');
    var grade = token('--ipix-border', '#EAEAEF');
    return {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 900, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) { return 'Percentual: ' + (ctx.parsed.x || 0) + '%'; }
          }
        }
      },
      scales: {
        x: {
          beginAtZero: true,
          max: 100,
          grid: { color: grade, drawTicks: false },
          ticks: { color: eixo, padding: 10, callback: function (v) { return v + '%'; } }
        },
        y: {
          grid: { display: false },
          ticks: { color: texto, padding: 15, font: { size: 14, weight: '600' } }
        }
      }
    };
  }

  function montar(canvas) {
    var dados = lerDados(canvas);
    var valores = (dados.data || [0, 0, 0]).map(function (v) { return v || 0; });
    var cores = [
      token('--ipix-success', '#28C76F'),
      token('--ipix-danger', '#EA5455'),
      token('--ipix-secondary', '#8592A3')
    ];
    return new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: dados.labels || ['Pagas', 'Vencidas', 'Desativados'],
        datasets: [{
          label: 'Percentual (%)',
          data: valores,
          backgroundColor: cores,
          borderColor: cores,
          borderWidth: 1,
          borderRadius: 14,
          borderSkipped: false,
          maxBarThickness: 85
        }]
      },
      options: opcoes()
    });
  }

  function iniciar() {
    var canvas = document.getElementById('parcelasChart');
    if (!canvas || typeof Chart === 'undefined') return;
    var grafico = montar(canvas);
    var raiz = document.documentElement;
    var escuro = raiz.classList.contains('dark-style');
    // Troca de tema (classe dark-style no <html>): redesenha com as cores novas.
    new MutationObserver(function () {
      var agora = raiz.classList.contains('dark-style');
      if (agora === escuro) return;
      escuro = agora;
      grafico.destroy();
      grafico = montar(canvas);
    }).observe(raiz, { attributes: true, attributeFilter: ['class', 'data-theme'] });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
