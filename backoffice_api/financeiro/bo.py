"""Notificação extrajudicial para B.O.: dados da prévia e PDF (WeasyPrint).

Regras extraídas de `financeiro/views.py` (`_build_references_text`,
`_get_primeira_parcela_atrasada`, `_get_notificacao_bo_context`), sem alterar
a tela Django. O PDF reaproveita `notificacao_bo/notificacao_bo_pdf.html`.
"""
import mimetypes
import os
from urllib.parse import urlparse

import weasyprint
from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import SuspiciousFileOperation
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils._os import safe_join

from vendas.models import Pagamento, Parcela

TEMPLATE_PDF = 'notificacao_bo/notificacao_bo_pdf.html'
SEM_VALOR = '—'
REFERENCIAS_MODELO = [
    'I. [Nome ou inicial], [vínculo], reside no endereço [endereço].',
    'II. [Nome ou inicial], [vínculo], telefone [telefone], observação [texto].',
]


def mascarar_cpf_bo(cpf: str | None) -> str:
    """Máscara usada no documento do BO (`123.***.***-45`), igual à tela Django."""
    digitos = ''.join(ch for ch in (cpf or '') if ch.isdigit())
    if len(digitos) != 11:
        return cpf or SEM_VALOR
    return f'{digitos[:3]}.***.***-{digitos[-2:]}'


def primeira_parcela_atrasada(pagamento: Pagamento) -> Parcela | None:
    hoje = timezone.localdate()
    return (
        pagamento.parcelas_pagamento.filter(pago=False, data_vencimento__lt=hoje)
        .order_by('data_vencimento', 'numero_parcela')
        .first()
    )


def _referencia(partes: list) -> str | None:
    partes = [p for p in partes if p]
    if not partes:
        return None
    return ' - '.join([partes[0], ', '.join(partes[1:])]).strip(' -')


def referencias_padrao(cliente) -> str:
    """Texto inicial das referências pessoais: contatos, info. adicional e comercial."""
    referencias = [c.observacao.strip() for c in cliente.contatos.all().order_by('data') if c.observacao]
    if cliente.informacao_pessoal:
        info = cliente.informacao_pessoal
        referencias.append(_referencia([info.nome, info.contato, info.endereco]))
    if cliente.contato_adicional:
        info = cliente.contato_adicional
        referencias.append(_referencia([info.nome_adicional, info.contato, info.endereco_adicional]))
    referencias = [r for r in referencias if r] or REFERENCIAS_MODELO
    return '\n'.join(f'{indice + 1}. {texto}' for indice, texto in enumerate(referencias))


def _formatar_data(valor) -> str | None:
    if not valor:
        return None
    if hasattr(valor, 'strftime'):
        return valor.strftime('%d/%m/%Y')
    return str(valor)


def contexto_bo(pagamento: Pagamento, referencias: str) -> dict:
    """Contexto do template do BO (mesmas chaves da tela Django)."""
    venda = pagamento.venda
    cliente, loja = venda.cliente, venda.loja
    item = venda.itens_venda.select_related('produto__marca').first()
    produto = item.produto if item else None
    parcelas = list(pagamento.parcelas_pagamento.order_by('data_vencimento', 'numero_parcela'))
    atrasada = primeira_parcela_atrasada(pagamento)
    contrato = loja.contrato or {}
    data_venda = timezone.localtime(venda.data_venda).date()
    cidade = getattr(loja, 'cidade', None) or contrato.get('cidade') or SEM_VALOR
    uf = getattr(loja, 'uf', None) or contrato.get('uf') or SEM_VALOR
    hoje = timezone.localtime().strftime('%d/%m/%Y')
    local = f'{cidade}/{uf}, {hoje}' if SEM_VALOR not in (cidade, uf) else f'{loja.nome}, {hoje}'
    return {
        'pagamento': pagamento,
        'venda': venda,
        'cliente': cliente,
        'loja': loja,
        'item': item,
        'produto': produto,
        'primeira_parcela_atrasada': atrasada,
        'referencias_personais': referencias,
        'cliente_cpf_exibicao': mascarar_cpf_bo(cliente.cpf),
        'cliente_endereco': ', '.join(p for p in [cliente.endereco, cliente.bairro, cliente.cidade] if p) or SEM_VALOR,
        'loja_nome': loja.nome,
        'loja_cnpj': loja.cnpj or SEM_VALOR,
        'loja_telefone': getattr(loja, 'telefone', None) or contrato.get('telefone') or SEM_VALOR,
        'loja_endereco': getattr(loja, 'endereco', None) or contrato.get('endereco') or SEM_VALOR,
        'loja_cidade': cidade,
        'loja_uf': uf,
        'data_assinatura': data_venda,
        'inicio_vigencia': _formatar_data(contrato.get('data_inicio') or contrato.get('inicio_vigencia') or data_venda),
        'fim_vigencia': _formatar_data(
            contrato.get('data_fim') or contrato.get('fim_vigencia')
            or (parcelas[-1].data_vencimento if parcelas else data_venda)
        ),
        'produto_nome': produto.nome if produto else SEM_VALOR,
        'produto_modelo': produto.nome if produto else SEM_VALOR,
        'produto_imei': item.imei if item and item.imei else SEM_VALOR,
        'valor_mensal': atrasada.valor if atrasada else pagamento.valor_parcela,
        'vencimento_primeira_atrasada': atrasada.data_vencimento if atrasada else None,
        'created_at': timezone.localtime(),
        'bo_local_assinatura': local,
    }


