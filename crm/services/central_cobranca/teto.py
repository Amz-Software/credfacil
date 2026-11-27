"""Teto diário de mensagens de cobrança e saúde do número na Meta.

- Teto automático = 80% do limite do número (TIER_250 → 200, TIER_2K → 1600...).
  `cobranca_teto_diario` só baixa esse valor. Sem leitura da Meta: última leitura ou 200.
- A Meta conta uma janela móvel de 24 h: o teto vale para os envios das últimas 24 h (não do dia).
- Conta todo template iniciado pela empresa: avisos da régua, disparos, aberturas e compra
  confirmada (sem as recusadas). Cada envio de cobrança confere o teto de novo dentro de uma
  transação travada (`reservar_vaga`): régua e disparos, em qualquer processo, não passam do teto.
- Qualidade YELLOW ou RED pausa a régua e os disparos até a Meta voltar a GREEN. Leitura da Meta
  falhando com a última leitura boa com mais de 1 h (ou nenhuma): pausa de segurança.
- A leitura fica 10 min no cache compartilhado (falha do cache não para nada).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from crm.models import ConfiguracaoCRM, Mensagem
from crm.whatsapp import obter_provider

logger = logging.getLogger(__name__)

PERCENTUAL_DO_LIMITE = 80
TETO_PADRAO = 200
CUSTO_POR_MENSAGEM = Decimal('0.035')  # estimativa em reais por template de utilidade
CHAVE_CACHE = 'crm:cobranca:saude_numero'
CACHE_SEGUNDOS = 10 * 60
CACHE_FALHA_SEGUNDOS = 2 * 60
LIMITE_ILIMITADO = 1_000_000
LIMITES_META = {
    'TIER_50': 50, 'TIER_250': 250, 'TIER_1K': 1_000, 'TIER_2K': 2_000, 'TIER_10K': 10_000,
    'TIER_100K': 100_000, 'TIER_UNLIMITED': LIMITE_ILIMITADO,
}
QUALIDADES_RUINS = frozenset({'YELLOW', 'RED'})
ROTULOS_QUALIDADE = {'GREEN': 'Alta', 'YELLOW': 'Média', 'RED': 'Baixa'}
ORIGENS_DA_EMPRESA = (Mensagem.Origem.COBRANCA, Mensagem.Origem.ABERTURA, Mensagem.Origem.COMPRA)
JANELA_DA_META = timedelta(hours=24)
LEITURA_VALIDA = timedelta(hours=1)  # Meta fora há mais que isso: pausa de segurança
PAUSA_QUALIDADE = 'pausada_por_qualidade'
PAUSA_SEM_LEITURA = 'sem_leitura_recente'


class TetoAtingido(Exception):
    """Sem vaga no teto das últimas 24 h: o envio fica para depois."""


class Fonte:
    META = 'meta'
    ULTIMA_LEITURA = 'ultima_leitura'
    PADRAO = 'padrao'


@dataclass(frozen=True)
class SaudeNumero:
    limite_tier: str
    qualidade: str
    fonte: str
    lido_em: datetime | None
    teto_configurado: int | None
    falhou: bool = False  # a última tentativa de ler a Meta deu erro

    @property
    def limite_meta(self) -> int | None:
        return LIMITES_META.get(self.limite_tier)

    @property
    def teto_automatico(self) -> int:
        limite = self.limite_meta
        return limite * PERCENTUAL_DO_LIMITE // 100 if limite else TETO_PADRAO

    @property
    def teto_efetivo(self) -> int:
        automatico = self.teto_automatico
        return min(automatico, self.teto_configurado) if self.teto_configurado else automatico

    @property
    def pausada_por_qualidade(self) -> bool:
        return self.qualidade in QUALIDADES_RUINS

    @property
    def sem_leitura_recente(self) -> bool:
        """Meta não responde e a última leitura boa é velha (ou não existe): não dá para saber a qualidade."""
        return self.falhou and (self.lido_em is None or timezone.now() - self.lido_em > LEITURA_VALIDA)

    @property
    def motivo_pausa(self) -> str:
        """'' = pode enviar; senão `PAUSA_QUALIDADE` ou `PAUSA_SEM_LEITURA`."""
        if self.pausada_por_qualidade:
            return PAUSA_QUALIDADE
        return PAUSA_SEM_LEITURA if self.sem_leitura_recente else ''

    @property
    def pausada(self) -> bool:
        return bool(self.motivo_pausa)

    @property
    def qualidade_display(self) -> str:
        return ROTULOS_QUALIDADE.get(self.qualidade, 'Desconhecida')


def _cache():
    return caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')]


def _do_cache() -> dict | None:
    try:
        return _cache().get(CHAVE_CACHE)
    except Exception:  # noqa: BLE001 — sem Redis, lê de novo (a Meta aguenta uma leitura por minuto)
        logger.warning('Cache compartilhado indisponível ao ler a saúde do número.', exc_info=True)
        return None


def _guardar(leitura: dict, segundos: int) -> None:
    try:
        _cache().set(CHAVE_CACHE, leitura, segundos)
    except Exception:  # noqa: BLE001
        logger.warning('Cache compartilhado indisponível ao gravar a saúde do número.', exc_info=True)


def limpar_cache() -> None:
    try:
        _cache().delete(CHAVE_CACHE)
    except Exception:  # noqa: BLE001
        logger.warning('Cache compartilhado indisponível ao limpar a saúde do número.', exc_info=True)


def _ler_da_meta() -> dict | None:
    """{'limite', 'qualidade'} ou None sem credenciais (modo simulado). Erro da Meta propaga."""
    consultar = getattr(obter_provider(), 'consultar_numero', None)
    return consultar() if consultar else None


def _gravar_ultima_leitura(config: ConfiguracaoCRM, limite: str, qualidade: str, agora: datetime) -> None:
    ConfiguracaoCRM.objects.filter(pk=config.pk).update(meta_limite=limite[:20], meta_qualidade=qualidade[:10],
                                                        meta_lido_em=agora)


def _ultima_conhecida(config: ConfiguracaoCRM) -> dict:
    fonte = Fonte.ULTIMA_LEITURA if config.meta_limite in LIMITES_META else Fonte.PADRAO
    lido_em = config.meta_lido_em.isoformat() if config.meta_lido_em else None
    return {'limite': config.meta_limite, 'qualidade': config.meta_qualidade, 'fonte': fonte, 'lido_em': lido_em}


def _atualizar(config: ConfiguracaoCRM) -> dict:
    try:
        lida = _ler_da_meta()
    except Exception as erro:  # noqa: BLE001 — ErroWhatsApp ou rede: vale a última leitura
        logger.warning('Não foi possível ler o número na Meta: %s', getattr(erro, 'mensagem', erro))
        leitura = {**_ultima_conhecida(config), 'falhou': True}
        _guardar(leitura, CACHE_FALHA_SEGUNDOS)
        return leitura
    if not lida:
        leitura = _ultima_conhecida(config)
        _guardar(leitura, CACHE_SEGUNDOS)
        return leitura
    agora = timezone.now()
    limite, qualidade = str(lida.get('limite') or ''), str(lida.get('qualidade') or '').upper()
    _gravar_ultima_leitura(config, limite, qualidade, agora)
    leitura = {'limite': limite, 'qualidade': qualidade, 'fonte': Fonte.META, 'lido_em': agora.isoformat()}
    _guardar(leitura, CACHE_SEGUNDOS)
    return leitura


def ler_saude(config: ConfiguracaoCRM | None = None, forcar: bool = False) -> SaudeNumero:
    """Saúde do número (até 10 min de cache). `forcar` lê a Meta agora."""
    config = config or ConfiguracaoCRM.obter()
    leitura = None if forcar else _do_cache()
    if not isinstance(leitura, dict):
        leitura = _atualizar(config)
    lido_em = parse_datetime(leitura['lido_em']) if leitura.get('lido_em') else None
    return SaudeNumero(limite_tier=leitura.get('limite') or '', qualidade=leitura.get('qualidade') or '',
                       fonte=leitura.get('fonte') or Fonte.PADRAO, lido_em=lido_em,
                       teto_configurado=config.cobranca_teto_diario, falhou=bool(leitura.get('falhou')))


def enviados_24h(agora: datetime | None = None) -> int:
    """Templates iniciados pela empresa nas últimas 24 h (régua, disparos, aberturas, compra confirmada)."""
    desde = (agora or timezone.now()) - JANELA_DA_META
    return (Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA, origem__in=ORIGENS_DA_EMPRESA, criado_em__gte=desde)
            .exclude(status=Mensagem.Status.ERRO).count())


def restante(saude: SaudeNumero, agora: datetime | None = None) -> int:
    """Vagas no teto agora (janela móvel de 24 h)."""
    return max(saude.teto_efetivo - enviados_24h(agora), 0)


def reservar_vaga(limite: int) -> None:
    """Dentro de uma transação, antes de criar a mensagem: trava a linha única da configuração (todos os
    envios de cobrança passam por aqui, em fila), reconta as últimas 24 h e recusa se não há vaga."""
    ConfiguracaoCRM.objects.select_for_update().filter(pk=1).values_list('pk', flat=True).first()
    if enviados_24h() >= limite:
        raise TetoAtingido(f'Teto de {limite} mensagens em 24 h atingido.')


def custo(quantidade: int) -> Decimal:
    return (CUSTO_POR_MENSAGEM * quantidade).quantize(Decimal('0.01'))
