"""Mensagens de abertura: templates UTILITY criados e versionados pela tela (arquitetura §16)."""
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from crm.models import Conversa, Mensagem, ModeloAbertura, VersaoAbertura
from crm.services import avisos
from crm.services.conversas import ConflitoCRM, assumir, conversa_do_telefone
from crm.telefone import com_ddi
from crm.whatsapp import ErroWhatsApp, obter_provider

logger = logging.getLogger(__name__)

MARCADOR = '{nome}'
EXEMPLO_NOME = 'Ana'
LIMITE_CORPO = 1024
MAX_EMOJIS = 6
MIN_PALAVRAS_POR_MARCADOR = 3
ENVIANDO_ORFA = timedelta(minutes=5)
PREFIXO_NOME = 'abertura_'
STATUS_DA_META = {
    'PENDING': VersaoAbertura.Status.EM_ANALISE,
    'IN_APPEAL': VersaoAbertura.Status.EM_ANALISE,
    'APPROVED': VersaoAbertura.Status.APROVADO,
    'FLAGGED': VersaoAbertura.Status.APROVADO,
    'REJECTED': VersaoAbertura.Status.REJEITADO,
    'PAUSED': VersaoAbertura.Status.PAUSADO,
    'DISABLED': VersaoAbertura.Status.DESATIVADO,
    'DELETED': VersaoAbertura.Status.DESATIVADO,
    'ARCHIVED': VersaoAbertura.Status.DESATIVADO,
    'PENDING_DELETION': VersaoAbertura.Status.DESATIVADO,
}
EM_ANALISE = (VersaoAbertura.Status.ENVIANDO, VersaoAbertura.Status.EM_ANALISE)
DECIDIDOS = (VersaoAbertura.Status.APROVADO, VersaoAbertura.Status.REJEITADO,
             VersaoAbertura.Status.PAUSADO, VersaoAbertura.Status.DESATIVADO)
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿]')


def validar_corpo(corpo: str) -> list[str]:
    """Regras da Meta e da tela; devolve todas as recusas juntas."""
    erros = []
    texto = (corpo or '').strip()
    marcadores = texto.count(MARCADOR)
    sem_marcador = texto.replace(MARCADOR, '')
    if not texto:
        return ['Escreva o texto da mensagem.']
    if marcadores > 1:
        erros.append('Use o marcador {nome} no máximo uma vez.')
    if '{' in sem_marcador or '}' in sem_marcador:
        erros.append('Só o marcador {nome} é aceito; remova as outras chaves.')
    if marcadores and (texto.startswith(MARCADOR) or texto.endswith(MARCADOR)):
        erros.append('A mensagem não pode começar nem terminar com {nome}.')
    if marcadores and len(sem_marcador.split()) < MIN_PALAVRAS_POR_MARCADOR:
        erros.append('Escreva pelo menos 3 palavras além do marcador.')
    if len(texto) > LIMITE_CORPO:
        erros.append(f'O texto passa de {LIMITE_CORPO} caracteres.')
    if len(EMOJI.findall(texto)) > MAX_EMOJIS:
        erros.append(f'Use no máximo {MAX_EMOJIS} emojis.')
    if '\n\n\n' in texto:
        erros.append('Deixe no máximo uma linha em branco seguida.')
    if '\t' in texto or '    ' in texto:
        erros.append('Não use tabulação nem 4 espaços seguidos.')
    return erros


def _nome_meta(modelo: ModeloAbertura, versao: int) -> str:
    base = f'{PREFIXO_NOME}{modelo.chave.replace("-", "_")}' + (f'_v{versao}' if versao > 1 else '')
    nome, sufixo = base[:110], 2
    while VersaoAbertura.objects.filter(nome_meta=nome).exists():
        nome, sufixo = f'{base[:105]}_{sufixo}', sufixo + 1
    return nome


def _chave_unica(titulo: str) -> str:
    base = slugify(titulo)[:36] or 'abertura'
    chave, sufixo = base, 2
    while ModeloAbertura.objects.filter(chave=chave).exists():
        chave, sufixo = f'{base}-{sufixo}', sufixo + 1
    return chave


def _nova_versao(modelo: ModeloAbertura, corpo: str, usuario) -> VersaoAbertura:
    """Cria a versão ENVIANDO (sob lock do modelo). O envio à Meta acontece fora da transação."""
    erros = validar_corpo(corpo)
    if erros:
        raise ConflitoCRM(' '.join(erros))
    corpo = corpo.strip()
    modelo = ModeloAbertura.objects.select_for_update().get(pk=modelo.pk)
    if modelo.versoes.filter(status__in=EM_ANALISE).exists():
        raise ConflitoCRM('Já existe uma versão em análise na Meta. Aguarde a decisão para editar de novo.')
    vigente = modelo.versoes.filter(vigente=True).first()
    if vigente and vigente.corpo == corpo:
        raise ConflitoCRM('Nada mudou no texto.')
    numero = (modelo.versoes.order_by('-versao').values_list('versao', flat=True).first() or 0) + 1
    usa_nome = MARCADOR in corpo
    return VersaoAbertura.objects.create(
        modelo=modelo, versao=numero, nome_meta=_nome_meta(modelo, numero), corpo=corpo,
        corpo_meta=corpo.replace(MARCADOR, '{{1}}'), mapa_parametros=['nome'] if usa_nome else [],
        criado_por=usuario,
    )


