"""Captura de fotos pelo celular (sessão por QR code)."""
from io import BytesIO
import logging

from PIL import Image, ImageOps
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.models import FotoSession


logger = logging.getLogger(__name__)


FOTO_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


@api_view(['POST'])
def foto_session_criar(request):
    """Cria uma nova sessão de foto e retorna o session_id e a URL para o celular."""
    from datetime import timedelta
    session = FotoSession.objects.create(expira_em=timezone.now() + timedelta(minutes=10))
    url_celular = request.build_absolute_uri(f'/foto/{session.session_id}/')
    return Response({'session_id': str(session.session_id), 'url': url_celular}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def foto_session_status(request, session_id):
    """Retorna o status da sessão: se a foto está pronta, a URL da foto e se expirou."""
    session = get_object_or_404(FotoSession, session_id=session_id)
    foto_url = request.build_absolute_uri(session.foto.url) if session.foto else None
    return Response({
        'pronta': bool(session.foto),
        'foto_url': foto_url,
        'expirada': session.expirada(),
    })


@csrf_exempt
def foto_session_upload(request, session_id):
    """Recebe a foto do celular (sem autenticação/CSRF) e salva na sessão."""
    if request.method != 'POST':
        return JsonResponse({'erro': 'Método não permitido.'}, status=405)

    session = get_object_or_404(FotoSession, session_id=session_id)

    if session.expirada():
        return JsonResponse({'erro': 'Sessão expirada.'}, status=410)

    arquivo = request.FILES.get('foto')
    if not arquivo:
        return JsonResponse({'erro': 'Nenhum arquivo enviado.'}, status=400)

    if arquivo.size > FOTO_MAX_SIZE:
        return JsonResponse({'erro': 'Arquivo muito grande. Máximo: 10 MB.'}, status=400)

    if not arquivo.content_type.startswith('image/'):
        return JsonResponse({'erro': 'Arquivo inválido. Envie uma imagem.'}, status=400)

    if session.foto:
        session.foto.delete(save=False)

    # Corrigir orientação baseada no EXIF
    try:
        img = Image.open(arquivo)
        formato = img.format
        img = ImageOps.exif_transpose(img)
        
        buffer = BytesIO()
        img.save(buffer, format=formato if formato else 'JPEG', quality=90)
        arquivo_corrigido = ContentFile(buffer.getvalue(), name=arquivo.name)
        arquivo = arquivo_corrigido
    except Exception:
        if hasattr(arquivo, 'seek'):
            arquivo.seek(0)
        pass

    session.foto = arquivo
    session.save()

    return JsonResponse({'ok': True})


def foto_celular_view(request, session_id):
    """Página HTML simples para captura de foto no celular."""
    session = get_object_or_404(FotoSession, session_id=session_id)
    return render(request, 'foto_celular.html', {
        'session_id': str(session_id),
        'expirada': session.expirada(),
        'upload_url': f'/api/foto-upload/{session_id}/',
    })
