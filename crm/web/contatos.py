"""Telefones e tentativas de contato do cliente, no painel da conversa.

Só para clientes vinculados à conversa e que o usuário pode ver. Número de referência
aparece só como contato para ligar: nada de dívida ou parcela junto dele.
"""
from datetime import timedelta

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from crm.models import Conversa, TelefoneCliente, TentativaContato
from crm.services import cobranca, contatos
from crm.services.contatos import ErroContato
from crm.services.conversas import ConflitoCRM, nota_automatica
from crm.services.organizacao import pode_ver_cliente
from crm.telefone import formatar_telefone
from crm.web.base import acao, ler_inteiro, responder, url_conversa

Origem = TelefoneCliente.Origem
Situacao = TelefoneCliente.Situacao
Resultado = TentativaContato.Resultado

MAX_TENTATIVAS_PAINEL = 10
ORIGENS_MANUAIS = (Origem.C4M, Origem.REFERENCIA, Origem.OUTRO)
RESULTADOS_AUTOMATICOS = (Resultado.ENVIADO, Resultado.FALHOU)
ESTADO_SITUACAO = {
    Situacao.NAO_VERIFICADO: 'secondary',
    Situacao.VALIDO: 'success',
    Situacao.SEM_WHATSAPP: 'warning',
    Situacao.INVALIDO: 'danger',
    Situacao.BLOQUEADO: 'danger',
}
ESTADO_RESULTADO = {
    Resultado.RESPONDEU: 'success',
    Resultado.REFERENCIA_AJUDOU: 'success',
    Resultado.ENVIADO: 'info',
    Resultado.NAO_ATENDEU: 'warning',
    Resultado.SEM_WHATSAPP: 'warning',
    Resultado.REFERENCIA_SEM_SUCESSO: 'warning',
}
ROTULO_PAPEL = {'principal': 'Principal do cadastro', 'secundario': 'Secundário do cadastro'}


# --- dados do painel -----------------------------------------------------------------------------

def _telefone_dict(cliente, telefone: TelefoneCliente) -> dict:
    papel = contatos.papel(cliente, telefone)
    return {
        'id': telefone.pk,
        'numero': formatar_telefone(telefone.telefone),
        'origem': ROTULO_PAPEL.get(papel, telefone.get_origem_display()),
        'situacao': telefone.situacao,
        'situacao_rotulo': telefone.get_situacao_display(),
        'situacao_estado': ESTADO_SITUACAO.get(telefone.situacao, 'secondary'),
        'eh_referencia': telefone.origem == Origem.REFERENCIA,
        'nome_contato': telefone.nome_contato,
        'observacao': telefone.observacao,
        'utilizavel': contatos.utilizavel(telefone),
    }


def _tentativa_dict(tentativa: TentativaContato) -> dict:
    usuario = tentativa.usuario
    return {
        'criado_em': tentativa.criado_em,
        'numero': formatar_telefone(tentativa.numero),
        'tipo': tentativa.get_tipo_display(),
        'automatica': tentativa.automatica,
        'canal': tentativa.get_canal_display(),
        'resultado': tentativa.get_resultado_display(),
        'resultado_estado': ESTADO_RESULTADO.get(tentativa.resultado, 'danger'),
        'usuario': (usuario.get_full_name() or usuario.username) if usuario else '',
        'observacao': tentativa.observacao,
    }


def _opcoes() -> dict:
    return {
        'origens': [(valor, Origem(valor).label) for valor in ORIGENS_MANUAIS],
        'situacoes': Situacao.choices,
        'canais': TentativaContato.Canal.choices,
        'resultados': [(v, r) for v, r in Resultado.choices if v not in RESULTADOS_AUTOMATICOS],
        'situacao_inicial': Situacao.NAO_VERIFICADO,
    }


JANELA_ALERTA = timedelta(days=30)


def _alerta(cliente) -> bool:
    """Mesmo critério da aba "Não pagou e não respondeu" (avisos dos últimos 30 dias)."""
    hoje = timezone.localdate()
    em_atraso = cliente.pk in cobranca.clientes_em_atraso([cliente.pk], hoje)
    return em_atraso and contatos.ficha(cliente, timezone.now() - JANELA_ALERTA, em_atraso=True).alerta


