"""API de cadastros, integração, configuração, atendentes e simulador (docs/CRM_WHATSAPP.md §4.2, §4.5, §4.6)."""
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from crm.models import ConfiguracaoCRM, Conversa, Etiqueta, ModeloAbertura, RespostaRapida
from crm.permissoes import AcessarCRM, GerenciarCRM, LeituraOuGerenciar, usuarios_com_acesso
from crm.serializers import (
    ConfiguracaoSerializer, EtiquetaSerializer, RespostaRapidaSerializer, abertura_dict, usuario_mini,
)
from crm.services import aberturas, organizacao
from crm.services.conversas import ConflitoCRM
from crm.views_base import TrataConflitoMixin, ler_inteiro
from crm.whatsapp import credenciais, obter_provider

CAMINHO_WEBHOOK = '/api/whatsapp/webhook/'


class EtiquetaViewSet(TrataConflitoMixin, viewsets.ModelViewSet):
    permission_classes = [LeituraOuGerenciar]
    serializer_class = EtiquetaSerializer
    queryset = Etiqueta.objects.all()
    pagination_class = None

    def perform_destroy(self, instance):
        instance.ativo = False
        instance.save(update_fields=['ativo'])


class RespostaRapidaViewSet(TrataConflitoMixin, viewsets.ModelViewSet):
    permission_classes = [LeituraOuGerenciar]
    serializer_class = RespostaRapidaSerializer
    queryset = RespostaRapida.objects.all()
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)


class AberturaViewSet(TrataConflitoMixin, viewsets.GenericViewSet):
    permission_classes = [LeituraOuGerenciar]
    queryset = ModeloAbertura.objects.prefetch_related('versoes')

    def list(self, request):
        return Response([abertura_dict(m) for m in self.get_queryset()])

    def create(self, request):
        modelo = aberturas.criar_modelo(request.data.get('titulo', ''), request.data.get('corpo', ''), request.user)
        return Response(abertura_dict(self.get_queryset().get(pk=modelo.pk)), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        dados = {campo: request.data[campo] for campo in ('titulo', 'corpo', 'ativo', 'ordem') if campo in request.data}
        if 'ordem' in dados:
            dados['ordem'] = ler_inteiro(dados['ordem'], 'ordem') or 0
        modelo = aberturas.editar_modelo(self.get_object(), dados, request.user)
        return Response(abertura_dict(self.get_queryset().get(pk=modelo.pk)))

    @action(detail=True, methods=['post'])
    def verificar(self, request, pk=None):
        modelo = self.get_object()
        for versao in modelo.versoes.exclude(status__in=['DESCARTADO', 'ERRO_ENVIO']):
            aberturas.sincronizar(versao)
        return Response(abertura_dict(self.get_queryset().get(pk=modelo.pk)))

    @action(detail=True, methods=['post'])
    def simular(self, request, pk=None):
        modelo = aberturas.simular_decisao(self.get_object(), request.data.get('status', ''))
        return Response(abertura_dict(self.get_queryset().get(pk=modelo.pk)))

    @action(detail=False, methods=['get'], permission_classes=[AcessarCRM])
    def disponiveis(self, request):
        return Response(aberturas.disponiveis())


class IntegracaoView(APIView):
    permission_classes = [GerenciarCRM]

    def get(self, request):
        cred = credenciais()
        import os
        configurado = {
            'token': bool(cred.token), 'phone_number_id': bool(cred.phone_number_id), 'waba_id': bool(cred.waba_id),
            'app_secret': bool(cred.app_secret), 'verify_token': bool(cred.verify_token),
            'transcricao': bool(os.environ.get('OPENAI_API_KEY', '').strip()),
        }
        nomes = {
            'token': 'WHATSAPP_TOKEN', 'phone_number_id': 'WHATSAPP_PHONE_NUMBER_ID',
            'waba_id': 'WHATSAPP_WABA_ID', 'app_secret': 'WHATSAPP_APP_SECRET',
            'verify_token': 'WHATSAPP_VERIFY_TOKEN',
        }
        pendencias = [f'Defina {var} no .env do servidor.' for chave, var in nomes.items() if not configurado[chave]]
        if not configurado['transcricao']:
            pendencias.append('Opcional: defina OPENAI_API_KEY para transcrever áudios.')
        return Response({
            'modo': 'real' if cred.modo_real else 'simulado',
            'configurado': configurado,
            'api_version': cred.versao,
            'webhook_url': request.build_absolute_uri(CAMINHO_WEBHOOK),
            'pendencias': pendencias,
        })


class ConfiguracaoView(APIView):
    def get_permissions(self):
        return [GerenciarCRM()] if self.request.method == 'PATCH' else [AcessarCRM()]

    def get(self, request):
        return Response(ConfiguracaoSerializer(ConfiguracaoCRM.obter()).data)

    def patch(self, request):
        serializer = ConfiguracaoSerializer(ConfiguracaoCRM.obter(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AtendentesView(APIView):
    permission_classes = [AcessarCRM]

    def get(self, request):
        usuarios = usuarios_com_acesso().order_by('first_name', 'username')
        return Response([usuario_mini(u) for u in usuarios])


class _SimuladorBase(TrataConflitoMixin, APIView):
    permission_classes = [GerenciarCRM]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not getattr(obter_provider(), 'simulado', False):
            raise ConflitoCRM('O simulador só funciona com o WhatsApp simulado.')


class SimuladorReceberView(_SimuladorBase):
    def post(self, request):
        texto = (request.data.get('texto') or '').strip()
        telefone = request.data.get('telefone') or ''
        if not texto or not telefone:
            raise ConflitoCRM('Informe o telefone e o texto.')
        mensagem = organizacao.simular_recebida(telefone, request.data.get('nome', ''), texto)
        return Response({'conversa_id': mensagem.conversa_id if mensagem else None}, status=status.HTTP_201_CREATED)


class SimuladorLerView(_SimuladorBase):
    def post(self, request):
        conversa = get_object_or_404(Conversa, pk=ler_inteiro(request.data.get('conversa'), 'conversa'))
        return Response({'alteradas': organizacao.simular_leitura(conversa)})
