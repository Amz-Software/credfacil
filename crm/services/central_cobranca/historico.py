"""Histórico da Central de cobrança: avisos da régua e envios de disparos, com o status da mensagem.

Só leitura. Lista e resumo respeitam o escopo de lojas dos relatórios (`relatorios_cobranca._no_escopo`).
"""
from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Q, QuerySet

from crm.models import Mensagem, TentativaContato
from crm.services.cobranca import TIPOS_CONTATO_CLIENTE

from .janela import dia_local

Tipo = TentativaContato.Tipo
Resultado = TentativaContato.Resultado

ETAPAS = {
    'antes': Tipo.AVISO_ANTES, 'dia': Tipo.AVISO_DIA, 'apos': Tipo.AVISO_APOS,
    'insistencia': Tipo.AVISO_INSISTENCIA, 'quitacao': Tipo.AVISO_QUITACAO, 'disparo': Tipo.DISPARO,
}
CHAVE_DO_TIPO = {tipo: chave for chave, tipo in ETAPAS.items()}
RESULTADOS_DE_FALHA = (Resultado.FALHOU, Resultado.SEM_WHATSAPP, Resultado.NUMERO_INVALIDO)


class StatusEnvio:
    ENVIANDO = 'enviando'
    ENVIADO = 'enviado'
    ENTREGUE = 'entregue'
    LIDO = 'lido'
    FALHOU = 'falhou'

    ROTULOS = {ENVIANDO: 'Enviando', ENVIADO: 'Enviado', ENTREGUE: 'Entregue', LIDO: 'Lido', FALHOU: 'Não entregue'}
    DA_MENSAGEM = {
        Mensagem.Status.PENDENTE: ENVIANDO, Mensagem.Status.ENVIADO: ENVIADO, Mensagem.Status.ENTREGUE: ENTREGUE,
        Mensagem.Status.LIDO: LIDO, Mensagem.Status.ERRO: FALHOU,
    }


FALHA = Q(resultado__in=RESULTADOS_DE_FALHA) | Q(mensagem__status=Mensagem.Status.ERRO) | Q(mensagem__isnull=True)
FILTRO_STATUS = {
    StatusEnvio.FALHOU: FALHA,
    StatusEnvio.ENVIANDO: Q(mensagem__status=Mensagem.Status.PENDENTE) & ~FALHA,
    StatusEnvio.ENVIADO: Q(mensagem__status=Mensagem.Status.ENVIADO) & ~FALHA,
    StatusEnvio.ENTREGUE: Q(mensagem__status=Mensagem.Status.ENTREGUE) & ~FALHA,
    StatusEnvio.LIDO: Q(mensagem__status=Mensagem.Status.LIDO) & ~FALHA,
}


@dataclass(frozen=True)
class Filtros:
    desde: date
    ate: date
    etapa: str = ''
    resultado: str = ''
    status: str = ''
    disparo: int | None = None


def status_envio(tentativa: TentativaContato) -> str:
    """Status da mensagem do aviso (o resultado de falha vindo do webhook tem prioridade)."""
    if tentativa.resultado in RESULTADOS_DE_FALHA or tentativa.mensagem is None:
        return StatusEnvio.FALHOU
    return StatusEnvio.DA_MENSAGEM.get(tentativa.mensagem.status, StatusEnvio.ENVIADO)


def _no_escopo(consulta: QuerySet, usuario) -> QuerySet:
    from crm.services.relatorios_cobranca import _no_escopo as clientes_no_escopo
    from vendas.models import Cliente

    if usuario is None:
        return consulta
    return consulta.filter(cliente__in=clientes_no_escopo(Cliente.objects.all(), usuario))


def consultar(filtros: Filtros, usuario=None) -> QuerySet:
    inicio, _ = dia_local(filtros.desde)
    _, fim = dia_local(filtros.ate)
    consulta = TentativaContato.objects.filter(tipo__in=TIPOS_CONTATO_CLIENTE, criado_em__gte=inicio,
                                               criado_em__lt=fim)
    if filtros.etapa:
        consulta = consulta.filter(tipo=ETAPAS[filtros.etapa])
    if filtros.resultado:
        consulta = consulta.filter(resultado=filtros.resultado)
    if filtros.status:
        consulta = consulta.filter(FILTRO_STATUS[filtros.status])
    if filtros.disparo:
        consulta = consulta.filter(tipo=Tipo.DISPARO, sequencia=filtros.disparo)
    return (_no_escopo(consulta, usuario)
            .select_related('cliente', 'mensagem', 'parcela')
            .order_by('-criado_em', '-id'))


def _contar(consulta: QuerySet, campo: str) -> dict[str, int]:
    return {linha[campo]: linha['qtd'] for linha in consulta.values(campo).annotate(qtd=Count('pk')).order_by()}


def resumo(consulta: QuerySet) -> dict:
    """Totais do período filtrado: por etapa, por status da mensagem e por resultado."""
    base = consulta.order_by()
    por_tipo = _contar(base, 'tipo')
    return {
        'total': base.count(),
        'por_etapa': {CHAVE_DO_TIPO[tipo]: qtd for tipo, qtd in por_tipo.items() if tipo in CHAVE_DO_TIPO},
        'por_status': {status: base.filter(condicao).count() for status, condicao in FILTRO_STATUS.items()},
        'por_resultado': _contar(base, 'resultado'),
    }
