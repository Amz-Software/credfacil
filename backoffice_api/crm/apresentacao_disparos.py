"""Disparos manuais de cobrança: objetos → dicionários do contrato (CONTRATO.md, "Central de cobrança")."""
from collections import Counter

from django.db.models import Count
from django.utils import timezone

from crm.apresentacao import usuario_mini
from crm.models import ConfiguracaoCRM, DisparoCobranca, ItemDisparo
from crm.services import aberturas, cobranca
from crm.services.central_cobranca import disparos, teto
from crm.services.central_cobranca.motivos import mascarar, rotulo, telefone_para_aviso
from crm.services.conversas import ConflitoCRM
from crm.services.pagamentos import formatar_reais

from .apresentacao_cobranca import _iso, _motivos, parcela_mini

Situacao = ItemDisparo.Situacao
COM_ESTIMATIVA = (DisparoCobranca.Status.PREVIA, *DisparoCobranca.EM_ANDAMENTO, DisparoCobranca.Status.PAUSADO)
PERCENTUAL = 100


def _contagens(disparo: DisparoCobranca) -> tuple[Counter, Counter, int]:
    linhas = disparo.itens.values('situacao', 'motivo').annotate(qtd=Count('pk')).order_by()
    excluidos, ignorados, pendentes = Counter(), Counter(), 0
    for linha in linhas:
        if linha['situacao'] == Situacao.EXCLUIDO:
            excluidos[linha['motivo']] += linha['qtd']
        elif linha['situacao'] == Situacao.IGNORADO:
            ignorados[linha['motivo']] += linha['qtd']
        elif linha['situacao'] == Situacao.PENDENTE:
            pendentes += linha['qtd']
    return excluidos, ignorados, pendentes


def _exemplo(disparo: DisparoCobranca, usuario) -> str:
    """Texto como o primeiro destinatário (visível ao usuário, pelo escopo de lojas) vai receber."""
    from crm.services.relatorios_cobranca import _no_escopo
    from vendas.models import Cliente

    item = (disparo.itens.exclude(situacao=Situacao.EXCLUIDO).exclude(parcela=None)
            .filter(cliente__in=_no_escopo(Cliente.objects.all(), usuario))
            .select_related('parcela__pagamento__venda__cliente').order_by('ordem').first())
    if item is None:
        return ''
    parcela = item.parcela
    try:
        texto, _ = aberturas.renderizar(disparo.versao, {
            'nome': cobranca._primeiro_nome(parcela.pagamento.venda.cliente),
            'valor': formatar_reais(parcela.valor_restante),
            'vencimento': parcela.data_vencimento.strftime('%d/%m/%Y')})
    except ConflitoCRM:
        return ''
    return texto


def _estimativa(pendentes: int, config: ConfiguracaoCRM, saude: teto.SaudeNumero) -> dict:
    dias, sem_previsao = disparos.distribuicao(pendentes, config, saude)
    hoje = timezone.localdate()
    return {'cabem_hoje': next((qtd for dia, qtd in dias if dia == hoje), 0),
            'distribuicao': [{'data': dia.isoformat(), 'quantidade': qtd} for dia, qtd in dias],
            'sem_previsao': sem_previsao}


def disparo_item(disparo: DisparoCobranca) -> dict:
    """Resumo para a lista."""
    return {
        'id': disparo.pk, 'status': disparo.status, 'status_display': disparo.get_status_display(),
        'modelo': {'id': disparo.modelo_id, 'titulo': disparo.modelo.titulo}, 'filtros': disparo.filtros,
        'criado_por': usuario_mini(disparo.criado_por), 'criado_em': _iso(disparo.criado_em),
        'confirmado_em': _iso(disparo.confirmado_em), 'concluido_em': _iso(disparo.concluido_em),
        'total': disparo.total, 'excluidos': disparo.excluidos, 'enviados': disparo.enviados,
        'falhas': disparo.falhas, 'ignorados': disparo.ignorados,
        'percentual': disparo_percentual(disparo), 'motivo_pausa': disparo.motivo_pausa,
    }


def disparo_percentual(disparo: DisparoCobranca) -> int:
    processados = disparo.enviados + disparo.falhas + disparo.ignorados
    return min(processados * PERCENTUAL // disparo.total, PERCENTUAL) if disparo.total else 0


def lista_disparos(disparos_pagina) -> list[dict]:
    return [disparo_item(disparo) for disparo in disparos_pagina]


def disparo_detalhe(disparo: DisparoCobranca, usuario) -> dict:
    excluidos, ignorados, pendentes = _contagens(disparo)
    estimativa, situacao = None, ''
    if disparo.status in COM_ESTIMATIVA:
        config = ConfiguracaoCRM.obter()
        saude = teto.ler_saude(config)
        estimativa, situacao = _estimativa(pendentes, config, saude), disparos.situacao_envio(config, saude)
    return {
        **disparo_item(disparo),
        'versao': {'nome_meta': disparo.versao.nome_meta, 'corpo': disparo.versao.corpo},
        'confirmado_por': usuario_mini(disparo.confirmado_por), 'iniciado_em': _iso(disparo.iniciado_em),
        'cancelado_por': usuario_mini(disparo.cancelado_por), 'cancelado_em': _iso(disparo.cancelado_em),
        'pendentes': pendentes if disparo.status != DisparoCobranca.Status.CANCELADO else 0,
        'motivos_exclusao': _motivos(excluidos), 'motivos_ignorados': _motivos(ignorados),
        'custo_estimado': str(teto.custo(disparo.total)), 'exemplo': _exemplo(disparo, usuario),
        'estimativa': estimativa,
        'situacao_envio': situacao, 'situacao_envio_display': rotulo(situacao) if situacao else '',
    }


def itens_destinatarios(itens) -> list[dict]:
    resultado = []
    for item in itens:
        telefone = telefone_para_aviso(item.cliente)[0] if item.situacao == Situacao.PENDENTE else ''
        tentativa = item.tentativa
        resultado.append({
            'id': item.pk, 'ordem': item.ordem, 'cliente': {'id': item.cliente_id, 'nome': item.cliente.nome},
            'parcela': parcela_mini(item.parcela), 'situacao': item.situacao,
            'situacao_display': item.get_situacao_display(), 'motivo': item.motivo,
            'motivo_display': rotulo(item.motivo) if item.motivo else '',
            'telefone': mascarar(tentativa.numero if tentativa else telefone),
            'processado_em': _iso(item.processado_em),
            'conversa_id': tentativa.mensagem.conversa_id if tentativa and tentativa.mensagem_id else None,
        })
    return resultado
