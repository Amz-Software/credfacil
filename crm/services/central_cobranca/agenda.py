"""Agenda da régua (só leitura): o que a rotina vai enviar hoje e nos próximos dias, e quem fica de fora.

Simula as rodadas dia a dia com as mesmas funções de seleção da rotina (`cobranca_selecao`,
`cobranca.estado_insistencia`, `cobranca.versao_vigente`), na mesma ordem (quitação, antes, dia,
depois, insistência), com um aviso por cliente por dia e o teto diário. O que fica de fora por um
bloqueio passageiro (domingo, teto, régua pausada) volta a ser candidato no dia seguinte, como na rotina.
Nada é gravado: telefones são avaliados sem sincronizar (`contatos.para_aviso_sem_gravar`).
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import caches
from django.db.models import Count, Prefetch
from django.utils import timezone

from crm.models import ConfiguracaoCRM, TentativaContato
from crm.services import cobranca
from crm.services.cobranca_selecao import (ETAPAS, JANELA_QUITACAO, _parcelas_abertas,
                                           _parcelas_do_crediario, _quitacoes, bons_pagadores)

from . import janela
from .motivos import Motivo, mascarar, telefone_para_aviso
from .teto import SaudeNumero, restante

logger = logging.getLogger(__name__)
Tipo = TentativaContato.Tipo
DIAS_PADRAO = 7
MAX_DIAS = 14
CHAVES = {Tipo.AVISO_QUITACAO: 'quitacao', Tipo.AVISO_ANTES: 'antes', Tipo.AVISO_DIA: 'dia',
          Tipo.AVISO_APOS: 'apos', Tipo.AVISO_INSISTENCIA: 'insistencia'}
ROTULOS = {'quitacao': 'Quitação', 'antes': 'Antes do vencimento', 'dia': 'No dia do vencimento',
           'apos': 'Depois do vencimento', 'insistencia': 'Nova tentativa sem retorno'}
ORDEM = ('quitacao', 'antes', 'dia', 'apos', 'insistencia')
PREFETCH_TELEFONES = 'pagamento__venda__cliente__telefones_crm'
CHAVE_RESERVA = 'crm:cobranca:reserva_regua'
CHAVE_GERACAO = 'crm:cobranca:agenda_geracao'
CACHE_SEGUNDOS = 5 * 60  # projeção é cara: lista, resumo e reserva ficam 5 min no cache (mudar a config recalcula)


@dataclass(frozen=True)
class ItemAgenda:
    parcela: object
    etapa: str
    motivo: str  # '' = previsto
    telefone: str  # mascarado

    @property
    def previsto(self) -> bool:
        return not self.motivo

    @property
    def cliente(self):
        return self.parcela.pagamento.venda.cliente


@dataclass(frozen=True)
class DiaAgenda:
    data: date
    bloqueio: str
    capacidade: int
    itens: tuple
    enviados: dict = field(default_factory=dict)  # só hoje: avisos que já saíram, por etapa


@dataclass
class _Dia:
    """Estado de um dia durante a simulação (interno)."""

    data: date
    bloqueio: str
    capacidade: int
    avisados: set
    itens: list = field(default_factory=list)
    previstos: int = 0


class _Projecao:
    def __init__(self, config: ConfiguracaoCRM, saude: SaudeNumero, agora: datetime):
        self.config, self.saude = config, saude
        self.local = timezone.localtime(agora)
        self.hoje = self.local.date()
        ativada = config.cobranca_ativada_em
        self.ativada = timezone.localtime(ativada) if ativada else None
        self.ativada_em = self.ativada.date() if self.ativada else self.hoje
        self.projetadas: set[tuple[int, str, int]] = set()
        self.insistencias: dict[int, cobranca.EstadoInsistencia] = {}
        self.parcelas_insistencia: dict = {}
        self.telefones: dict[int, tuple[str, str]] = {}
        campos = [etapa.campo_modelo for etapa in ETAPAS] + [cobranca.CAMPO_INSISTENCIA, cobranca.CAMPO_QUITACAO]
        self.versoes = {campo: cobranca.versao_vigente(config, campo) for campo in campos}
        self._base_insistencia = None
        # Uma consulta por etapa para todo o horizonte (separadas por dia em memória): por dia eram segundos.
        self._etapas_no_horizonte: dict[str, list] = {}
        self._informadas_no_horizonte: dict[str, list] = {}
        self._quitacoes_base: list | None = None

    def _horizonte(self, etapa, base, guardadas: dict) -> list:
        """Candidatas da etapa de hoje até hoje + MAX_DIAS (mesma regra de `cobranca_selecao._candidatas_da_etapa`)."""
        if etapa.tipo not in guardadas:
            inicio = max(self.hoje - timedelta(days=etapa.ultimo_dia),
                         self.ativada_em - timedelta(days=etapa.primeiro_dia))
            fim = self.hoje + timedelta(days=MAX_DIAS) - timedelta(days=etapa.primeiro_dia)
            guardadas[etapa.tipo] = list(base.filter(data_vencimento__gte=inicio, data_vencimento__lte=fim)
                                         .exclude(avisos_crm__tipo=etapa.tipo)
                                         .order_by('data_vencimento', 'pk')
                                         .prefetch_related(PREFETCH_TELEFONES))
        return guardadas[etapa.tipo]

    def _do_dia(self, etapa, dia: date, parcelas: list) -> list:
        inicio = max(dia - timedelta(days=etapa.ultimo_dia), self.ativada_em - timedelta(days=etapa.primeiro_dia))
        fim = dia - timedelta(days=etapa.primeiro_dia)
        return [p for p in parcelas if inicio <= p.data_vencimento <= fim]

    # --- dia ---------------------------------------------------------------------------------
    def bloqueio(self, dia: date) -> str:
        if not janela.dia_de_envio(dia):
            return Motivo.DOMINGO_FERIADO
        if not self.config.cobranca_ativa:
            return Motivo.REGUA_PAUSADA
        if self.ativada and dia < self.ativada.date():
            return Motivo.ANTES_DA_ATIVACAO
        if self.saude.pausada:
            return self.saude.motivo_pausa  # pausada_por_qualidade ou sem_leitura_recente
        if dia == self.hoje and self.local.time() >= janela.FIM_DOS_ENVIOS:
            return Motivo.FORA_DO_HORARIO
        return ''

    def dia(self, data: date) -> DiaAgenda:
        hoje = data == self.hoje
        # Hoje: vagas da janela móvel de 24 h agora. Dias seguintes: o teto inteiro (estimativa).
        capacidade = restante(self.saude, self.local) if hoje else self.saude.teto_efetivo
        estado = _Dia(data=data, bloqueio=self.bloqueio(data), capacidade=capacidade,
                      avisados=cobranca.avisados_no_dia(data) if hoje else set())
        self._quitacoes(estado)
        self._etapas(estado)
        self._insistencias(estado)
        self._informados(estado)
        return DiaAgenda(data=data, bloqueio=estado.bloqueio, capacidade=capacidade, itens=tuple(estado.itens),
                         enviados=_enviados_hoje(data) if hoje else {})

    # --- avaliação de um aviso -----------------------------------------------------------------
    def _telefone(self, cliente) -> tuple[str, str]:
        if cliente.pk not in self.telefones:
            self.telefones[cliente.pk] = telefone_para_aviso(cliente)
        return self.telefones[cliente.pk]

    def _motivo(self, estado: _Dia, cliente, motivo_fixo: str) -> str:
        telefone_motivo = self._telefone(cliente)[1]
        if estado.bloqueio or motivo_fixo or telefone_motivo:
            return estado.bloqueio or motivo_fixo or telefone_motivo
        if cliente.pk in estado.avisados:
            return Motivo.JA_AVISADO_HOJE
        return Motivo.LIMITE_DIARIO if estado.previstos >= estado.capacidade else ''

    def _avaliar(self, estado: _Dia, parcela, tipo: str, sequencia: int = 0, motivo_fixo: str = '') -> None:
        chave = (parcela.pk, tipo, sequencia)
        if chave in self.projetadas:
            return
        cliente = parcela.pagamento.venda.cliente
        motivo = self._motivo(estado, cliente, motivo_fixo)
        estado.itens.append(ItemAgenda(parcela=parcela, etapa=CHAVES[tipo], motivo=motivo,
                                       telefone=mascarar(self._telefone(cliente)[0])))
        if motivo:
            return  # fica para o próximo dia (se ainda estiver na janela)
        estado.avisados.add(cliente.pk)
        estado.previstos += 1
        self.projetadas.add(chave)
        self._seguir_insistencia(parcela, tipo, estado.data)

    def _seguir_insistencia(self, parcela, tipo: str, dia: date) -> None:
        if tipo == Tipo.AVISO_APOS:
            agora = timezone.make_aware(datetime.combine(dia, janela.FIM_DOS_ENVIOS))
            self.insistencias[parcela.pk] = cobranca.EstadoInsistencia(pedido_em=agora, ultimo=dia, feitas=0)
            self.parcelas_insistencia[parcela.pk] = parcela
        elif tipo == Tipo.AVISO_INSISTENCIA:
            anterior = self.insistencias[parcela.pk]
            self.insistencias[parcela.pk] = cobranca.EstadoInsistencia(
                pedido_em=anterior.pedido_em, ultimo=dia, feitas=anterior.feitas + 1)

    # --- etapas (mesma ordem da rotina) ----------------------------------------------------------
    def _quitacoes(self, estado: _Dia) -> None:
        sem_modelo = '' if self.versoes[cobranca.CAMPO_QUITACAO] else Motivo.ETAPA_SEM_MODELO
        from vendas.models import Parcela

        if self._quitacoes_base is None:
            # Pagamentos já feitos (até hoje) servem a todos os dias: uma consulta só.
            parcelas = Parcela.objects.select_related('pagamento__venda__cliente').order_by('-numero_parcela')
            self._quitacoes_base = list(_quitacoes(self.config, self.hoje).prefetch_related(
                Prefetch('parcelas_pagamento', queryset=parcelas, to_attr='parcelas_desc')))
        desde = max(estado.data - JANELA_QUITACAO, self.ativada_em)
        for pagamento in (p for p in self._quitacoes_base if p.ultima and p.ultima >= desde):
            ultima = pagamento.parcelas_desc[0] if pagamento.parcelas_desc else None
            if ultima is not None:
                self._avaliar(estado, ultima, Tipo.AVISO_QUITACAO, motivo_fixo=sem_modelo)

    def _etapas(self, estado: _Dia) -> None:
        for etapa in ETAPAS:
            sem_modelo = '' if self.versoes[etapa.campo_modelo] else Motivo.ETAPA_SEM_MODELO
            candidatas = self._do_dia(etapa, estado.data,
                                      self._horizonte(etapa, _parcelas_abertas(), self._etapas_no_horizonte))
            bons = set()
            if candidatas and etapa.tipo == Tipo.AVISO_ANTES and self.config.cobranca_pular_bom_pagador:
                bons = bons_pagadores({p.pagamento.venda.cliente_id for p in candidatas}, estado.data)
            for parcela in candidatas:
                bom = Motivo.BOM_PAGADOR if parcela.pagamento.venda.cliente_id in bons else ''
                self._avaliar(estado, parcela, etapa.tipo, motivo_fixo=sem_modelo or bom)

    def _candidatas_insistencia(self) -> list:
        if self._base_insistencia is None:
            base = []
            for parcela in cobranca.candidatas_insistencia(self.config).prefetch_related(PREFETCH_TELEFONES):
                estado = cobranca.estado_insistencia(self.config, parcela)
                cliente = parcela.pagamento.venda.cliente
                if estado and not cobranca._cliente_escreveu_depois(cliente, estado.pedido_em):
                    self.insistencias.setdefault(parcela.pk, estado)
                    base.append(parcela)
            self._base_insistencia = base
        extras = [p for pk, p in self.parcelas_insistencia.items() if pk not in {b.pk for b in self._base_insistencia}]
        return self._base_insistencia + extras

    def _insistencias(self, estado: _Dia) -> None:
        sem_modelo = '' if self.versoes[cobranca.CAMPO_INSISTENCIA] else Motivo.ETAPA_SEM_MODELO
        for parcela in self._candidatas_insistencia():
            situacao = self.insistencias.get(parcela.pk)
            if situacao is None or situacao.feitas >= self.config.cobranca_max_insistencias:
                continue
            if cobranca.intervalo_cumprido(self.config, situacao.ultimo, estado.data):
                self._avaliar(estado, parcela, Tipo.AVISO_INSISTENCIA, situacao.feitas + 1, sem_modelo)

    def _informados(self, estado: _Dia) -> None:
        """Pagamento informado (aguardando baixa) não recebe aviso: só aparece como excluído."""
        informadas = _parcelas_do_crediario().filter(pago=False, pagamento_efetuado=True)
        for etapa in ETAPAS:
            horizonte = self._horizonte(etapa, informadas, self._informadas_no_horizonte)
            for parcela in self._do_dia(etapa, estado.data, horizonte):
                cliente = parcela.pagamento.venda.cliente
                estado.itens.append(ItemAgenda(parcela=parcela, etapa=CHAVES[etapa.tipo],
                                               motivo=Motivo.PAGAMENTO_INFORMADO,
                                               telefone=mascarar(self._telefone(cliente)[0])))


def _enviados_hoje(dia: date) -> dict[str, int]:
    inicio, fim = janela.dia_local(dia)
    linhas = (TentativaContato.objects.filter(tipo__in=cobranca.TIPOS_AVISO, criado_em__gte=inicio, criado_em__lt=fim)
              .values('tipo').annotate(qtd=Count('pk')).order_by())
    return {CHAVES[linha['tipo']]: linha['qtd'] for linha in linhas}


def projetar(config: ConfiguracaoCRM, saude: SaudeNumero, dias: int = DIAS_PADRAO,
             agora: datetime | None = None) -> list[DiaAgenda]:
    """Hoje e os próximos `dias` (até MAX_DIAS), na ordem."""
    projecao = _Projecao(config, saude, agora or timezone.now())
    quantidade = min(max(dias, 0), MAX_DIAS)
    return [projecao.dia(projecao.hoje + timedelta(days=deslocamento)) for deslocamento in range(quantidade + 1)]


def dia_da_projecao(config: ConfiguracaoCRM, saude: SaudeNumero, data: date,
                    agora: datetime | None = None) -> DiaAgenda:
    """Um dia da agenda (simula os anteriores, para o mesmo resultado da lista completa)."""
    projecao = _Projecao(config, saude, agora or timezone.now())
    dia = projecao.hoje
    while dia < data:
        projecao.dia(dia)
        dia += timedelta(days=1)
    return projecao.dia(data)


def _cache():
    return caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')]


def _geracao() -> int:
    try:
        return int(_cache().get(CHAVE_GERACAO) or 0)
    except Exception:  # noqa: BLE001
        logger.warning('Cache compartilhado indisponível ao ler a geração da agenda.', exc_info=True)
        return 0


def invalidar() -> None:
    """Configuração mudou (ligar, pausar, teto, modelos): a próxima leitura recalcula a agenda."""
    try:
        _cache().set(CHAVE_GERACAO, _geracao() + 1, None)
    except Exception:  # noqa: BLE001
        logger.warning('Cache compartilhado indisponível ao invalidar a agenda.', exc_info=True)


def em_cache(chave: str, calcular):
    """Valor calculado (serializável) por CACHE_SEGUNDOS; sem cache compartilhado, calcula sempre."""
    chave = f'{chave}:g{_geracao()}'
    try:
        guardado = _cache().get(chave)
    except Exception:  # noqa: BLE001
        logger.warning('Cache compartilhado indisponível ao ler a agenda.', exc_info=True)
        guardado = None
    if guardado is not None:
        return guardado
    valor = calcular()
    try:
        _cache().set(chave, valor, CACHE_SEGUNDOS)
    except Exception:  # noqa: BLE001
        logger.warning('Cache compartilhado indisponível ao gravar a agenda.', exc_info=True)
    return valor


def reserva_da_regua(config: ConfiguracaoCRM, saude: SaudeNumero, agora: datetime | None = None) -> dict[date, int]:
    """Envios que a régua ainda vai fazer, por dia (hoje + MAX_DIAS), para os disparos não ocuparem a vaga dela.

    Fica CACHE_SEGUNDOS no cache compartilhado (a projeção é cara).
    """
    local = timezone.localtime(agora or timezone.now())

    def calcular() -> dict[str, int]:
        return {dia.data.isoformat(): sum(1 for item in dia.itens if item.previsto)
                for dia in projetar(config, saude, MAX_DIAS, agora=local)}

    guardada = em_cache(f'{CHAVE_RESERVA}:{local.date().isoformat()}', calcular)
    return {date.fromisoformat(dia): qtd for dia, qtd in guardada.items()}
