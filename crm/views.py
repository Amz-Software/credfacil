"""API das conversas e mensagens do CRM (docs/CRM_WHATSAPP.md §4.3 e §4.4)."""
from django.contrib.auth import get_user_model
from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from crm import tarefas
from crm.models import Conversa, LogAcessoMidia, Mensagem, MensagemProgramada, Nota, RespostaRapida
from crm.permissoes import AcessarCRM, pode_gerenciar
from crm.serializers import (
    EPOCA, LIMITE_MENSAGENS_DETALHE, anotar_lista, base_mensagens, conversa_detalhe, conversa_resumo,
    mensagem_dict, mensagens_dicts, nota_dict, programada_dict,
)
from crm.services import aberturas, conversas, envio, midias, organizacao
from crm.services.conversas import ConflitoCRM
from crm.telefone import somente_digitos
from crm.views_base import TrataConflitoMixin, ler_datahora, ler_inteiro

TAMANHO_PAGINA = 50
MIN_BUSCA_TEXTO = 3
LIMITE_BUSCA = 50
CONTEXTO_TRECHO = 40
MENSAGENS_EM_TORNO = 25


class PaginacaoConversas(PageNumberPagination):
    page_size = TAMANHO_PAGINA


def _filtro_fila(fila: str, usuario):
    agora = timezone.now()
    if fila == 'minhas':
        return (Q(modo=Conversa.Modo.HUMANO, assumida_por=usuario)
                | Q(lembrete_para=usuario, lembrete_em__lte=agora))
    if fila == 'sem_dono':
        return Q(modo=Conversa.Modo.AGUARDANDO) | Q(modo=Conversa.Modo.HUMANO, assumida_por__isnull=True)
    if fila == 'automatico':
        return Q(modo=Conversa.Modo.AUTOMATICO)
    return Q()


