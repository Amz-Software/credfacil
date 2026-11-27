"""Central de cobrança: objetos dos serviços → dicionários do contrato (CONTRATO.md, "Central de cobrança").

Só monta a resposta; regras ficam em `crm/services/central_cobranca/*`.
"""
from collections import Counter
from datetime import datetime

from django.utils import timezone

from crm.forms import MAX_INSISTENCIAS, MAX_INTERVALO_COBRANCA, MAX_TETO_DIARIO, CobrancaForm
from crm.models import ConfiguracaoCRM, DisparoCobranca, ModeloAbertura
from crm.services import cobranca, expediente
from crm.services.central_cobranca import agenda, disparos, historico, janela, teto
from crm.services.central_cobranca.motivos import mascarar, rotulo

from .servicos import simulado

FORMATO_HORA = '%H:%M'


def _iso(momento: datetime | None) -> str | None:
    return timezone.localtime(momento).isoformat() if momento else None


def _motivos(contagem: Counter) -> list[dict]:
    return [{'motivo': motivo, 'rotulo': rotulo(motivo), 'quantidade': qtd} for motivo, qtd in contagem.most_common()]


def parcela_mini(parcela) -> dict | None:
    if parcela is None:
        return None
    return {'id': parcela.pk, 'numero': parcela.numero_parcela, 'valor': f'{parcela.valor_restante:.2f}',
            'vencimento': parcela.data_vencimento.isoformat()}


# --- saúde do número ---------------------------------------------------------------------------

def _status_regua(config: ConfiguracaoCRM, saude: teto.SaudeNumero, agora: datetime) -> str:
    if not config.cobranca_ativa:
        return 'pausada'
    if saude.pausada_por_qualidade:
        return 'pausada_por_qualidade'
    if config.cobranca_ativada_em and config.cobranca_ativada_em > agora:
        return 'antes_da_ativacao'
    return 'ativa'


STATUS_REGUA = {'ativa': 'Ativa', 'pausada': 'Pausada', 'pausada_por_qualidade': 'Pausada pela qualidade do número',
                'antes_da_ativacao': 'Ligada, começa na data marcada'}


def _janela_dict(config: ConfiguracaoCRM, agora: datetime) -> dict | None:
    proxima = janela.proxima(config, agora)
    return {'inicio': _iso(proxima.inicio), 'fim': _iso(proxima.fim)} if proxima else None


def saude_dict(config: ConfiguracaoCRM, saude: teto.SaudeNumero, agora: datetime | None = None) -> dict:
    agora = agora or timezone.now()
    hoje = timezone.localtime(agora).date()
    enviados = teto.enviados_no_dia(hoje)
    status = _status_regua(config, saude, agora)
    situacao = disparos.situacao_envio(config, saude, agora)
    return {
        'numero': {'limite_tier': saude.limite_tier, 'limite_meta': saude.limite_meta, 'qualidade': saude.qualidade,
                   'qualidade_display': saude.qualidade_display, 'fonte': saude.fonte, 'lido_em': _iso(saude.lido_em)},
        'teto': {'automatico': saude.teto_automatico, 'configurado': saude.teto_configurado,
                 'efetivo': saude.teto_efetivo, 'enviados_hoje': enviados,
                 'restante_hoje': max(saude.teto_efetivo - enviados, 0)},
        'regua': {'status': status, 'status_display': STATUS_REGUA[status], 'ativa': config.cobranca_ativa,
                  'ativada_em': _iso(config.cobranca_ativada_em),
                  'hora_envio': config.cobranca_hora_envio.strftime(FORMATO_HORA),
                  'fim_envio': janela.FIM_DOS_ENVIOS.strftime(FORMATO_HORA),
                  'proxima_janela': _janela_dict(config, agora),
                  'enviando_agora': status == 'ativa' and not situacao},
        'disparos': {'em_andamento': DisparoCobranca.objects.filter(status__in=DisparoCobranca.EM_ANDAMENTO).count(),
                     'situacao_envio': situacao, 'situacao_envio_display': rotulo(situacao) if situacao else ''},
        'custo_por_mensagem': str(teto.CUSTO_POR_MENSAGEM),
        'simulado': simulado(),
    }


# --- configuração --------------------------------------------------------------------------------