def dados_da_previa(pagamento: Pagamento) -> dict:
    """Campos do documento para a SPA montar a prévia (sem objetos de modelo)."""
    ctx = contexto_bo(pagamento, referencias_padrao(pagamento.venda.cliente))
    cliente = ctx['cliente']
    return {
        'pagamento_id': pagamento.pk,
        'venda_id': ctx['venda'].pk,
        'cliente': {
            'nome': cliente.nome,
            'cpf_exibicao': ctx['cliente_cpf_exibicao'],
            'telefone': cliente.telefone or SEM_VALOR,
            'telefone_secundario': cliente.telefone_secundario or SEM_VALOR,
            'endereco': ctx['cliente_endereco'],
        },
        'loja': {key: ctx[f'loja_{key}'] for key in ('nome', 'cnpj', 'telefone', 'endereco', 'cidade', 'uf')},
        'produto': {'nome': ctx['produto_nome'], 'modelo': ctx['produto_modelo'], 'imei': ctx['produto_imei']},
        'data_assinatura': ctx['data_assinatura'].isoformat(),
        'inicio_vigencia': ctx['inicio_vigencia'],
        'fim_vigencia': ctx['fim_vigencia'],
        'valor_mensal': str(ctx['valor_mensal']),
        'vencimento_primeira_atrasada': (
            ctx['vencimento_primeira_atrasada'].isoformat() if ctx['vencimento_primeira_atrasada'] else None
        ),
        'local_assinatura': ctx['bo_local_assinatura'],
        'referencias_padrao': ctx['referencias_personais'],
    }


def _arquivo_estatico(caminho_url: str) -> str | None:
    relativo = caminho_url[len(settings.STATIC_URL):]
    encontrado = finders.find(relativo)
    if encontrado:
        return encontrado
    if settings.STATIC_ROOT:
        try:
            candidato = safe_join(settings.STATIC_ROOT, relativo)
        except SuspiciousFileOperation:
            return None
        return candidato if os.path.isfile(candidato) else None
    return None


def buscar_recurso_local(url: str, *args, **kwargs) -> dict:
    """`url_fetcher` do WeasyPrint: só `data:` e arquivos estáticos locais (sem rede)."""
    if url.startswith('data:'):
        return weasyprint.default_url_fetcher(url, *args, **kwargs)
    caminho = urlparse(url).path
    if caminho.startswith(settings.STATIC_URL):
        local = _arquivo_estatico(caminho)
        if local:
            with open(local, 'rb') as arquivo:
                conteudo = arquivo.read()
            return {'string': conteudo, 'mime_type': mimetypes.guess_type(local)[0], 'redirected_url': url}
    raise ValueError(f'Recurso não permitido no PDF: {url}')


def gerar_pdf_bo(pagamento: Pagamento, referencias: str, request) -> bytes:
    django_request = getattr(request, '_request', request)
    html = render_to_string(TEMPLATE_PDF, contexto_bo(pagamento, referencias), request=django_request)
    return weasyprint.HTML(
        string=html, base_url=django_request.build_absolute_uri('/'), url_fetcher=buscar_recurso_local,
    ).write_pdf()
