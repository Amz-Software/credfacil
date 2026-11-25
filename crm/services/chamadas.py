"""Ligações de voz pelo WhatsApp: recebidas (toca para a equipe) e feitas pela equipe.

Recebida: webhook `connect` traz a oferta SDP → Chamada TOCANDO → evento "chamada_tocando"
para todos do CRM → quem atende manda a resposta SDP do navegador (`atender`), a primeira
vence (trava no banco) → `terminate` do webhook fecha com a duração.
Feita: o navegador manda a oferta (`ligar`), a Meta liga para o cliente e devolve a
resposta SDP pelo webhook `connect`; status RINGING/ACCEPTED/REJECTED; `terminate` fecha.
A Meta só deixa ligar para quem deu permissão (pedido pelo próprio WhatsApp).
"""
import logging
from datetime import datetime, timedelta, timezone as tz

from django.db import transaction
from django.utils import timezone

from crm.models import Chamada, Conversa, Mensagem, TentativaContato
from crm.services import avisos
from crm.services.conversas import ConflitoCRM, conversa_do_telefone
from crm.telefone import mesmo_telefone
from crm.whatsapp import ErroWhatsApp
from crm.whatsapp_chamadas import obter_chamadas

logger = logging.getLogger(__name__)

Status = Chamada.Status
TOQUE_MAXIMO = timedelta(seconds=60)          # a Meta dá de 30 a 60 s para atender
CHAMADA_ESQUECIDA = timedelta(hours=2)        # em andamento sem terminate: fecha na rotina
MAX_SDP = 20000
CODIGO_SEM_PERMISSAO = 138006
SEM_PERMISSAO = 'SEM_PERMISSAO'
ROTULO_FIM = {
    Status.ENCERRADA: 'Ligação {direcao} · {duracao}',
    Status.PERDIDA: 'Ligação {direcao} não atendida',
    Status.RECUSADA: 'Ligação {direcao} recusada',
    Status.FALHOU: 'Ligação {direcao} falhou',
}


def _evento(chamada: Chamada, tipo: str) -> None:
    avisos.emitir(chamada.conversa, tipo, chamada_id=chamada.pk, chamada_status=chamada.status)


def _sdp(valor) -> str:
    sdp = str(valor or '').strip()
    if not sdp.startswith('v=0') or len(sdp) > MAX_SDP:
        raise ConflitoCRM('Não foi possível preparar o áudio da ligação. Recarregue a página e tente de novo.')
    return sdp


def _quando(valor) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(valor), tz=tz.utc)
    except (TypeError, ValueError):
        return None


def _formatar_duracao(segundos: int | None) -> str:
    minutos, resto = divmod(int(segundos or 0), 60)
    return f'{minutos} min {resto:02d} s' if minutos else f'{resto} s'


# --- webhook ---------------------------------------------------------------------------------------

def receber_conexao(dados: dict, phone_number_id: str) -> Chamada | None:
    call_id = dados.get('id', '')
    sessao = dados.get('session') or {}
    if not call_id:
        return None
    if dados.get('direction') == 'BUSINESS_INITIATED':
        chamada = Chamada.objects.filter(wa_call_id=call_id).first()
        if chamada is not None and sessao.get('sdp'):
            Chamada.objects.filter(pk=chamada.pk).update(sdp_resposta=str(sessao['sdp'])[:MAX_SDP])
            chamada.refresh_from_db()
            _evento(chamada, 'chamada_atualizada')
        return chamada
    conversa = conversa_do_telefone(dados.get('from', ''))
    chamada, criada = Chamada.objects.get_or_create(wa_call_id=call_id, defaults={
        'conversa': conversa, 'phone_number_id': phone_number_id, 'direcao': Chamada.Direcao.ENTRADA,
        'status': Status.TOCANDO, 'sdp_oferta': str(sessao.get('sdp') or '')[:MAX_SDP],
    })
    if criada:
        _evento(chamada, 'chamada_tocando')
    return chamada


def aplicar_status(dados: dict) -> None:
    """Status de ligação feita pela equipe: RINGING, ACCEPTED, REJECTED."""
    chamada = Chamada.objects.filter(wa_call_id=dados.get('id', '')).first()
    status = str(dados.get('status', '')).upper()
    if chamada is None or not chamada.ativa:
        return
    if status == 'ACCEPTED':
        Chamada.objects.filter(pk=chamada.pk).update(status=Status.EM_ANDAMENTO, atendida_em=timezone.now())
    elif status == 'REJECTED':
        Chamada.objects.filter(pk=chamada.pk).update(status=Status.RECUSADA, encerrada_em=timezone.now())
    else:
        return
    chamada.refresh_from_db()
    _evento(chamada, 'chamada_atualizada')
    if not chamada.ativa:
        _registrar_fim(chamada)


