"""Edição da solicitação pelo backoffice, com os forms de `vendas/forms.py`.

Mesmo fluxo da tela `vendas/views/clientes.py:ClienteUpdateView` (forms, conflito
entre os contatos, "pelo menos um contato completo") e da edição da API do
vendedor (`api/views/solicitacoes_cadastro.py`: parcelamento cadastrado e
produto travado depois da venda gerada).

O PATCH é parcial: os forms recebem os valores atuais da solicitação com os
campos enviados por cima, então o que não veio no corpo continua como está.
"""
import copy
from dataclasses import dataclass

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from api.views.solicitacoes_regras import (
    _avisos_solicitacoes_existentes,
    _normalizar_campos_opcionais_solicitacao,
    _validar_parcelamento,
)
from backoffice_api.nucleo.erros import ErroBackoffice
from vendas.forms import (
    AnaliseCreditoClienteForm,
    ClienteForm,
    ComprovantesClienteForm,
    ContatoAdicionalForm,
    InformacaoPessoalForm,
    erro_pelo_menos_um_contato,
)
from vendas.models import Cliente
from vendas.services import ErroDeNegocio
from vendas.services.erros import PROIBIDO

from .arquivos import ARQUIVOS_SOLICITACAO, validar_uploads
from .regras import pode_editar_apos_venda

CAMPOS_CLIENTE = (
    'nome', 'telefone', 'telefone_secundario', 'cpf', 'nascimento', 'rg', 'cep', 'endereco',
    'bairro', 'cidade', 'profissao', 'quantidade_dependentes', 'recebe_auxilio', 'total_renda',
)
CAMPOS_CONTATO_ADICIONAL = ('nome_adicional', 'contato', 'endereco_adicional', 'obteve_contato')
CAMPOS_INFORMACAO_PESSOAL = ('nome_pessoal', 'contato_pessoal', 'endereco_pessoal', 'obteve_contato_pessoal')
CAMPOS_COMPROVANTES = (
    'documento_identificacao_frente', 'documento_identificacao_frente_analise',
    'documento_identificacao_verso', 'documento_identificacao_verso_analise',
    'comprovante_residencia', 'comprovante_residencia_analise',
    'consulta_serasa', 'consulta_serasa_analise', 'consulta_serasa_2', 'consulta_serasa_2_analise',
    'restricao', 'foto_cliente',
)
CAMPOS_ANALISE = (
    'produto', 'data_pagamento', 'numero_parcelas', 'entrada_informada',
    'analise_online', 'segunda_compra', 'numero_autenticador',
)
CAMPOS_EDITAVEIS = (
    CAMPOS_CLIENTE + CAMPOS_CONTATO_ADICIONAL + CAMPOS_INFORMACAO_PESSOAL + CAMPOS_COMPROVANTES + CAMPOS_ANALISE
)
CAMPOS_ARQUIVO = tuple(campo for campo, d in ARQUIVOS_SOLICITACAO.items() if d.origem == 'comprovantes')
# Depois da venda gerada a aba "Produto" fica travada para todos (regra da API do vendedor).
CAMPOS_PRODUTO = ('produto', 'data_pagamento', 'numero_parcelas', 'entrada_informada')

MSG_SEM_PERMISSAO_CAMPO = 'Você não pode alterar este campo.'
MSG_PRODUTO_TRAVADO = 'As informações de Produto não podem ser alteradas após a venda ter sido gerada.'
MSG_EDICAO_APOS_VENDA = 'Somente ANALISTA/ADMIN podem editar a solicitação após a venda ser gerada.'
CONFLITOS_CONTATO = (
    ('contato', 'contato_pessoal', 'Contato'),
    ('endereco_adicional', 'endereco_pessoal', 'Endereço'),
    ('nome_adicional', 'nome_pessoal', 'Nome'),
)


@dataclass(frozen=True)
class Formularios:
    cliente: ClienteForm
    adicional: ContatoAdicionalForm
    informacao: InformacaoPessoalForm
    comprovantes: ComprovantesClienteForm
    analise: AnaliseCreditoClienteForm

    def todos(self) -> tuple:
        return (self.cliente, self.adicional, self.informacao, self.comprovantes, self.analise)