def dados_do_cliente(cliente) -> dict:
    """Telefones (sincronizados com o cadastro) e as últimas tentativas, prontos para o template."""
    telefones = contatos.sincronizar(cliente)
    tentativas = (TentativaContato.objects.filter(cliente=cliente).select_related('usuario')
                  [:MAX_TENTATIVAS_PAINEL])
    return {
        'cliente_id': cliente.pk,
        'alerta': _alerta(cliente),
        'telefones': [_telefone_dict(cliente, t) for t in telefones],
        'tentativas': [_tentativa_dict(t) for t in tentativas],
        **_opcoes(),
    }


# --- ações ---------------------------------------------------------------------------------------

def _cliente_da_conversa(request: HttpRequest, conversa: Conversa, cliente_id: int):
    cliente = conversa.clientes.filter(pk=cliente_id).first()
    if cliente is None or not pode_ver_cliente(request.user, cliente):
        raise Http404
    return cliente


def _telefone_da_conversa(request: HttpRequest, pk: int, telefone_id: int) -> TelefoneCliente:
    conversa = get_object_or_404(Conversa, pk=pk)
    telefone = get_object_or_404(TelefoneCliente.objects.select_related('cliente'), pk=telefone_id)
    _cliente_da_conversa(request, conversa, telefone.cliente_id)
    return telefone


def _executar(funcao, *args, **kwargs):
    """ErroContato traz a mensagem pronta: vira aviso na tela (nunca 500)."""
    try:
        return funcao(*args, **kwargs)
    except ErroContato as erro:
        raise ConflitoCRM(str(erro)) from erro


@acao
def adicionar_telefone(request: HttpRequest, pk: int, cliente_id: int) -> HttpResponse:
    cliente = _cliente_da_conversa(request, get_object_or_404(Conversa, pk=pk), cliente_id)
    dados = request.POST
    _executar(contatos.adicionar_telefone, cliente, dados.get('telefone', ''), dados.get('origem', ''),
              request.user, nome_contato=dados.get('nome_contato', ''), observacao=dados.get('observacao', ''),
              situacao=dados.get('situacao') or Situacao.NAO_VERIFICADO)
    return responder(request, url_conversa(pk), 'Telefone adicionado.')


@acao
def mudar_situacao(request: HttpRequest, pk: int, telefone_id: int) -> HttpResponse:
    telefone = _telefone_da_conversa(request, pk, telefone_id)
    situacao = request.POST.get('situacao', '')
    if situacao == Situacao.BLOQUEADO and not request.user.has_perm('crm.gerenciar_crm'):
        raise ConflitoCRM('Só quem gerencia o CRM confirma bloqueio.')
    anterior = telefone.get_situacao_display()
    _executar(contatos.mudar_situacao, telefone, situacao)
    # Trilha: quem mudou e quando (a situação decide se o número recebe aviso de cobrança).
    nota_automatica(Conversa.objects.get(pk=pk), f'{_nome_usuario(request.user)} mudou o número '
                    f'{formatar_telefone(telefone.telefone)} de "{anterior}" para "{telefone.get_situacao_display()}".')
    return responder(request, url_conversa(pk), f'Telefone marcado como {telefone.get_situacao_display().lower()}.')


def _nome_usuario(usuario) -> str:
    return usuario.get_full_name() or usuario.get_username()


@acao
def registrar_tentativa(request: HttpRequest, pk: int, cliente_id: int) -> HttpResponse:
    cliente = _cliente_da_conversa(request, get_object_or_404(Conversa, pk=pk), cliente_id)
    telefone_id = ler_inteiro(request.POST.get('telefone'), 'telefone')
    telefone = cliente.telefones_crm.filter(pk=telefone_id).first() if telefone_id else None
    if telefone is None:
        raise ConflitoCRM('Escolha o telefone usado na tentativa.')
    _executar(contatos.registrar_tentativa, telefone, request.POST.get('resultado', ''), request.user,
              canal=request.POST.get('canal') or TentativaContato.Canal.LIGACAO,
              observacao=request.POST.get('observacao', ''))
    return responder(request, url_conversa(pk), 'Tentativa registrada.')