def _status_final(chamada: Chamada, dados: dict) -> str:
    if str(dados.get('status', '')).upper() == 'FAILED':
        return Status.FALHOU
    if dados.get('duration') or chamada.status in (Status.EM_ANDAMENTO, Status.ENCERRADA):
        return Status.ENCERRADA
    return Status.RECUSADA if chamada.status == Status.RECUSADA else Status.PERDIDA


def encerrar_pelo_webhook(dados: dict) -> None:
    chamada = Chamada.objects.filter(wa_call_id=dados.get('id', '')).first()
    if chamada is None or chamada.mensagem_id:
        return
    duracao = dados.get('duration')
    erros = '; '.join(str((e or {}).get('message') or (e or {}).get('title') or '') for e in dados.get('errors') or [])
    Chamada.objects.filter(pk=chamada.pk).update(
        status=_status_final(chamada, dados), duracao_s=int(duracao) if duracao else None, erro=erros[:500],
        atendida_em=chamada.atendida_em or _quando(dados.get('start_time')),
        encerrada_em=_quando(dados.get('end_time')) or timezone.now())
    chamada.refresh_from_db()
    _registrar_fim(chamada)
    _evento(chamada, 'chamada_atualizada')


def _registrar_fim(chamada: Chamada) -> None:
    """Uma linha na conversa e, na ligação feita, a tentativa de contato do cliente."""
    if chamada.mensagem_id:
        return
    direcao = 'recebida' if chamada.direcao == Chamada.Direcao.ENTRADA else 'feita'
    texto = ROTULO_FIM.get(chamada.status, 'Ligação {direcao}').format(
        direcao=direcao, duracao=_formatar_duracao(chamada.duracao_s))
    if chamada.usuario_id and chamada.status == Status.ENCERRADA:
        texto += f' · {chamada.usuario.get_full_name() or chamada.usuario.get_username()}'
    entrada = chamada.direcao == Chamada.Direcao.ENTRADA
    mensagem = Mensagem.objects.create(
        conversa=chamada.conversa, direcao=Mensagem.Direcao.ENTRADA if entrada else Mensagem.Direcao.SAIDA,
        autor=Mensagem.Autor.SISTEMA, tipo=Mensagem.Tipo.CHAMADA, texto=texto, processada=True,
        status=Mensagem.Status.RECEBIDO, dados={'chamada_id': chamada.pk, 'status': chamada.status})
    Chamada.objects.filter(pk=chamada.pk).update(mensagem=mensagem)
    chamada.mensagem = mensagem
    if not entrada:
        _registrar_tentativa(chamada)


def _registrar_tentativa(chamada: Chamada) -> None:
    resultado = (TentativaContato.Resultado.RESPONDEU if chamada.status == Status.ENCERRADA
                 else TentativaContato.Resultado.NAO_ATENDEU)
    for cliente in chamada.conversa.clientes.all():
        telefone = next((t for t in cliente.telefones_crm.all()
                         if mesmo_telefone(t.telefone, chamada.conversa.telefone)), None)
        TentativaContato.objects.create(
            cliente=cliente, telefone=telefone, numero=chamada.conversa.telefone,
            canal=TentativaContato.Canal.LIGACAO, resultado=resultado, usuario=chamada.usuario,
            observacao='Ligação pelo WhatsApp pelo CRM.')


# --- ações da equipe -------------------------------------------------------------------------------

def atender(chamada: Chamada, usuario, sdp: str) -> Chamada:
    """A primeira pessoa que atende fica com a ligação; as outras recebem aviso de que já foi atendida."""
    resposta = _sdp(sdp)
    with transaction.atomic():
        travada = Chamada.objects.select_for_update().get(pk=chamada.pk)
        if travada.status != Status.TOCANDO:
            raise ConflitoCRM('Essa ligação já foi atendida ou terminou.', 'JA_ATENDIDA')
        if timezone.now() - travada.iniciada_em > TOQUE_MAXIMO:
            raise ConflitoCRM('A ligação já parou de tocar.', 'EXPIRADA')
        travada.status, travada.usuario, travada.atendida_em = Status.EM_ANDAMENTO, usuario, timezone.now()
        travada.save(update_fields=['status', 'usuario', 'atendida_em'])
    try:
        obter_chamadas().aceitar(travada.wa_call_id, resposta)
    except ErroWhatsApp as erro:
        Chamada.objects.filter(pk=travada.pk).update(status=Status.FALHOU, erro=erro.mensagem[:500],
                                                     encerrada_em=timezone.now())
        travada.refresh_from_db()
        _registrar_fim(travada)
        _evento(travada, 'chamada_atualizada')
        raise ConflitoCRM(f'A Meta não aceitou atender: {erro.mensagem}') from erro
    _assumir_se_livre(travada.conversa, usuario)
    _evento(travada, 'chamada_atualizada')
    return travada


