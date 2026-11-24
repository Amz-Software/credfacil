"""PDF de um período de repasse: vendas da competência, total devido e repasses lançados."""
from decimal import Decimal
from pathlib import Path

from django.http import HttpResponse
from django.template import Context, Engine
from django.utils import timezone

from backoffice_api.relatorios.pdf import TIPO_PDF, gerar_pdf, resposta_arquivo
from backoffice_api.vendas.pdfs import LOGO_IPIX, data, data_hora, formatar_cpf, imagem_estatica, moeda

from .repasse_periodo import ResumoDoPeriodo
from .servicos import ROTULOS_STATUS_REPASSE

PASTA_TEMPLATES = Path(__file__).resolve().parent / 'templates_pdf'
PASTA_BASE = Path(__file__).resolve().parent.parent / 'vendas' / 'templates_pdf'
_MOTOR = Engine(dirs=[str(PASTA_TEMPLATES), str(PASTA_BASE)], autoescape=True)
TEMPLATE = 'repasse_periodo.html'


def _produtos(venda) -> str:
    return ', '.join(item.produto.nome for item in venda.itens_venda.all())


def _contexto(resumo: ResumoDoPeriodo) -> dict:
    loja, periodo = resumo.loja, resumo.periodo
    lancado = sum((r.valor for r in resumo.repasses if r.status != 'cancelado'), Decimal('0'))
    return {
        'logo': imagem_estatica(LOGO_IPIX),
        'titulo': 'Repasse ao logista',
        'emitido_em': data_hora(timezone.now()),
        'loja': {'nome': loja.nome, 'endereco': loja.endereco or '', 'cnpj': loja.cnpj or ''},
        'periodo': {'data': data(periodo.data), 'inicio': data(periodo.inicio), 'fim': data(periodo.fim)},
        'vendas': [
            {
                'numero': venda.pk, 'data': data_hora(venda.data_venda), 'cliente': venda.cliente.nome,
                'cpf': formatar_cpf(venda.cliente.cpf), 'produtos': _produtos(venda),
                'repasse': moeda(venda.repasse_logista),
            }
            for venda in resumo.vendas
        ],
        'total': moeda(resumo.total),
        'repasses': [
            {
                'data': data(timezone.localtime(r.data).date()), 'valor': moeda(r.valor),
                'status': ROTULOS_STATUS_REPASSE.get(r.status, r.status), 'observacao': r.observacao or '',
            }
            for r in resumo.repasses
        ],
        'total_lancado': moeda(lancado),
    }


def resposta_pdf_do_periodo(resumo: ResumoDoPeriodo) -> HttpResponse:
    html = _MOTOR.get_template(TEMPLATE).render(Context(_contexto(resumo)))
    nome = f'repasse_{resumo.loja.pk}_{resumo.periodo.data:%Y%m%d}.pdf'
    return resposta_arquivo(gerar_pdf(html), TIPO_PDF, nome)
