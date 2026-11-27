"""Agenda da régua (só leitura): o que a rotina vai enviar hoje e nos próximos dias, e quem fica de fora.

Simula as rodadas dia a dia com as mesmas funções de seleção da rotina (`cobranca_selecao`,
`cobranca.estado_insistencia`, `cobranca.versao_vigente`), na mesma ordem (quitação, antes, dia,
depois, insistência), com um aviso por cliente por dia e o teto diário. O que fica de fora por um
bloqueio passageiro (domingo, teto, régua pausada) volta a ser candidato no dia seguinte, como na rotina.
Nada é gravado: telefones são avaliados sem sincronizar (`contatos.para_aviso_sem_gravar`).
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.utils import timezone

from crm.models import ConfiguracaoCRM, TentativaContato
from crm.services import cobranca
from crm.services.cobranca_selecao import (ETAPAS, _candidatas_da_etapa, _parcelas_do_crediario, _quitacoes,
                                           bons_pagadores)

from . import janela
from .motivos import Motivo, mascarar, telefone_para_aviso
from .teto import SaudeNumero, restante_no_dia

Tipo = TentativaContato.Tipo
DIAS_PADRAO = 7
MAX_DIAS = 14
CHAVES = {Tipo.AVISO_QUITACAO: 'quitacao', Tipo.AVISO_ANTES: 'antes', Tipo.AVISO_DIA: 'dia',
          Tipo.AVISO_APOS: 'apos', Tipo.AVISO_INSISTENCIA: 'insistencia'}
ROTULOS = {'quitacao': 'Quitação', 'antes': 'Antes do vencimento', 'dia': 'No dia do vencimento',
           'apos': 'Depois do vencimento', 'insistencia': 'Nova tentativa sem retorno'}
ORDEM = ('quitacao', 'antes', 'dia', 'apos', 'insistencia')
PREFETCH_TELEFONES = 'pagamento__venda__cliente__telefones_crm'


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

    # --- dia ---------------------------------------------------------------------------------
    def bloqueio(self, dia: date) -> str:
        if not janela.dia_de_envio(dia):
            return Motivo.DOMINGO_FERIADO
        if not self.config.cobranca_ativa:
            return Motivo.REGUA_PAUSADA
        if self.ativada and dia < self.ativada.date():
            return Motivo.ANTES_DA_ATIVACAO
        if self.saude.pausada_por_qualidade:
            return Motivo.PAUSADA_POR_QUALIDADE
        if dia == self.hoje and self.local.time() >= janela.FIM_DOS_ENVIOS:
            return Motivo.FORA_DO_HORARIO
        return ''

    def dia(self, data: date) -> DiaAgenda:
        hoje = data == self.hoje
        capacidade = restante_no_dia(self.saude, data) if hoje else self.saude.teto_efetivo
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
        for pagamento in _quitacoes(self.config, estado.data):
            ultima = pagamento.parcelas_pagamento.select_related('pagamento__venda__cliente').order_by(
                '-numero_parcela').first()
            if ultima is not None:
                self._avaliar(estado, ultima, Tipo.AVISO_QUITACAO, motivo_fixo=sem_modelo)

    def _etapas(self, estado: _Dia) -> None:
        for etapa in ETAPAS:
            sem_modelo = '' if self.versoes[etapa.campo_modelo] else Motivo.ETAPA_SEM_MODELO
            candidatas = list(_candidatas_da_etapa(etapa, estado.data, self.ativada_em)
                              .prefetch_related(PREFETCH_TELEFONES))
            bons = set()
            if etapa.tipo == Tipo.AVISO_ANTES and self.config.cobranca_pular_bom_pagador:
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
            for parcela in _candidatas_da_etapa(etapa, estado.data, self.ativada_em, informadas):
                cliente = parcela.pagamento.venda.cliente
                estado.itens.append(ItemAgenda(parcela=parcela, etapa=CHAVES[etapa.tipo],
                                               motivo=Motivo.PAGAMENTO_INFORMADO,
                                               telefone=mascarar(self._telefone(cliente)[0])))


def _enviados_hoje(dia: date) -> dict[str, int]:
    inicio, fim = janela.dia_local(dia)
    linhas = (TentativaContato.objects.filter(tipo__in=cobranca.TIPOS_AVISO, criado_em__gte=inicio, criado_em__lt=fim)
              .values_list('tipo', flat=True))
    contagem: dict[str, int] = {}
    for tipo in linhas:
        contagem[CHAVES[tipo]] = contagem.get(CHAVES[tipo], 0) + 1
    return contagem


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

