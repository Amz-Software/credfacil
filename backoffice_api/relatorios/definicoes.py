"""Catálogo dos relatórios: permissão, filtros, consulta, formatos e template de PDF de cada um."""
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import import_module
from types import ModuleType

from rest_framework import serializers

from . import filtros as f
from . import serializers as s
from .servicos import contas_a_receber, parcelas, situacoes, solicitacoes, vendas

PERMISSAO_RELATORIO_VENDAS = 'vendas.can_generate_report_sale'
PERMISSAO_RELATORIO_PAGAMENTOS = 'vendas.can_genarate_report_payments'  # grafia do modelo
PERMISSAO_TODAS_LOJAS = 'vendas.can_view_all_stores'
PERMISSAO_TODOS_PAGAMENTOS = 'vendas.can_view_all_payments'


@dataclass(frozen=True)
class DefinicaoRelatorio:
    id: str
    titulo: str
    descricao: str
    permissao: str
    permissao_global_lojas: str
    filtros: type[f.FiltrosBase]
    servico: ModuleType  # expõe consultar(filtros, escopo), totais(consulta, filtros), linhas(itens)
    serializer_linha: type[serializers.Serializer]
    serializer_totais: type[serializers.Serializer]
    template_pdf: str
    formatos: tuple[str, ...] = ('previa', 'pdf')
    contexto_pdf: Callable[[dict], dict] = field(default=lambda filtros: {})


def _rotulos(campo_filtro: str, form_path: str) -> Callable[[dict], dict]:
    """Rótulos dos status/situações escolhidos, para o cabeçalho do PDF."""
    def contexto(filtros: dict) -> dict:
        modulo, classe = form_path.rsplit('.', 1)
        form = getattr(import_module(modulo), classe)
        rotulos = dict(form.base_fields[campo_filtro].choices)
        return {f'{campo_filtro}_rotulos': [rotulos.get(v, v) for v in sorted(filtros.get(campo_filtro) or [])]}
    return contexto


RELATORIOS: dict[str, DefinicaoRelatorio] = {d.id: d for d in (
    DefinicaoRelatorio(
        id='vendas', titulo='Relatório de vendas',
        descricao='Vendas do período com entrada, repasse, valor total e juros.',
        permissao=PERMISSAO_RELATORIO_VENDAS, permissao_global_lojas=PERMISSAO_TODAS_LOJAS,
        filtros=f.FiltrosVendasSerializer, servico=vendas,
        serializer_linha=s.LinhaVendaSerializer, serializer_totais=s.TotaisVendasSerializer,
        template_pdf='relatorio_vendas.html',
    ),
    DefinicaoRelatorio(
        id='solicitacoes', titulo='Relatório de solicitações',
        descricao='Solicitações de crédito do período, com status e valores da venda gerada.',
        permissao=PERMISSAO_RELATORIO_VENDAS, permissao_global_lojas=PERMISSAO_TODAS_LOJAS,
        filtros=f.FiltrosSolicitacoesSerializer, servico=solicitacoes,
        serializer_linha=s.LinhaSolicitacaoSerializer, serializer_totais=s.TotaisSolicitacoesSerializer,
        template_pdf='relatorio_solicitacoes.html',
    ),
    DefinicaoRelatorio(
        id='contas_a_receber', titulo='Relatório de contas a receber',
        descricao='Pagamentos por status no período; só "Pago" lista uma linha por parcela paga.',
        permissao=PERMISSAO_RELATORIO_PAGAMENTOS, permissao_global_lojas=PERMISSAO_TODOS_PAGAMENTOS,
        filtros=f.FiltrosContasAReceberSerializer, servico=contas_a_receber,
        serializer_linha=s.LinhaContaSerializer, serializer_totais=s.TotaisContasSerializer,
        template_pdf='relatorio_contas_a_receber.html',
        contexto_pdf=_rotulos('status', 'financeiro.forms.RelatorioContasAReceberForm'),
    ),
    DefinicaoRelatorio(
        id='situacoes', titulo='Relatório de situações',
        descricao='Pagamentos por situação (cobrança, BO, bloqueio...) com o último contato registrado.',
        permissao=PERMISSAO_RELATORIO_PAGAMENTOS, permissao_global_lojas=PERMISSAO_TODOS_PAGAMENTOS,
        filtros=f.FiltrosSituacoesSerializer, servico=situacoes,
        serializer_linha=s.LinhaSituacaoSerializer, serializer_totais=s.TotaisQuantidadeSerializer,
        template_pdf='relatorio_situacoes.html',
        contexto_pdf=_rotulos('situacoes', 'financeiro.forms.RelatorioContasAReceberAvancadoForm'),
    ),
    DefinicaoRelatorio(
        id='parcelas', titulo='Relatório de parcelas',
        descricao='Grade das parcelas de cada cliente, colorida por status (pago, atrasado, a vencer).',
        permissao=PERMISSAO_RELATORIO_PAGAMENTOS, permissao_global_lojas=PERMISSAO_TODOS_PAGAMENTOS,
        filtros=f.FiltrosParcelasSerializer, servico=parcelas,
        serializer_linha=s.LinhaParcelasSerializer, serializer_totais=s.TotaisParcelasSerializer,
        template_pdf='relatorio_parcelas.html', formatos=('previa', 'pdf', 'excel'),
    ),
)}
