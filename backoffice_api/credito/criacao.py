"""Criação da solicitação pelo backoffice (analista/administrador).

Mesmos forms e regras da edição (`edicao.py`) e do cadastro do vendedor: referências que
não podem ser iguais, pelo menos uma referência completa e parcelamento cadastrado para a
marca do produto. Diferenças do vendedor: a loja é sempre a da CredFácil (IPIXX, marcada
com `Loja.credfacil`), que enxerga todos os produtos ativos, e os documentos são opcionais
(a equipe anexa depois pela aba Comprovantes).
"""
from dataclasses import dataclass

from django.db import transaction

from api.views.solicitacoes_regras import _validar_parcelamento
from backoffice_api.nucleo.erros import ErroBackoffice
from vendas.forms import (
    AnaliseCreditoClienteForm,
    ClienteForm,
    ComprovantesClienteForm,
    ContatoAdicionalForm,
    InformacaoPessoalForm,
)
from vendas.models import Cliente, Loja

from .arquivos import validar_uploads
from .edicao import (
    CAMPOS_ARQUIVO,
    MSG_REVISE,
    Formularios,
    _aviso_de_duplicidade,
    _dados_enviados,
    _erros_de_conflito,
    _erros_dos_formularios,
)

MSG_SEM_LOJA = 'Nenhuma loja da CredFácil (IPIXX) está marcada no cadastro de lojas.'
# O app do vendedor também envia 0 (o campo não aparece no cadastro).
PADROES = {'quantidade_dependentes': 0}
# Exigidos do vendedor; aqui a equipe anexa depois, pela aba Comprovantes.
DOCUMENTOS_OPCIONAIS = ('documento_identificacao_frente', 'documento_identificacao_verso', 'foto_cliente')


def loja_da_credfacil() -> Loja:
    loja = Loja.objects.filter(credfacil=True).order_by('pk').first()
    if loja is None:
        raise ErroBackoffice(MSG_SEM_LOJA)
    return loja


def formulario_de_analise(user, loja: Loja, dados=None) -> AnaliseCreditoClienteForm:
    return AnaliseCreditoClienteForm(dados, user=user, loja=loja)


def _comprovantes_opcionais(dados: dict, arquivos: dict, user) -> ComprovantesClienteForm:
    form = ComprovantesClienteForm(dados, arquivos, user=user)
    for campo in DOCUMENTOS_OPCIONAIS:
        if campo in form.fields:
            form.fields[campo].required = False
    return form


def _montar_novos(user, loja: Loja, dados: dict, arquivos: dict) -> Formularios:
    dados = {**PADROES, **dados}
    return Formularios(
        cliente=ClienteForm(dados, user=user),
        adicional=ContatoAdicionalForm(dados, user=user),
        informacao=InformacaoPessoalForm(dados, user=user),
        comprovantes=_comprovantes_opcionais(dados, arquivos, user),
        analise=formulario_de_analise(user, loja, dados),
    )


def _validar_criacao(formularios: Formularios) -> None:
    if not all([form.is_valid() for form in formularios.todos()]):
        raise ErroBackoffice(MSG_REVISE, campos=_erros_dos_formularios(formularios))
    erros = _erros_de_conflito(formularios)
    erros.update(_validar_parcelamento(formularios.analise) or {})
    if erros:
        raise ErroBackoffice(MSG_REVISE, campos=erros)


def _gravar_nova(formularios: Formularios, loja: Loja, user) -> Cliente:
    with transaction.atomic():
        adicional = formularios.adicional.save(commit=False)
        adicional.save(user=user)
        informacao = formularios.informacao.save(commit=False)
        informacao.save(user=user)
        comprovantes = formularios.comprovantes.save(commit=False)
        comprovantes.save(user=user)
        cliente = formularios.cliente.save(commit=False)
        cliente.loja = loja
        cliente.contato_adicional = adicional
        cliente.informacao_pessoal = informacao
        cliente.comprovantes = comprovantes
        cliente.save(user=user)
        analise = formularios.analise.save(commit=False)
        analise.cliente = cliente
        analise.loja = loja
        analise.save(user=user)  # dispara a notificação "proposta_criada" (notificacao/signals.py)
    return cliente


@dataclass(frozen=True)
class ResultadoCriacao:
    cliente: Cliente
    aviso: str | None


def criar_solicitacao(user, dados_requisicao, arquivos_requisicao) -> ResultadoCriacao:
    """Valida e grava cliente + análise na loja da CredFácil; `ErroBackoffice` sem gravar nada se falhar."""
    loja = loja_da_credfacil()
    arquivos = {campo: arquivo for campo, arquivo in arquivos_requisicao.items() if campo in CAMPOS_ARQUIVO}
    validar_uploads(arquivos)
    dados = _dados_enviados(dados_requisicao, arquivos)  # descarta `loja` e campos desconhecidos
    formularios = _montar_novos(user, loja, dados, arquivos)
    _validar_criacao(formularios)
    aviso = _aviso_de_duplicidade(formularios, None)
    return ResultadoCriacao(cliente=_gravar_nova(formularios, loja, user), aviso=aviso)