def _montar(cliente: Cliente, user, dados=None, arquivos=None) -> Formularios:
    args = (dados, arquivos) if dados is not None else ()
    return Formularios(
        cliente=ClienteForm(*args[:1], instance=cliente, user=user),
        adicional=ContatoAdicionalForm(*args[:1], instance=cliente.contato_adicional, user=user),
        informacao=InformacaoPessoalForm(*args[:1], instance=cliente.informacao_pessoal, user=user),
        comprovantes=ComprovantesClienteForm(*args, instance=cliente.comprovantes, user=user),
        analise=AnaliseCreditoClienteForm(*args[:1], instance=cliente.analise_credito, user=user, loja=cliente.loja),
    )


def _campo_do_formulario(formularios: Formularios, nome: str):
    for form in formularios.todos():
        if nome in form.fields:
            return form, form.fields[nome]
    return None, None


def _valores_atuais(formularios: Formularios) -> dict:
    """Valores atuais de todos os campos (não arquivo), no formato aceito pelos forms."""
    valores = {}
    for form in formularios.todos():
        for nome in form.fields:
            if nome not in CAMPOS_ARQUIVO:
                valores[nome] = form[nome].value()
    return valores


def _limpo(campo, valor):
    livre = copy.copy(campo)  # cópia: `clean` de um campo desabilitado não muda nada no form
    livre.disabled = False
    return livre.clean(valor)


def _mudou(form, campo, nome: str, valor) -> bool:
    """Compara pelo valor Python (o `has_changed` do Django erra com os TypedChoiceField daqui)."""
    if isinstance(campo, forms.FileField):
        return valor is not None
    try:
        return _limpo(campo, valor) != _limpo(campo, form.get_initial_for_field(campo, nome))
    except ValidationError:
        return True


def _conferir_enviados(formularios: Formularios, enviados: dict, venda_gerada: bool) -> tuple[list, dict]:
    """Devolve (campos alterados, erros dos campos que o usuário não pode alterar)."""
    alterados, erros = [], {}
    for nome, valor in enviados.items():
        form, campo = _campo_do_formulario(formularios, nome)
        if campo is None:
            erros[nome] = [MSG_SEM_PERMISSAO_CAMPO]
            continue
        if not _mudou(form, campo, nome, valor):
            continue
        alterados.append(nome)
        if venda_gerada and nome in CAMPOS_PRODUTO:
            erros[nome] = [MSG_PRODUTO_TRAVADO]
        elif campo.disabled:
            erros[nome] = [MSG_SEM_PERMISSAO_CAMPO]
    return sorted(alterados), erros


def campos_editaveis(cliente: Cliente, user) -> list[str]:
    """Campos que este usuário pode alterar agora (para a SPA habilitar o formulário)."""
    if not pode_editar(cliente, user):
        return []
    formularios = _montar(cliente, user)
    venda_gerada = cliente.analise_credito.venda_id is not None
    editaveis = []
    for nome in CAMPOS_EDITAVEIS:
        _, campo = _campo_do_formulario(formularios, nome)
        if campo is None or campo.disabled or (venda_gerada and nome in CAMPOS_PRODUTO):
            continue
        editaveis.append(nome)
    return editaveis


def pode_editar(cliente: Cliente, user) -> bool:
    if not user.has_perm('vendas.change_cliente'):
        return False
    return cliente.analise_credito.venda_id is None or pode_editar_apos_venda(user)


def _erros_dos_formularios(formularios: Formularios) -> dict:
    erros = {}
    for form in formularios.todos():
        for campo, mensagens in form.errors.items():
            erros.setdefault(campo, []).extend(str(m) for m in mensagens)
    return erros