class ConversaViewSet(TrataConflitoMixin, viewsets.GenericViewSet):
    permission_classes = [AcessarCRM]
    queryset = Conversa.objects.all()
    pagination_class = PaginacaoConversas

    # --- leitura ---------------------------------------------------------------
    def _filtrar(self, request):
        params = request.query_params
        qs = Conversa.objects.filter(_filtro_fila(params.get('fila', 'todas'), request.user))
        if params.get('situacao'):
            qs = qs.filter(situacao=params['situacao'])
        if params.get('etiqueta'):
            ids = [ler_inteiro(i, 'etiqueta') for i in params['etiqueta'].split(',') if i.strip()]
            qs = qs.filter(Exists(Conversa.etiquetas.through.objects.filter(conversa_id=OuterRef('pk'), etiqueta_id__in=ids)))
        if params.get('nao_lidas') == '1':
            qs = qs.filter(nao_lidas__gt=0)
        if params.get('lembrete') == 'vencido':
            qs = qs.filter(lembrete_em__lte=timezone.now())
        termo = (params.get('search') or '').strip()
        if termo:
            # Exists em vez de join: sem DISTINCT (caro no MySQL e incompatível com o ORDER BY por espera).
            clientes = Conversa.clientes.through.objects.filter(conversa_id=OuterRef('pk'), cliente__nome__icontains=termo)
            filtro = Q(contato_nome__icontains=termo) | Q(apelido__icontains=termo) | Q(Exists(clientes))
            digitos = somente_digitos(termo)
            if digitos:
                filtro |= Q(telefone__contains=digitos)
            if len(termo) >= MIN_BUSCA_TEXTO:
                filtro |= Q(Exists(Mensagem.objects.filter(conversa_id=OuterRef('pk'), texto__icontains=termo)))
            qs = qs.filter(filtro)
        if params.get('ordem') == 'espera':
            espera = (Mensagem.objects
                      .filter(conversa=OuterRef('pk'), direcao=Mensagem.Direcao.ENTRADA,
                              criado_em__gt=Coalesce(OuterRef('ultima_humana_em'), Value(EPOCA)))
                      .order_by('criado_em').values('criado_em')[:1])
            qs = qs.annotate(
                _espera=Subquery(espera),
                _aberta=Case(When(situacao=Conversa.Situacao.ABERTA, then=0), default=1, output_field=IntegerField()),
            ).order_by('_aberta', F('_espera').asc(nulls_last=True), '-ultima_mensagem_em')
        else:
            qs = qs.order_by('-ultima_mensagem_em', '-id')
        return qs

    def list(self, request):
        pagina = self.paginate_queryset(anotar_lista(self._filtrar(request)))
        agora = timezone.now()
        return self.get_paginated_response([conversa_resumo(c, agora) for c in pagina])

    @action(detail=False, methods=['get'])
    def contadores(self, request):
        usuario = request.user
        base = Conversa.objects.all()
        return Response({
            'minhas': base.filter(_filtro_fila('minhas', usuario)).count(),
            'sem_dono': base.filter(_filtro_fila('sem_dono', usuario)).count(),
            'automatico': base.filter(modo=Conversa.Modo.AUTOMATICO).count(),
            'todas': base.count(),
            'nao_lidas_minhas': base.filter(_filtro_fila('minhas', usuario), nao_lidas__gt=0).count(),
        })

    def retrieve(self, request, pk=None):
        conversa = self.get_object()
        if conversa.nao_lidas:
            Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)
        tarefas.agendar(envio.enviar_recibo_leitura, conversa.pk)
        return Response(conversa_detalhe(conversa, request.user))

    @action(detail=True, methods=['get'])
    def mensagens(self, request, pk=None):
        conversa = self.get_object()
        qs = base_mensagens(conversa)
        em_torno = ler_inteiro(request.query_params.get('em_torno_de'), 'em_torno_de')
        if em_torno:
            antes = list(qs.filter(id__lt=em_torno).order_by('-id')[:MENSAGENS_EM_TORNO])
            depois = list(qs.filter(id__gte=em_torno).order_by('id')[:MENSAGENS_EM_TORNO + 1])
            lista = list(reversed(antes)) + depois
            return Response({'results': mensagens_dicts(lista), 'tem_mais_antigas': qs.filter(
                id__lt=lista[0].pk).exists() if lista else False})
        limite = max(1, min(ler_inteiro(request.query_params.get('limite'), 'limite') or LIMITE_MENSAGENS_DETALHE, 100))
        antes_de = ler_inteiro(request.query_params.get('antes'), 'antes')
        if antes_de:
            qs = qs.filter(id__lt=antes_de)
        pagina = list(qs.order_by('-criado_em', '-id')[:limite + 1])
        return Response({'results': mensagens_dicts(list(reversed(pagina[:limite]))),
                         'tem_mais_antigas': len(pagina) > limite})

    @action(detail=True, methods=['get'])
    def busca(self, request, pk=None):
        conversa = self.get_object()
        termo = (request.query_params.get('q') or '').strip()
        if len(termo) < MIN_BUSCA_TEXTO:
            return Response([])
        achadas = base_mensagens(conversa).filter(texto__icontains=termo).order_by('-criado_em')[:LIMITE_BUSCA]
        resultado = []
        for mensagem in achadas:
            posicao = mensagem.texto.lower().find(termo.lower())
            inicio = max(posicao - CONTEXTO_TRECHO, 0)
            trecho = mensagem.texto[inicio:posicao + len(termo) + CONTEXTO_TRECHO]
            resultado.append({'mensagem_id': mensagem.pk, 'trecho': trecho, 'criado_em': mensagem.criado_em,
                              'direcao': mensagem.direcao})
        return Response(resultado)

    @action(detail=True, methods=['get'])
    def painel(self, request, pk=None):
        return Response(organizacao.painel(self.get_object(), request.user))

    # --- posse e situação ------------------------------------------------------------
    def _detalhe(self, conversa, codigo=status.HTTP_200_OK):
        conversa.refresh_from_db()
        return Response(conversa_detalhe(conversa, self.request.user), status=codigo)

    @action(detail=True, methods=['post'])
    def assumir(self, request, pk=None):
        return self._detalhe(conversas.assumir(self.get_object(), request.user))

    @action(detail=True, methods=['post'])
    def puxar(self, request, pk=None):
        de = ler_inteiro(request.data.get('de'), 'de')
        return self._detalhe(conversas.puxar(self.get_object(), request.user, de))

    @action(detail=True, methods=['post'])
    def atribuir(self, request, pk=None):
        destino = get_object_or_404(get_user_model(), pk=ler_inteiro(request.data.get('usuario'), 'usuario'))
        return self._detalhe(conversas.atribuir(self.get_object(), request.user, destino, pode_gerenciar(request.user)))

    @action(detail=True, methods=['post'])
    def devolver(self, request, pk=None):
        conversa = conversas.devolver(self.get_object(), request.user, pode_gerenciar=pode_gerenciar(request.user))
        return self._detalhe(conversa)

    @action(detail=True, methods=['post'])
    def situacao(self, request, pk=None):
        conversa = self.get_object()
        nova = request.data.get('situacao')
        if nova not in Conversa.Situacao.values:
            raise ConflitoCRM('Situação inválida.')
        devolver = bool(request.data.get('devolver_automatico'))
        if devolver and nova != Conversa.Situacao.RESOLVIDA:
            raise ConflitoCRM('Só é possível devolver ao automático ao resolver.')
        conversas.mudar_situacao(conversa, nova, request.user)
        if devolver:
            conversas.devolver(conversa, request.user, pode_gerenciar=pode_gerenciar(request.user))
        from crm.services import avisos
        avisos.emitir(conversa, 'conversa_atualizada')
        return self._detalhe(conversa)

    @action(detail=True, methods=['post'])
    def etiquetas(self, request, pk=None):
        conversa = self.get_object()
        ids = request.data.get('etiquetas')
        if not isinstance(ids, list):
            raise ConflitoCRM('Envie a lista de etiquetas.')
        organizacao.definir_etiquetas(conversa, [ler_inteiro(i, 'etiquetas') for i in ids])
        return self._detalhe(conversa)

    @action(detail=True, methods=['patch'])
    def apelido(self, request, pk=None):
        conversa = self.get_object()
        organizacao.definir_apelido(conversa, request.data.get('apelido', ''))
        return self._detalhe(conversa)

    @action(detail=True, methods=['post'], url_path='vincular-cliente')
    def vincular_cliente(self, request, pk=None):
        conversa = self.get_object()
        organizacao.vincular_cliente(conversa, ler_inteiro(request.data.get('cliente'), 'cliente'), True, request.user)
        return self._detalhe(conversa)

    @action(detail=True, methods=['post'], url_path='desvincular-cliente')
    def desvincular_cliente(self, request, pk=None):
        conversa = self.get_object()
        organizacao.vincular_cliente(conversa, ler_inteiro(request.data.get('cliente'), 'cliente'), False)
        return self._detalhe(conversa)

    @action(detail=False, methods=['post'])
    def iniciar(self, request):
        conversa = aberturas.iniciar_conversa(request.data.get('telefone', ''), request.user,
                                              request.data.get('modelo', ''), request.data.get('nome', ''))
        return self._detalhe(conversa, status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def abrir(self, request, pk=None):
        conversa = aberturas.enviar_abertura(self.get_object(), request.user, request.data.get('modelo', ''),
                                             request.data.get('nome', ''))
        return self._detalhe(conversa)

    # --- envio ------------------------------------------------------------------------
    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        mensagem = envio.enviar_texto(self.get_object(), request.data.get('texto', ''), usuario=request.user,
                                      responde_a_id=ler_inteiro(request.data.get('responde_a'), 'responde_a'))
        return Response(mensagem_dict(mensagem), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='enviar-midia')
    def enviar_midia(self, request, pk=None):
        arquivo = request.FILES.get('arquivo')
        if arquivo is None:
            raise ConflitoCRM('Escolha um arquivo.')
        if arquivo.size > midias.LIMITE_ENVIO:
            raise ConflitoCRM('O arquivo passa de 25 MB.')
        mensagem = envio.preparar_envio_midia(
            self.get_object(), request.user, arquivo, legenda=request.data.get('legenda', ''),
            voz=str(request.data.get('voz', '')).lower() == 'true',
            responde_a_id=ler_inteiro(request.data.get('responde_a'), 'responde_a'),
        )
        mensagem.refresh_from_db()
        return Response(mensagem_dict(mensagem), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def digitando(self, request, pk=None):
        envio.digitando(self.get_object(), request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # --- notas, lembrete, programadas, respostas rápidas ------------------------------
    @action(detail=True, methods=['get', 'post'])
    def notas(self, request, pk=None):
        conversa = self.get_object()
        if request.method == 'POST':
            nota = organizacao.criar_nota(conversa, request.user, request.data.get('texto', ''))
            return Response(nota_dict(nota, request.user), status=status.HTTP_201_CREATED)
        notas = Nota.objects.filter(conversa=conversa, apagada_em__isnull=True).select_related('usuario')
        return Response([nota_dict(n, request.user) for n in notas])

    @action(detail=True, methods=['delete'], url_path=r'notas/(?P<nota_id>\d+)')
    def apagar_nota(self, request, pk=None, nota_id=None):
        nota = get_object_or_404(Nota, pk=nota_id, conversa=self.get_object(), apagada_em__isnull=True)
        organizacao.apagar_nota(nota, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['put', 'delete'])
    def lembrete(self, request, pk=None):
        conversa = self.get_object()
        if request.method == 'DELETE':
            organizacao.concluir_lembrete(conversa)
        else:
            para_id = ler_inteiro(request.data.get('para'), 'para')
            para = get_object_or_404(get_user_model(), pk=para_id) if para_id else None
            organizacao.definir_lembrete(conversa, request.user, ler_datahora(request.data.get('lembrete_em')),
                                         request.data.get('texto', ''), para)
        return self._detalhe(conversa)

    @action(detail=True, methods=['post'])
    def programadas(self, request, pk=None):
        programada = organizacao.programar(self.get_object(), request.user, request.data.get('texto', ''),
                                           ler_datahora(request.data.get('enviar_em')))
        return Response(programada_dict(programada), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path=r'respostas-rapidas/(?P<resposta_id>\d+)/previa')
    def previa_resposta(self, request, pk=None, resposta_id=None):
        resposta = get_object_or_404(RespostaRapida, pk=resposta_id, ativo=True)
        return Response(organizacao.previa_resposta(self.get_object(), resposta, request.user))


class MensagemViewSet(TrataConflitoMixin, viewsets.GenericViewSet):
    permission_classes = [AcessarCRM]
    queryset = Mensagem.objects.select_related('conversa', 'usuario', 'responde_a')

    @action(detail=True, methods=['get'])
    def arquivo(self, request, pk=None):
        mensagem = self.get_object()
        midia = getattr(mensagem, 'midia', None)
        if midia is None or midia.status != midia.Status.OK:
            raise ConflitoCRM('A mídia ainda não foi baixada ou expirou.')
        versao = request.query_params.get('versao', '')
        url = midias.url_assinada(midia, versao, request)
        encaminhado = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
        LogAcessoMidia.objects.create(
            midia=midia, usuario=request.user, ip=encaminhado or request.META.get('REMOTE_ADDR'),
            user_agent=(request.headers.get('User-Agent') or '')[:300],
        )
        return Response({'url': url, 'expira_em_segundos': int(midias.VALIDADE_URL.total_seconds())})

    @action(detail=True, methods=['post'])
    def reenviar(self, request, pk=None):
        mensagem = envio.reenviar(self.get_object(), request.user)
        mensagem.refresh_from_db()
        return Response(mensagem_dict(mensagem))

    @action(detail=True, methods=['post'])
    def reagir(self, request, pk=None):
        mensagem = envio.reagir(self.get_object(), request.user, request.data.get('emoji', ''))
        return Response(mensagem_dict(mensagem))


class ProgramadaViewSet(TrataConflitoMixin, viewsets.GenericViewSet):
    permission_classes = [AcessarCRM]
    queryset = MensagemProgramada.objects.select_related('conversa', 'criado_por')

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        return Response(programada_dict(organizacao.cancelar_programada(self.get_object(), request.user)))


class MidiaDownloadView(View):
    """Entrega a mídia do storage local por um token assinado de 1 h (sem cabeçalho de auth)."""

    MIMES_EM_LINHA = ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'video/', 'audio/')

    def get(self, request, token):
        try:
            midia, versao = midias.midia_do_token(token)
            campo = midias.campo_para_download(midia, versao)
            arquivo = campo.open('rb') if campo else None
        except Exception:  # noqa: BLE001 — token inválido, mídia ou arquivo inexistente
            raise Http404('Mídia não encontrada.')
        if arquivo is None:
            raise Http404('Mídia não encontrada.')
        mime = 'image/jpeg' if versao == 'miniatura' else (midia.mime or 'application/octet-stream')
        em_linha = mime.startswith(self.MIMES_EM_LINHA)  # SVG, HTML e afins só como download
        resposta = FileResponse(arquivo, as_attachment=not em_linha, filename=midia.nome_original or None,
                                content_type=mime if em_linha else 'application/octet-stream')
        resposta['Cache-Control'] = 'private, max-age=3600'
        resposta['X-Content-Type-Options'] = 'nosniff'
        return resposta
