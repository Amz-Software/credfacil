"""Central de cobrança: saúde do número, configuração da régua, pausa, agenda e histórico.

Leitura (`crm.acessar_crm`): saúde, agenda, histórico, modelos. Escrita (`crm.gerenciar_crm`):
configuração, pausar e retomar — sempre auditadas. Listas de clientes respeitam o escopo de lojas
dos relatórios de cobrança; as contagens da agenda são da régua inteira (ela é uma só).
"""
from datetime import date, timedelta

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from crm.forms import CobrancaForm
from crm.models import ConfiguracaoCRM
from crm.services import cobranca
from crm.services.central_cobranca import agenda, historico, teto
from crm.services.conversas import ConflitoCRM

from ..apresentacao_cobranca import (agenda_dict, configuracao_dict, dia_resumo, itens_agenda, itens_historico,
                                     saude_dict)
from ..base import CrmAPIView
from ..permissoes import ACESSO, GERENCIA
from ..serializers.cobranca import (
    AgendaDiaQuerySerializer, AgendaQuerySerializer, AgendaSerializer, CobrancaConfigSerializer,
    CobrancaEntradaSerializer, DiaAgendaSerializer, HistoricoQuerySerializer, ItemAgendaSerializer,
    ItemHistoricoSerializer, PausarSerializer, ResumoHistoricoSerializer, SaudeQuerySerializer, SaudeSerializer,
)
from ..servicos import validar_form
from . import TAGS

TAGS_COBRANCA = TAGS


def _clientes_visiveis(ids: set[int], usuario) -> set[int]:
    from crm.services.relatorios_cobranca import _no_escopo
    from vendas.models import Cliente

    return set(_no_escopo(Cliente.objects.filter(pk__in=ids), usuario).values_list('pk', flat=True))


class SaudeView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA,
                   summary='Saúde do número: limite e qualidade na Meta, teto do dia, situação da régua',
                   parameters=[SaudeQuerySerializer], responses=SaudeSerializer)
    def get(self, request):
        forcar = self.validar_query(SaudeQuerySerializer)['atualizar']
        config = ConfiguracaoCRM.obter()
        return Response(SaudeSerializer(saude_dict(config, teto.ler_saude(config, forcar=forcar))).data)


class ConfiguracaoCobrancaView(CrmAPIView):
    permissoes = {'GET': GERENCIA, 'PATCH': GERENCIA}

    @extend_schema(tags=TAGS_COBRANCA, summary='Configuração da régua de cobrança',
                   responses=CobrancaConfigSerializer)
    def get(self, request):
        return Response(CobrancaConfigSerializer(configuracao_dict(ConfiguracaoCRM.obter())).data)

    @extend_schema(tags=TAGS_COBRANCA, summary='Alterar a configuração da régua (só os campos enviados)',
                   request=CobrancaEntradaSerializer, responses=CobrancaConfigSerializer)
    def patch(self, request):
        form = validar_form(CobrancaForm, request.data, ConfiguracaoCRM.obter())
        config = form.save()
        cobranca.ao_ligar(config)
        teto.limpar_cache()  # o teto configurado vale já
        self.auditar('crm_cobranca_configuracao_alterada', objeto=config, dados={'campos': sorted(form.changed_data)})
        return Response(CobrancaConfigSerializer(configuracao_dict(ConfiguracaoCRM.obter())).data)


class _Alternar(CrmAPIView):
    permissoes = {'POST': GERENCIA}
    ativar = False
    acao = ''
    mensagem_repetida = ''

    def post(self, request):
        motivo = self.validar(PausarSerializer).get('motivo', '')
        config = ConfiguracaoCRM.obter()
        if config.cobranca_ativa == self.ativar:
            raise ConflitoCRM(self.mensagem_repetida)
        ConfiguracaoCRM.objects.filter(pk=config.pk).update(cobranca_ativa=self.ativar)
        config.cobranca_ativa = self.ativar
        cobranca.ao_ligar(config)  # retomar não refaz a data de ativação já marcada
        self.auditar(self.acao, objeto=config, motivo=motivo)
        return Response(SaudeSerializer(saude_dict(config, teto.ler_saude(config))).data)


