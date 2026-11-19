"""Motor de conversas: gravar entradas, travar, processar em lote, posse e situação.

Regras em docs/CRM_WHATSAPP.md §3 e arquitetura-bot-crm-whatsapp.md §5, §6, §11.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from crm import tarefas
from crm.models import ConfiguracaoCRM, Conversa, Mensagem, Midia, Nota
from crm.services import avisos
from crm.telefone import chave_telefone, somente_digitos

logger = logging.getLogger(__name__)

MAX_LOTES_POR_RODADA = 5
TRAVA_ORFA = timedelta(minutes=10)
INTERVALO_BOAS_VINDAS = timedelta(hours=24)
DIGITOS_MINIMOS_TELEFONE = 4
LIMITE_NOTA = 2000


class ConflitoCRM(Exception):
    """Regra de negócio violada; vira HTTP 409 com `detail` pronto para a tela."""

    def __init__(self, detail: str, motivo: str = ''):
        super().__init__(detail)
        self.detail = detail
        self.motivo = motivo


@dataclass(frozen=True)
class EntradaNormalizada:
    telefone: str
    wa_message_id: str
    tipo: str
    texto: str = ''
    contato_nome: str = ''
    context_wa_id: str = ''
    midia_id: str = ''
    midia_meta: dict | None = None
    dados: dict | None = None
    criado_em: object = None


# --- conversa ---------------------------------------------------------------

def conversa_do_telefone(wa_id: str, criar: bool = True) -> Conversa | None:
    """Acha a conversa pela chave do telefone (o wa_id pode vir sem o 9º dígito)."""
    digitos = somente_digitos(wa_id)
    chave = chave_telefone(digitos)
    candidatas = Conversa.objects.filter(telefone__endswith=digitos[-4:])
    for conversa in candidatas:
        if chave_telefone(conversa.telefone) == chave:
            return conversa
    if not criar:
        return None
    try:
        with transaction.atomic():
            return Conversa.objects.create(telefone=digitos)
    except IntegrityError:
        return Conversa.objects.get(telefone=digitos)


def nota_automatica(conversa: Conversa, texto: str, tipo: str = Nota.Tipo.GERAL,
                    silenciosa: bool = False, usuario=None) -> Nota:
    return Nota.objects.create(
        conversa=conversa, texto=texto[:LIMITE_NOTA], automatica=True, tipo=tipo,
        silenciosa=silenciosa, usuario=usuario,
    )


def _salvar(conversa: Conversa, *campos: str) -> None:
    conversa.save(update_fields=list(campos))


def mudar_situacao(conversa: Conversa, situacao: str, usuario=None) -> None:
    """Grava só quando muda (cada mudança entra no histórico)."""
    if conversa.situacao == situacao:
        return
    conversa.situacao = situacao
    conversa.situacao_em = timezone.now()
    conversa.resolvida_por = usuario if situacao == Conversa.Situacao.RESOLVIDA else None
    _salvar(conversa, 'situacao', 'situacao_em', 'resolvida_por')


# --- entrada ----------------------------------------------------------------

def receber_mensagem(entrada: EntradaNormalizada) -> Mensagem | None:
    """Grava a mensagem recebida (idempotente pelo wa_message_id) e agenda o processamento."""
    if len(somente_digitos(entrada.telefone)) < DIGITOS_MINIMOS_TELEFONE:
        return None
    if entrada.wa_message_id and Mensagem.objects.filter(wa_message_id=entrada.wa_message_id).exists():
        return None

    agora = entrada.criado_em or timezone.now()
    eh_reacao = entrada.tipo == Mensagem.Tipo.REACAO
    dados = dict(entrada.dados or {})

    with transaction.atomic():
        conversa = conversa_do_telefone(entrada.telefone)
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        alvo_id = (dados.get('reacao') or {}).get('alvo_wa_id') if eh_reacao else entrada.context_wa_id
        responde_a = None
        if alvo_id:
            responde_a = Mensagem.objects.filter(conversa=conversa, wa_message_id=alvo_id).first()
            if responde_a is None:
                dados['context_id'] = alvo_id
        try:
            with transaction.atomic():
                mensagem = Mensagem.objects.create(
                    conversa=conversa, direcao=Mensagem.Direcao.ENTRADA, autor=Mensagem.Autor.CLIENTE,
                    tipo=entrada.tipo, texto=(entrada.texto or '')[:4096], responde_a=responde_a,
                    dados=dados, wa_message_id=entrada.wa_message_id or None, midia_id=entrada.midia_id,
                    status=Mensagem.Status.RECEBIDO, processada=eh_reacao, criado_em=agora,
                    transcricao_status=(Mensagem.Transcricao.PENDENTE if entrada.tipo == Mensagem.Tipo.AUDIO else ''),
                )
        except IntegrityError:
            return None  # reentrega concorrente da Meta

        if entrada.midia_id:
            meta = entrada.midia_meta or {}
            Midia.objects.create(
                mensagem=mensagem, wa_media_id=entrada.midia_id, mime=meta.get('mime', ''),
                sha256=meta.get('sha256', ''), nome_original=meta.get('nome_original', '')[:255],
                voz=bool(meta.get('voz')),
            )

        campos = ['ultima_mensagem_em', 'telefone']
        # Reentrega atrasada não pode encolher a janela de 24 h nem reordenar a lista.
        conversa.ultima_mensagem_em = max(filter(None, (conversa.ultima_mensagem_em, agora)))
        conversa.telefone = somente_digitos(entrada.telefone)
        if entrada.contato_nome and entrada.contato_nome != conversa.contato_nome:
            conversa.contato_nome = entrada.contato_nome[:150]
            campos.append('contato_nome')
        if not eh_reacao:
            conversa.ultima_entrada_em = max(filter(None, (conversa.ultima_entrada_em, agora)))
            conversa.nao_lidas = F('nao_lidas') + 1
            campos += ['ultima_entrada_em', 'nao_lidas']
        _salvar(conversa, *campos)
        conversa.refresh_from_db()

        if not eh_reacao:
            avaliar_retorno_automatico(conversa)
            mudar_situacao(conversa, Conversa.Situacao.ABERTA)
            tarefas.agendar(processar_conversa, conversa.pk)
        avisos.emitir(conversa, 'mensagem_nova' if not eh_reacao else 'conversa_atualizada')
    return mensagem


# --- processamento ------------------------------------------------------------

def _travar(conversa_id: int) -> bool:
    agora = timezone.now()
    livre = Q(processando=False) | Q(processando_desde__lt=agora - TRAVA_ORFA)
    return bool(Conversa.objects.filter(livre, pk=conversa_id).update(processando=True, processando_desde=agora))


def _destravar(conversa_id: int) -> None:
    Conversa.objects.filter(pk=conversa_id).update(processando=False, processando_desde=None)


def _pendentes(conversa_id: int):
    return list(Mensagem.objects.filter(
        conversa_id=conversa_id, direcao=Mensagem.Direcao.ENTRADA, processada=False,
    ).order_by('criado_em', 'id'))


def processar_conversa(conversa_id: int) -> None:
    """Uma thread por conversa (compare-and-set); até 5 lotes por rodada."""
    ciclos = 0
    while ciclos < MAX_LOTES_POR_RODADA and _travar(conversa_id):
        try:
            while ciclos < MAX_LOTES_POR_RODADA:
                pendentes = _pendentes(conversa_id)
                if not pendentes:
                    break
                ciclos += 1
                try:
                    _tratar_lote(conversa_id, pendentes)
                except Exception:  # noqa: BLE001 — na dúvida, vai para a equipe (princípio 6)
                    logger.exception('Falha ao tratar o lote da conversa %s.', conversa_id)
                    _transferir_por_falha(conversa_id)
                # Marca mesmo com falha: uma mensagem com defeito não pode travar a conversa.
                Mensagem.objects.filter(pk__in=[m.pk for m in pendentes]).update(processada=True)
                Conversa.objects.filter(pk=conversa_id).update(processando_desde=timezone.now())
        finally:
            _destravar(conversa_id)
        if not _pendentes(conversa_id):
            break


def _transferir_por_falha(conversa_id: int) -> None:
    try:
        conversa = Conversa.objects.get(pk=conversa_id)
        if conversa.modo == Conversa.Modo.AUTOMATICO:
            transferir(conversa, 'Erro ao processar a mensagem do cliente. Atenda pela equipe.', silenciosa=True)
    except Exception:  # noqa: BLE001
        logger.exception('Falha ao transferir a conversa %s depois de um erro.', conversa_id)


def _preparar_midia(mensagem: Mensagem) -> None:
    """Baixa e transcreve; erro numa mídia não impede o resto do lote."""
    from crm.services import midias  # import tardio: midias depende de conversas

    try:
        if hasattr(mensagem, 'midia'):
            midias.baixar(mensagem.midia)
        if mensagem.tipo == Mensagem.Tipo.AUDIO:
            midias.transcrever(mensagem)
    except Exception:  # noqa: BLE001 — o cron tenta a mídia de novo
        logger.exception('Falha ao preparar a mídia da mensagem %s.', mensagem.pk)


def _tratar_lote(conversa_id: int, pendentes: list[Mensagem]) -> None:
    for mensagem in pendentes:
        _preparar_midia(mensagem)

    conversa = Conversa.objects.get(pk=conversa_id)
    avaliar_retorno_automatico(conversa)
    if conversa.modo == Conversa.Modo.AUTOMATICO:
        atendimento_automatico(conversa, pendentes)


def atendimento_automatico(conversa: Conversa, pendentes: list[Mensagem] | None = None) -> None:
    """Autoatendimento de pagamentos (se ligado) ou boas-vindas + fila da equipe.

    Ponto de extensão para um agente de IA no futuro (arquitetura §7).
    """
    from crm.services import autoatendimento, envio

    config = ConfiguracaoCRM.obter()
    if config.autoatendimento_ativo:
        autoatendimento.tratar(conversa, pendentes or [])
        return
    agora = timezone.now()
    enviou = False
    recente = conversa.boas_vindas_em and agora - conversa.boas_vindas_em < INTERVALO_BOAS_VINDAS
    if config.boas_vindas_ativa and config.mensagem_boas_vindas.strip() and not recente:
        mensagem = envio.enviar_texto(
            conversa, config.mensagem_boas_vindas.strip(), usuario=None,
            autor=Mensagem.Autor.AUTOMATICO, origem=Mensagem.Origem.BOAS_VINDAS, exigir_trava=False,
        )
        enviou = mensagem.status != Mensagem.Status.ERRO
        Conversa.objects.filter(pk=conversa.pk).update(boas_vindas_em=agora)
    transferir(
        conversa,
        'Nova mensagem pelo WhatsApp. '
        + ('O cliente recebeu a boas-vindas automática.' if enviou else 'Nenhuma resposta automática foi enviada.'),
        silenciosa=not enviou,
    )


def transferir(conversa: Conversa, nota: str, silenciosa: bool = False) -> bool:
    """Único caminho para a fila da equipe: modo AGUARDANDO + nota de transferência + aviso.

    Só age se a conversa ainda estiver no automático: se alguém assumiu enquanto a
    boas-vindas saía, a posse dessa pessoa é mantida.
    """
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        if conversa.modo != Conversa.Modo.AUTOMATICO:
            return False
        conversa.modo = Conversa.Modo.AGUARDANDO
        conversa.assumida_por = None
        conversa.assumida_em = None
        conversa.aguardando_desde = timezone.now()
        _salvar(conversa, 'modo', 'assumida_por', 'assumida_em', 'aguardando_desde')
        mudar_situacao(conversa, Conversa.Situacao.ABERTA)
        nota_automatica(conversa, nota, tipo=Nota.Tipo.TRANSFERENCIA, silenciosa=silenciosa)
        avisos.emitir(conversa, 'transferencia')
    return True


def deve_retornar(conversa: Conversa, horas: int, agora=None) -> bool:
    if conversa.modo == Conversa.Modo.AUTOMATICO or horas <= 0:
        return False
    if conversa.situacao != Conversa.Situacao.RESOLVIDA:
        return False
    # Referência (arquitetura §11.3): em HUMANO, último envio da equipe ou posse;
    # em AGUARDANDO, último envio da equipe ou entrada na fila.
    inicio = conversa.assumida_em if conversa.modo == Conversa.Modo.HUMANO else conversa.aguardando_desde
    referencia = max((m for m in (conversa.ultima_humana_em, inicio) if m), default=None)
    return referencia is not None and (agora or timezone.now()) - referencia >= timedelta(hours=horas)


def avaliar_retorno_automatico(conversa: Conversa, agora=None) -> bool:
    """Conversa RESOLVIDA e parada há N horas volta ao atendimento automático."""
    horas = ConfiguracaoCRM.obter().retorno_automatico_horas
    if not deve_retornar(conversa, horas, agora):
        return False
    return devolver(conversa, usuario=None, automatico=True, horas=horas) is not None


# --- posse -------------------------------------------------------------------

def _nome(usuario) -> str:
    return (usuario.get_full_name() or usuario.username) if usuario else 'sistema'


def assumir(conversa: Conversa, usuario) -> Conversa:
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        dono = conversa.assumida_por
        if conversa.modo == Conversa.Modo.HUMANO and dono and dono != usuario:
            raise ConflitoCRM(f'A conversa está com {_nome(dono)}. Puxe a conversa para responder.', 'OUTRO_DONO')
        if conversa.modo == Conversa.Modo.HUMANO and dono == usuario:
            return conversa
        conversa.modo = Conversa.Modo.HUMANO
        conversa.assumida_por = usuario
        conversa.assumida_em = timezone.now()
        _salvar(conversa, 'modo', 'assumida_por', 'assumida_em')
        avisos.emitir(conversa, 'conversa_atualizada')
    return conversa


def puxar(conversa: Conversa, usuario, de_usuario_id: int | None) -> Conversa:
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        dono = conversa.assumida_por
        if conversa.modo != Conversa.Modo.HUMANO or dono is None:
            raise ConflitoCRM('A conversa não está com ninguém. Use "Assumir".')
        if dono == usuario:
            raise ConflitoCRM('A conversa já está com você.')
        if de_usuario_id and dono.pk != int(de_usuario_id):
            raise ConflitoCRM(f'A conversa passou para {_nome(dono)} enquanto você decidia.')
        conversa.assumida_por = usuario
        conversa.assumida_em = timezone.now()
        _salvar(conversa, 'assumida_por', 'assumida_em')
        nota_automatica(conversa, f'{_nome(usuario)} puxou a conversa de {_nome(dono)}.', usuario=usuario)
        avisos.notificar_usuario(dono, f'{_nome(usuario)} puxou a conversa com {conversa.nome_exibicao}', conversa)
        avisos.emitir(conversa, 'atribuida')
    return conversa


def atribuir(conversa: Conversa, usuario, destino, pode_gerenciar: bool) -> Conversa:
    from crm.permissoes import pode_acessar

    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        eh_dono = conversa.modo == Conversa.Modo.HUMANO and conversa.assumida_por == usuario
        if not (pode_gerenciar or eh_dono):
            raise ConflitoCRM('Só o dono da conversa ou quem gerencia o CRM pode repassar.')
        if not pode_acessar(destino):
            raise ConflitoCRM('O destino não tem acesso ao CRM.')
        if conversa.modo == Conversa.Modo.HUMANO and conversa.assumida_por == destino:
            raise ConflitoCRM('A conversa já está com essa pessoa.')
        anterior = conversa.assumida_por
        conversa.modo = Conversa.Modo.HUMANO
        conversa.assumida_por = destino
        conversa.assumida_em = timezone.now()
        _salvar(conversa, 'modo', 'assumida_por', 'assumida_em')
        verbo = 'repassou' if eh_dono else 'atribuiu'
        origem = f' (estava com {_nome(anterior)})' if anterior and not eh_dono else ''
        nota_automatica(conversa, f'{_nome(usuario)} {verbo} a conversa para {_nome(destino)}{origem}.', usuario=usuario)
        avisos.notificar_usuario(destino, f'{_nome(usuario)} passou para você a conversa com {conversa.nome_exibicao}', conversa)
        avisos.emitir(conversa, 'atribuida')
    return conversa


def devolver(conversa: Conversa, usuario=None, automatico: bool = False, pode_gerenciar: bool = False,
             horas: int | None = None) -> Conversa | None:
    """Volta ao automático. No retorno automático a condição é reconferida sob o lock
    (alguém pode ter reaberto a conversa entre a leitura e a escrita); se não vale mais, None."""
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        if automatico and horas is not None and not deve_retornar(conversa, horas):
            return None
        if not automatico:
            dono = conversa.assumida_por
            eh_dono = dono is None or dono == usuario
            if not (eh_dono or pode_gerenciar):
                raise ConflitoCRM(f'A conversa está com {_nome(dono)}. Só o dono ou quem gerencia pode devolver.')
        conversa.modo = Conversa.Modo.AUTOMATICO
        conversa.assumida_por = None
        conversa.assumida_em = None
        conversa.aguardando_desde = None
        _salvar(conversa, 'modo', 'assumida_por', 'assumida_em', 'aguardando_desde')
        if automatico:
            nota_automatica(conversa, 'Conversa resolvida e parada voltou ao atendimento automático.', silenciosa=True)
        avisos.emitir(conversa, 'conversa_atualizada')
    return conversa


# --- trava de resposta ----------------------------------------------------------

def bloqueio_de(conversa: Conversa, usuario) -> dict | None:
    """Por que `usuario` não pode responder agora (None = pode)."""
    dono = conversa.assumida_por
    if conversa.modo == Conversa.Modo.HUMANO and dono and dono != usuario:
        return {'motivo': 'OUTRO_DONO', 'detail': f'A conversa está com {_nome(dono)}. Puxe a conversa para responder.'}
    if not conversa.janela_aberta():
        return {'motivo': 'JANELA_FECHADA',
                'detail': 'Fora da janela de 24 h: envie uma mensagem de abertura para retomar a conversa.'}
    if conversa.modo != Conversa.Modo.HUMANO:
        return {'motivo': 'NAO_ASSUMIDA', 'detail': 'Assuma a conversa antes de responder.'}
    return None


def exigir_resposta_liberada(conversa: Conversa, usuario) -> None:
    bloqueio = bloqueio_de(conversa, usuario)
    if bloqueio:
        raise ConflitoCRM(bloqueio['detail'], bloqueio['motivo'])
