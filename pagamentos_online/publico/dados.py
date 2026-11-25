"""Dados do app do cliente (área pública): só o necessário, acessado pelo token aleatório do pagamento."""
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from vendas.models import Loja, Pagamento, Parcela
from vendas.services.erros import ErroDeNegocio
from vendas.services.pix import payload_pix, qr_code_base64

from ..models import Cobranca, ConfiguracaoPagamentoOnline
from ..servicos.cobrancas import disponivel, opcoes_da_parcela, opcoes_para_valor
from ..servicos.planos import Plano, plano_de_quitacao

NOME_PIX = 'credfacil'
CIDADE_PIX = 'Belem'


def _dinheiro(valor) -> str:
    return f'{Decimal(valor or 0):.2f}'


def _produto(pagamento: Pagamento) -> str:
    item = pagamento.venda.itens_venda.select_related('produto').first()
    return item.produto.nome if item and item.produto_id else f'Compra #{pagamento.venda_id}'


def situacao(parcela: Parcela, hoje: date) -> str:
    if parcela.pago:
        return 'paga'
    if parcela.pagamento_efetuado:
        return 'em_confirmacao'
    if parcela.data_vencimento < hoje:
        return 'atrasada'
    return 'vence_hoje' if parcela.data_vencimento == hoje else 'a_vencer'


def _chave_pix() -> str:
    loja = Loja.objects.filter(credfacil=True).order_by('pk').first()
    return (loja.chave_pix or '') if loja else ''


def pix_estatico(chave: str, valor: Decimal, txid: str, descricao: str) -> dict | None:
    """Pix para a chave da empresa: o pagamento precisa ser informado e conferido pela equipe."""
    if not chave or valor <= 0:
        return None
    texto = payload_pix(chave, _dinheiro(valor), txid, NOME_PIX, CIDADE_PIX, descricao)
    return {'copia_cola': texto, 'qr_code_base64': qr_code_base64(texto)}


def cobranca(cobranca_online: Cobranca) -> dict:
    dados = {
        'referencia': str(cobranca_online.referencia),
        'forma': cobranca_online.forma,
        'status': cobranca_online.status,
        'tipo': cobranca_online.tipo,
        'parcela_id': cobranca_online.parcela_id,
        'parcelas': [_item(item) for item in _itens(cobranca_online)],
        'valor_parcela': _dinheiro(cobranca_online.valor_parcela),
        'taxa': _dinheiro(cobranca_online.taxa),
        'valor_total': _dinheiro(cobranca_online.valor_total),
        'expira_em': cobranca_online.expira_em.isoformat(),
        'paga_em': cobranca_online.paga_em.isoformat() if cobranca_online.paga_em else None,
        'pix_copia_cola': cobranca_online.pix_copia_cola or None,
        'qr_code_base64': None,
        'boleto_linha_digitavel': cobranca_online.boleto_linha_digitavel or None,
        'boleto_pdf_url': cobranca_online.boleto_pdf_url or None,
        'link_pagamento': cobranca_online.link_pagamento or None,
    }
    if cobranca_online.pix_copia_cola and cobranca_online.status == Cobranca.Status.PENDENTE:
        dados['qr_code_base64'] = qr_code_base64(cobranca_online.pix_copia_cola)
    return dados


def _itens(cobranca_online: Cobranca) -> list:
    return cobranca_online.itens_da_baixa()


def _item(item) -> dict:
    return {'id': item.parcela_id, 'numero': item.parcela.numero_parcela,
            'valor': _dinheiro(item.valor), 'desconto': _dinheiro(item.desconto)}


def _cobrancas_relevantes(pagamento: Pagamento) -> list[Cobranca]:
    """Pagas e pendentes ainda válidas, mais recentes primeiro."""
    agora = timezone.now()
    pendente_valida = Q(status=Cobranca.Status.PENDENTE, expira_em__gt=agora) & ~Q(pagbank_id='')
    return list(Cobranca.objects.filter(parcela__pagamento=pagamento)
                .filter(Q(status=Cobranca.Status.PAGA) | pendente_valida)
                .select_related('parcela').prefetch_related('itens__parcela').order_by('-criado_em'))


def _cobrancas_por_parcela(cobrancas: list[Cobranca]) -> dict[int, list[Cobranca]]:
    """Por parcela: pendentes só as da própria parcela; pagas de qualquer tipo (para o comprovante)."""
    por_parcela: dict[int, list[Cobranca]] = {}
    for item in cobrancas:
        if item.status == Cobranca.Status.PENDENTE and item.tipo != Cobranca.Tipo.PARCELA:
            continue
        for parcela_id in (i.parcela_id for i in _itens(item)):
            por_parcela.setdefault(parcela_id, []).append(item)
    return por_parcela


