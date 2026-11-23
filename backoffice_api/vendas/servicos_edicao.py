"""Edição da venda (PATCH) e edição especial (IMEI/produto/parcelamento).

A persistência segue as telas: só o que mudou é gravado; pagamento com valor,
parcelas ou 1º vencimento alterado tem as parcelas recriadas por
`vendas.services.parcelas.criar_parcelas`. Nenhum valor é recalculado aqui.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from produtos.models import Produto
from vendas.forms import PagamentoEdicaoEspecialForm, ProdutoVendaEdicaoEspecialForm
from vendas.models import Cliente, Pagamento, ProdutoVenda, TipoPagamento
from vendas.services.erros import ErroDeNegocio
from vendas.services.parcelas import criar_parcelas

from .regras import eh_entrada, garantir_pode_editar, garantir_venda_ativa

CAMPOS_ITEM = ('imei', 'quantidade', 'valor_unitario', 'valor_desconto')
CAMPOS_PAGAMENTO = ('tipo_pagamento_id', 'valor', 'parcelas', 'data_primeira_parcela', 'porcentagem_desconto')
CAMPOS_QUE_RECRIAM_PARCELAS = {'valor', 'parcelas', 'data_primeira_parcela'}
CAMPOS_RASTREIO = ['modificado_por', 'modificado_em']


def _texto(valor):
    return None if valor is None else str(valor)


def tem_parcela_paga(pagamento) -> bool:
    return pagamento.parcelas_pagamento.filter(
        Q(pago=True) | Q(pagamento_efetuado=True) | Q(valor_pago__gt=0)
    ).exists()


def _garantir_sem_parcela_paga(pagamento) -> None:
    if tem_parcela_paga(pagamento):
        raise ErroDeNegocio(
            f'O pagamento #{pagamento.pk} já tem parcela paga ou informada. Alterar valor, parcelas ou '
            'vencimento recriaria as parcelas e apagaria esses registros; ajuste em Contas a receber.'
        )


def _salvar_pagamento(pagamento, alterados: set[str], user, loja) -> None:
    """Grava o pagamento; recria as parcelas só quando valor, parcelas ou vencimento mudaram."""
    if pagamento.pk and not (alterados & CAMPOS_QUE_RECRIAM_PARCELAS):
        # update_fields faz o signal de parcelas ignorar a gravação.
        campos = [c.removesuffix('_id') for c in alterados] + CAMPOS_RASTREIO
        pagamento.save(user=user, update_fields=campos)
        return
    pagamento.save(user=user)
    criar_parcelas(pagamento, loja)


# --- edição (PATCH) ------------------------------------------------------------------

def _editar_campos_da_venda(venda, dados: dict, user, clientes, alteracoes: dict) -> None:
    mudancas = {}
    if 'cliente' in dados and dados['cliente'] != venda.cliente_id:
        cliente = clientes.filter(pk=dados['cliente']).first()
        if cliente is None:
            raise ValidationError({'cliente': ['Cliente não encontrado.']})
        mudancas['cliente'] = [venda.cliente_id, cliente.pk]
        venda.cliente = cliente
    if 'vendedor' in dados and dados['vendedor'] != venda.vendedor_id:
        vendedor = get_user_model().objects.filter(pk=dados['vendedor'], is_active=True).first()
        if vendedor is None:
            raise ValidationError({'vendedor': ['Vendedor não encontrado ou inativo.']})
        mudancas['vendedor'] = [venda.vendedor_id, vendedor.pk]
        venda.vendedor = vendedor
    if 'observacao' in dados and (dados['observacao'] or '') != (venda.observacao or ''):
        mudancas['observacao'] = [venda.observacao, dados['observacao']]
        venda.observacao = dados['observacao']
    if mudancas:
        venda.save(user=user)
        alteracoes['venda'] = mudancas


def _validar_itens(venda, itens: list[dict], existentes: dict) -> None:
    erros = {}
    permitidos = (
        venda.loja.produtos_permitidos_qs(require_stock=False) if venda.loja
        else Produto.objects.filter(ativo=True)
    )
    for indice, dados in enumerate(itens):
        item = existentes.get(dados.get('id'))
        if dados.get('id') is not None and item is None:
            erros[f'itens.{indice}.id'] = ['Item não pertence a esta venda.']
        elif item is not None and dados.get('produto') not in (None, item.produto_id):
            erros[f'itens.{indice}.produto'] = ['Para trocar o produto use a troca de produto.']
        elif item is None and not permitidos.filter(pk=dados['produto']).exists():
            erros[f'itens.{indice}.produto'] = ['Produto não liberado para a loja da venda.']
    if erros:
        raise ValidationError(erros)


def _editar_itens(venda, itens: list[dict] | None, user, alteracoes: dict) -> None:
    if not itens:
        return
    existentes = {item.pk: item for item in venda.itens_venda.all()}
    _validar_itens(venda, itens, existentes)
    resumo = []
    for dados in itens:
        item = existentes.get(dados.get('id'))
        if item is not None and dados.get('remover'):
            resumo.append({'id': item.pk, 'acao': 'removido', 'produto': item.produto_id, 'imei': item.imei})
            item.delete()
            continue
        if item is None:
            item = ProdutoVenda(
                venda=venda, loja=venda.loja, produto_id=dados['produto'],
                imei=dados.get('imei') or None, quantidade=dados['quantidade'],
                valor_unitario=dados['valor_unitario'], valor_desconto=dados.get('valor_desconto') or 0,
            )
            item.save(user=user)
            resumo.append({'id': item.pk, 'acao': 'incluido', 'produto': item.produto_id})
            continue
        mudancas = {
            campo: [_texto(getattr(item, campo)), _texto(dados[campo])]
            for campo in CAMPOS_ITEM
            if campo in dados and dados[campo] != getattr(item, campo)
        }
        if mudancas:
            for campo in mudancas:
                setattr(item, campo, dados[campo])
            item.save(user=user)
            resumo.append({'id': item.pk, 'acao': 'alterado', 'campos': mudancas})
    if not ProdutoVenda.objects.filter(venda=venda).exists():
        raise ValidationError({'itens': ['A venda precisa ter ao menos um item.']})
    if resumo:
        alteracoes['itens'] = resumo


def _validar_pagamentos(pagamentos: list[dict], existentes: dict) -> None:
    erros = {}
    tipos = set(TipoPagamento.objects.filter(
        pk__in=[p['tipo_pagamento'] for p in pagamentos if p.get('tipo_pagamento') is not None]
    ).values_list('pk', flat=True))
    for indice, dados in enumerate(pagamentos):
        if dados.get('id') is not None and dados['id'] not in existentes:
            erros[f'pagamentos.{indice}.id'] = ['Pagamento não pertence a esta venda.']
        if dados.get('tipo_pagamento') is not None and dados['tipo_pagamento'] not in tipos:
            erros[f'pagamentos.{indice}.tipo_pagamento'] = ['Tipo de pagamento não encontrado.']
    if erros:
        raise ValidationError(erros)


def _mudancas_do_pagamento(pagamento, dados: dict) -> dict:
    entrada = {**dados, 'tipo_pagamento_id': dados.get('tipo_pagamento')}
    return {
        campo: [_texto(getattr(pagamento, campo)), _texto(entrada[campo])]
        for campo in CAMPOS_PAGAMENTO
        if entrada.get(campo) is not None and entrada[campo] != getattr(pagamento, campo)
    }


def _editar_pagamentos(venda, pagamentos: list[dict] | None, user, alteracoes: dict) -> None:
    if not pagamentos:
        return
    existentes = {p.pk: p for p in venda.pagamentos.all()}
    _validar_pagamentos(pagamentos, existentes)
    resumo = []
    for dados in pagamentos:
        pagamento = existentes.get(dados.get('id'))
        if pagamento is not None and dados.get('remover'):
            _garantir_sem_parcela_paga(pagamento)
            resumo.append({'id': pagamento.pk, 'acao': 'removido', 'valor': _texto(pagamento.valor)})
            pagamento.delete()
            continue
        if pagamento is None:
            pagamento = Pagamento(
                venda=venda, loja=venda.loja, tipo_pagamento_id=dados['tipo_pagamento'],
                valor=dados['valor'], parcelas=dados['parcelas'],
                data_primeira_parcela=dados['data_primeira_parcela'],
                porcentagem_desconto=dados.get('porcentagem_desconto') or 0,
            )
            _salvar_pagamento(pagamento, set(), user, venda.loja)
            resumo.append({'id': pagamento.pk, 'acao': 'incluido', 'valor': _texto(pagamento.valor)})
            continue
        mudancas = _mudancas_do_pagamento(pagamento, dados)
        if not mudancas:
            continue
        if set(mudancas) & CAMPOS_QUE_RECRIAM_PARCELAS:
            _garantir_sem_parcela_paga(pagamento)
        for campo in mudancas:
            setattr(pagamento, campo, dados['tipo_pagamento' if campo == 'tipo_pagamento_id' else campo])
        _salvar_pagamento(pagamento, set(mudancas), user, venda.loja)
        resumo.append({'id': pagamento.pk, 'acao': 'alterado', 'campos': mudancas})
    if resumo:
        alteracoes['pagamentos'] = resumo


def editar_venda(venda, dados: dict, user, *, clientes=None) -> dict:
    """Aplica a edição numa transação e devolve o resumo das mudanças (para a auditoria).

    `clientes`: queryset dos clientes que podem ser escolhidos (escopo de lojas).
    """
    garantir_pode_editar(venda, user)
    alteracoes: dict = {}
    with transaction.atomic():
        _editar_campos_da_venda(venda, dados, user, clientes if clientes is not None else Cliente.objects.all(), alteracoes)
        _editar_itens(venda, dados.get('itens'), user, alteracoes)
        _editar_pagamentos(venda, dados.get('pagamentos'), user, alteracoes)
    return alteracoes


# --- edição especial ------------------------------------------------------------------

def _erros_do_form(form, prefixo: str) -> dict:
    return {f'{prefixo}.{campo}': [str(m) for m in mensagens] for campo, mensagens in form.errors.items()}


def _editar_itens_especial(venda, itens: list[dict], user) -> list[dict]:
    existentes = {item.pk: item for item in venda.itens_venda.select_related('produto')}
    formularios, erros = [], {}
    for indice, dados in enumerate(itens):
        item = existentes.get(dados['id'])
        if item is None:
            erros[f'itens.{indice}.id'] = ['Item não pertence a esta venda.']
            continue
        # O ModelForm altera a instância já no is_valid(): guarda o estado anterior antes.
        antes = {'produto': item.produto_id, 'imei': item.imei or ''}
        form = ProdutoVendaEdicaoEspecialForm(
            {'produto': dados.get('produto', item.produto_id), 'imei': dados.get('imei', item.imei or '')},
            instance=item, loja=venda.loja,
        )
        if not form.is_valid():
            erros.update(_erros_do_form(form, f'itens.{indice}'))
            continue
        formularios.append((item, antes, form))
    if erros:
        raise ValidationError(erros)
    resumo = []
    for item, antes, form in formularios:
        novo = form.save(commit=False)
        depois = {'produto': novo.produto_id, 'imei': novo.imei or ''}
        if antes != depois:
            novo.save(user=user)
            resumo.append({'id': item.pk, 'de': antes, 'para': depois})
    return resumo


def _editar_pagamentos_especial(venda, pagamentos: list[dict], user) -> list[dict]:
    existentes = {p.pk: p for p in venda.pagamentos.select_related('tipo_pagamento')}
    resumo, erros = [], {}
    for indice, dados in enumerate(pagamentos):
        pagamento = existentes.get(dados['id'])
        if pagamento is None:
            erros[f'pagamentos.{indice}.id'] = ['Pagamento não pertence a esta venda.']
        elif eh_entrada(pagamento) and int(dados['parcelas']) != pagamento.parcelas:
            erros[f'pagamentos.{indice}.parcelas'] = ['A entrada não é parcelada.']
    if erros:
        raise ValidationError(erros)
    for dados in pagamentos:
        pagamento = existentes[dados['id']]
        form = PagamentoEdicaoEspecialForm({'parcelas': str(dados['parcelas'])}, instance=pagamento)
        antes = pagamento.parcelas
        if not form.is_valid() or form.cleaned_data['parcelas'] == antes:
            continue
        _garantir_sem_parcela_paga(pagamento)
        _salvar_pagamento(form.save(commit=False), {'parcelas'}, user, venda.loja)
        resumo.append({'id': pagamento.pk, 'parcelas': [antes, pagamento.parcelas]})
    return resumo


def editar_venda_especial(venda, dados: dict, user) -> dict:
    """IMEI/produto dos itens e parcelas dos pagamentos, com os forms da tela de edição especial.

    Como na API atual, os valores monetários gravados são preservados (nada é recalculado).
    """
    garantir_venda_ativa(venda)
    with transaction.atomic():
        itens = _editar_itens_especial(venda, dados.get('itens') or [], user)
        pagamentos = _editar_pagamentos_especial(venda, dados.get('pagamentos') or [], user)
    return {'itens': itens, 'pagamentos': pagamentos}
