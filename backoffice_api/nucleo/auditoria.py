"""Registro das ações sensíveis do backoffice."""
from django.conf import settings
from django.db import models
from ipware import get_client_ip

from ..models import RegistroAuditoria


def ip_do_cliente(request) -> str | None:
    """IP real do cliente atrás do(s) proxy(s) confiável(is) (`AXES_PROXY_COUNT`)."""
    django_request = getattr(request, '_request', request)
    ip, _ = get_client_ip(django_request, proxy_count=settings.AXES_IPWARE_PROXY_COUNT)
    return ip or django_request.META.get('REMOTE_ADDR') or None


def auditar(
    request,
    acao: str,
    *,
    objeto: models.Model | None = None,
    descricao: str = '',
    motivo: str = '',
    dados: dict | None = None,
    usuario=None,
    usuario_nome: str | None = None,
) -> RegistroAuditoria:
    """Grava um `RegistroAuditoria`. `acao` é um verbo curto: 'login', 'analise_reprovada'..."""
    autenticado = getattr(getattr(request, 'user', None), 'is_authenticated', False)
    user = usuario or (request.user if autenticado else None)
    return RegistroAuditoria.objects.create(
        usuario=user,
        usuario_nome=(usuario_nome or (user.get_username() if user else ''))[:150],
        acao=acao,
        objeto_tipo=objeto._meta.label_lower if objeto is not None else '',
        objeto_id=str(objeto.pk) if objeto is not None else '',
        descricao=descricao[:255],
        motivo=motivo or '',
        dados=dados or {},
        ip=ip_do_cliente(request),
        user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:255],
    )
