"""Saídas: texto (síncrono), mídia (fila), reenvio, reação, digitando, leitura e status."""
import logging
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from crm import tarefas
from crm.erros_meta import traduzir_erro
from crm.models import LIMITE_TEXTO, Conversa, Mensagem, Midia
from crm.services import avisos
from crm.services.conversas import ConflitoCRM, exigir_resposta_liberada, mudar_situacao
from crm.whatsapp import ErroWhatsApp, obter_provider

logger = logging.getLogger(__name__)

LIMITE_LEGENDA = 1024
LIMITE_REACAO = timedelta(days=30)
TIPO_META = {
    Mensagem.Tipo.IMAGEM: 'image',
    Mensagem.Tipo.VIDEO: 'video',
    Mensagem.Tipo.AUDIO: 'audio',
    Mensagem.Tipo.DOCUMENTO: 'document',
    Mensagem.Tipo.FIGURINHA: 'sticker',
}
ORDEM_STATUS = {
    Mensagem.Status.PENDENTE: 0,
    Mensagem.Status.ENVIADO: 1,
    Mensagem.Status.ENTREGUE: 2,
    Mensagem.Status.LIDO: 3,
}
STATUS_META = {
    'sent': Mensagem.Status.ENVIADO,
    'delivered': Mensagem.Status.ENTREGUE,
    'read': Mensagem.Status.LIDO,
    'failed': Mensagem.Status.ERRO,
}


def _resposta_valida(conversa: Conversa, responde_a_id) -> Mensagem | None:
    if not responde_a_id:
        return None
    alvo = Mensagem.objects.filter(pk=responde_a_id, conversa=conversa).first()
    if alvo is None or not alvo.wa_message_id:
        raise ConflitoCRM('Não é possível responder a essa mensagem.')
    return alvo


def _apos_envio(conversa: Conversa, mensagem: Mensagem) -> None:
    agora = timezone.now()
    campos = {'ultima_mensagem_em': agora}
    sucesso = mensagem.status != Mensagem.Status.ERRO
    if mensagem.autor == Mensagem.Autor.HUMANO and sucesso:
        campos['ultima_humana_em'] = agora
    Conversa.objects.filter(pk=conversa.pk).update(**campos)
    conversa.refresh_from_db()
    if mensagem.autor == Mensagem.Autor.HUMANO and sucesso:
        mudar_situacao(conversa, Conversa.Situacao.PENDENTE)
    avisos.emitir(conversa, 'conversa_atualizada')


def _despachar_texto(mensagem: Mensagem) -> None:
    alvo = mensagem.responde_a.wa_message_id if mensagem.responde_a_id else ''
    try:
        wamid = obter_provider().enviar_texto(mensagem.conversa.telefone, mensagem.texto, alvo)
        mensagem.status, mensagem.wa_message_id, mensagem.erro = Mensagem.Status.ENVIADO, wamid or None, ''
    except ErroWhatsApp as exc:
        mensagem.status, mensagem.erro = Mensagem.Status.ERRO, exc.mensagem
    mensagem.save(update_fields=['status', 'wa_message_id', 'erro'])


def enviar_texto(conversa: Conversa, texto: str, usuario=None, autor: str = Mensagem.Autor.HUMANO,
                 origem: str = '', responde_a_id=None, exigir_trava: bool = True) -> Mensagem:
    texto = (texto or '').strip()
    if not texto:
        raise ConflitoCRM('Escreva a mensagem antes de enviar.')
    if len(texto) > LIMITE_TEXTO:
        raise ConflitoCRM(f'A mensagem passa de {LIMITE_TEXTO} caracteres.')
    if exigir_trava:
        exigir_resposta_liberada(conversa, usuario)
    responde_a = _resposta_valida(conversa, responde_a_id)
    mensagem = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=autor, tipo=Mensagem.Tipo.TEXTO,
        texto=texto, responde_a=responde_a, origem=origem, usuario=usuario,
        status=Mensagem.Status.PENDENTE, envio_iniciado_em=timezone.now(), processada=True,
    )
    _despachar_texto(mensagem)
    _apos_envio(conversa, mensagem)
    return mensagem


