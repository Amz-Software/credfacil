"""Dados de apresentação do CRM: dicionários prontos para os templates do backoffice."""
from datetime import datetime, timezone as dt_timezone

from django.db.models import Exists, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from crm.models import (
    Conversa, Etiqueta, Mensagem, MensagemProgramada, ModeloAbertura, Nota,
    VersaoAbertura,
)
from crm.services.conversas import bloqueio_de

TAMANHO_PREVIA = 120
EPOCA = datetime(2000, 1, 1, tzinfo=dt_timezone.utc)


def usuario_mini(usuario) -> dict | None:
    if usuario is None:
        return None
    return {'id': usuario.pk, 'nome': usuario.get_full_name() or usuario.username}


def etiqueta_dict(etiqueta: Etiqueta) -> dict:
    return {'id': etiqueta.pk, 'nome': etiqueta.nome, 'cor': etiqueta.cor, 'ordem': etiqueta.ordem,
            'ativo': etiqueta.ativo}


def anotar_lista(queryset):
    """Prévia, motivo de transferência pendente e programadas, por subquery (sem N+1)."""
    ultima = Mensagem.objects.filter(conversa=OuterRef('pk')).exclude(tipo=Mensagem.Tipo.REACAO).order_by('-criado_em', '-id')
    motivo = (Nota.objects
              .filter(conversa=OuterRef('pk'), tipo=Nota.Tipo.TRANSFERENCIA, apagada_em__isnull=True,
                      criado_em__gt=Coalesce(OuterRef('ultima_humana_em'), Value(EPOCA)))
              .order_by('-criado_em', '-id'))
    agendadas = MensagemProgramada.objects.filter(conversa=OuterRef('pk'), status=MensagemProgramada.Status.AGENDADA)
    return (queryset
            .select_related('assumida_por', 'lembrete_para')
            .prefetch_related('etiquetas', 'clientes')
            .annotate(
                _previa_texto=Subquery(ultima.values('texto')[:1]),
                _previa_tipo=Subquery(ultima.values('tipo')[:1]),
                _previa_direcao=Subquery(ultima.values('direcao')[:1]),
                _motivo_texto=Subquery(motivo.values('texto')[:1]),
                _motivo_silenciosa=Subquery(motivo.values('silenciosa')[:1]),
                _motivo_em=Subquery(motivo.values('criado_em')[:1]),
                _tem_programada=Exists(agendadas),
            ))






_PREVIA_POR_TIPO = {
    Mensagem.Tipo.AUDIO: '🎤 Áudio', Mensagem.Tipo.IMAGEM: '📷 Foto', Mensagem.Tipo.VIDEO: '🎥 Vídeo',
    Mensagem.Tipo.DOCUMENTO: '📄 Documento', Mensagem.Tipo.FIGURINHA: 'Figurinha',
    Mensagem.Tipo.LOCALIZACAO: '📍 Localização', Mensagem.Tipo.CONTATO: '👤 Contato',
}


def _previa(conversa) -> str:
    texto = getattr(conversa, '_previa_texto', '') or ''
    tipo = getattr(conversa, '_previa_tipo', '') or ''
    if tipo in _PREVIA_POR_TIPO and not texto:
        texto = _PREVIA_POR_TIPO[tipo]
    elif tipo == Mensagem.Tipo.AUDIO:
        texto = f'🎤 {texto}'
    return texto[:TAMANHO_PREVIA]


