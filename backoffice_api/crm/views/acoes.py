"""Ações sobre a conversa: posse, situação, etiquetas, apelido, clientes e mensagem de abertura.

Todas são `POST /conversas/{id}/<acao>/` e devolvem o estado atualizado da conversa
(vincular/desvincular devolvem o painel do cliente). Regra violada → 409 `conflito`.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.response import Response

from crm.models import Conversa
from crm.permissoes import pode_gerenciar
from crm.services import aberturas, conversas, organizacao

from ..apresentacao import estado, painel
from ..base import CrmAPIView, obter_conversa
from ..permissoes import ACESSO
from ..serializers.entrada import (
    AberturaEnvioSerializer, ApelidoSerializer, AtribuirSerializer, ClienteSerializer, EtiquetasSerializer,
    PuxarSerializer, SituacaoSerializer,
)
from ..serializers.saida import ConversaEstadoSerializer, PainelSerializer
from ..servicos import mudar_situacao
from . import TAGS


def documentar(resumo: str, entrada=None, saida=ConversaEstadoSerializer, descricao: str = ''):
    return extend_schema_view(post=extend_schema(tags=TAGS, summary=resumo, description=descricao,
                                                 request=entrada, responses=saida))


class AcaoConversaView(CrmAPIView):
    """Valida a entrada (`entrada`), chama o serviço (`executar`) e responde o estado da conversa."""

    permissoes = {'POST': ACESSO}
    entrada = None

    def post(self, request, pk: int):
        conversa = obter_conversa(pk)
        dados = self.validar(self.entrada) if self.entrada else {}
        self.executar(conversa, dados)
        return self.responder(conversa)

    def executar(self, conversa: Conversa, dados: dict) -> None:
        raise NotImplementedError

    def responder(self, conversa: Conversa) -> Response:
        return Response(ConversaEstadoSerializer(estado(conversa.pk, self.request.user)).data)


@documentar('Assumir a conversa (sem dono ou no automático)')
class AssumirView(AcaoConversaView):
    def executar(self, conversa, dados):
        conversas.assumir(conversa, self.request.user)


@documentar('Puxar a conversa de outro atendente', PuxarSerializer)
class PuxarView(AcaoConversaView):
    entrada = PuxarSerializer

    def executar(self, conversa, dados):
        anterior = conversa.assumida_por_id
        conversas.puxar(conversa, self.request.user, dados.get('de'))
        self.auditar('crm_conversa_puxada', objeto=conversa, dados={'de': anterior})


@documentar('Atribuir (quem gerencia) ou repassar (dono) a outro atendente', AtribuirSerializer)
class AtribuirView(AcaoConversaView):
    entrada = AtribuirSerializer

    def executar(self, conversa, dados):
        usuario = self.request.user
        anterior = conversa.assumida_por_id
        conversas.atribuir(conversa, usuario, dados['usuario'], pode_gerenciar(usuario))
        self.auditar('crm_conversa_atribuida', objeto=conversa, dados={'de': anterior, 'para': dados['usuario'].pk})


@documentar('Devolver ao atendimento automático (dono, sem dono ou quem gerencia)')
class DevolverView(AcaoConversaView):
    def executar(self, conversa, dados):
        conversas.devolver(conversa, self.request.user, pode_gerenciar=pode_gerenciar(self.request.user))


@documentar('Mudar a situação (com `devolver_automatico` ao resolver)', SituacaoSerializer)
class SituacaoView(AcaoConversaView):
    entrada = SituacaoSerializer

    def executar(self, conversa, dados):
        mudar_situacao(conversa, dados['situacao'], self.request.user, dados['devolver_automatico'])


@documentar('Definir as etiquetas (substitui o conjunto)', EtiquetasSerializer)
class EtiquetasConversaView(AcaoConversaView):
    entrada = EtiquetasSerializer

    def executar(self, conversa, dados):
        organizacao.definir_etiquetas(conversa, dados['etiquetas'])


@documentar('Apelido da conversa (só a equipe vê; vazio remove)', ApelidoSerializer)
class ApelidoView(AcaoConversaView):
    entrada = ApelidoSerializer

    def executar(self, conversa, dados):
        organizacao.definir_apelido(conversa, dados['apelido'])


@documentar('Enviar mensagem de abertura (janela fechada) e assumir',
            AberturaEnvioSerializer, descricao='Com a janela aberta, só assume. Antispam: 409 se já saiu uma '
                                               'abertura nas últimas 24 h sem resposta.')
class AbrirView(AcaoConversaView):
    entrada = AberturaEnvioSerializer

    def executar(self, conversa, dados):
        aberturas.enviar_abertura(conversa, self.request.user, dados['modelo'], dados['nome'])


class _VinculoClienteView(AcaoConversaView):
    entrada = ClienteSerializer
    vincular = True

    def executar(self, conversa, dados):
        usuario = self.request.user if self.vincular else None  # desvincular não confere loja (como a tela)
        organizacao.vincular_cliente(conversa, dados['cliente'], self.vincular, usuario)
        acao = 'crm_cliente_vinculado' if self.vincular else 'crm_cliente_desvinculado'
        self.auditar(acao, objeto=conversa, dados={'cliente': dados['cliente']})

    def responder(self, conversa):
        return Response(PainelSerializer(painel(conversa, self.request.user)).data)


@documentar('Vincular cliente (só os das lojas do usuário)', ClienteSerializer, PainelSerializer)
class VincularClienteView(_VinculoClienteView):
    vincular = True


@documentar('Desvincular cliente (o cadastro não é apagado)', ClienteSerializer, PainelSerializer)
class DesvincularClienteView(_VinculoClienteView):
    vincular = False
