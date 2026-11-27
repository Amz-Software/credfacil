"""Contato de cobrança da conta ligado ao CRM: telefones, status, linha do tempo, tentativas e notas.

A linha do tempo junta, do mais novo para o mais antigo:
- `manual`: registros de `vendas.Contato` (data + texto livre, inclusive de outro número);
- `tentativa`: `crm.TentativaContato` (avisos da régua, ligações do CRM e tentativas da equipe);
- `nota`: notas internas das conversas do cliente no CRM (sem as automáticas e as apagadas).

Quem não tem acesso ao CRM vê só os registros manuais. Conversa ligada também a cliente que o
usuário não pode ver (outra loja) fica de fora: nem as notas aparecem nem recebe nota daqui.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone

from crm.models import Conversa, Nota, TelefoneCliente, TentativaContato
from crm.permissoes import pode_acessar
from crm.services import cobranca, contatos, organizacao
from crm.services.organizacao import pode_ver_cliente
from crm.services.contatos import ErroContato
from crm.services.conversas import ConflitoCRM
from crm.telefone import formatar_telefone
from crm.web.contatos import ESTADO_RESULTADO, dados_do_cliente
from vendas.models import Contato
from vendas.services.erros import ErroDeNegocio

from .serializers import nome_do_usuario

JANELA_STATUS = timedelta(days=30)
LIMITE_POR_ORIGEM = 100
ESTADO_RESULTADO_PADRAO = 'danger'
HORA_DO_REGISTRO_MANUAL = time(12)  # meio-dia: o dia não muda em outro fuso do navegador
MENSAGEM_SEM_CONVERSA = 'O cliente ainda não tem conversa no CRM. Registre um contato manual.'
Resultado = TentativaContato.Resultado
RESULTADOS_DA_EQUIPE = [r for r in Resultado if r not in (Resultado.ENVIADO, Resultado.FALHOU)]
RESULTADOS_DE_REFERENCIA = {Resultado.REFERENCIA_AJUDOU, Resultado.REFERENCIA_SEM_SUCESSO}
CAMPOS_TELEFONE = ('id', 'numero', 'origem', 'situacao', 'situacao_rotulo', 'situacao_estado', 'eh_referencia',
                   'nome_contato', 'observacao', 'utilizavel')
SEM_DETALHE_DE_TENTATIVA = {'canal': None, 'numero': None, 'resultado': None, 'resultado_estado': None,
                            'parcela': None}


@dataclass(frozen=True)
class _Item:
    ordem: datetime
    dados: dict


def _opcao(valor: str, rotulo: str) -> dict:
    return {'valor': valor, 'rotulo': rotulo}


def _opcoes() -> dict:
    """Resultados de referência só valem para número de referência (mesma regra de `contatos`)."""
    return {
        'canais': [_opcao(v, r) for v, r in TentativaContato.Canal.choices],
        'resultados_cliente': [_opcao(r.value, r.label) for r in RESULTADOS_DA_EQUIPE
                               if r not in RESULTADOS_DE_REFERENCIA],
        'resultados_referencia': [_opcao(r.value, r.label) for r in RESULTADOS_DA_EQUIPE
                                  if r != Resultado.RESPONDEU],
    }


def _item_manual(contato: Contato) -> _Item:
    """`Contato` só tem a data: vai ao meio-dia local; a hora do registro só desempata o mesmo dia."""
    hora = timezone.localtime(contato.criado_em).time() if contato.criado_em else time.min
    ordem = timezone.make_aware(datetime.combine(contato.data, hora))
    quando = timezone.make_aware(datetime.combine(contato.data, HORA_DO_REGISTRO_MANUAL))
    return _Item(ordem, {
        'id': f'manual-{contato.pk}', 'origem': 'manual', 'quando': quando, 'somente_data': True,
        'titulo': 'Registro manual', 'texto': contato.observacao or '', 'autor': nome_do_usuario(contato.criado_por),
        'contato_id': contato.pk, 'automatica': False, **SEM_DETALHE_DE_TENTATIVA,
    })


def _item_tentativa(tentativa: TentativaContato) -> _Item:
    return _Item(tentativa.criado_em, {
        'id': f'tentativa-{tentativa.pk}', 'origem': 'tentativa', 'quando': tentativa.criado_em,
        'somente_data': False, 'titulo': tentativa.get_tipo_display(), 'texto': tentativa.observacao,
        'autor': nome_do_usuario(tentativa.usuario), 'contato_id': None, 'automatica': tentativa.automatica,
        'canal': tentativa.get_canal_display(), 'numero': formatar_telefone(tentativa.numero),
        'resultado': tentativa.get_resultado_display(),
        'resultado_estado': ESTADO_RESULTADO.get(tentativa.resultado, ESTADO_RESULTADO_PADRAO),
        'parcela': tentativa.parcela.numero_parcela if tentativa.parcela else None,
    })


def _item_nota(nota: Nota) -> _Item:
    return _Item(nota.criado_em, {
        'id': f'nota-{nota.pk}', 'origem': 'nota', 'quando': nota.criado_em, 'somente_data': False,
        'titulo': 'Nota interna do CRM', 'texto': nota.texto, 'autor': nome_do_usuario(nota.usuario),
        'contato_id': None, 'automatica': False, **SEM_DETALHE_DE_TENTATIVA,
    })


def conversas_visiveis(cliente, usuario) -> list[Conversa]:
    """Conversas do cliente, a mais recente primeiro, sem as ligadas a cliente que o usuário não vê."""
    conversas = (Conversa.objects.filter(clientes=cliente).prefetch_related('clientes')
                 .order_by('-ultima_mensagem_em', '-id'))
    return [conversa for conversa in conversas
            if all(outro.pk == cliente.pk or pode_ver_cliente(usuario, outro) for outro in conversa.clientes.all())]


def _linha_do_tempo(cliente, conversas: list[Conversa] | None) -> list[dict]:
    """`conversas` None: sem acesso ao CRM (só os registros manuais)."""
    manuais = (Contato.objects.filter(cliente=cliente).select_related('criado_por')
               .order_by('-data', '-id')[:LIMITE_POR_ORIGEM])
    itens = [_item_manual(c) for c in manuais]
    if conversas is not None:
        tentativas = (TentativaContato.objects.filter(cliente=cliente)
                      .select_related('usuario', 'parcela')[:LIMITE_POR_ORIGEM])
        notas = (Nota.objects.filter(conversa__in=conversas, automatica=False, apagada_em__isnull=True)
                 .select_related('usuario').order_by('-criado_em', '-id')[:LIMITE_POR_ORIGEM])
        itens += [_item_tentativa(t) for t in tentativas] + [_item_nota(n) for n in notas]
    return [item.dados for item in sorted(itens, key=lambda item: item.ordem, reverse=True)]


def _status(cliente) -> dict:
    """Status de contato dos últimos 30 dias (mesma janela do alerta do CRM)."""
    em_atraso = cliente.pk in cobranca.clientes_em_atraso([cliente.pk], timezone.localdate())
    ficha = contatos.ficha(cliente, timezone.now() - JANELA_STATUS, em_atraso=em_atraso)
    return {'codigo': ficha.status, 'rotulo': ficha.rotulo}


def painel(cliente, usuario) -> dict:
    """Tudo o que a aba Contatos mostra; sem acesso ao CRM, só os registros manuais."""
    if not pode_acessar(usuario):
        return {'crm_disponivel': False, 'linha_do_tempo': _linha_do_tempo(cliente, None), 'opcoes': _opcoes(),
                'status': None, 'alerta': False, 'telefones': [], 'conversa_id': None, 'pode_anotar': False}
    conversas = conversas_visiveis(cliente, usuario)
    conversa = conversas[0] if conversas else None
    dados = dados_do_cliente(cliente)  # também sincroniza os telefones do cadastro (como o painel do CRM)
    base = {'crm_disponivel': True, 'linha_do_tempo': _linha_do_tempo(cliente, conversas), 'opcoes': _opcoes()}
    return {
        **base,
        'status': _status(cliente),
        'alerta': dados['alerta'],
        'telefones': [{campo: t[campo] for campo in CAMPOS_TELEFONE} for t in dados['telefones']],
        'conversa_id': conversa.pk if conversa else None,
        'pode_anotar': conversa is not None,
    }


def registrar_tentativa(telefone: TelefoneCliente, usuario, dados: dict) -> TentativaContato:
    try:
        return contatos.registrar_tentativa(telefone, dados['resultado'], usuario, canal=dados['canal'],
                                            observacao=dados.get('observacao', ''))
    except ErroContato as erro:
        raise ErroDeNegocio(str(erro)) from erro


def criar_nota(cliente, usuario, texto: str) -> Nota:
    """A nota vai para a conversa visível do cliente com mensagem mais recente."""
    conversas = conversas_visiveis(cliente, usuario)
    if not conversas:
        raise ErroDeNegocio(MENSAGEM_SEM_CONVERSA)
    try:
        return organizacao.criar_nota(conversas[0], usuario, texto)
    except ConflitoCRM as erro:
        raise ErroDeNegocio(str(erro.detail)) from erro