def _parcela(parcela: Parcela, hoje: date, cobrancas: list[Cobranca], chave: str, online: bool) -> dict:
    estado = situacao(parcela, hoje)
    aberta = estado != 'paga'
    pendente = next((c for c in cobrancas if c.status == Cobranca.Status.PENDENTE), None)
    pagas = [c for c in cobrancas if c.status == Cobranca.Status.PAGA]
    txid = f'{parcela.pagamento_id:04d}{parcela.numero_parcela:02d}'
    return {
        'id': parcela.pk,
        'numero': parcela.numero_parcela,
        'valor': _dinheiro(parcela.valor),
        'valor_restante': _dinheiro(max(parcela.valor_restante, Decimal('0'))),
        'vencimento': parcela.data_vencimento.isoformat(),
        'data_pagamento': parcela.data_pagamento.isoformat() if parcela.data_pagamento else None,
        'situacao': estado,
        'pode_pagar_online': online and aberta and estado != 'em_confirmacao',
        'pode_informar': aberta and estado != 'em_confirmacao',
        'cobranca_pendente': cobranca(pendente) if pendente and aberta else None,
        'comprovantes': [str(c.referencia) for c in pagas],
        'pix_estatico': None if online or not aberta else pix_estatico(
            chave, parcela.valor_restante, txid, f'Parcela {parcela.numero_parcela}'),
    }


def _plano_quitacao(pagamento: Pagamento, abertas: list[Parcela]) -> Plano | None:
    try:
        return plano_de_quitacao(pagamento, abertas)
    except ErroDeNegocio:
        return None


def _quitacao(pagamento: Pagamento, abertas: list[Parcela], chave: str, online: bool) -> dict | None:
    plano = _plano_quitacao(pagamento, abertas)
    if plano is None:
        return None
    informada = any(p.pagamento_efetuado for p in abertas)
    opcoes_online = [o.como_dict() for o in opcoes_para_valor(plano.valor)] if online and not informada else []
    return {
        'total_restante': _dinheiro(plano.total_sem_desconto),
        'porcentagem_desconto': _dinheiro(pagamento.porcentagem_desconto or 0),
        'valor_desconto': _dinheiro(plano.desconto),
        'total_com_desconto': _dinheiro(plano.valor),
        'pode_pagar_online': bool(opcoes_online),
        'opcoes': opcoes_online,
        'pix_estatico': None if opcoes_online else pix_estatico(
            chave, plano.valor, f'{pagamento.pk:04d}QT', 'Quitacao total'),
        'pode_informar': any(not p.pagamento_efetuado for p in abertas),
    }


def detalhe_do_pagamento(pagamento: Pagamento) -> dict:
    hoje = timezone.localdate()
    online = disponivel(ConfiguracaoPagamentoOnline.obter())
    chave = _chave_pix()
    parcelas = list(pagamento.parcelas_pagamento.order_by('numero_parcela', 'id'))
    abertas = [p for p in parcelas if not p.pago]
    pagas = [p for p in parcelas if p.pago]
    relevantes = _cobrancas_relevantes(pagamento)
    cobrancas = _cobrancas_por_parcela(relevantes)
    agrupadas = [c for c in relevantes if c.status == Cobranca.Status.PENDENTE and c.tipo != Cobranca.Tipo.PARCELA]
    return {
        'token': str(pagamento.token_publico),
        'cliente': {'primeiro_nome': (pagamento.venda.cliente.nome or '').split(' ')[0]},
        'produto': _produto(pagamento),
        'pagamento_online': online,
        'encerrado': pagamento.quitado or pagamento.desativado or pagamento.devolucao,
        'resumo': {
            'total': _dinheiro(pagamento.valor),
            'total_pago': _dinheiro(sum((p.valor_pago_efetivo for p in pagas), Decimal('0'))),
            'parcelas_total': len(parcelas),
            'parcelas_pagas': len(pagas),
            'parcelas_atrasadas': sum(1 for p in abertas if situacao(p, hoje) == 'atrasada'),
            'em_confirmacao': sum(1 for p in abertas if p.pagamento_efetuado),
        },
        'quitacao': _quitacao(pagamento, abertas, chave, online),
        'cobrancas_agrupadas_pendentes': [cobranca(c) for c in agrupadas] if abertas else [],
        'parcelas': [_parcela(p, hoje, cobrancas.get(p.pk, []), chave, online) for p in parcelas],
    }


def resumo_para_consulta(pagamento: Pagamento) -> dict:
    parcelas = list(pagamento.parcelas_pagamento.all())
    abertas = [p for p in parcelas if not p.pago]
    hoje = timezone.localdate()
    return {
        'token': str(pagamento.token_publico),
        'produto': _produto(pagamento),
        'parcelas_total': len(parcelas),
        'parcelas_abertas': len(abertas),
        'parcelas_atrasadas': sum(1 for p in abertas if situacao(p, hoje) == 'atrasada'),
        'encerrado': pagamento.quitado or pagamento.desativado or pagamento.devolucao,
    }


def opcoes(parcela: Parcela) -> list[dict]:
    return [opcao.como_dict() for opcao in opcoes_da_parcela(parcela)]


def opcoes_do_plano(plano: Plano) -> dict:
    return {
        'tipo': plano.tipo,
        'valor': _dinheiro(plano.valor),
        'desconto': _dinheiro(plano.desconto),
        'parcelas': [{'id': i.parcela.pk, 'numero': i.parcela.numero_parcela, 'valor': _dinheiro(i.valor),
                      'desconto': _dinheiro(i.desconto)} for i in plano.itens],
        'opcoes': [o.como_dict() for o in opcoes_para_valor(plano.valor)],
    }
