"""Disparo manual de cobrança: público, prévia, confirmação, cancelamento e retomada.

- Template: mensagem de abertura ativa com versão vigente aprovada pela Meta (os marcadores
  aceitos são só {nome}, {valor} e {vencimento}, preenchidos com a parcela de cada cliente).
- Público: atraso entre X e Y dias, vencimento numa data ou no próximo dia 1/10/20, ou lista de parcelas;
  só clientes das lojas do usuário.
- A prévia congela o público (`ItemDisparo`); o envio (`envio_disparos`) confere cada item de novo com a
  mesma função (`motivo_do_destinatario`): o que a prévia mostrou é o que sai, menos quem deixou de valer.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from crm.models import DisparoCobranca, ItemDisparo, ModeloAbertura, TentativaContato, VersaoAbertura
from crm.services.cobranca import TIPOS_CONTATO_CLIENTE
from crm.services.cobranca_selecao import _parcelas_do_crediario
from crm.services.conversas import ConflitoCRM

from . import janela
from .motivos import Motivo, telefone_para_aviso
from .teto import SaudeNumero, restante

Status = DisparoCobranca.Status
Situacao = ItemDisparo.Situacao
MAX_DESTINATARIOS = 2000
MAX_PARCELAS_AVALIADAS = 5000
MAX_PARCELAS_LISTA = 500
MAX_DIAS_ATRASO = 365
DIAS_VENCIMENTO = (1, 10, 20)
JANELA_AVISO_RECENTE = timedelta(hours=48)
VALIDADE_PREVIA = timedelta(hours=24)
ENVIOS_POR_MINUTO = 20
MAX_DIAS_DISTRIBUICAO = 30
IDADE_MAXIMA = timedelta(days=3)  # depois disso da confirmação, o que não saiu expira (texto e valores velhos)
MENSAGEM_MUDOU = 'A mensagem mudou ou deixou de estar aprovada depois da prévia; crie um novo disparo.'


@dataclass(frozen=True)
class Publico:
    atraso_min: int | None = None
    atraso_max: int | None = None
    vencimento_data: date | None = None
    vencimento_dia: int | None = None
    parcelas: tuple = ()

    @property
    def criterio(self) -> str:
        if self.parcelas:
            return 'parcelas'
        if self.vencimento_data:
            return 'vencimento_data'
        if self.vencimento_dia:
            return 'vencimento_dia'
        return 'atraso'

    def como_json(self) -> dict:
        dados = {chave: valor for chave, valor in asdict(self).items() if valor not in (None, ())}
        if self.vencimento_data:
            dados['vencimento_data'] = self.vencimento_data.isoformat()
        if self.parcelas:
            dados['parcelas'] = list(self.parcelas)
        return {'criterio': self.criterio, **dados}


@dataclass(frozen=True)
class Avaliacao:
    parcela: object
    motivo: str  # '' = destinatário


def proxima_ocorrencia(dia_do_mes: int, hoje: date) -> date:
    """Próximo vencimento no dia do mês (hoje conta)."""
    candidato = hoje.replace(day=dia_do_mes)
    if candidato >= hoje:
        return candidato
    proximo_mes = (hoje.replace(day=1) + timedelta(days=32)).replace(day=1)
    return proximo_mes.replace(day=dia_do_mes)


def versao_para_disparo(modelo: ModeloAbertura) -> VersaoAbertura:
    aprovadas = modelo.versoes.filter(vigente=True, status=VersaoAbertura.Status.APROVADO)
    versao = aprovadas.first() if modelo.ativo else None
    if versao is None:
        raise ConflitoCRM('Escolha uma mensagem ativa e aprovada pela Meta.')
    return versao


def modelos_disponiveis() -> list[tuple[ModeloAbertura, VersaoAbertura]]:
    modelos = ModeloAbertura.objects.filter(ativo=True).prefetch_related('versoes')
    pares = [(m, next((v for v in m.versoes.all() if v.vigente and v.status == VersaoAbertura.Status.APROVADO), None))
             for m in modelos]
    return [(modelo, versao) for modelo, versao in pares if versao is not None]


def _parcelas_do_publico(publico: Publico, hoje: date):
    consulta = _parcelas_do_crediario().filter(pago=False)
    if publico.criterio == 'parcelas':
        consulta = consulta.filter(pk__in=publico.parcelas)
    elif publico.criterio == 'vencimento_data':
        consulta = consulta.filter(data_vencimento=publico.vencimento_data)
    elif publico.criterio == 'vencimento_dia':
        consulta = consulta.filter(data_vencimento=proxima_ocorrencia(publico.vencimento_dia, hoje))
    else:
        consulta = consulta.filter(data_vencimento__gte=hoje - timedelta(days=publico.atraso_max),
                                   data_vencimento__lte=hoje - timedelta(days=publico.atraso_min))
    return consulta.prefetch_related('pagamento__venda__cliente__telefones_crm').order_by('data_vencimento', 'pk')


def _no_escopo(consulta, usuario):
    from crm.services.relatorios_cobranca import _no_escopo as clientes_no_escopo
    from vendas.models import Cliente

    return consulta.filter(pagamento__venda__cliente__in=clientes_no_escopo(Cliente.objects.all(), usuario))


def clientes_avisados_desde(ids, desde: datetime) -> set[int]:
    return set(TentativaContato.objects.filter(cliente_id__in=list(ids), tipo__in=TIPOS_CONTATO_CLIENTE,
                                               criado_em__gte=desde).values_list('cliente_id', flat=True))


def motivo_do_destinatario(parcela, recentes: set[int]) -> str:
    """Por que a parcela não recebe agora ('' = recebe). Mesma regra na prévia e no envio."""
    if parcela.pago:
        return Motivo.PARCELA_PAGA
    if parcela.pagamento_efetuado:
        return Motivo.PAGAMENTO_INFORMADO
    cliente = parcela.pagamento.venda.cliente
    motivo_telefone = telefone_para_aviso(cliente)[1]
    if motivo_telefone:
        return motivo_telefone
    return Motivo.AVISO_RECENTE if cliente.pk in recentes else ''


def avaliar(parcelas: list, agora: datetime) -> list[Avaliacao]:
    """Um destinatário por cliente (a parcela de vencimento mais antigo); os demais com o motivo."""
    recentes = clientes_avisados_desde({p.pagamento.venda.cliente_id for p in parcelas}, agora - JANELA_AVISO_RECENTE)
    escolhidos: set[int] = set()
    avaliacoes = []
    for parcela in parcelas:
        cliente_id = parcela.pagamento.venda.cliente_id
        motivo = motivo_do_destinatario(parcela, recentes) or (Motivo.MESMO_CLIENTE if cliente_id in escolhidos else '')
        if not motivo:
            escolhidos.add(cliente_id)
        avaliacoes.append(Avaliacao(parcela=parcela, motivo=motivo))
    return avaliacoes


def _itens(disparo: DisparoCobranca, avaliacoes: list[Avaliacao]) -> list[ItemDisparo]:
    return [ItemDisparo(disparo=disparo, cliente_id=a.parcela.pagamento.venda.cliente_id, parcela=a.parcela,
                        ordem=ordem, situacao=Situacao.EXCLUIDO if a.motivo else Situacao.PENDENTE, motivo=a.motivo)
            for ordem, a in enumerate(avaliacoes, start=1)]


def montar_previa(modelo: ModeloAbertura, publico: Publico, usuario, agora: datetime | None = None) -> DisparoCobranca:
    """Avalia o público e grava a prévia (status PREVIA). Nada é enviado."""
    agora = agora or timezone.now()
    versao = versao_para_disparo(modelo)
    parcelas = list(_no_escopo(_parcelas_do_publico(publico, timezone.localtime(agora).date()), usuario)
                    [:MAX_PARCELAS_AVALIADAS + 1])
    if len(parcelas) > MAX_PARCELAS_AVALIADAS:
        raise ConflitoCRM(f'O filtro pega mais de {MAX_PARCELAS_AVALIADAS} parcelas; restrinja o público.')
    avaliacoes = avaliar(parcelas, agora)
    total = sum(1 for a in avaliacoes if not a.motivo)
    if total > MAX_DESTINATARIOS:
        raise ConflitoCRM(f'O público passa de {MAX_DESTINATARIOS} clientes; divida em mais de um disparo.')
    filtros = publico.como_json()
    if publico.parcelas:
        filtros['nao_encontradas'] = sorted(set(publico.parcelas) - {p.pk for p in parcelas})
    with transaction.atomic():
        disparo = DisparoCobranca.objects.create(modelo=modelo, versao=versao, filtros=filtros, total=total,
                                                 excluidos=len(avaliacoes) - total, criado_por=usuario)
        ItemDisparo.objects.bulk_create(_itens(disparo, avaliacoes))
    return disparo


def versao_igual(disparo: DisparoCobranca) -> bool:
    """A versão vigente aprovada da mensagem ainda é a da prévia (texto que o gestor conferiu)."""
    try:
        return versao_para_disparo(disparo.modelo).pk == disparo.versao_id
    except ConflitoCRM:
        return False


def expirado(disparo: DisparoCobranca, agora: datetime | None = None) -> bool:
    return bool(disparo.confirmado_em and (agora or timezone.now()) - disparo.confirmado_em > IDADE_MAXIMA)


def visiveis(usuario):
    """Disparos que o usuário pode ver e mexer: todos para quem vê todas as lojas; senão só os que criou."""
    from crm.services.organizacao import _ve_todas_as_lojas

    consulta = DisparoCobranca.objects.all()
    return consulta if _ve_todas_as_lojas(usuario) else consulta.filter(criado_por=usuario)


def _travar(disparo: DisparoCobranca) -> DisparoCobranca:
    return DisparoCobranca.objects.select_for_update().get(pk=disparo.pk)


def confirmar(disparo: DisparoCobranca, usuario, agora: datetime | None = None) -> DisparoCobranca:
    agora = agora or timezone.now()
    with transaction.atomic():
        disparo = _travar(disparo)
        if disparo.status != Status.PREVIA:
            raise ConflitoCRM('Só uma prévia pode ser confirmada.')
        if agora - disparo.criado_em > VALIDADE_PREVIA:
            raise ConflitoCRM('A prévia tem mais de 24 horas; gere uma nova para conferir o público.')
        if disparo.total == 0:
            raise ConflitoCRM('Nenhum destinatário nesta prévia.')
        if not versao_igual(disparo):
            raise ConflitoCRM(MENSAGEM_MUDOU)
        disparo.status, disparo.confirmado_por, disparo.confirmado_em = Status.AGENDADO, usuario, agora
        disparo.save(update_fields=['status', 'confirmado_por', 'confirmado_em', 'atualizado_em'])
    return disparo


def cancelar(disparo: DisparoCobranca, usuario, agora: datetime | None = None) -> DisparoCobranca:
    with transaction.atomic():
        disparo = _travar(disparo)
        if disparo.status not in DisparoCobranca.CANCELAVEIS:
            raise ConflitoCRM('Este disparo já terminou ou foi cancelado.')
        disparo.status, disparo.cancelado_por = Status.CANCELADO, usuario
        disparo.cancelado_em = agora or timezone.now()
        disparo.save(update_fields=['status', 'cancelado_por', 'cancelado_em', 'atualizado_em'])
    return disparo


def retomar(disparo: DisparoCobranca) -> DisparoCobranca:
    with transaction.atomic():
        disparo = _travar(disparo)
        if disparo.status != Status.PAUSADO:
            raise ConflitoCRM('Só um disparo pausado pode ser retomado.')
        if expirado(disparo):
            raise ConflitoCRM('Este disparo foi confirmado há mais de 3 dias; crie um novo com a prévia atual.')
        if not versao_igual(disparo):
            raise ConflitoCRM(MENSAGEM_MUDOU)
        disparo.status, disparo.falhas_seguidas, disparo.motivo_pausa = Status.AGENDADO, 0, ''
        disparo.save(update_fields=['status', 'falhas_seguidas', 'motivo_pausa', 'atualizado_em'])
    return disparo


# --- estimativa de quando sai -------------------------------------------------------------------

def _capacidade(config, saude: SaudeNumero, dia: date, agora: datetime, reserva: dict) -> int:
    hoje = timezone.localtime(agora).date()
    vagas = restante(saude, agora) if dia == hoje else saude.teto_efetivo
    return max(min(vagas - reserva.get(dia, 0), janela.minutos_no_dia(config, dia, agora) * ENVIOS_POR_MINUTO), 0)


def distribuicao(quantidade: int, config, saude: SaudeNumero, agora: datetime | None = None,
                 reserva: dict | None = None) -> tuple[list, int]:
    """[(dia, quantidade)] nos próximos dias de envio, pelo teto e pelo ritmo; e quantos ficam sem previsão.

    Hoje: vagas da janela móvel de 24 h; dias seguintes: o teto inteiro. Desconta a `reserva` da régua
    ({dia: envios previstos}, `agenda.reserva_da_regua`). Com o número pausado, nada tem previsão.
    """
    agora = agora or timezone.now()
    if saude.pausada:
        return [], quantidade
    reserva = reserva or {}
    hoje, falta, dias = timezone.localtime(agora).date(), quantidade, []
    for deslocamento in range(MAX_DIAS_DISTRIBUICAO):
        if falta <= 0:
            break
        dia = hoje + timedelta(days=deslocamento)
        lote = min(falta, _capacidade(config, saude, dia, agora, reserva))
        if lote > 0:
            dias.append((dia, lote))
            falta -= lote
    return dias, falta


def vagas_do_disparo(saude: SaudeNumero, reserva_hoje: int, agora: datetime | None = None) -> int:
    """Vagas agora para disparos: o que resta do teto menos o que a régua ainda vai mandar hoje."""
    return max(restante(saude, agora) - reserva_hoje, 0)


def situacao_envio(config, saude: SaudeNumero, agora: datetime | None = None, reserva_hoje: int = 0) -> str:
    """Por que os disparos não estão saindo agora ('' = saindo)."""
    local = timezone.localtime(agora or timezone.now())
    if not janela.dia_de_envio(local.date()):
        return Motivo.DOMINGO_FERIADO
    if not janela.no_horario(config, local):
        return Motivo.FORA_DO_HORARIO
    if saude.pausada:
        return saude.motivo_pausa
    return Motivo.LIMITE_DIARIO if vagas_do_disparo(saude, reserva_hoje, local) <= 0 else ''
