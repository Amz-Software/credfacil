"""Regras que hoje só existem dentro das views Django do CRM (`crm/web/*`), extraídas sem alterá-las.

A regra de negócio continua em `crm/services/*`; aqui ficam só as orquestrações que as
telas fazem antes ou depois de chamar os serviços.
"""
from django.db import transaction
from django.forms.models import model_to_dict
from rest_framework.exceptions import ValidationError

from crm import tarefas
from crm.models import Conversa, ModeloAbertura, RespostaRapida, VersaoAbertura
from crm.permissoes import pode_gerenciar
from crm.services import aberturas, avisos, conversas, envio
from crm.services.conversas import ConflitoCRM
from crm.whatsapp import obter_provider

STATUS_SEM_SINCRONIA = (VersaoAbertura.Status.DESCARTADO, VersaoAbertura.Status.ERRO_ENVIO)


def simulado() -> bool:
    """WhatsApp simulado (sem credenciais da Meta): nada sai para a Meta."""
    return bool(getattr(obter_provider(), 'simulado', False))


def marcar_lida(conversa: Conversa) -> None:
    """Zera as não lidas e agenda o recibo de leitura (tiques azuis), como a tela faz ao abrir.

    Origem: `crm/web/caixa.py::_marcar_lida`.
    """
    if conversa.nao_lidas:
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)
        tarefas.agendar(envio.enviar_recibo_leitura, conversa.pk)


def mudar_situacao(conversa: Conversa, nova: str, usuario, devolver_automatico: bool = False) -> None:
    """Muda a situação e, ao resolver, pode devolver ao automático (tudo ou nada).

    Origem: `crm/web/acoes.py::situacao`.
    """
    if devolver_automatico and nova != Conversa.Situacao.RESOLVIDA:
        raise ConflitoCRM('Só é possível devolver ao automático ao resolver.')
    with transaction.atomic():  # se a devolução for recusada, a situação também não muda
        conversas.mudar_situacao(conversa, nova, usuario)
        if devolver_automatico:
            conversas.devolver(conversa, usuario, pode_gerenciar=pode_gerenciar(usuario))
        avisos.emitir(conversa, 'conversa_atualizada')


def verificar_abertura(modelo: ModeloAbertura) -> None:
    """Consulta a Meta para cada versão que ainda pode mudar de situação.

    Origem: `crm/web/configuracao.py::abertura_verificar`.
    """
    for versao in modelo.versoes.exclude(status__in=STATUS_SEM_SINCRONIA):
        aberturas.sincronizar(versao)


def dados_edicao_abertura(validados: dict, corpo_atual: str) -> dict:
    """Só manda `corpo` ao serviço quando o texto mudou (texto novo = versão nova na Meta).

    Origem: `crm/web/configuracao.py::_dados_edicao`.
    """
    dados = {chave: validados[chave] for chave in ('titulo', 'ordem', 'ativo') if chave in validados}
    corpo = (validados.get('corpo') or '').strip()
    if corpo and corpo != (corpo_atual or '').strip():
        dados['corpo'] = corpo
    return dados


def acoes_disponiveis(conversa: Conversa, usuario) -> dict[str, bool]:
    """O que o cabeçalho da conversa oferece ao usuário (regras de `crm/parciais/cabecalho.html`).

    É só conforto para a interface: os serviços conferem tudo de novo.
    """
    gerencia = pode_gerenciar(usuario)
    dono = conversa.assumida_por_id
    eh_dono = conversa.modo == Conversa.Modo.HUMANO and dono == usuario.pk
    sem_dono = conversa.modo != Conversa.Modo.HUMANO or not dono
    pode_devolver = conversa.modo != Conversa.Modo.AUTOMATICO and (dono == usuario.pk or gerencia or not dono)
    return {
        'assumir': sem_dono,
        'puxar': not sem_dono and dono != usuario.pk,
        'atribuir': gerencia or eh_dono,
        'devolver': pode_devolver,
        'resolver': conversa.situacao != Conversa.Situacao.RESOLVIDA,
        'resolver_e_devolver': pode_devolver and conversa.situacao != Conversa.Situacao.RESOLVIDA,
        'reabrir': conversa.situacao == Conversa.Situacao.RESOLVIDA,
        'marcar_pendente': conversa.situacao != Conversa.Situacao.PENDENTE,
        'enviar_abertura': not conversa.janela_aberta(),
    }


def validar_form(form_class, dados, instancia=None):
    """Valida com o form das telas (mesmas regras). Campos não enviados ficam como estão (edição) ou com o
    padrão do modelo (criação).

    Erros viram 400 `validacao` com `campos`.
    """
    base = instancia if instancia is not None else form_class._meta.model()  # criação: padrões do modelo
    atuais = model_to_dict(base, fields=form_class._meta.fields)
    dados = {**atuais, **{chave: dados[chave] for chave in dados if chave in form_class._meta.fields}}
    form = form_class(data=dados, instance=instancia)
    if not form.is_valid():
        raise ValidationError({campo: list(erros) for campo, erros in form.errors.items()})
    return form


def salvar_cadastro(form, usuario):
    """Etiqueta ou resposta rápida (a resposta guarda quem criou). Origem: `crm/web/configuracao.py`."""
    objeto = form.save(commit=False)
    if isinstance(objeto, RespostaRapida) and objeto.criado_por_id is None:
        objeto.criado_por = usuario
    objeto.save()
    return objeto
