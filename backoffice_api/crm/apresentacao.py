"""Dados que a API do CRM devolve, montados sobre `crm/apresentacao.py` (os mesmos das telas Django).

Os dicionários daqui são lidos pelos serializers de saída (`serializers/saida.py`), que fixam
os campos e o formato (datas ISO no fuso do sistema, valores como texto decimal).
"""
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from crm.apresentacao import _anotacoes, anotar_lista, base_mensagens, conversa_resumo, mensagens_dicts
from crm.models import Conversa, Mensagem, Midia
from crm.services import organizacao
from crm.services.conversas import bloqueio_de
from crm.telefone import formatar_telefone

from .servicos import acoes_disponiveis

ROTA_MIDIA = 'backoffice_api:crm:mensagem-arquivo'
VERSAO_MINIATURA = 'miniatura'


# --- conversa -------------------------------------------------------------------------------

def item_lista(conversa: Conversa, agora=None) -> dict:
    """Item da lista (a conversa precisa vir de `anotar_lista`)."""
    resumo = conversa_resumo(conversa, agora)
    return {
        **{chave: resumo[chave] for chave in (
            'id', 'telefone', 'contato_nome', 'apelido', 'nome_exibicao', 'modo', 'modo_display', 'situacao',
            'situacao_display', 'assumida_por', 'nao_lidas', 'etiquetas', 'lembrete', 'tem_programada',
            'motivo_transferencia',
        )},
        'telefone_formatado': formatar_telefone(conversa.telefone),
        'ultima_mensagem': {
            'em': resumo['ultima_mensagem_em'],
            'previa': resumo['ultima_mensagem_texto'],
            'tipo': getattr(conversa, '_previa_tipo', None) or '',
            'direcao': resumo['ultima_mensagem_direcao'] or '',
        },
        'janela': {'aberta': resumo['janela_aberta'], 'expira_em': resumo['janela_expira_em']},
        # Nomes dos clientes só no painel (lá o escopo de lojas é aplicado).
        'total_clientes': len(resumo['clientes']),
    }


def itens_lista(conversas) -> list[dict]:
    agora = timezone.now()
    return [item_lista(conversa, agora) for conversa in conversas]


def conversa_anotada(conversa_id: int) -> Conversa:
    return anotar_lista(Conversa.objects.filter(pk=conversa_id)).get()


def estado(conversa_id: int, usuario) -> dict:
    """Cabeçalho e compositor: resumo, trava de resposta e ações que a tela oferece."""
    conversa = conversa_anotada(conversa_id)
    bloqueio = bloqueio_de(conversa, usuario)
    return {
        **item_lista(conversa),
        'clientes_nomes': organizacao.nomes_dos_clientes(conversa, usuario),
        'pode_responder': bloqueio is None,
        'bloqueio': None if bloqueio is None else {'motivo': bloqueio['motivo'], 'mensagem': bloqueio['detail']},
        'acoes': acoes_disponiveis(conversa, usuario),
    }


def painel(conversa: Conversa, usuario) -> dict:
    """Clientes vinculados que o usuário vê (escopo de lojas), sugeridos pelo telefone e pagamentos."""
    return organizacao.painel(conversa, usuario)


def detalhe(conversa: Conversa, usuario) -> dict:
    return {
        **estado(conversa.pk, usuario),
        'painel': painel(conversa, usuario),
        **_anotacoes(conversa, usuario),  # notas (100 mais recentes) e programadas agendadas
    }


# --- mensagens ------------------------------------------------------------------------------

def _urls_midia(dados: dict) -> dict:
    midia = dados.get('midia')
    if not midia:
        return dados
    disponivel = midia['status'] == Midia.Status.OK
    url = reverse(ROTA_MIDIA, args=[dados['id']]) if disponivel else None
    miniatura = f'{url}?versao={VERSAO_MINIATURA}' if url and midia['tem_miniatura'] else None
    return {**dados, 'midia': {**midia, 'url': url, 'url_miniatura': miniatura}}


def _rotulos(dados: dict) -> dict:
    return {
        **dados,
        'tipo_display': Mensagem.Tipo(dados['tipo']).label,
        'status_display': Mensagem.Status(dados['status']).label,
        'autor_display': Mensagem.Autor(dados['autor']).label,
    }


def mensagens_api(mensagens: list[Mensagem]) -> list[dict]:
    return [_rotulos(_urls_midia(dados)) for dados in mensagens_dicts(mensagens)]


def mensagem_api(mensagem_id: int) -> dict:
    mensagem = (Mensagem.objects.select_related('usuario', 'responde_a', 'midia', 'conversa')
                .get(pk=mensagem_id))
    return mensagens_api([mensagem])[0]


def pagina_mensagens(conversa: Conversa, antes: Mensagem | None, limite: int) -> dict:
    """Página em ordem cronológica, da mais recente para trás (cursor = id da mais antiga já vista).

    O cursor segue a mesma ordem da lista (`criado_em`, `id`), então reentregas com horário
    antigo não somem nem se repetem entre páginas.
    """
    qs = base_mensagens(conversa)
    if antes is not None:
        qs = qs.filter(Q(criado_em__lt=antes.criado_em) | Q(criado_em=antes.criado_em, id__lt=antes.pk))
    pagina = list(qs.order_by('-criado_em', '-id')[:limite + 1])
    tem_mais = len(pagina) > limite
    visiveis = list(reversed(pagina[:limite]))
    return {
        'results': mensagens_api(visiveis),
        'tem_mais_antigas': tem_mais,
        'proximo_cursor': visiveis[0].pk if tem_mais and visiveis else None,
    }