def preparar_envio_midia(conversa: Conversa, usuario, arquivo, legenda: str = '', voz: bool = False,
                         responde_a_id=None) -> Mensagem:
    """Valida e grava como PENDENTE; o envio à Meta roda em segundo plano."""
    from crm.services import midias

    exigir_resposta_liberada(conversa, usuario)
    responde_a = _resposta_valida(conversa, responde_a_id)
    conteudo = arquivo.read()
    tipo, mime = midias.validar_anexo(conteudo, arquivo.name)
    legenda = (legenda or '').strip()
    if tipo == Mensagem.Tipo.AUDIO and legenda:
        raise ConflitoCRM('Áudio não aceita legenda.')
    if len(legenda) > LIMITE_LEGENDA:
        raise ConflitoCRM(f'A legenda passa de {LIMITE_LEGENDA} caracteres.')
    if voz and tipo != Mensagem.Tipo.AUDIO:
        raise ConflitoCRM('Só áudio pode ser enviado como mensagem de voz.')

    with transaction.atomic():
        mensagem = Mensagem.objects.create(
            conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.HUMANO, tipo=tipo,
            texto=legenda, responde_a=responde_a, usuario=usuario, status=Mensagem.Status.PENDENTE,
            envio_iniciado_em=timezone.now(), processada=True,
        )
        Midia.objects.create(
            mensagem=mensagem, arquivo=ContentFile(conteudo, name=arquivo.name), mime=mime,
            nome_original=(arquivo.name or '')[:255], tamanho_bytes=len(conteudo), voz=voz,
            status=Midia.Status.OK, baixado_em=timezone.now(),
        )
        Conversa.objects.filter(pk=conversa.pk).update(ultima_mensagem_em=timezone.now())
        tarefas.agendar(processar_envio_midia, mensagem.pk)
        avisos.emitir(conversa, 'conversa_atualizada')
    return mensagem


def processar_envio_midia(mensagem_id: int) -> None:
    from crm.services import midias

    mensagem = Mensagem.objects.select_related('conversa', 'midia', 'responde_a').get(pk=mensagem_id)
    if mensagem.status != Mensagem.Status.PENDENTE:
        return
    midia = mensagem.midia
    try:
        conteudo, mime, nome = midias.preparar_para_meta(midia)
        provider = obter_provider()
        media_id = provider.subir_midia(conteudo, mime, nome)
        alvo = mensagem.responde_a.wa_message_id if mensagem.responde_a_id else ''
        wamid = provider.enviar_midia(
            mensagem.conversa.telefone, TIPO_META[mensagem.tipo], media_id, legenda=mensagem.texto,
            nome_arquivo=midia.nome_original, voz=midia.voz, responde_a=alvo,
        )
        midia.wa_media_id = media_id
        midia.save(update_fields=['wa_media_id'])
        mensagem.status, mensagem.wa_message_id, mensagem.erro = Mensagem.Status.ENVIADO, wamid or None, ''
    except (ErroWhatsApp, midias.ErroMidia) as exc:
        mensagem.status, mensagem.erro = Mensagem.Status.ERRO, str(exc)
    except Exception:  # noqa: BLE001 — nunca deixa o envio preso em PENDENTE
        logger.exception('Falha inesperada ao enviar a mídia da mensagem %s.', mensagem.pk)
        mensagem.status, mensagem.erro = Mensagem.Status.ERRO, 'Não foi possível enviar o arquivo. Reenvie.'
    mensagem.save(update_fields=['status', 'wa_message_id', 'erro'])
    _apos_envio(mensagem.conversa, mensagem)