def enviar_versao(versao: VersaoAbertura) -> VersaoAbertura:
    exemplos = [EXEMPLO_NOME] if versao.mapa_parametros else []
    try:
        resposta = obter_provider().criar_template(versao.nome_meta, versao.corpo_meta, exemplos)
    except ErroWhatsApp as exc:
        versao.status, versao.erro = VersaoAbertura.Status.ERRO_ENVIO, exc.mensagem
        versao.save(update_fields=['status', 'erro'])
        return versao
    versao.meta_template_id = resposta.get('id', '')
    versao.enviado_em = timezone.now()
    versao.save(update_fields=['meta_template_id', 'enviado_em'])
    return aplicar_status_meta(versao, resposta.get('status', 'PENDING'), resposta.get('categoria', ''))


def criar_modelo(titulo: str, corpo: str, usuario) -> ModeloAbertura:
    titulo = (titulo or '').strip()
    if not 3 <= len(titulo) <= 60:
        raise ConflitoCRM('O título precisa ter de 3 a 60 caracteres.')
    if ModeloAbertura.objects.filter(titulo__iexact=titulo, ativo=True).exists():
        raise ConflitoCRM('Já existe uma mensagem de abertura ativa com esse título.')
    with transaction.atomic():
        modelo = ModeloAbertura.objects.create(chave=_chave_unica(titulo), titulo=titulo, criado_por=usuario)
        versao = _nova_versao(modelo, corpo, usuario)
    enviar_versao(versao)
    return modelo


def editar_modelo(modelo: ModeloAbertura, dados: dict, usuario) -> ModeloAbertura:
    campos = []
    for campo in ('titulo', 'ordem', 'ativo'):
        if campo in dados:
            setattr(modelo, campo, dados[campo])
            campos.append(campo)
    if campos:
        modelo.save(update_fields=campos)
    if 'corpo' in dados:
        with transaction.atomic():
            versao = _nova_versao(modelo, dados['corpo'], usuario)
        enviar_versao(versao)
    return modelo


def aplicar_status_meta(versao: VersaoAbertura, status_meta: str, categoria: str = '', motivo: str = '') -> VersaoAbertura:
    novo = STATUS_DA_META.get((status_meta or '').upper())
    if novo is None:
        return versao
    with transaction.atomic():
        versao = VersaoAbertura.objects.select_for_update().get(pk=versao.pk)
        if versao.status in DECIDIDOS and novo == VersaoAbertura.Status.EM_ANALISE:
            return versao  # decidida nunca volta para análise
        if versao.status == novo and not categoria:
            return versao
        versao.status = novo
        versao.categoria_meta = categoria or versao.categoria_meta
        if novo == VersaoAbertura.Status.REJEITADO:
            versao.motivo = motivo or versao.motivo
        if novo in DECIDIDOS and versao.decidido_em is None:
            versao.decidido_em = timezone.now()
        versao.save(update_fields=['status', 'categoria_meta', 'motivo', 'decidido_em'])
        _promover(versao)
    return versao


def _promover(versao: VersaoAbertura) -> None:
    """Aprovada e mais nova que a vigente vira vigente; até lá a anterior continua valendo."""
    modelo = versao.modelo
    vigente = modelo.versoes.filter(vigente=True).first()
    if versao.status == VersaoAbertura.Status.APROVADO and (vigente is None or vigente.versao < versao.versao):
        modelo.versoes.filter(vigente=True).update(vigente=False)
        VersaoAbertura.objects.filter(pk=versao.pk).update(vigente=True)
    elif versao.vigente and versao.status in (VersaoAbertura.Status.PAUSADO, VersaoAbertura.Status.DESATIVADO):
        logger.warning('Abertura vigente %s ficou %s na Meta.', versao.nome_meta, versao.status)


def sincronizar(versao: VersaoAbertura) -> VersaoAbertura:
    """Consulta a Meta. ENVIANDO há mais de 5 min que a Meta não conhece → ERRO_ENVIO."""
    try:
        info = obter_provider().consultar_template(versao.nome_meta)
    except ErroWhatsApp as exc:
        logger.warning('Falha ao consultar a abertura %s: %s', versao.nome_meta, exc.mensagem)
        return versao
    if info:
        if info.get('id') and not versao.meta_template_id:
            VersaoAbertura.objects.filter(pk=versao.pk).update(meta_template_id=info['id'])
        return aplicar_status_meta(versao, info.get('status', ''), info.get('categoria', ''), info.get('motivo', ''))
    orfa = versao.status == VersaoAbertura.Status.ENVIANDO and timezone.now() - versao.criado_em > ENVIANDO_ORFA
    if orfa:
        versao.status, versao.erro = VersaoAbertura.Status.ERRO_ENVIO, 'A Meta não recebeu esta versão.'
        versao.save(update_fields=['status', 'erro'])
    return versao


