"""Seleção das parcelas da régua de cobrança (só consulta, nada é enviado aqui).

Usada pela rotina (`crm.services.cobranca`) e pela agenda da Central de cobrança
(`crm.services.central_cobranca.agenda`): a prévia usa exatamente a mesma seleção do envio.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, F, Max, Q
from django.utils import timezone

from crm.models import ConfiguracaoCRM, TentativaContato
from crm.services.pagamentos import TIPO_CREDFACIL

Tipo = TentativaContato.Tipo
JANELA_QUITACAO = timedelta(days=3)
MIN_PARCELAS_BOM_PAGADOR = 3


@dataclass(frozen=True)
class Etapa:
    tipo: str
    campo_modelo: str
    primeiro_dia: int  # dias em relação ao vencimento (negativo = antes)
    ultimo_dia: int


ETAPAS = (
    Etapa(Tipo.AVISO_ANTES, 'modelo_aviso_antes', -3, -1),
    Etapa(Tipo.AVISO_DIA, 'modelo_aviso_dia', 0, 0),
    Etapa(Tipo.AVISO_APOS, 'modelo_aviso_apos', 2, 3),
)


def _parcelas_do_crediario():
    """Parcelas do crediário IPX em vigor (paga ou não)."""
    from vendas.models import Parcela

    return (Parcela.objects
            .filter(pagamento__tipo_pagamento__nome__iexact=TIPO_CREDFACIL,
                    pagamento__venda__is_deleted=False, pagamento__quitado=False, pagamento__desativado=False,
                    pagamento__devolucao=False, pagamento__roubo=False)
            .select_related('pagamento__venda__cliente__contato_adicional',
                            'pagamento__venda__cliente__informacao_pessoal'))


def _parcelas_abertas():
    return _parcelas_do_crediario().filter(pago=False, pagamento_efetuado=False)


def _candidatas_da_etapa(etapa: Etapa, hoje: date, ativada_em: date, parcelas=None):
    """Parcelas (padrão: em aberto) cuja etapa cai em `hoje` e ainda não receberam esse aviso."""
    # Só etapas cujo dia é a partir da ativação: ligar a régua não recupera avisos "atrasados".
    inicio = max(hoje - timedelta(days=etapa.ultimo_dia), ativada_em - timedelta(days=etapa.primeiro_dia))
    return ((_parcelas_abertas() if parcelas is None else parcelas)
            .filter(data_vencimento__gte=inicio, data_vencimento__lte=hoje - timedelta(days=etapa.primeiro_dia))
            .exclude(avisos_crm__tipo=etapa.tipo)
            .order_by('data_vencimento', 'pk'))


def clientes_em_atraso(ids, hoje: date) -> set[int]:
    """Clientes (entre `ids`) com parcela do crediário vencida e sem pagamento informado."""
    return set(_parcelas_abertas().filter(data_vencimento__lt=hoje, pagamento__venda__cliente_id__in=list(ids))
               .values_list('pagamento__venda__cliente_id', flat=True))


def bons_pagadores(ids, hoje: date) -> set[int]:
    """Pagou ao menos MIN_PARCELAS_BOM_PAGADOR parcelas do crediário, todas até o vencimento, e não tem
    parcela vencida em aberto. Parcela paga sem data de pagamento (legado) não conta."""
    from vendas.models import Parcela

    pagas = (Parcela.objects
             .filter(pago=True, data_pagamento__isnull=False, pagamento__venda__cliente_id__in=list(ids),
                     pagamento__tipo_pagamento__nome__iexact=TIPO_CREDFACIL, pagamento__venda__is_deleted=False)
             .values('pagamento__venda__cliente_id')
             .annotate(total=Count('pk'), atrasadas=Count('pk', filter=Q(data_pagamento__gt=F('data_vencimento'))))
             .order_by())
    pontuais = {item['pagamento__venda__cliente_id'] for item in pagas
                if item['total'] >= MIN_PARCELAS_BOM_PAGADOR and item['atrasadas'] == 0}
    return pontuais - clientes_em_atraso(pontuais, hoje)


def _quitacoes(config: ConfiguracaoCRM, hoje: date):
    from vendas.models import Pagamento

    from vendas.models import Parcela

    desde = hoje - JANELA_QUITACAO
    if config.cobranca_ativada_em:
        desde = max(desde, timezone.localtime(config.cobranca_ativada_em).date())
    # Só agrupa compras com alguma parcela paga na janela (sem isso o banco agrega todas: segundos).
    com_pagamento_recente = (Parcela.objects.filter(pago=True, data_pagamento__gte=desde, data_pagamento__lte=hoje)
                             .values('pagamento_id'))
    return (Pagamento.objects
            .filter(tipo_pagamento__nome__iexact=TIPO_CREDFACIL, venda__is_deleted=False, devolucao=False,
                    desativado=False, pk__in=com_pagamento_recente)
            .annotate(abertas=Count('parcelas_pagamento', filter=Q(parcelas_pagamento__pago=False)),
                      ultima=Max('parcelas_pagamento__data_pagamento'))
            .filter(abertas=0, ultima__gte=desde, ultima__lte=hoje)  # data no futuro = erro de digitação
            .exclude(parcelas_pagamento__avisos_crm__tipo=Tipo.AVISO_QUITACAO)
            .select_related('venda__cliente'))