def conversa_resumo(conversa: Conversa, agora=None) -> dict:
    agora = agora or timezone.now()
    lembrete = None
    if conversa.lembrete_em:
        lembrete = {'em': conversa.lembrete_em, 'texto': conversa.lembrete_texto,
                    'para': usuario_mini(conversa.lembrete_para), 'vencido': conversa.lembrete_em <= agora}
    motivo = None
    if getattr(conversa, '_motivo_texto', None) and conversa.modo != Conversa.Modo.AUTOMATICO:
        motivo = {'texto': conversa._motivo_texto, 'silenciosa': bool(conversa._motivo_silenciosa),
                  'criado_em': conversa._motivo_em}
    return {
        'id': conversa.pk,
        'telefone': conversa.telefone,
        'contato_nome': conversa.contato_nome,
        'apelido': conversa.apelido,
        'nome_exibicao': conversa.nome_exibicao,
        'clientes': [{'id': c.pk, 'nome': c.nome} for c in conversa.clientes.all()],
        'modo': conversa.modo,
        'modo_display': conversa.get_modo_display(),
        'assumida_por': usuario_mini(conversa.assumida_por),
        'situacao': conversa.situacao,
        'situacao_display': conversa.get_situacao_display(),
        'ultima_mensagem_em': conversa.ultima_mensagem_em,
        'ultima_mensagem_texto': _previa(conversa),
        'ultima_mensagem_direcao': getattr(conversa, '_previa_direcao', None),
        'nao_lidas': conversa.nao_lidas,
        'janela_aberta': conversa.janela_aberta(agora),
        'janela_expira_em': conversa.janela_expira_em(),
        'etiquetas': [etiqueta_dict(e) for e in conversa.etiquetas.all()],
        'lembrete': lembrete,
        'tem_programada': bool(getattr(conversa, '_tem_programada', False)),
        'motivo_transferencia': motivo,
    }


def mensagem_dict(mensagem: Mensagem, reacoes: dict[int, str] | None = None) -> dict:
    midia = getattr(mensagem, 'midia', None) if mensagem.tipo in (
        Mensagem.Tipo.AUDIO, Mensagem.Tipo.IMAGEM, Mensagem.Tipo.VIDEO,
        Mensagem.Tipo.DOCUMENTO, Mensagem.Tipo.FIGURINHA) else None
    dados = mensagem.dados or {}
    responde_a = None
    if mensagem.responde_a_id and mensagem.responde_a:
        alvo = mensagem.responde_a
        responde_a = {'id': alvo.pk, 'tipo': alvo.tipo, 'texto': alvo.texto[:TAMANHO_PREVIA],
                      'autor': alvo.get_autor_display()}
    if mensagem.direcao == Mensagem.Direcao.ENTRADA:
        autor_nome = mensagem.conversa.nome_exibicao
    elif mensagem.usuario_id:
        autor_nome = mensagem.usuario.get_full_name() or mensagem.usuario.username
    else:
        autor_nome = mensagem.get_autor_display()
    return {
        'id': mensagem.pk,
        'direcao': mensagem.direcao,
        'autor': mensagem.autor,
        'autor_nome': autor_nome,
        'tipo': mensagem.tipo,
        'texto': mensagem.texto,
        'status': mensagem.status,
        'erro': mensagem.erro,
        'origem': mensagem.origem,
        'criado_em': mensagem.criado_em,
        'responde_a': responde_a,
        'reacao_cliente': (reacoes or {}).get(mensagem.pk, ''),
        'reacao_equipe': dados.get('reacao_equipe', ''),
        'midia': None if midia is None else {
            'status': midia.status, 'mime': midia.mime, 'nome_original': midia.nome_original,
            'tamanho_bytes': midia.tamanho_bytes, 'duracao_s': midia.duracao_s, 'largura': midia.largura,
            'altura': midia.altura, 'voz': midia.voz, 'tem_miniatura': bool(midia.miniatura),
        },
        'dados': {chave: dados[chave] for chave in ('localizacao', 'contatos', 'encaminhada') if chave in dados},
        'transcricao_status': mensagem.transcricao_status,
        'pode_reenviar': mensagem.direcao == Mensagem.Direcao.SAIDA and mensagem.status == Mensagem.Status.ERRO,
    }


def reacoes_do_cliente(mensagens: list[Mensagem]) -> dict[int, str]:
    """Última reação do cliente em cada mensagem da página."""
    ids = [m.pk for m in mensagens]
    reacoes = {}
    for reacao in (Mensagem.objects.filter(tipo=Mensagem.Tipo.REACAO, direcao=Mensagem.Direcao.ENTRADA,
                                           responde_a_id__in=ids).order_by('criado_em', 'id')):
        reacoes[reacao.responde_a_id] = (reacao.dados.get('reacao') or {}).get('emoji', '')
    return reacoes


