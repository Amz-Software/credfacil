"""Serializers das notificações do usuário logado (django-notifications-hq)."""
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.urls import NoReverseMatch
from rest_framework import serializers

TAMANHO_MAXIMO_SELECAO = 500


def _url_do_alvo(alvo) -> str | None:
    """`get_absolute_url()` do alvo, ou None se ele não tiver (ou não resolver)."""
    if alvo is None or not hasattr(alvo, 'get_absolute_url'):
        return None
    try:
        return alvo.get_absolute_url()
    except (NoReverseMatch, AttributeError, ValueError):
        return None


def resolver_destinos(notificacoes: list) -> dict[int, str | None]:
    """URL de destino de cada notificação, buscando os alvos em lote (uma consulta por tipo).

    Não usa `prefetch_related('target')`: um content type de modelo removido quebraria a lista.
    """
    ids_por_tipo: dict[int, set[str]] = defaultdict(set)
    for notificacao in notificacoes:
        if notificacao.target_content_type_id and notificacao.target_object_id:
            ids_por_tipo[notificacao.target_content_type_id].add(notificacao.target_object_id)

    alvos: dict[tuple[int, str], object] = {}
    for tipo_id, ids in ids_por_tipo.items():
        modelo = ContentType.objects.get_for_id(tipo_id).model_class()
        if modelo is None:
            continue
        for objeto in modelo._default_manager.filter(pk__in=ids):
            alvos[(tipo_id, str(objeto.pk))] = objeto

    return {
        n.pk: _url_do_alvo(alvos.get((n.target_content_type_id, str(n.target_object_id))))
        for n in notificacoes
    }


class NotificacaoListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        notificacoes = list(data.all() if hasattr(data, 'all') else data)
        self.child.context['destinos'] = resolver_destinos(notificacoes)
        return super().to_representation(notificacoes)


class NotificacaoSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    titulo = serializers.CharField(source='verb', read_only=True)
    descricao = serializers.CharField(source='description', read_only=True, allow_null=True)
    lida = serializers.SerializerMethodField()
    criada_em = serializers.DateTimeField(source='timestamp', read_only=True)
    target_url = serializers.SerializerMethodField()
    nivel = serializers.CharField(source='level', read_only=True)

    class Meta:
        list_serializer_class = NotificacaoListSerializer

    def get_lida(self, obj) -> bool:
        return not obj.unread

    def get_target_url(self, obj) -> str | None:
        destinos = self.context.get('destinos')
        if destinos is not None and obj.pk in destinos:
            return destinos[obj.pk]
        return resolver_destinos([obj])[obj.pk]


class MarcarSelecionadasSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=TAMANHO_MAXIMO_SELECAO,
        error_messages={'empty': 'Selecione ao menos uma notificação.'},
    )