def sincronizar_pendentes() -> int:
    versoes = VersaoAbertura.objects.filter(status__in=EM_ANALISE + (VersaoAbertura.Status.APROVADO,))
    for versao in versoes:
        sincronizar(versao)
    return versoes.count()


def simular_decisao(modelo: ModeloAbertura, status: str) -> ModeloAbertura:
    if not getattr(obter_provider(), 'simulado', False):
        raise ConflitoCRM('A simulação só existe com o WhatsApp simulado.')
    versao = modelo.versoes.filter(status__in=EM_ANALISE).order_by('-versao').first()
    if versao is None:
        raise ConflitoCRM('Não há versão em análise para simular.')
    meta = {'APROVADO': 'APPROVED', 'REJEITADO': 'REJECTED'}.get(status)
    if meta is None:
        raise ConflitoCRM('Status de simulação inválido.')
    aplicar_status_meta(versao, meta, 'UTILITY', 'Rejeição simulada.' if meta == 'REJECTED' else '')
    return modelo


# --- envio ao cliente ----------------------------------------------------------------

def disponiveis() -> list[dict]:
    resultado = []
    for modelo in ModeloAbertura.objects.filter(ativo=True).prefetch_related('versoes'):
        vigente = next((v for v in modelo.versoes.all() if v.vigente), None)
        ultima = max(modelo.versoes.all(), key=lambda v: v.versao, default=None)
        exibida = vigente or ultima
        resultado.append({
            'chave': modelo.chave, 'titulo': modelo.titulo,
            'texto': exibida.corpo if exibida else '',
            'usa_nome': bool(exibida and exibida.mapa_parametros),
            'disponivel': bool(vigente and vigente.status == VersaoAbertura.Status.APROVADO),
        })
    return resultado


def _versao_para_envio(chave: str) -> VersaoAbertura:
    modelo = ModeloAbertura.objects.filter(chave=chave, ativo=True).first()
    if modelo is None:
        raise ConflitoCRM('Mensagem de abertura não encontrada.')
    vigente = modelo.versoes.filter(vigente=True, status=VersaoAbertura.Status.APROVADO).first()
    if vigente is None:
        raise ConflitoCRM('Esta mensagem de abertura ainda não foi aprovada pela Meta.')
    return vigente


def enviar_abertura(conversa: Conversa, usuario, chave: str, nome: str = '') -> Conversa:
    """Com a janela aberta só assume; fora dela envia o template e assume."""
    conversa = assumir(conversa, usuario)
    if conversa.janela_aberta():
        return conversa
    versao = _versao_para_envio(chave)
    nome = (nome or conversa.primeiro_nome).strip()
    if versao.mapa_parametros and not nome:
        raise ConflitoCRM('Informe o nome do cliente para esta mensagem.')
    parametros = [nome.split()[0]] if versao.mapa_parametros else []
    texto = versao.corpo.replace(MARCADOR, parametros[0] if parametros else '')
    mensagem = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.HUMANO,
        tipo=Mensagem.Tipo.TEXTO, texto=texto, origem=Mensagem.Origem.ABERTURA, usuario=usuario,
        status=Mensagem.Status.PENDENTE, envio_iniciado_em=timezone.now(), processada=True,
        dados={'abertura': {'versao': versao.nome_meta, 'valores': parametros}},
    )
    try:
        wamid = obter_provider().enviar_template(conversa.telefone, versao.nome_meta, parametros)
        mensagem.status, mensagem.wa_message_id = Mensagem.Status.ENVIADO, wamid or None
    except ErroWhatsApp as exc:
        mensagem.status, mensagem.erro = Mensagem.Status.ERRO, exc.mensagem
    mensagem.save(update_fields=['status', 'wa_message_id', 'erro'])
    agora = timezone.now()
    campos = {'ultima_mensagem_em': agora}
    if mensagem.status != Mensagem.Status.ERRO:
        campos.update(ultima_humana_em=agora, situacao=Conversa.Situacao.PENDENTE, situacao_em=agora)
    Conversa.objects.filter(pk=conversa.pk).update(**campos)
    conversa.refresh_from_db()
    if mensagem.status == Mensagem.Status.ERRO:
        raise ConflitoCRM(f'A Meta recusou a mensagem de abertura: {mensagem.erro}')
    avisos.emitir(conversa, 'conversa_atualizada')
    return conversa


def iniciar_conversa(telefone: str, usuario, chave: str, nome: str = '') -> Conversa:
    digitos = com_ddi(telefone)
    if len(digitos) < 12:
        raise ConflitoCRM('Informe o telefone com DDD.')
    conversa = conversa_do_telefone(digitos)
    if nome and not conversa.contato_nome:
        Conversa.objects.filter(pk=conversa.pk).update(contato_nome=nome.strip()[:150])
        conversa.refresh_from_db()
    return enviar_abertura(conversa, usuario, chave, nome)