def mensagens_dicts(mensagens: list[Mensagem]) -> list[dict]:
    reacoes = reacoes_do_cliente(mensagens)
    return [mensagem_dict(m, reacoes) for m in mensagens]


def nota_dict(nota: Nota, usuario) -> dict:
    return {
        'id': nota.pk, 'texto': nota.texto, 'autor': usuario_mini(nota.usuario), 'automatica': nota.automatica,
        'tipo': nota.tipo, 'silenciosa': nota.silenciosa, 'criado_em': nota.criado_em,
        'pode_apagar': not nota.automatica and nota.usuario_id == usuario.pk,
    }


def programada_dict(programada: MensagemProgramada) -> dict:
    return {'id': programada.pk, 'texto': programada.texto, 'enviar_em': programada.enviar_em,
            'status': programada.status, 'criado_por': usuario_mini(programada.criado_por), 'erro': programada.erro}


LIMITE_MENSAGENS_DETALHE = 50
LIMITE_NOTAS_DETALHE = 100


def base_mensagens(conversa: Conversa):
    return (Mensagem.objects.filter(conversa=conversa).exclude(tipo=Mensagem.Tipo.REACAO)
            .select_related('usuario', 'responde_a', 'midia', 'conversa'))


def conversa_estado(conversa: Conversa, usuario) -> dict:
    """Resumo + trava de resposta (cabeçalho e compositor), sem mensagens nem notas."""
    conversa = anotar_lista(Conversa.objects.filter(pk=conversa.pk)).get()
    bloqueio = bloqueio_de(conversa, usuario)
    return {**conversa_resumo(conversa), 'pode_responder': bloqueio is None, 'bloqueio': bloqueio}


def _mensagens_recentes(conversa: Conversa) -> dict:
    recentes = list(base_mensagens(conversa).order_by('-criado_em', '-id')[:LIMITE_MENSAGENS_DETALHE + 1])
    return {
        'mensagens': mensagens_dicts(list(reversed(recentes[:LIMITE_MENSAGENS_DETALHE]))),
        'tem_mais_antigas': len(recentes) > LIMITE_MENSAGENS_DETALHE,
    }


def _anotacoes(conversa: Conversa, usuario) -> dict:
    notas = (Nota.objects.filter(conversa=conversa, apagada_em__isnull=True)
             .select_related('usuario').order_by('-criado_em', '-id')[:LIMITE_NOTAS_DETALHE])
    programadas = (MensagemProgramada.objects.filter(conversa=conversa, status=MensagemProgramada.Status.AGENDADA)
                   .select_related('criado_por'))
    return {
        'notas': [nota_dict(n, usuario) for n in reversed(list(notas))],
        'programadas': [programada_dict(p) for p in programadas],
    }


def conversa_detalhe(conversa: Conversa, usuario, mensagens: bool = True, anotacoes: bool = True) -> dict:
    """Estado da conversa com as últimas mensagens e/ou notas e programadas (cada trecho pede o que mostra)."""
    detalhe = conversa_estado(conversa, usuario)
    if mensagens:
        detalhe.update(_mensagens_recentes(conversa))
    if anotacoes:
        detalhe.update(_anotacoes(conversa, usuario))
    return detalhe


def versao_dict(versao: VersaoAbertura | None) -> dict | None:
    if versao is None:
        return None
    return {'versao': versao.versao, 'corpo': versao.corpo, 'status': versao.status, 'motivo': versao.motivo,
            'erro': versao.erro, 'nome_meta': versao.nome_meta, 'criado_em': versao.criado_em}


def abertura_dict(modelo: ModeloAbertura) -> dict:
    versoes = sorted(modelo.versoes.all(), key=lambda v: v.versao, reverse=True)
    return {
        'id': modelo.pk, 'chave': modelo.chave, 'titulo': modelo.titulo, 'ordem': modelo.ordem, 'ativo': modelo.ativo,
        'vigente': versao_dict(next((v for v in versoes if v.vigente), None)),
        'em_analise': versao_dict(next((v for v in versoes if v.status in (
            VersaoAbertura.Status.ENVIANDO, VersaoAbertura.Status.EM_ANALISE)), None)),
        'ultima': versao_dict(versoes[0] if versoes else None),
    }