def configuracao_dict(config: ConfiguracaoCRM) -> dict:
    campos = {campo: getattr(config, f'{campo}_id') for campo in CobrancaForm.CAMPOS_MODELO}
    etapas = [{'campo': campo, 'rotulo': CobrancaForm.Meta.labels[campo],
               'modelo': {'id': modelo.pk, 'titulo': modelo.titulo} if (modelo := getattr(config, campo)) else None,
               'pronta': cobranca.versao_vigente(config, campo) is not None} for campo in CobrancaForm.CAMPOS_MODELO]
    prontos = {modelo.pk for modelo, _ in disparos.modelos_disponiveis()}
    return {
        'configuracao': {
            'cobranca_ativa': config.cobranca_ativa, 'cobranca_ativada_em': _iso(config.cobranca_ativada_em),
            'cobranca_hora_envio': config.cobranca_hora_envio.strftime(FORMATO_HORA),
            'cobranca_pular_bom_pagador': config.cobranca_pular_bom_pagador,
            'cobranca_intervalo_dias': config.cobranca_intervalo_dias,
            'cobranca_max_insistencias': config.cobranca_max_insistencias,
            'cobranca_teto_diario': config.cobranca_teto_diario, **campos,
        },
        'etapas': etapas,
        'modelos': [{'id': m.pk, 'titulo': m.titulo, 'pronto': m.pk in prontos}
                    for m in ModeloAbertura.objects.filter(ativo=True)],
        'limites': {'intervalo_dias_max': MAX_INTERVALO_COBRANCA, 'insistencias_max': MAX_INSISTENCIAS,
                    'teto_diario_max': MAX_TETO_DIARIO},
    }


# --- agenda ----------------------------------------------------------------------------------------

def _etapa_resumo(dia: agenda.DiaAgenda, etapa: str) -> dict:
    itens = [item for item in dia.itens if item.etapa == etapa]
    previstos = sum(1 for item in itens if item.previsto)
    return {'etapa': etapa, 'rotulo': agenda.ROTULOS[etapa], 'previstos': previstos,
            'excluidos': len(itens) - previstos, 'custo_estimado': str(teto.custo(previstos)),
            'enviados': dia.enviados.get(etapa, 0)}


def dia_resumo(dia: agenda.DiaAgenda) -> dict:
    previstos = sum(1 for item in dia.itens if item.previsto)
    return {
        'data': dia.data.isoformat(), 'dia_semana': expediente.DIAS_SEMANA[dia.data.weekday()],
        'bloqueio': dia.bloqueio, 'bloqueio_display': rotulo(dia.bloqueio) if dia.bloqueio else '',
        'capacidade': dia.capacidade, 'previstos': previstos, 'excluidos': len(dia.itens) - previstos,
        'custo_estimado': str(teto.custo(previstos)),
        'etapas': [_etapa_resumo(dia, etapa) for etapa in agenda.ORDEM],
        'motivos': _motivos(Counter(item.motivo for item in dia.itens if item.motivo)),
    }


def agenda_dict(dias: list[agenda.DiaAgenda], saude: teto.SaudeNumero) -> dict:
    resumos = [dia_resumo(dia) for dia in dias]
    previstos = sum(resumo['previstos'] for resumo in resumos)
    return {'gerado_em': _iso(timezone.now()), 'teto_efetivo': saude.teto_efetivo,
            'custo_por_mensagem': str(teto.CUSTO_POR_MENSAGEM), 'dias': resumos,
            'totais': {'previstos': previstos, 'custo_estimado': str(teto.custo(previstos))}}


def itens_agenda(itens) -> list[dict]:
    return [{'parcela_id': item.parcela.pk, 'cliente': {'id': item.cliente.pk, 'nome': item.cliente.nome},
             'parcela': parcela_mini(item.parcela), 'etapa': item.etapa, 'etapa_display': agenda.ROTULOS[item.etapa],
             'situacao': 'previsto' if item.previsto else 'excluido', 'motivo': item.motivo,
             'motivo_display': rotulo(item.motivo) if item.motivo else '', 'telefone': item.telefone}
            for item in itens]


# --- histórico -------------------------------------------------------------------------------------

def itens_historico(tentativas) -> list[dict]:
    resultado = []
    for tentativa in tentativas:
        status = historico.status_envio(tentativa)
        disparo = tentativa.tipo == cobranca.Tipo.DISPARO
        resultado.append({
            'id': tentativa.pk, 'criado_em': _iso(tentativa.criado_em),
            'cliente': {'id': tentativa.cliente_id, 'nome': tentativa.cliente.nome},
            'parcela': parcela_mini(tentativa.parcela),
            'etapa': historico.CHAVE_DO_TIPO.get(tentativa.tipo, ''), 'etapa_display': tentativa.get_tipo_display(),
            'origem': 'disparo' if disparo else 'regua', 'disparo_id': tentativa.sequencia if disparo else None,
            'telefone': mascarar(tentativa.numero), 'status': status,
            'status_display': historico.StatusEnvio.ROTULOS[status], 'resultado': tentativa.resultado,
            'resultado_display': tentativa.get_resultado_display(), 'respondido_em': _iso(tentativa.respondido_em),
            'conversa_id': tentativa.mensagem.conversa_id if tentativa.mensagem_id else None,
        })
    return resultado