@extend_schema(tags=TAGS_COBRANCA, summary='Pausar a régua automática (cobranca_ativa = false)',
               request=PausarSerializer, responses=SaudeSerializer)
class PausarView(_Alternar):
    ativar, acao, mensagem_repetida = False, 'crm_cobranca_pausada', 'A régua já está pausada.'


@extend_schema(tags=TAGS_COBRANCA, summary='Retomar a régua automática (cobranca_ativa = true)',
               request=PausarSerializer, responses=SaudeSerializer)
class RetomarView(_Alternar):
    ativar, acao, mensagem_repetida = True, 'crm_cobranca_retomada', 'A régua já está ativa.'


class AgendaView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA, summary='Agenda da régua: previstos, excluídos e custo por dia e etapa',
                   parameters=[AgendaQuerySerializer], responses=AgendaSerializer)
    def get(self, request):
        dias = self.validar_query(AgendaQuerySerializer)['dias']
        config = ConfiguracaoCRM.obter()
        saude = teto.ler_saude(config)
        return Response(AgendaSerializer(agenda_dict(agenda.projetar(config, saude, dias), saude)).data)


def _filtrar_itens(dia: agenda.DiaAgenda, filtros: dict, visiveis: set[int]) -> list:
    situacao, etapa, motivo = filtros.get('situacao'), filtros.get('etapa'), filtros.get('motivo')
    return [item for item in dia.itens
            if item.cliente.pk in visiveis and (not etapa or item.etapa == etapa)
            and (not motivo or item.motivo == motivo) and (not situacao or (situacao == 'previsto') == item.previsto)]


class AgendaDiaView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA, summary='Agenda de um dia: destinatários previstos e excluídos (paginada)',
                   parameters=[AgendaDiaQuerySerializer,
                               OpenApiParameter('data', str, OpenApiParameter.PATH, description='AAAA-MM-DD')],
                   responses=ItemAgendaSerializer(many=True))
    def get(self, request, data: str):
        filtros = self.validar_query(AgendaDiaQuerySerializer)
        dia = self._data(data)
        config = ConfiguracaoCRM.obter()
        projetado = agenda.dia_da_projecao(config, teto.ler_saude(config), dia)
        visiveis = _clientes_visiveis({item.cliente.pk for item in projetado.itens}, request.user)
        resposta = self.paginar_convertendo(_filtrar_itens(projetado, filtros, visiveis), itens_agenda,
                                            ItemAgendaSerializer)
        resposta.data['resumo'] = DiaAgendaSerializer(dia_resumo(projetado)).data
        return resposta

    @staticmethod
    def _data(texto: str) -> date:
        hoje = timezone.localdate()
        try:
            dia = date.fromisoformat(texto)
        except ValueError as erro:
            raise ValidationError({'data': ['Use a data no formato AAAA-MM-DD.']}) from erro
        if not hoje <= dia <= hoje + timedelta(days=agenda.MAX_DIAS):
            raise ValidationError({'data': [f'Escolha um dia entre hoje e daqui a {agenda.MAX_DIAS} dias.']})
        return dia


class HistoricoView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA,
                   summary='Histórico de avisos da régua e envios de disparos (paginado, com resumo)',
                   parameters=[HistoricoQuerySerializer], responses=ItemHistoricoSerializer(many=True))
    def get(self, request):
        dados = self.validar_query(HistoricoQuerySerializer)
        filtros = historico.Filtros(desde=dados['desde'], ate=dados['ate'], etapa=dados.get('etapa') or '',
                                    resultado=dados.get('resultado') or '', status=dados.get('status') or '',
                                    disparo=dados.get('disparo'))
        consulta = historico.consultar(filtros, request.user)
        resposta = self.paginar_convertendo(consulta, itens_historico, ItemHistoricoSerializer)
        resposta.data['resumo'] = ResumoHistoricoSerializer(historico.resumo(consulta)).data
        return resposta
