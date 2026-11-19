/**
 * Gráficos do dashboard de vendas (Balanço por Loja e Balanço Mensal).
 * Dados: atributo data-dados dos canvas #graficoLojas e #graficoLojasMes.
 * Textos e grades usam os tokens --ipix-* do tema.
 */
function token(nome, padrao) {
  const valor = getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  return valor || padrao;
}

function lerDados(id) {
  const canvas = document.getElementById(id);
  if (!canvas) return {};
  try {
    return JSON.parse(canvas.dataset.dados || '{}');
  } catch (erro) {
    return {};
  }
}

function initCharts() {
  if (typeof Chart === 'undefined') {
    setTimeout(initCharts, 100);
    return;
  }

  const isDarkMode = document.documentElement.classList.contains('dark-style');
  
  const gridColor = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
  const axisTextColor = token('--ipix-text', '#566A7F');
  const labelTextColor = token('--ipix-heading', '#384551');

  // Gráfico 1: Balanço por Loja
  const dadosLojas = lerDados('graficoLojas');
  const labels = Object.keys(dadosLojas);
  const pctPagas = labels.map(loja => dadosLojas[loja].pct_pagas);
  const pctVencidas = labels.map(loja => dadosLojas[loja].pct_vencidas);
  const pctDesativados = labels.map(loja => dadosLojas[loja].pct_desativados || 0);
  const pctCobrancas = labels.map(loja => dadosLojas[loja].pct_cobrancas || 0);
  const totalPagas = labels.map(loja => dadosLojas[loja].total_pagas);
  const totalVencidas = labels.map(loja => dadosLojas[loja].total_vencidas);
  const totalDesativados = labels.map(loja => 
    Number(dadosLojas[loja].total_desativados_vencidas || 0) + Number(dadosLojas[loja].total_desativados_a_vencer || 0)
  );
  const totalCobrancas = labels.map(loja => 
    Number(dadosLojas[loja].total_cobranca_vencidas || 0) + Number(dadosLojas[loja].total_cobranca_a_vencer || 0)
  );
  const totais = labels.map(loja =>
    Number(dadosLojas[loja].total_pagas) + Number(dadosLojas[loja].total_vencidas) + Number(dadosLojas[loja].total_a_vencer) + Number(dadosLojas[loja].total_desativados_vencidas || 0) + Number(dadosLojas[loja].total_desativados_a_vencer || 0) + Number(dadosLojas[loja].total_cobranca_vencidas || 0) + Number(dadosLojas[loja].total_cobranca_a_vencer || 0)
  );

  const ctxLojas = document.getElementById('graficoLojas');
  if (ctxLojas) {
    const ctx = ctxLojas.getContext('2d');
    
    // Criar gradientes
    const gradientPagas = ctx.createLinearGradient(0, 0, 0, 400);
    gradientPagas.addColorStop(0, 'rgba(113, 221, 55, 0.8)');
    gradientPagas.addColorStop(1, 'rgba(113, 221, 55, 0.2)');

    const gradientVencidas = ctx.createLinearGradient(0, 0, 0, 400);
    gradientVencidas.addColorStop(0, 'rgba(255, 99, 132, 0.8)');
    gradientVencidas.addColorStop(1, 'rgba(255, 99, 132, 0.2)');

    const gradientDesativados = ctx.createLinearGradient(0, 0, 0, 400);
    gradientDesativados.addColorStop(0, 'rgba(108, 117, 125, 0.8)');
    gradientDesativados.addColorStop(1, 'rgba(108, 117, 125, 0.2)');

    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: '% Pagas',
            data: pctPagas,
            totalValores: totalPagas,
            backgroundColor: gradientPagas,
            borderColor: 'rgba(113, 221, 55, 1)',
            borderWidth: 2,
            stack: 'percentual'
          },
          {
            label: '% Vencidas',
            data: pctVencidas,
            totalValores: totalVencidas,
            backgroundColor: gradientVencidas,
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 2,
            stack: 'percentual'
          },
          {
            label: '% Desativados',
            data: pctDesativados,
            totalValores: totalDesativados,
            backgroundColor: gradientDesativados,
            borderColor: 'rgba(108, 117, 125, 1)',
            borderWidth: 2,
            stack: 'percentual'
          },
          {
            label: '% Cobranças',
            data: pctCobrancas,
            totalValores: totalCobrancas,
            backgroundColor: 'rgba(255, 171, 0, 0.5)',
            borderColor: 'rgba(255, 171, 0, 1)',
            borderWidth: 2,
            stack: 'percentual'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: {
          duration: 1500,
          easing: 'easeOutQuart'
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              color: labelTextColor,
              font: {
                size: 14,
                weight: '600',
                family: "'Public Sans', sans-serif"
              },
              padding: 15
            }
          },
          tooltip: {
            enabled: true,
            backgroundColor: isDarkMode ? 'rgba(43, 44, 64, 0.95)' : 'rgba(0, 0, 0, 0.85)',
            padding: 14,
            titleFont: {
              size: 15,
              weight: '700',
              family: "'Public Sans', sans-serif"
            },
            titleColor: '#fff',
            bodyFont: {
              size: 14,
              weight: '600',
              family: "'Public Sans', sans-serif"
            },
            bodyColor: '#fff',
            borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.2)' : 'rgba(255, 255, 255, 0.15)',
            borderWidth: 2,
            cornerRadius: 10,
            callbacks: {
              label: function (context) {
                const percentual = context.parsed.y;
                const valor = context.dataset.totalValores[context.dataIndex];
                const total = totais[context.dataIndex];
                return `${context.dataset.label}: ${percentual}% (R$ ${valor.toLocaleString('pt-BR')})\nTotal Loja: R$ ${total.toLocaleString('pt-BR')}`;
              }
            }
          }
        },
        scales: {
          x: {
            stacked: true,
            grid: {
              color: gridColor,
              drawBorder: false
            },
            ticks: {
              color: axisTextColor,
              font: {
                size: 12,
                weight: '500',
                family: "'Public Sans', sans-serif"
              }
            }
          },
          y: {
            stacked: true,
            beginAtZero: true,
            max: 100,
            grid: {
              color: gridColor,
              drawBorder: false
            },
            ticks: {
              color: axisTextColor,
              font: {
                size: 12,
                weight: '500',
                family: "'Public Sans', sans-serif"
              },
              callback: value => value + '%'
            }
          }
        }
      }
    });
  }

  // Gráfico 2: Balanço Mensal (se existir)
  const ctxLojasMes = document.getElementById('graficoLojasMes');
  if (ctxLojasMes) {
    const dadosLojasMes = lerDados('graficoLojasMes');
    const mesesSet = new Set();
    Object.values(dadosLojasMes).forEach(arr => arr.forEach(obj => mesesSet.add(obj.mes)));
    const meses = Array.from(mesesSet).sort();

    const lojas = Object.keys(dadosLojasMes);
    const cores = [
      'rgba(113, 221, 55, 0.7)',
      'rgba(255, 99, 132, 0.7)',
      'rgba(255, 171, 0, 0.7)',
      'rgba(3, 195, 236, 0.7)',
      'rgba(153, 102, 255, 0.7)',
      'rgba(201, 203, 207, 0.7)'
    ];

    function getPercentuais(loja, campo) {
      const dados = {};
      dadosLojasMes[loja].forEach(obj => { dados[obj.mes] = obj; });
      return meses.map(mes => {
        const obj = dados[mes];
        if (!obj) return 0;
        const total = (obj.pago || 0) + (obj.vencido || 0) + (obj.a_vencer || 0);
        if (total === 0) return 0;
        return Math.round(((obj[campo] || 0) / total) * 100);
      });
    }

    function getValores(loja, campo) {
      const dados = {};
      dadosLojasMes[loja].forEach(obj => { dados[obj.mes] = obj; });
      return meses.map(mes => {
        const obj = dados[mes];
        return obj ? (obj[campo] || 0) : 0;
      });
    }

    function getTotais(loja) {
      const dados = {};
      dadosLojasMes[loja].forEach(obj => { dados[obj.mes] = obj; });
      return meses.map(mes => {
        const obj = dados[mes];
        return obj ? ((obj.pago || 0) + (obj.vencido || 0) + (obj.a_vencer || 0)) : 0;
      });
    }

    const datasets = [];
    lojas.forEach((loja, idx) => {
      datasets.push({
        label: loja + ' - Pago',
        data: getPercentuais(loja, 'pago'),
        valores: getValores(loja, 'pago'),
        totais: getTotais(loja),
        backgroundColor: cores[idx % cores.length],
        borderColor: cores[idx % cores.length].replace('0.7', '1'),
        borderWidth: 2,
        stack: loja
      });
      datasets.push({
        label: loja + ' - Vencido',
        data: getPercentuais(loja, 'vencido'),
        valores: getValores(loja, 'vencido'),
        totais: getTotais(loja),
        backgroundColor: 'rgba(255, 99, 132, 0.5)',
        borderColor: 'rgba(255, 99, 132, 1)',
        borderWidth: 2,
        stack: loja
      });
      datasets.push({
        label: loja + ' - A Vencer',
        data: getPercentuais(loja, 'a_vencer'),
        valores: getValores(loja, 'a_vencer'),
        totais: getTotais(loja),
        backgroundColor: 'rgba(255, 171, 0, 0.5)',
        borderColor: 'rgba(255, 171, 0, 1)',
        borderWidth: 2,
        stack: loja
      });
    });

    const ctx = ctxLojasMes.getContext('2d');
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: meses,
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: {
          duration: 1500,
          easing: 'easeOutQuart'
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              color: labelTextColor,
              font: {
                size: 12,
                weight: '600',
                family: "'Public Sans', sans-serif"
              },
              padding: 10
            }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: isDarkMode ? 'rgba(43, 44, 64, 0.95)' : 'rgba(0, 0, 0, 0.85)',
            padding: 14,
            titleFont: {
              size: 15,
              weight: '700',
              family: "'Public Sans', sans-serif"
            },
            titleColor: '#fff',
            bodyFont: {
              size: 14,
              weight: '600',
              family: "'Public Sans', sans-serif"
            },
            bodyColor: '#fff',
            borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.2)' : 'rgba(255, 255, 255, 0.15)',
            borderWidth: 2,
            cornerRadius: 10,
            callbacks: {
              label: function(context) {
                const percentual = context.parsed.y;
                const valor = context.dataset.valores[context.dataIndex];
                const total = context.dataset.totais[context.dataIndex];
                return `${context.dataset.label}: ${percentual}% (R$ ${valor.toLocaleString('pt-BR')})\nTotal Loja: R$ ${total.toLocaleString('pt-BR')}`;
              }
            }
          }
        },
        scales: {
          x: { 
            stacked: true,
            grid: {
              color: gridColor,
              drawBorder: false
            },
            ticks: {
              color: axisTextColor,
              font: {
                size: 12,
                weight: '500',
                family: "'Public Sans', sans-serif"
              }
            }
          },
          y: {
            stacked: true,
            beginAtZero: true,
            max: 100,
            grid: {
              color: gridColor,
              drawBorder: false
            },
            ticks: {
              color: axisTextColor,
              font: {
                size: 12,
                weight: '500',
                family: "'Public Sans', sans-serif"
              },
              callback: value => value + '%'
            }
          }
        }
      }
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initCharts);
} else {
  initCharts();
}
