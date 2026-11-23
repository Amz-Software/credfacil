"""Linha do tempo da solicitação: histórico (simple_history) da análise, do cliente
e dos comprovantes, mais as observações, do mais recente para o mais antigo."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

from django.contrib.auth import get_user_model
from rest_framework.fields import DateTimeField

from estoque.models import EstoqueImei
from produtos.models import Produto
from vendas.models import AnaliseCreditoCliente, Cliente, NumeroAutenticador

from .regras import (
    ROTULOS_STATUS,
    ROTULOS_STATUS_APP,
    pode_ver_numero_autenticador,
    pode_ver_serasa,
    referencia_usuario,
)

LIMITE_EVENTOS = 200
ARQUIVO_ENVIADO = 'Arquivo enviado'
ARQUIVO_SUBSTITUIDO = 'Arquivo substituído'
ROTULOS_DIA_PAGAMENTO = {'1': 'Dia 1', '10': 'Dia 10', '20': 'Dia 20'}


@dataclass(frozen=True)
class Campo:
    atributo: str
    rotulo: str
    tipo: str = 'texto'  # texto | bool | escolha | fk | arquivo
    escolhas: dict | None = None
    referencia: str | None = None  # chave de `_RESOLVEDORES` para FKs


CAMPOS_ANALISE = (
    Campo('status', 'Status', 'escolha', ROTULOS_STATUS),
    Campo('status_aplicativo', 'Status do aplicativo', 'escolha', ROTULOS_STATUS_APP),
    Campo('produto_id', 'Produto', 'fk', referencia='produto'),
    Campo('numero_parcelas', 'Número de parcelas'),
    Campo('data_pagamento', 'Dia de pagamento', 'escolha', ROTULOS_DIA_PAGAMENTO),
    Campo('entrada_informada', 'Entrada informada'),
    Campo('analise_online', 'Análise online', 'bool'),
    Campo('segunda_compra', 'Segunda compra', 'bool'),
    Campo('imei_id', 'IMEI (estoque)', 'fk', referencia='imei'),
    Campo('imei_informado', 'IMEI informado'),
    Campo('imei_ultimos_digitos_vendedor', 'IMEI (4 últimos dígitos)'),
    Campo('icloud_configurado_vendedor', 'iCloud configurado pelo vendedor', 'bool'),
    Campo('icloud_confirmado_analista', 'iCloud confirmado pelo analista', 'bool'),
    Campo('venda_id', 'Venda', 'fk', referencia='venda'),
    Campo('aprovado_por_id', 'Aprovado por', 'fk', referencia='usuario'),
    Campo('observacao', 'Observação'),
    Campo('codigo_reserva', 'Código de reserva', 'arquivo'),
)
CAMPO_NUMERO_AUTENTICADOR = Campo('numero_autenticador_id', 'Número autenticador', 'fk', referencia='autenticador')
CAMPOS_CLIENTE = (
    Campo('nome', 'Nome'),
    Campo('cpf', 'CPF'),
    Campo('rg', 'RG'),
    Campo('nascimento', 'Nascimento'),
    Campo('email', 'E-mail'),
    Campo('telefone', 'Telefone'),
    Campo('telefone_secundario', 'Telefone secundário'),
    Campo('cep', 'CEP'),
    Campo('endereco', 'Endereço'),
    Campo('bairro', 'Bairro'),
    Campo('cidade', 'Cidade'),
    Campo('profissao', 'Profissão'),
    Campo('quantidade_dependentes', 'Dependentes'),
    Campo('recebe_auxilio', 'Recebe auxílio', 'bool'),
    Campo('total_renda', 'Renda total'),
    Campo('observacao_cliente', 'Observação do cliente'),
)
CAMPOS_COMPROVANTES = (
    Campo('documento_identificacao_frente', 'Documento (frente)', 'arquivo'),
    Campo('documento_identificacao_frente_analise', 'Documento (frente) analisado', 'bool'),
    Campo('documento_identificacao_verso', 'Documento (verso)', 'arquivo'),
    Campo('documento_identificacao_verso_analise', 'Documento (verso) analisado', 'bool'),
    Campo('comprovante_residencia', 'Comprovante de residência', 'arquivo'),
    Campo('comprovante_residencia_analise', 'Comprovante de residência analisado', 'bool'),
    Campo('foto_cliente', 'Foto do cliente', 'arquivo'),
)
CAMPOS_SERASA = (
    Campo('consulta_serasa', 'Consulta Serasa', 'arquivo'),
    Campo('consulta_serasa_analise', 'Consulta Serasa analisada', 'bool'),
    Campo('consulta_serasa_2', 'Consulta Serasa 2', 'arquivo'),
    Campo('consulta_serasa_2_analise', 'Consulta Serasa 2 analisada', 'bool'),
    Campo('restricao', 'Restrição', 'bool'),
)
TITULOS = {
    'analise': 'Análise alterada',
    'cliente': 'Dados do cliente alterados',
    'comprovantes': 'Comprovantes alterados',
}


def _nomes_usuarios(ids) -> dict:
    usuarios = get_user_model().objects.filter(pk__in=ids)
    return {u.pk: (u.get_full_name() or u.username) for u in usuarios}


_RESOLVEDORES: dict[str, Callable[[set], dict]] = {
    'produto': lambda ids: dict(Produto.objects.filter(pk__in=ids).values_list('pk', 'nome')),
    'imei': lambda ids: dict(EstoqueImei.objects.filter(pk__in=ids).values_list('pk', 'imei')),
    'autenticador': lambda ids: dict(NumeroAutenticador.objects.filter(pk__in=ids).values_list('pk', 'numero')),
    'usuario': _nomes_usuarios,
    'venda': lambda ids: {pk: f'Venda #{pk}' for pk in ids},
}


def _formatar(campo: Campo, valor, nomes: dict):
    if campo.tipo == 'arquivo':
        return ARQUIVO_ENVIADO if valor else None
    if valor is None or valor == '':
        return None
    if campo.tipo == 'bool':
        return 'Sim' if valor else 'Não'
    if campo.tipo == 'escolha':
        return campo.escolhas.get(str(valor), str(valor))
    if campo.tipo == 'fk':
        return nomes.get(campo.referencia, {}).get(valor, f'#{valor}')
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def _mudancas(anterior, atual, campos, nomes) -> list[dict]:
    mudancas = []
    for campo in campos:
        de, para = getattr(anterior, campo.atributo, None), getattr(atual, campo.atributo, None)
        de_fmt, para_fmt = _formatar(campo, de, nomes), _formatar(campo, para, nomes)
        if campo.tipo == 'arquivo' and de and para and de != para:
            para_fmt = ARQUIVO_SUBSTITUIDO
        if de_fmt == para_fmt:
            continue
        mudancas.append({'campo': campo.atributo.removesuffix('_id'), 'rotulo': campo.rotulo, 'de': de_fmt, 'para': para_fmt})
    return mudancas


def _historico(modelo, pk) -> list:
    if pk is None:
        return []
    return list(
        modelo.history.filter(id=pk).select_related('history_user').order_by('history_date', 'history_id')
    )


def _carregar_nomes(registros_por_origem: dict, campos_por_origem: dict) -> dict:
    ids: dict[str, set] = {}
    for origem, registros in registros_por_origem.items():
        for campo in campos_por_origem[origem]:
            if campo.tipo != 'fk':
                continue
            valores = {getattr(r, campo.atributo, None) for r in registros}
            ids.setdefault(campo.referencia, set()).update(v for v in valores if v is not None)
    return {chave: _RESOLVEDORES[chave](valores) for chave, valores in ids.items() if valores}


def _evento(tipo, origem, registro, titulo, mudancas=None, texto=None) -> dict:
    return {
        'tipo': tipo,
        'origem': origem,
        'data': registro.history_date,
        'usuario': referencia_usuario(registro.history_user),
        'titulo': titulo,
        'mudancas': mudancas or [],
        'texto': texto,
    }


def _titulo(origem: str, mudancas: list[dict]) -> str:
    status = next((m for m in mudancas if m['campo'] == 'status'), None)
    if origem == 'analise' and status:
        return f"Status: {status['de'] or '—'} → {status['para'] or '—'}"
    return TITULOS[origem]


def _eventos_de_historico(origem, registros, campos, nomes) -> list[dict]:
    eventos = []
    for indice, registro in enumerate(registros):
        if indice == 0:
            if origem == 'analise':
                eventos.append(_evento('criacao', origem, registro, 'Solicitação criada'))
            continue
        mudancas = _mudancas(registros[indice - 1], registro, campos, nomes)
        if mudancas:
            eventos.append(_evento('alteracao', origem, registro, _titulo(origem, mudancas), mudancas))
    return eventos


def _eventos_de_observacoes(analise: AnaliseCreditoCliente) -> list[dict]:
    return [
        {
            'tipo': 'observacao',
            'origem': 'observacao',
            'data': obs.criado_em,
            'usuario': referencia_usuario(obs.autor),
            'titulo': 'Observação',
            'mudancas': [],
            'texto': obs.texto,
        }
        for obs in analise.observacoes.select_related('autor').order_by('-criado_em')
    ]


def montar_linha_do_tempo(cliente: Cliente, user) -> list[dict]:
    analise = cliente.analise_credito
    campos_analise = CAMPOS_ANALISE + ((CAMPO_NUMERO_AUTENTICADOR,) if pode_ver_numero_autenticador(user) else ())
    campos_comprovantes = CAMPOS_COMPROVANTES + (CAMPOS_SERASA if pode_ver_serasa(user) else ())
    campos = {'analise': campos_analise, 'cliente': CAMPOS_CLIENTE, 'comprovantes': campos_comprovantes}
    registros = {
        'analise': _historico(AnaliseCreditoCliente, analise.pk),
        'cliente': _historico(Cliente, cliente.pk),
        'comprovantes': _historico(type(cliente.comprovantes), cliente.comprovantes_id),
    }
    nomes = _carregar_nomes(registros, campos)
    eventos = _eventos_de_observacoes(analise)
    for origem, lista in registros.items():
        eventos.extend(_eventos_de_historico(origem, lista, campos[origem], nomes))
    eventos.sort(key=lambda evento: evento['data'], reverse=True)
    formato = DateTimeField()
    return [{**evento, 'data': formato.to_representation(evento['data'])} for evento in eventos[:LIMITE_EVENTOS]]