def _erros_de_conflito(formularios: Formularios) -> dict:
    adicional = formularios.adicional.cleaned_data
    pessoal = formularios.informacao.cleaned_data
    erros = {}
    for campo_adicional, campo_pessoal, rotulo in CONFLITOS_CONTATO:
        valor_adicional = (adicional.get(campo_adicional) or '').strip().lower()
        valor_pessoal = (pessoal.get(campo_pessoal) or '').strip().lower()
        if valor_adicional and valor_adicional == valor_pessoal:
            erros[campo_adicional] = [f'{rotulo} do Contato Adicional não pode ser igual ao de Informações Pessoais.']
            erros[campo_pessoal] = [f'{rotulo} de Informações Pessoais não pode ser igual ao do Contato Adicional.']
    erro_contato = erro_pelo_menos_um_contato(formularios.adicional, formularios.informacao)
    if erro_contato:
        erros.setdefault('contato', []).append(erro_contato)
        erros.setdefault('contato_pessoal', []).append(erro_contato)
    return erros


def _validar(formularios: Formularios) -> None:
    if not all([form.is_valid() for form in formularios.todos()]):
        raise ErroBackoffice('Revise os campos destacados.', campos=_erros_dos_formularios(formularios))
    erros = _erros_de_conflito(formularios)
    erros.update(_validar_parcelamento(formularios.analise, somente_se_alterado=True) or {})
    if erros:
        raise ErroBackoffice('Revise os campos destacados.', campos=erros)


def _gravar(formularios: Formularios, cliente: Cliente, user) -> Cliente:
    with transaction.atomic():
        adicional = formularios.adicional.save(commit=False)
        adicional.save(user=user)
        informacao = formularios.informacao.save(commit=False)
        informacao.save(user=user)
        comprovantes = formularios.comprovantes.save(commit=False)
        comprovantes.save(user=user)
        analise = formularios.analise.save(commit=False)
        analise.save(user=user)
        atualizado = formularios.cliente.save(commit=False)
        atualizado.contato_adicional = adicional
        atualizado.informacao_pessoal = informacao
        atualizado.comprovantes = comprovantes
        atualizado.save(user=user)
    return atualizado


def _dados_enviados(dados_requisicao, arquivos: dict) -> dict:
    """Campos editáveis enviados no corpo (aliases e booleanos normalizados como na API do vendedor)."""
    dados = _normalizar_campos_opcionais_solicitacao(dados_requisicao)
    return {chave: valor for chave, valor in dados.items() if chave in CAMPOS_EDITAVEIS and chave not in arquivos}


@dataclass(frozen=True)
class ResultadoEdicao:
    cliente: Cliente
    campos: list
    aviso: str | None


def _aviso_de_duplicidade(formularios: Formularios, cliente: Cliente) -> str | None:
    dados = formularios.cliente.cleaned_data
    return _avisos_solicitacoes_existentes(
        cpf=dados.get('cpf'),
        rg=dados.get('rg'),
        nome=dados.get('nome'),
        telefone=dados.get('telefone'),
        telefone_secundario=dados.get('telefone_secundario'),
        exclude_cliente_id=cliente.pk,
    )


def editar_solicitacao(cliente: Cliente, user, dados_requisicao, arquivos_requisicao) -> ResultadoEdicao:
    """Valida e grava a edição; levanta `ErroBackoffice`/`ErroDeNegocio` sem gravar nada se algo falhar."""
    venda_gerada = cliente.analise_credito.venda_id is not None
    if venda_gerada and not pode_editar_apos_venda(user):
        raise ErroDeNegocio(MSG_EDICAO_APOS_VENDA, codigo=PROIBIDO)

    arquivos = {campo: arquivo for campo, arquivo in arquivos_requisicao.items() if campo in CAMPOS_EDITAVEIS}
    dados = _dados_enviados(dados_requisicao, arquivos)
    atuais = _montar(cliente, user)
    alterados, bloqueados = _conferir_enviados(atuais, {**dados, **arquivos}, venda_gerada)
    if bloqueados:
        raise ErroBackoffice('Alguns campos não podem ser alterados.', campos=bloqueados)
    validar_uploads(arquivos)

    formularios = _montar(cliente, user, {**_valores_atuais(atuais), **dados}, arquivos)
    _validar(formularios)
    aviso = _aviso_de_duplicidade(formularios, cliente)
    atualizado = _gravar(formularios, cliente, user)
    return ResultadoEdicao(cliente=atualizado, campos=alterados, aviso=aviso)
