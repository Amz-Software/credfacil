"""Repasses ao logista e agenda de repasses."""
from datetime import date
import logging

from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.escopo import filtrar_por_escopo, loja_no_escopo
from api.permissions import RepassePermission
from api.serializers import RepasseSerializer
from financeiro.models import Repasse
from vendas.models import Loja


logger = logging.getLogger(__name__)


def _data_do_parametro(valor: str | None) -> date | None:
    """Data YYYY-MM-DD do query param; valor inválido é ignorado (como antes)."""
    try:
        return parse_date(valor or '')
    except ValueError:
        return None


class RepasseViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar repasses agendados.
    
    Endpoints disponíveis:
    - GET /api/repasses/ - Lista repasses (com filtros)
    - GET /api/repasses/agendados/ - Lista TODOS os repasses da loja (igual sistema web normal)
    - GET /api/repasses/{id}/ - Detalhe de um repasse
    - POST /api/repasses/ - Cria novo repasse
    - PUT /api/repasses/{id}/ - Atualiza repasse
    - PATCH /api/repasses/{id}/ - Atualiza parcialmente
    - DELETE /api/repasses/{id}/ - Deleta repasse
    """
    queryset = Repasse.objects.all()
    serializer_class = RepasseSerializer
    permission_classes = [RepassePermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ['data', 'valor', 'status']
    ordering = ['-data']

    def get_queryset(self):
        """
        Repasses das lojas do usuário (todas para superusuário ou
        `vendas.can_view_all_stores`), com ou sem `?loja`. Filtros opcionais:
        - loja: ID da loja (fora do escopo → lista vazia)
        - status: pendente, pago, cancelado (nenhum filtro de status por padrão)
        - data_inicio / data_fim: período (YYYY-MM-DD)
        """
        queryset = filtrar_por_escopo(Repasse.objects.all(), self.request.user)

        loja_filter = self.request.query_params.get('loja')
        if loja_filter:
            try:
                queryset = queryset.filter(loja_id=int(loja_filter))
            except (ValueError, TypeError):
                return queryset.none()

        status_filter = self.request.query_params.get('status')
        if status_filter in ['pendente', 'pago', 'cancelado']:
            queryset = queryset.filter(status=status_filter)

        data_inicio = _data_do_parametro(self.request.query_params.get('data_inicio'))
        if data_inicio:
            queryset = queryset.filter(data__date__gte=data_inicio)

        data_fim = _data_do_parametro(self.request.query_params.get('data_fim'))
        if data_fim:
            queryset = queryset.filter(data__date__lte=data_fim)

        return queryset.order_by('-data')
    
    @action(detail=False, methods=['get'], url_path='agendados')
    @extend_schema(
        description='Retorna repasses calculados automaticamente baseado nos períodos de venda (dias 6, 16, 26)',
        responses={200: OpenApiTypes.OBJECT},
        parameters=[
            OpenApiParameter('loja', OpenApiTypes.INT, description='ID da loja (obrigatório para não-admin)'),
            OpenApiParameter('meses_atras', OpenApiTypes.INT, description='Quantos meses olhar para trás (padrão: 0, máximo: 6)'),
        ]
    )
    def agendados(self, request):
        """
        Retorna repasses CALCULADOS automaticamente pela loja.
        
        Baseado no método get_repasses_status do modelo Loja:
        - Calcula repasses nos dias 6, 16 e 26 de cada mês
        - Períodos de competência:
          * Dia 6: vendas de 26 do mês anterior até 05 do mês atual
          * Dia 16: vendas de 06 até 15 do mês atual
          * Dia 26: vendas de 16 até 25 do mês atual
        - Verifica se repasse foi registrado no banco (feito=True/False)
        - Calcula valor total baseado no repasse_logista de cada venda
        """
        loja_id = request.query_params.get('loja') or request.session.get('loja_id')
        if not loja_id:
            return Response(
                {'erro': 'Parâmetro loja é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            loja_id = int(loja_id)
        except (ValueError, TypeError):
            return Response(
                {'erro': 'ID da loja inválido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not loja_no_escopo(request.user, loja_id):
            return Response(
                {'erro': 'Você não tem acesso a esta loja'},
                status=status.HTTP_403_FORBIDDEN
            )
        loja = Loja.objects.filter(id=loja_id).first()
        if loja is None:
            return Response(
                {'erro': 'Loja não encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Obter quantos meses olhar para trás (padrão: 0)
        meses_atras = request.query_params.get('meses_atras', 0)
        try:
            meses_atras = int(meses_atras)
            meses_atras = max(0, min(meses_atras, 6))  # Limitar entre 0 e 6
        except (ValueError, TypeError):
            meses_atras = 0
        
        # Calcular repasses usando o método do modelo
        resultados, total_atrasados = loja.get_repasses_status(meses_atras=meses_atras)
        
        # Formatar resposta
        repasses_formatados = []
        for rep in resultados:
            repasses_formatados.append({
                'data': rep['data'].strftime('%Y-%m-%d'),
                'data_formatada': rep['data'].strftime('%d/%m/%Y'),
                'inicio_periodo': rep['inicio_periodo'].strftime('%Y-%m-%d'),
                'inicio_periodo_formatado': rep['inicio_periodo'].strftime('%d/%m/%Y'),
                'fim_periodo': rep['fim_periodo'].strftime('%Y-%m-%d'),
                'fim_periodo_formatado': rep['fim_periodo'].strftime('%d/%m/%Y'),
                'qtd_vendas': rep['qtd_vendas'],
                'valor_total_repasse': str(rep['valor_total_repasse']),
                'feito': rep['feito'],
                'atrasado': rep['data'] < date.today() and not rep['feito'],
            })
        
        return Response({
            'loja_id': loja.id,
            'loja_nome': loja.nome,
            'meses_consultados': meses_atras,
            'total_atrasados': total_atrasados,
            'repasses': repasses_formatados
        })
    
    @extend_schema(
        description='Lista repasses com filtros opcionais',
        parameters=[
            OpenApiParameter('loja', OpenApiTypes.INT, description='Filtrar por ID da loja'),
            OpenApiParameter('status', OpenApiTypes.STR, description='Filtrar por status: pendente, pago, cancelado'),
            OpenApiParameter('data_inicio', OpenApiTypes.DATE, description='Filtrar a partir desta data (YYYY-MM-DD)'),
            OpenApiParameter('data_fim', OpenApiTypes.DATE, description='Filtrar até esta data (YYYY-MM-DD)'),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