def reenviar(mensagem: Mensagem, usuario) -> Mensagem:
    if mensagem.direcao != Mensagem.Direcao.SAIDA or mensagem.status != Mensagem.Status.ERRO:
        raise ConflitoCRM('Só mensagens enviadas com erro podem ser reenviadas.')
    if mensagem.origem == Mensagem.Origem.ABERTURA:
        from crm.services.aberturas import reenviar_abertura
        return reenviar_abertura(mensagem, usuario)
    exigir_resposta_liberada(mensagem.conversa, usuario)
    mensagem.status, mensagem.erro, mensagem.envio_iniciado_em = Mensagem.Status.PENDENTE, '', timezone.now()
    mensagem.save(update_fields=['status', 'erro', 'envio_iniciado_em'])
    if mensagem.tipo == Mensagem.Tipo.TEXTO:
        _despachar_texto(mensagem)
        _apos_envio(mensagem.conversa, mensagem)
    else:
        tarefas.agendar(processar_envio_midia, mensagem.pk)
    return mensagem


def reagir(mensagem: Mensagem, usuario, emoji: str) -> Mensagem:
    conversa = mensagem.conversa
    exigir_resposta_liberada(conversa, usuario)
    if not mensagem.wa_message_id or timezone.now() - mensagem.criado_em > LIMITE_REACAO:
        raise ConflitoCRM('Só é possível reagir a mensagens dos últimos 30 dias.')
    try:
        obter_provider().reagir(conversa.telefone, mensagem.wa_message_id, emoji or '')
    except ErroWhatsApp as exc:
        raise ConflitoCRM(exc.mensagem) from exc
    mensagem.dados = {**(mensagem.dados or {}), 'reacao_equipe': emoji or ''}
    mensagem.save(update_fields=['dados'])
    avisos.emitir(conversa, 'conversa_atualizada')
    return mensagem


def _ultima_entrada_com_id(conversa: Conversa) -> Mensagem | None:
    return (Mensagem.objects
            .filter(conversa=conversa, direcao=Mensagem.Direcao.ENTRADA, wa_message_id__isnull=False)
            .exclude(tipo=Mensagem.Tipo.REACAO).order_by('-criado_em', '-id').first())


def digitando(conversa: Conversa, usuario) -> None:
    from crm.services.conversas import bloqueio_de

    if bloqueio_de(conversa, usuario):
        return
    ultima = _ultima_entrada_com_id(conversa)
    if ultima is None:
        return
    try:
        obter_provider().marcar_lida(ultima.wa_message_id, digitando=True)
    except ErroWhatsApp:
        logger.info('Indicador de digitação recusado pela Meta (ignorado).')


def enviar_recibo_leitura(conversa_id: int) -> None:
    """Tiques azuis: só a última recebida vai à Meta; as anteriores ficam lidas juntas."""
    conversa = Conversa.objects.get(pk=conversa_id)
    nao_lidas = Mensagem.objects.filter(conversa=conversa, direcao=Mensagem.Direcao.ENTRADA, lida_em__isnull=True)
    ultima = _ultima_entrada_com_id(conversa)
    if ultima is None or not nao_lidas.exists():
        return
    try:
        obter_provider().marcar_lida(ultima.wa_message_id)
    except ErroWhatsApp:
        logger.info('Recibo de leitura recusado pela Meta (ignorado).')
        return
    nao_lidas.update(lida_em=timezone.now())


def aplicar_status(wa_message_id: str, status_meta: str, erros: list | None = None) -> bool:
    """Status do webhook: só avança (ENVIADO → ENTREGUE → LIDO); ERRO é terminal."""
    novo = STATUS_META.get(status_meta)
    if not wa_message_id or novo is None:
        return False
    with transaction.atomic():
        mensagem = Mensagem.objects.select_for_update().filter(wa_message_id=wa_message_id).first()
        if mensagem is None:
            return False
        atual = mensagem.status
        if atual == Mensagem.Status.ERRO:
            return True
        if novo == Mensagem.Status.ERRO:
            erro = (erros or [{}])[0]
            mensagem.status = novo
            mensagem.erro = traduzir_erro(erro.get('code'), erro.get('title', ''),
                                          (erro.get('error_data') or {}).get('details', '') or erro.get('message', ''))
        elif ORDEM_STATUS.get(novo, 0) > ORDEM_STATUS.get(atual, 0):
            mensagem.status = novo
        else:
            return True
        mensagem.save(update_fields=['status', 'erro'])
        avisos.emitir(mensagem.conversa, 'mensagem_status')
    return True
