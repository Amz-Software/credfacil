"""Configuração do CRM (`crm.gerenciar_crm`): geral e integração, etiquetas, respostas rápidas e aberturas.

Etiquetas e respostas rápidas não se excluem (como nas telas): desative com `ativo: false`.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.response import Response

from crm.apresentacao import abertura_dict
from crm.forms import ConfiguracaoForm, EtiquetaForm, RespostaRapidaForm
from crm.models import ConfiguracaoCRM, Etiqueta, ModeloAbertura, RespostaRapida
from crm.services import aberturas
from crm.web.configuracao import _integracao

from ..base import CrmAPIView
from ..permissoes import GERENCIA
from ..serializers.configuracao import (
    AberturaCriarSerializer, AberturaEditarSerializer, AberturaSerializer, ConfiguracaoEntradaSerializer,
    ConfiguracaoGeralSerializer, EtiquetaEntradaSerializer, EtiquetaSerializer, RespostaRapidaEntradaSerializer,
    RespostaRapidaSerializer, SimularDecisaoSerializer,
)
from ..servicos import dados_edicao_abertura, salvar_cadastro, simulado, validar_form, verificar_abertura
from . import TAGS


class ConfiguracaoView(CrmAPIView):
    permissoes = {'GET': GERENCIA, 'PATCH': GERENCIA}

    def _resposta(self) -> Response:
        return Response(ConfiguracaoGeralSerializer({
            'configuracao': ConfiguracaoCRM.obter(),
            'integracao': _integracao(self.request._request),  # nunca expõe valores, só se estão definidos
            'simulado': simulado(),
        }).data)

    @extend_schema(tags=TAGS, summary='Configuração do atendimento e situação da integração com a Meta',
                   responses=ConfiguracaoGeralSerializer)
    def get(self, request):
        return self._resposta()

    @extend_schema(tags=TAGS, summary='Alterar a configuração do atendimento (só os campos enviados)',
                   request=ConfiguracaoEntradaSerializer, responses=ConfiguracaoGeralSerializer)
    def patch(self, request):
        config = ConfiguracaoCRM.obter()
        form = validar_form(ConfiguracaoForm, request.data, config)
        form.save()
        self.auditar('crm_configuracao_alterada', objeto=config, dados={'campos': sorted(form.changed_data)})
        return self._resposta()


# --- etiquetas e respostas rápidas (mesmo fluxo: lista + criar + editar) --------------------

class _Cadastro(CrmAPIView):
    modelo = None
    form = None
    serializer = None
    nome = ''

    def consulta(self):
        return self.modelo.objects.all()


class _CadastroLista(_Cadastro):
    permissoes = {'GET': GERENCIA, 'POST': GERENCIA}

    def get(self, request):
        return self.paginar(self.consulta(), self.serializer)

    def post(self, request):
        objeto = salvar_cadastro(validar_form(self.form, request.data), request.user)
        self.auditar(f'crm_{self.nome}_criada', objeto=objeto)
        return Response(self.serializer(objeto).data, status=201)


class _CadastroItem(_Cadastro):
    permissoes = {'GET': GERENCIA, 'PATCH': GERENCIA}

    def get(self, request, pk: int):
        return Response(self.serializer(get_object_or_404(self.consulta(), pk=pk)).data)

    def patch(self, request, pk: int):
        form = validar_form(self.form, request.data, get_object_or_404(self.consulta(), pk=pk))
        objeto = salvar_cadastro(form, request.user)
        self.auditar(f'crm_{self.nome}_alterada', objeto=objeto, dados={'campos': sorted(form.changed_data)})
        return Response(self.serializer(objeto).data)


def _documentar_cadastro(titulo: str, entrada, serializer, lista: bool):
    if lista:
        return extend_schema_view(
            get=extend_schema(tags=TAGS, summary=f'{titulo}: lista (ativas e inativas)', responses=serializer(many=True)),
            post=extend_schema(tags=TAGS, summary=f'{titulo}: criar', request=entrada, responses={201: serializer}),
        )
    return extend_schema_view(
        get=extend_schema(tags=TAGS, summary=f'{titulo}: detalhe', responses=serializer),
        patch=extend_schema(tags=TAGS, summary=f'{titulo}: alterar (só os campos enviados)', request=entrada,
                            responses=serializer),
    )


class _Etiquetas:
    modelo, form, serializer, nome = Etiqueta, EtiquetaForm, EtiquetaSerializer, 'etiqueta'


class _Respostas:
    modelo, form, serializer, nome = RespostaRapida, RespostaRapidaForm, RespostaRapidaSerializer, 'resposta'

    def consulta(self):
        return RespostaRapida.objects.select_related('criado_por')


@_documentar_cadastro('Etiquetas', EtiquetaEntradaSerializer, EtiquetaSerializer, lista=True)
class EtiquetasConfigView(_Etiquetas, _CadastroLista):
    pass


@_documentar_cadastro('Etiquetas', EtiquetaEntradaSerializer, EtiquetaSerializer, lista=False)
class EtiquetaConfigView(_Etiquetas, _CadastroItem):
    pass


@_documentar_cadastro('Respostas rápidas', RespostaRapidaEntradaSerializer, RespostaRapidaSerializer, lista=True)
class RespostasConfigView(_Respostas, _CadastroLista):
    pass


@_documentar_cadastro('Respostas rápidas', RespostaRapidaEntradaSerializer, RespostaRapidaSerializer, lista=False)
class RespostaConfigView(_Respostas, _CadastroItem):
    pass


# --- mensagens de abertura (templates da Meta) ---------------------------------------------

def _modelos():
    return ModeloAbertura.objects.prefetch_related('versoes')


def _abertura(pk: int) -> dict:
    return AberturaSerializer(abertura_dict(get_object_or_404(_modelos(), pk=pk))).data


def _converter_aberturas(modelos) -> list[dict]:
    return [abertura_dict(modelo) for modelo in modelos]


class AberturasConfigView(CrmAPIView):
    permissoes = {'GET': GERENCIA, 'POST': GERENCIA}

    @extend_schema(tags=TAGS, summary='Mensagens de abertura com as versões (vigente, em análise, última)',
                   responses=AberturaSerializer(many=True))
    def get(self, request):
        return self.paginar_convertendo(_modelos(), _converter_aberturas, AberturaSerializer)

    @extend_schema(tags=TAGS, summary='Criar mensagem de abertura (vai à Meta para aprovação)',
                   request=AberturaCriarSerializer, responses={201: AberturaSerializer})
    def post(self, request):
        dados = self.validar(AberturaCriarSerializer)
        modelo = aberturas.criar_modelo(dados['titulo'], dados['corpo'], request.user)
        self.auditar('crm_abertura_criada', objeto=modelo)
        return Response(_abertura(modelo.pk), status=201)


class AberturaConfigView(CrmAPIView):
    permissoes = {'GET': GERENCIA, 'PATCH': GERENCIA}

    @extend_schema(tags=TAGS, summary='Mensagem de abertura', responses=AberturaSerializer)
    def get(self, request, pk: int):
        return Response(_abertura(pk))

    @extend_schema(tags=TAGS, summary='Alterar título, ordem, ativo e/ou texto (texto novo = versão nova na Meta)',
                   request=AberturaEditarSerializer, responses=AberturaSerializer)
    def patch(self, request, pk: int):
        modelo = get_object_or_404(_modelos(), pk=pk)
        validados = self.validar(AberturaEditarSerializer, parcial=True)
        ultima = abertura_dict(modelo)['ultima'] or {}
        dados = dados_edicao_abertura(validados, ultima.get('corpo', ''))
        aberturas.editar_modelo(modelo, dados, request.user)
        self.auditar('crm_abertura_alterada', objeto=modelo, dados={'campos': sorted(dados)})
        return Response(_abertura(pk))


class AberturaVerificarView(CrmAPIView):
    permissoes = {'POST': GERENCIA}

    @extend_schema(tags=TAGS, summary='Consultar a situação na Meta agora', request=None, responses=AberturaSerializer)
    def post(self, request, pk: int):
        verificar_abertura(get_object_or_404(ModeloAbertura, pk=pk))
        return Response(_abertura(pk))


class AberturaSimularView(CrmAPIView):
    permissoes = {'POST': GERENCIA}

    @extend_schema(tags=TAGS, summary='Simular a decisão da Meta (só no modo simulado)',
                   request=SimularDecisaoSerializer, responses=AberturaSerializer)
    def post(self, request, pk: int):
        modelo = get_object_or_404(ModeloAbertura, pk=pk)
        status = self.validar(SimularDecisaoSerializer)['status']
        aberturas.simular_decisao(modelo, status)
        self.auditar('crm_abertura_simulada', objeto=modelo, dados={'status': status})
        return Response(_abertura(pk))
