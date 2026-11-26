"""Inscrição do aparelho do usuário no Web Push (avisos com o sistema fechado)."""
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from notificacao import push
from notificacao.models import AssinaturaPush

LIMITE_USER_AGENT = 300


class ChavesSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=100)


class AssinaturaSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=500)
    keys = ChavesSerializer()

    def validate_endpoint(self, valor: str) -> str:
        if not valor.startswith('https://'):
            raise serializers.ValidationError('Endpoint de push inválido.')
        return valor


@extend_schema(
    tags=['Push'],
    responses=inline_serializer('PushChave', {'ativo': serializers.BooleanField(), 'chave_publica': serializers.CharField()}),
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def push_chave(request):
    return Response({'ativo': push.ativo(), 'chave_publica': push.chave_publica()})


@extend_schema(tags=['Push'], request=AssinaturaSerializer, responses={201: None, 204: None})
@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def push_assinaturas(request):
    if request.method == 'DELETE':
        endpoint = str(request.data.get('endpoint') or '')
        AssinaturaPush.objects.filter(usuario=request.user, endpoint=endpoint).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if not push.ativo():
        return Response({'detail': 'Notificações push não estão ativas neste servidor.'}, status=status.HTTP_400_BAD_REQUEST)
    dados = AssinaturaSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    # O mesmo aparelho logado com outro usuário passa a avisar só o usuário atual.
    AssinaturaPush.objects.update_or_create(
        endpoint=dados.validated_data['endpoint'],
        defaults={
            'usuario': request.user,
            'p256dh': dados.validated_data['keys']['p256dh'],
            'auth': dados.validated_data['keys']['auth'],
            'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:LIMITE_USER_AGENT],
        },
    )
    return Response(status=status.HTTP_201_CREATED)
