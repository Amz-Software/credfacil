"""De quem é a vez numa solicitação em andamento, do ponto de vista do vendedor.

- "minha ação": aprovada e sem venda, esperando o vendedor instalar o app
  (Android), fazer a configuração inicial (iPhone) ou gerar a venda já liberada;
- "aguardando analista": em análise, ou com a instalação/configuração do
  vendedor feita e esperando a analista validar o aparelho.

Usado pelo filtro da listagem da SPA e pelos contadores. A mesma regra está
espelhada em `front-connect-magic/src/lib/solicitacao.ts` (`proximoPasso`).
"""
from django.db.models import Q, QuerySet

from vendas.models import AnaliseCreditoCliente

MINHA_ACAO = 'minha_acao'
AGUARDANDO_ANALISTA = 'aguardando_analista'
ETAPAS = (MINHA_ACAO, AGUARDANDO_ANALISTA)

APP_PENDENTE = 'P'
APP_CONFIRMACAO_PENDENTE = 'C'
APP_INSTALADO = 'I'


def _filtros(prefixo: str) -> dict[str, Q]:
    def q(**condicoes) -> Q:
        return Q(**{f'{prefixo}{campo}': valor for campo, valor in condicoes.items()})

    com_imei = q(imei__isnull=False) | (q(imei_informado__isnull=False) & ~q(imei_informado=''))
    andamento = q(status='A', venda__isnull=True)
    android = q(produto__is_iphone=False)
    iphone = q(produto__is_iphone=True)
    iphone_configurado = iphone & q(icloud_configurado_vendedor=True)

    minha_acao = andamento & (
        (android & q(status_aplicativo=APP_PENDENTE))
        | (iphone & q(icloud_configurado_vendedor=False))
        | (android & q(status_aplicativo=APP_INSTALADO) & com_imei)
        | (iphone_configurado & com_imei)
    )
    aguardando = q(status='EA') | (
        andamento & ((android & q(status_aplicativo=APP_CONFIRMACAO_PENDENTE)) | (iphone_configurado & ~com_imei))
    )
    return {MINHA_ACAO: minha_acao, AGUARDANDO_ANALISTA: aguardando}


def filtro_etapa(etapa: str, *, prefixo: str = '') -> Q | None:
    """Q da etapa (`prefixo='analise_credito__'` para filtrar clientes); None se a etapa não existe."""
    return _filtros(prefixo).get(etapa)


def contar_por_etapa(analises: QuerySet[AnaliseCreditoCliente]) -> dict[str, int]:
    return {etapa: analises.filter(filtro).count() for etapa, filtro in _filtros('').items()}