def _assumir_se_livre(conversa: Conversa, usuario) -> None:
    """Quem atende a ligação fica com a conversa, se ninguém estiver com ela."""
    from crm.services.conversas import assumir

    conversa.refresh_from_db()
    if conversa.modo == Conversa.Modo.HUMANO and conversa.assumida_por_id:
        return
    try:
        assumir(conversa, usuario)
    except ConflitoCRM:
        logger.info('Ligação atendida sem assumir a conversa %s.', conversa.pk)


def encerrar(chamada: Chamada, usuario) -> Chamada:
    if not chamada.ativa:
        return chamada
    if chamada.usuario_id and chamada.usuario_id != usuario.pk and chamada.status == Status.EM_ANDAMENTO:
        raise ConflitoCRM('Só quem está na ligação pode desligar.')
    try:
        obter_chamadas().encerrar(chamada.wa_call_id)
    except ErroWhatsApp as erro:
        logger.warning('Meta recusou encerrar a ligação %s: %s', chamada.pk, erro.mensagem)
    novo = Status.ENCERRADA if chamada.status == Status.EM_ANDAMENTO else Status.PERDIDA
    Chamada.objects.filter(pk=chamada.pk).update(status=novo, encerrada_em=timezone.now())
    chamada.refresh_from_db()
    _evento(chamada, 'chamada_atualizada')  # o terminate do webhook completa a duração e o registro
    return chamada


def _exigir_dono(conversa: Conversa, usuario) -> None:
    if conversa.modo != Conversa.Modo.HUMANO or conversa.assumida_por_id != usuario.pk:
        raise ConflitoCRM('Assuma a conversa antes de ligar.', 'NAO_ASSUMIDA')


def ligar(conversa: Conversa, usuario, sdp: str) -> Chamada:
    oferta = _sdp(sdp)
    _exigir_dono(conversa, usuario)
    if conversa.chamadas.filter(status__in=Chamada.ATIVAS).exists():
        raise ConflitoCRM('Já existe uma ligação em andamento com este cliente.')
    cliente = obter_chamadas()
    try:
        if cliente.permissao(conversa.telefone) == 'no_permission':
            raise ConflitoCRM('O cliente ainda não autorizou receber ligações. Peça a permissão pelo WhatsApp.',
                              SEM_PERMISSAO)
        call_id = cliente.ligar(conversa.telefone, oferta, referencia=f'conversa:{conversa.pk}')
    except ErroWhatsApp as erro:
        motivo = SEM_PERMISSAO if erro.codigo == CODIGO_SEM_PERMISSAO else ''
        raise ConflitoCRM(f'Não foi possível ligar: {erro.mensagem}', motivo) from erro
    chamada = Chamada.objects.create(
        conversa=conversa, wa_call_id=call_id or None, phone_number_id=cliente.phone_number_id,
        direcao=Chamada.Direcao.SAIDA, status=Status.CHAMANDO, usuario=usuario)
    _evento(chamada, 'chamada_atualizada')
    return chamada


def pedir_permissao(conversa: Conversa, usuario) -> Mensagem:
    _exigir_dono(conversa, usuario)
    if not conversa.janela_aberta():
        raise ConflitoCRM('A janela de 24 h está fechada: mande uma mensagem de abertura e, quando o cliente '
                          'responder, peça a permissão.', 'JANELA_FECHADA')
    try:
        wamid = obter_chamadas().pedir_permissao(conversa.telefone)
    except ErroWhatsApp as erro:
        raise ConflitoCRM(f'A Meta não enviou o pedido: {erro.mensagem}') from erro
    mensagem = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.HUMANO, usuario=usuario,
        tipo=Mensagem.Tipo.TEXTO, texto='📞 Pedido de permissão para ligar pelo WhatsApp', processada=True,
        status=Mensagem.Status.ENVIADO, wa_message_id=wamid or None, dados={'pedido_ligacao': True})
    avisos.emitir(conversa, 'conversa_atualizada')
    return mensagem


# --- rotina ----------------------------------------------------------------------------------------

def fechar_esquecidas() -> int:
    """Webhook perdido: toque que passou do tempo vira não atendida; em andamento antiga fecha."""
    agora = timezone.now()
    tocando = Chamada.objects.filter(status__in=(Status.TOCANDO, Status.CHAMANDO),
                                     iniciada_em__lt=agora - 2 * TOQUE_MAXIMO)
    andando = Chamada.objects.filter(status=Status.EM_ANDAMENTO, iniciada_em__lt=agora - CHAMADA_ESQUECIDA)
    total = 0
    for chamada in (tocando | andando).select_related('conversa'):
        novo = Status.ENCERRADA if chamada.status == Status.EM_ANDAMENTO else Status.PERDIDA
        Chamada.objects.filter(pk=chamada.pk).update(status=novo, encerrada_em=agora)
        chamada.refresh_from_db()
        _registrar_fim(chamada)
        _evento(chamada, 'chamada_atualizada')
        total += 1
    return total
