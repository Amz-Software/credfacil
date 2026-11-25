"""Conversa no CRM a partir de uma conta a receber (Pagamento do crediário).

A conta conhece o cliente e a parcela, então aqui as aberturas de cobrança ({valor} e
{vencimento}) também podem ser enviadas pela equipe, com os valores vindos do banco.
"""
from django.utils import timezone

from crm.models import ModeloAbertura, VersaoAbertura
from crm.services import aberturas
from crm.services.cobranca import _parcelas_abertas
from crm.services.conversas import conversa_do_telefone
from crm.services.pagamentos import formatar_reais
from crm.telefone import chave_telefone, com_ddi, formatar_telefone

TELEFONES = (('Principal', 'telefone'), ('Secundário', 'telefone_secundario'))
DIGITOS_MINIMOS = 12


def parcela_de_referencia(pagamento):
    """A parcela em aberto mais antiga (a vencida mais velha ou, sem atraso, a próxima)."""
    return _parcelas_abertas().filter(pagamento=pagamento).order_by('data_vencimento', 'pk').first()


def valores_de_cobranca(parcela) -> dict[str, str] | None:
    if parcela is None:
        return None
    return {'valor': formatar_reais(parcela.valor_restante),
            'vencimento': parcela.data_vencimento.strftime('%d/%m/%Y')}


def primeiro_nome(cliente) -> str:
    partes = (cliente.nome or '').split()
    return partes[0].capitalize() if partes else ''


def _conversa_resumo(numero: str) -> dict | None:
    conversa = conversa_do_telefone(numero, criar=False)
    if conversa is None:
        return None
    dono = conversa.assumida_por
    return {
        'id': conversa.pk,
        'janela_aberta': conversa.janela_aberta(),
        'assumida_por': (dono.get_full_name() or dono.username) if dono else None,
    }


def _numeros(cliente) -> list[tuple[str, str]]:
    """(rótulo, número com 55) dos telefones válidos do cliente, sem repetir."""
    resultado: list[tuple[str, str]] = []
    for rotulo, campo in TELEFONES:
        numero = com_ddi(getattr(cliente, campo, '') or '')
        if len(numero) >= DIGITOS_MINIMOS and all(n != numero for _, n in resultado):
            resultado.append((rotulo, numero))
    return resultado


def telefones(cliente) -> list[dict]:
    return [{'rotulo': rotulo, 'telefone': numero, 'telefone_formatado': formatar_telefone(numero),
             'conversa': _conversa_resumo(numero)} for rotulo, numero in _numeros(cliente)]


def telefone_do_cliente(cliente, telefone: str) -> bool:
    """O número é um dos telefones cadastrados do cliente (compara sem o 9º dígito)."""
    chave = chave_telefone(telefone)
    return any(chave_telefone(numero) == chave for _, numero in _numeros(cliente))


def _abertura(modelo: ModeloAbertura, valores: dict[str, str], tem_parcela: bool) -> dict:
    vigente = next((v for v in modelo.versoes.all() if v.vigente), None)
    ultima = max(modelo.versoes.all(), key=lambda v: v.versao, default=None)
    exibida = vigente or ultima
    cobranca = aberturas.so_cobranca(exibida)
    aprovada = bool(vigente and vigente.status == VersaoAbertura.Status.APROVADO)
    texto = exibida.corpo if exibida else ''
    for marcador, nome in aberturas.MARCADORES.items():
        if valores.get(nome):
            texto = texto.replace(marcador, valores[nome])
    return {'chave': modelo.chave, 'titulo': modelo.titulo, 'texto': texto, 'cobranca': cobranca,
            'disponivel': aprovada and (tem_parcela or not cobranca)}


def contexto(pagamento) -> dict:
    """Telefones (com a conversa de cada um, sem criar), parcela de referência e aberturas preenchidas."""
    cliente = pagamento.venda.cliente
    parcela = parcela_de_referencia(pagamento)
    valores = {'nome': primeiro_nome(cliente), **(valores_de_cobranca(parcela) or {})}
    modelos = ModeloAbertura.objects.filter(ativo=True).prefetch_related('versoes')
    return {
        'cliente': {'id': cliente.pk, 'nome': cliente.nome},
        'parcela': None if parcela is None else {
            'numero': parcela.numero_parcela, 'valor': valores['valor'], 'vencimento': parcela.data_vencimento,
            'vencida': parcela.data_vencimento < timezone.localdate(),
        },
        'telefones': telefones(cliente),
        'aberturas': [_abertura(m, valores, parcela is not None) for m in modelos],
    }
