"""Filtros da caixa de entrada: fila, situação, etiqueta, não lidas, busca e ordem."""
from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.http import QueryDict
from django.utils import timezone

from crm.apresentacao import EPOCA
from crm.models import Conversa, Mensagem
from crm.telefone import somente_digitos
from crm.web.base import inteiro_ou_none

FILAS = (
    ('minhas', 'Minhas'),
    ('sem_dono', 'Sem dono'),
    ('automatico', 'Automático'),
    ('todas', 'Todas'),
)
FILA_PADRAO = 'minhas'
ORDENS = (('recentes', 'Mais recentes'), ('espera', 'Maior espera'))
MIN_BUSCA_TEXTO = 3


@dataclass(frozen=True)
class Filtros:
    fila: str = FILA_PADRAO
    situacao: str = ''
    etiqueta: int | None = None
    nao_lidas: bool = False
    busca: str = ''
    ordem: str = 'recentes'

    @classmethod
    def do_request(cls, params: QueryDict) -> 'Filtros':
        fila = params.get('fila', FILA_PADRAO)
        situacao = params.get('situacao', '')
        etiqueta = params.get('etiqueta', '')
        ordem = params.get('ordem', 'recentes')
        return cls(
            fila=fila if fila in dict(FILAS) else FILA_PADRAO,
            situacao=situacao if situacao in Conversa.Situacao.values else '',
            etiqueta=inteiro_ou_none(etiqueta),
            nao_lidas=params.get('nao_lidas') == '1',
            busca=(params.get('q') or '').strip()[:100],
            ordem=ordem if ordem in dict(ORDENS) else 'recentes',
        )

    def querystring(self, **trocas) -> str:
        """Querystring dos filtros atuais (sem os vazios), com trocas opcionais."""
        valores = {
            'fila': self.fila, 'situacao': self.situacao, 'etiqueta': self.etiqueta or '',
            'nao_lidas': '1' if self.nao_lidas else '', 'q': self.busca,
            'ordem': '' if self.ordem == 'recentes' else self.ordem,
        }
        valores.update(trocas)
        return urlencode({chave: valor for chave, valor in valores.items() if valor not in ('', None)})


def filtro_fila(fila: str, usuario) -> Q:
    agora = timezone.now()
    if fila == 'minhas':
        return (Q(modo=Conversa.Modo.HUMANO, assumida_por=usuario)
                | Q(lembrete_para=usuario, lembrete_em__lte=agora))
    if fila == 'sem_dono':
        return Q(modo=Conversa.Modo.AGUARDANDO) | Q(modo=Conversa.Modo.HUMANO, assumida_por__isnull=True)
    if fila == 'automatico':
        return Q(modo=Conversa.Modo.AUTOMATICO)
    return Q()


def _filtro_busca(termo: str) -> Q:
    # Exists em vez de join: sem DISTINCT (caro no MySQL e incompatível com o ORDER BY por espera).
    clientes = Conversa.clientes.through.objects.filter(conversa_id=OuterRef('pk'), cliente__nome__icontains=termo)
    filtro = Q(contato_nome__icontains=termo) | Q(apelido__icontains=termo) | Q(Exists(clientes))
    digitos = somente_digitos(termo)
    if digitos:
        filtro |= Q(telefone__contains=digitos)
    if len(termo) >= MIN_BUSCA_TEXTO:
        filtro |= Q(Exists(Mensagem.objects.filter(conversa_id=OuterRef('pk'), texto__icontains=termo)))
    return filtro


def _ordenar_por_espera(qs):
    espera = (Mensagem.objects
              .filter(conversa=OuterRef('pk'), direcao=Mensagem.Direcao.ENTRADA,
                      criado_em__gt=Coalesce(OuterRef('ultima_humana_em'), Value(EPOCA)))
              .order_by('criado_em').values('criado_em')[:1])
    return qs.annotate(
        _espera=Subquery(espera),
        _aberta=Case(When(situacao=Conversa.Situacao.ABERTA, then=0), default=1, output_field=IntegerField()),
    ).order_by('_aberta', F('_espera').asc(nulls_last=True), '-ultima_mensagem_em')


def filtrar_conversas(filtros: Filtros, usuario):
    qs = Conversa.objects.filter(filtro_fila(filtros.fila, usuario))
    if filtros.situacao:
        qs = qs.filter(situacao=filtros.situacao)
    if filtros.etiqueta:
        qs = qs.filter(Exists(Conversa.etiquetas.through.objects.filter(
            conversa_id=OuterRef('pk'), etiqueta_id=filtros.etiqueta)))
    if filtros.nao_lidas:
        qs = qs.filter(nao_lidas__gt=0)
    if filtros.busca:
        qs = qs.filter(_filtro_busca(filtros.busca))
    if filtros.ordem == 'espera':
        return _ordenar_por_espera(qs)
    return qs.order_by('-ultima_mensagem_em', '-id')


def contadores(usuario) -> dict[str, int]:
    base = Conversa.objects.all()
    return {
        'minhas': base.filter(filtro_fila('minhas', usuario)).count(),
        'sem_dono': base.filter(filtro_fila('sem_dono', usuario)).count(),
        'automatico': base.filter(modo=Conversa.Modo.AUTOMATICO).count(),
        'todas': base.count(),
    }
