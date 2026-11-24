"""Avisos automáticos de cobrança pelo WhatsApp (templates de utilidade aprovados pela Meta).

Etapas por parcela do crediário (TipoPagamento IPX):
- 3 dias antes do vencimento (tolerância até a véspera, se a rotina perdeu o dia);
- no dia do vencimento (só no próprio dia: o texto diz "vence hoje");
- 2 dias depois, pedindo o comprovante (tolerância de 1 dia);
- sem retorno do cliente, repete a cada `cobranca_intervalo_dias` até `cobranca_max_insistencias`.
E a mensagem de quitação quando a última parcela de uma compra é paga.

Nunca cobra parcela paga ou com pagamento informado; no máximo um aviso por cliente por dia;
nunca usa número de referência (contatos.para_aviso). Só parcelas que entram na régua depois
de ligada: o histórico antigo de atrasos não é disparado em massa.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.cache import caches
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, Mensagem, TentativaContato, VersaoAbertura
from crm.services import aberturas, avisos, contatos, expediente
from crm.services.conversas import ConflitoCRM, conversa_do_telefone
from crm.services.pagamentos import formatar_reais
from crm.telefone import com_ddi
from crm.whatsapp import obter_provider

logger = logging.getLogger(__name__)

Tipo = TentativaContato.Tipo
TIPO_CREDFACIL = 'IPX'
FIM_DOS_ENVIOS = time(20, 0)
INTERVALO_RODADAS = 15 * 60  # segundos: a rotina do worker roda a cada minuto
CHAVE_RODADA = 'crm:cobranca:ultima_rodada'
JANELA_QUITACAO = timedelta(days=3)
MAX_ENVIOS_POR_RODADA = 300
MIN_PARCELAS_BOM_PAGADOR = 3
ALERTA_DEPOIS_DE_REPETICOES = 1  # pedido de comprovante + 1 repetição sem resposta → a equipe assume
MAX_FALHAS_SEGUIDAS = 5  # Meta fora do ar, token vencido, template pausado: para e tenta na próxima rodada
TIPOS_AVISO = (Tipo.AVISO_ANTES, Tipo.AVISO_DIA, Tipo.AVISO_APOS, Tipo.AVISO_INSISTENCIA, Tipo.AVISO_QUITACAO)


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
CAMPO_INSISTENCIA = 'modelo_aviso_insistencia'
CAMPO_QUITACAO = 'modelo_aviso_quitacao'


def _parcelas_abertas():
    from vendas.models import Parcela

    return (Parcela.objects
            .filter(pago=False, pagamento_efetuado=False,
                    pagamento__tipo_pagamento__nome__iexact=TIPO_CREDFACIL,
                    pagamento__venda__is_deleted=False, pagamento__quitado=False, pagamento__desativado=False,
                    pagamento__devolucao=False, pagamento__roubo=False)
            .select_related('pagamento__venda__cliente__contato_adicional',
                            'pagamento__venda__cliente__informacao_pessoal'))


class FalhaDeEnvio(Exception):
    """A Meta recusou o envio (não é problema do número do cliente): a etapa fica para depois."""


def _dia_local(dia: date) -> tuple[datetime, datetime]:
    """[início, fim) do dia em Belém, sem depender das tabelas de fuso do MySQL (__date)."""
    inicio = timezone.make_aware(datetime.combine(dia, time.min))
    return inicio, inicio + timedelta(days=1)


def versao_vigente(config: ConfiguracaoCRM, campo: str) -> VersaoAbertura | None:
    modelo_id = getattr(config, f'{campo}_id')
    if not modelo_id:
        return None
    return VersaoAbertura.objects.filter(modelo_id=modelo_id, modelo__ativo=True, vigente=True,
                                         status=VersaoAbertura.Status.APROVADO).first()


def _primeiro_nome(cliente) -> str:
    partes = (cliente.nome or '').split()
    return partes[0].capitalize() if partes else 'cliente'


def _ja_avisado_hoje(cliente, hoje: date) -> bool:
    inicio, fim = _dia_local(hoje)
    return TentativaContato.objects.filter(cliente=cliente, tipo__in=TIPOS_AVISO, criado_em__gte=inicio,
                                           criado_em__lt=fim).exists()


def _despachar(mensagem: Mensagem, tentativa_id: int, nome_meta: str, parametros: list[str]) -> None:
    """Envia o template. Recusa da Meta desfaz a tentativa (a etapa volta a valer) e levanta FalhaDeEnvio."""
    try:
        wamid = obter_provider().enviar_template(mensagem.conversa.telefone, nome_meta, parametros)
    except Exception as erro:  # noqa: BLE001 — ErroWhatsApp ou rede: nada saiu
        detalhe = getattr(erro, 'mensagem', '') or str(erro)
        # Nada saiu: some a tentativa e a mensagem (a etapa volta a valer na próxima rodada).
        TentativaContato.objects.filter(pk=tentativa_id).delete()
        Mensagem.objects.filter(pk=mensagem.pk).delete()
        raise FalhaDeEnvio(detalhe) from erro
    Mensagem.objects.filter(pk=mensagem.pk).update(status=Mensagem.Status.ENVIADO, wa_message_id=wamid or None)


def enviar_aviso(versao: VersaoAbertura, parcela, tipo: str, sequencia: int = 0,
                 hoje: date | None = None) -> Mensagem | None:
    """Registra a tentativa (única por parcela/etapa/sequência) e envia o template. None = nada enviado."""
    from vendas.models import Cliente

    hoje = hoje or timezone.localdate()
    cliente = parcela.pagamento.venda.cliente
    telefone = contatos.para_aviso(cliente)
    if telefone is None:
        return None
    try:
        texto, parametros = aberturas.renderizar(versao, {
            'nome': _primeiro_nome(cliente), 'valor': formatar_reais(parcela.valor_restante),
            'vencimento': parcela.data_vencimento.strftime('%d/%m/%Y'),
        })
    except ConflitoCRM:
        logger.warning('Template %s com parâmetro desconhecido; aviso não enviado.', versao.nome_meta)
        return None
    try:
        with transaction.atomic():
            # Trava o cliente: duas rodadas ao mesmo tempo não mandam dois avisos no mesmo dia.
            Cliente.objects.select_for_update().filter(pk=cliente.pk).first()
            if _ja_avisado_hoje(cliente, hoje):
                return None
            tentativa = TentativaContato.objects.create(
                cliente=cliente, telefone=telefone, numero=telefone.telefone, tipo=tipo, parcela=parcela,
                sequencia=sequencia)
            conversa = conversa_do_telefone(com_ddi(telefone.telefone))
            conversa.clientes.add(cliente)
            mensagem = Mensagem.objects.create(
                conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.AUTOMATICO,
                tipo=Mensagem.Tipo.TEXTO, texto=texto, origem=Mensagem.Origem.COBRANCA,
                status=Mensagem.Status.PENDENTE, envio_iniciado_em=timezone.now(), processada=True,
                dados={'cobranca': {'tipo': tipo, 'parcela_id': parcela.pk}, 'pessoal': True,
                       'abertura': {'versao': versao.nome_meta, 'valores': parametros}},
            )
            TentativaContato.objects.filter(pk=tentativa.pk).update(mensagem=mensagem)
    except IntegrityError:
        return None  # outra rodada já enviou esta etapa
    _despachar(mensagem, tentativa.pk, versao.nome_meta, parametros)
    Conversa.objects.filter(pk=conversa.pk).update(ultima_mensagem_em=timezone.now())
    avisos.emitir(conversa, 'conversa_atualizada')
    mensagem.refresh_from_db()
    return mensagem


def _candidatas_da_etapa(etapa: Etapa, hoje: date, ativada_em: date):
    # Só etapas cujo dia é a partir da ativação: ligar a régua não recupera avisos "atrasados".
    inicio = max(hoje - timedelta(days=etapa.ultimo_dia), ativada_em - timedelta(days=etapa.primeiro_dia))
    return (_parcelas_abertas()
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


def _cliente_escreveu_depois(cliente, momento: datetime) -> bool:
    return (Mensagem.objects.filter(conversa__clientes=cliente, direcao=Mensagem.Direcao.ENTRADA,
                                    criado_em__gt=momento)
            .exclude(tipo=Mensagem.Tipo.REACAO).exists())


def _proxima_insistencia(config: ConfiguracaoCRM, parcela, hoje: date) -> int | None:
    """Sequência da próxima insistência, ou None se não é hora (respondeu, intervalo, limite)."""
    avisos_da_parcela = [a for a in parcela.avisos_crm.all() if a.tipo != Tipo.ALERTA]
    pedido = next((a for a in avisos_da_parcela if a.tipo == Tipo.AVISO_APOS), None)
    if pedido is None:
        return None
    if any(a.resultado == TentativaContato.Resultado.RESPONDEU for a in avisos_da_parcela):
        return None
    feitas = sum(1 for a in avisos_da_parcela if a.tipo == Tipo.AVISO_INSISTENCIA)
    if feitas >= config.cobranca_max_insistencias:
        return None
    ultimo = max(a.criado_em for a in avisos_da_parcela)
    if (hoje - timezone.localtime(ultimo).date()).days < max(config.cobranca_intervalo_dias, 1):
        return None
    cliente = parcela.pagamento.venda.cliente
    return None if _cliente_escreveu_depois(cliente, pedido.criado_em) else feitas + 1


def _quitacoes(config: ConfiguracaoCRM, hoje: date):
    from vendas.models import Pagamento

    desde = hoje - JANELA_QUITACAO
    if config.cobranca_ativada_em:
        desde = max(desde, timezone.localtime(config.cobranca_ativada_em).date())
    return (Pagamento.objects
            .filter(tipo_pagamento__nome__iexact=TIPO_CREDFACIL, venda__is_deleted=False, devolucao=False,
                    desativado=False)
            .annotate(abertas=Count('parcelas_pagamento', filter=Q(parcelas_pagamento__pago=False)),
                      ultima=Max('parcelas_pagamento__data_pagamento'))
            .filter(abertas=0, ultima__gte=desde)
            .exclude(parcelas_pagamento__avisos_crm__tipo=Tipo.AVISO_QUITACAO)
            .select_related('venda__cliente'))


class _Rodada:
    """Uma passada da régua: um aviso por cliente por dia, no máximo MAX_ENVIOS_POR_RODADA."""

    def __init__(self, config: ConfiguracaoCRM, hoje: date):
        self.config, self.hoje = config, hoje
        inicio, fim = _dia_local(hoje)
        self.avisados = set(TentativaContato.objects.filter(tipo__in=TIPOS_AVISO, criado_em__gte=inicio,
                                                            criado_em__lt=fim)
                            .values_list('cliente_id', flat=True))
        self.enviados: dict[str, int] = {}
        self.falhas_seguidas = 0
        ativada = config.cobranca_ativada_em
        self.ativada_em = timezone.localtime(ativada).date() if ativada else hoje

    @property
    def parada(self) -> bool:
        return sum(self.enviados.values()) >= MAX_ENVIOS_POR_RODADA or self.falhas_seguidas >= MAX_FALHAS_SEGUIDAS

    def tentar(self, versao: VersaoAbertura, parcela, tipo: str, sequencia: int = 0) -> None:
        cliente_id = parcela.pagamento.venda.cliente_id
        if cliente_id in self.avisados or self.parada:
            return
        self.avisados.add(cliente_id)  # sem número ou com erro: só volta na próxima rodada
        try:
            mensagem = enviar_aviso(versao, parcela, tipo, sequencia, self.hoje)
        except FalhaDeEnvio as erro:
            self.falhas_seguidas += 1
            logger.warning('Meta recusou o aviso %s da parcela %s: %s', tipo, parcela.pk, erro)
            return
        except Exception:  # noqa: BLE001 — um cliente com defeito não para a régua
            logger.exception('Falha no aviso %s da parcela %s.', tipo, parcela.pk)
            return
        if mensagem is not None:
            self.falhas_seguidas = 0
            self.enviados[tipo] = self.enviados.get(tipo, 0) + 1

    def etapas(self) -> None:
        for etapa in ETAPAS:
            versao = versao_vigente(self.config, etapa.campo_modelo)
            if versao is None:
                continue
            candidatas = list(_candidatas_da_etapa(etapa, self.hoje, self.ativada_em))
            pular = set()
            if etapa.tipo == Tipo.AVISO_ANTES and self.config.cobranca_pular_bom_pagador:
                pular = bons_pagadores({p.pagamento.venda.cliente_id for p in candidatas}, self.hoje)
            for parcela in candidatas:
                if parcela.pagamento.venda.cliente_id not in pular:
                    self.tentar(versao, parcela, etapa.tipo)

    def insistencias(self) -> None:
        versao = versao_vigente(self.config, CAMPO_INSISTENCIA)
        if versao is None:
            return
        com_pedido = TentativaContato.objects.filter(tipo=Tipo.AVISO_APOS).values('parcela_id')
        candidatas = (_parcelas_abertas().filter(pk__in=com_pedido)
                      .annotate(repeticoes=Count('avisos_crm', filter=Q(avisos_crm__tipo=Tipo.AVISO_INSISTENCIA)))
                      .filter(repeticoes__lt=self.config.cobranca_max_insistencias)
                      .prefetch_related('avisos_crm').order_by('data_vencimento', 'pk'))
        for parcela in candidatas:
            sequencia = _proxima_insistencia(self.config, parcela, self.hoje)
            if sequencia is not None:
                self.tentar(versao, parcela, Tipo.AVISO_INSISTENCIA, sequencia)

    def alertas(self) -> None:
        """Não pagou e não respondeu ao pedido de comprovante nem à repetição: vai para a fila da equipe
        (ligação, C4M, referência). Um alerta por parcela; não conta como aviso ao cliente."""
        com_pedido = TentativaContato.objects.filter(tipo=Tipo.AVISO_APOS).values('parcela_id')
        candidatas = (_parcelas_abertas().filter(pk__in=com_pedido, data_vencimento__lt=self.hoje)
                      .annotate(repeticoes=Count('avisos_crm', filter=Q(avisos_crm__tipo=Tipo.AVISO_INSISTENCIA)),
                                alertas=Count('avisos_crm', filter=Q(avisos_crm__tipo=Tipo.ALERTA)))
                      .filter(repeticoes__gte=ALERTA_DEPOIS_DE_REPETICOES, alertas=0)
                      .prefetch_related('avisos_crm__mensagem__conversa'))
        for parcela in candidatas:
            try:
                alertar(parcela)
            except Exception:  # noqa: BLE001
                logger.exception('Falha no alerta da parcela %s.', parcela.pk)

    def quitacoes(self) -> None:
        versao = versao_vigente(self.config, CAMPO_QUITACAO)
        if versao is None:
            return
        for pagamento in _quitacoes(self.config, self.hoje):
            ultima = pagamento.parcelas_pagamento.order_by('-numero_parcela').first()
            if ultima is not None:
                self.tentar(versao, ultima, Tipo.AVISO_QUITACAO)


NOTA_ALERTA = ('Alerta de cobrança: {nome} não pagou a parcela {numero} (vencida em {vencimento}, {valor}) e não '
               'respondeu a {avisos} aviso(s). Tente ligação, outro número (C4M) ou as referências, sem falar da '
               'dívida com terceiros.')


def alertar(parcela) -> bool:
    """Registra o alerta (único por parcela) e põe a conversa do cliente na fila da equipe."""
    from crm.services.conversas import nota_automatica, transferir

    avisos_enviados = [a for a in parcela.avisos_crm.all() if a.automatica]
    cliente = parcela.pagamento.venda.cliente
    if any(a.resultado == TentativaContato.Resultado.RESPONDEU for a in avisos_enviados):
        return False
    pedido = next((a for a in avisos_enviados if a.tipo == Tipo.AVISO_APOS), None)
    if pedido is None or _cliente_escreveu_depois(cliente, pedido.criado_em):
        return False
    try:
        with transaction.atomic():
            TentativaContato.objects.create(cliente=cliente, numero=pedido.numero, tipo=Tipo.ALERTA, parcela=parcela,
                                            observacao='Não pagou e não respondeu aos avisos.')
    except IntegrityError:
        return False
    conversa = next((a.mensagem.conversa for a in reversed(avisos_enviados) if a.mensagem_id), None)
    if conversa is None:
        return True
    nota = NOTA_ALERTA.format(nome=_primeiro_nome(cliente), numero=parcela.numero_parcela,
                              vencimento=parcela.data_vencimento.strftime('%d/%m/%Y'),
                              valor=formatar_reais(parcela.valor_restante), avisos=len(avisos_enviados))
    if not transferir(conversa, nota):
        nota_automatica(conversa, nota)
        avisos.emitir(conversa, 'conversa_atualizada')
    return True


def _reservar_rodada() -> bool:
    """Trava no cache compartilhado (Redis): só um processo roda a régua a cada INTERVALO_RODADAS."""
    try:
        return caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')].add(CHAVE_RODADA, 1, INTERVALO_RODADAS)
    except Exception:  # noqa: BLE001 — sem Redis, a trava do cliente no banco ainda evita aviso duplicado
        logger.warning('Cache compartilhado indisponível; rodando a régua sem trava de rodada.', exc_info=True)
        return True


def rodar(agora: datetime | None = None, forcar: bool = False) -> dict:
    """Chamado pela rotina do worker a cada minuto; trabalha de 15 em 15 minutos, no horário de envio."""
    config = ConfiguracaoCRM.obter()
    local = timezone.localtime(agora or timezone.now())
    if not config.cobranca_ativa or not config.cobranca_hora_envio <= local.time() < FIM_DOS_ENVIOS:
        return {}
    if local.weekday() == expediente.DOMINGO or expediente.feriado(local.date()):
        return {}  # cobrança não sai em domingo nem feriado
    if not forcar and not _reservar_rodada():
        return {}
    rodada = _Rodada(config, local.date())
    rodada.quitacoes()
    rodada.etapas()
    rodada.insistencias()
    rodada.alertas()
    return rodada.enviados


def ao_ligar(config: ConfiguracaoCRM) -> None:
    """Marca quando a régua foi ligada (a quitação só vale para pagamentos depois disso)."""
    if config.cobranca_ativa and config.cobranca_ativada_em is None:
        agora = timezone.now()
        ConfiguracaoCRM.objects.filter(pk=config.pk).update(cobranca_ativada_em=agora)
        config.cobranca_ativada_em = agora
