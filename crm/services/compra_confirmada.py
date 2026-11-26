"""Mensagem de "compra confirmada" ao cliente pelo WhatsApp, assim que o vendedor gera a venda.

Usa um template de utilidade aprovado pela Meta (Configuração → Avisos de cobrança →
"Compra confirmada"), com {nome}, {valor} (1ª parcela do crediário) e {vencimento}.
A mensagem entra na conversa do cliente no CRM, como os avisos de cobrança, então a
resposta do cliente cai na caixa de entrada da equipe.

Nunca derruba a geração da venda: sem template aprovado, sem telefone utilizável
ou com a Meta fora do ar, nada é enviado (e fica registrado no log).
"""
import logging

from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, Mensagem
from crm.services import aberturas, avisos, contatos
from crm.services.cobranca import TIPO_CREDFACIL, versao_vigente
from crm.services.conversas import ConflitoCRM, conversa_do_telefone
from crm.services.pagamentos import formatar_reais
from crm.telefone import com_ddi
from crm.whatsapp import obter_provider

logger = logging.getLogger(__name__)

CAMPO_MODELO = 'modelo_compra_confirmada'


def configurada() -> bool:
    """Há template aprovado escolhido para a mensagem de compra confirmada."""
    return versao_vigente(ConfiguracaoCRM.obter(), CAMPO_MODELO) is not None


def agendar(venda) -> bool:
    """Agenda o envio para depois do commit da venda. Devolve se a mensagem vai sair."""
    if not configurada():
        return False
    from crm import tarefas

    tarefas.agendar(enviar, venda.pk)
    return True


def _primeiro_nome(cliente) -> str:
    partes = (cliente.nome or '').split()
    return partes[0].capitalize() if partes else 'cliente'


def _primeira_parcela(venda):
    from vendas.models import Parcela

    return (
        Parcela.objects.filter(pagamento__venda=venda, pagamento__tipo_pagamento__nome__iexact=TIPO_CREDFACIL)
        .order_by('data_vencimento', 'numero_parcela')
        .first()
    )


def _ja_enviada(venda_id: int) -> bool:
    return Mensagem.objects.filter(origem=Mensagem.Origem.COMPRA, dados__compra__venda_id=venda_id).exists()


def enviar(venda_id: int) -> Mensagem | None:
    """Envia o template da compra confirmada (uma vez por venda). None = nada enviado."""
    from vendas.models import Venda

    venda = Venda.objects.select_related('cliente').filter(pk=venda_id, is_deleted=False).first()
    versao = versao_vigente(ConfiguracaoCRM.obter(), CAMPO_MODELO)
    if venda is None or versao is None or _ja_enviada(venda_id):
        return None
    cliente = venda.cliente
    telefone = contatos.para_aviso(cliente)
    parcela = _primeira_parcela(venda)
    if telefone is None or parcela is None:
        logger.info('Compra confirmada da venda %s não enviada: sem telefone utilizável ou sem parcela.', venda_id)
        return None
    try:
        texto, parametros = aberturas.renderizar(versao, {
            'nome': _primeiro_nome(cliente), 'valor': formatar_reais(parcela.valor),
            'vencimento': parcela.data_vencimento.strftime('%d/%m/%Y'),
        })
    except ConflitoCRM:
        logger.warning('Template %s com parâmetro desconhecido; compra confirmada não enviada.', versao.nome_meta)
        return None

    conversa = conversa_do_telefone(com_ddi(telefone.telefone))
    conversa.clientes.add(cliente)
    mensagem = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.AUTOMATICO,
        tipo=Mensagem.Tipo.TEXTO, texto=texto, origem=Mensagem.Origem.COMPRA,
        status=Mensagem.Status.PENDENTE, envio_iniciado_em=timezone.now(), processada=True,
        dados={'compra': {'venda_id': venda_id}, 'pessoal': True,
               'abertura': {'versao': versao.nome_meta, 'valores': parametros}},
    )
    try:
        wamid = obter_provider().enviar_template(conversa.telefone, versao.nome_meta, parametros)
    except Exception:  # noqa: BLE001 — ErroWhatsApp ou rede: a venda já existe, só registra
        logger.warning('Falha ao enviar a compra confirmada da venda %s.', venda_id, exc_info=True)
        Mensagem.objects.filter(pk=mensagem.pk).update(status=Mensagem.Status.ERRO)
        return None
    Mensagem.objects.filter(pk=mensagem.pk).update(status=Mensagem.Status.ENVIADO, wa_message_id=wamid or None)
    Conversa.objects.filter(pk=conversa.pk).update(ultima_mensagem_em=timezone.now())
    avisos.emitir(conversa, 'conversa_atualizada')
    mensagem.refresh_from_db()
    return mensagem
