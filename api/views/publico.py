"""Endpoints públicos: health check, contrato por token e busca de lojas no login."""
import logging
import re

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.services import lojas_para_login
from api.throttles import LimitePublicoThrottle
from vendas.models import Pagamento, Venda


logger = logging.getLogger(__name__)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


def _montar_payload_contrato(venda, loja):
    valor_total = venda.pagamentos_valor_total
    pagamento_carne = Pagamento.objects.filter(venda=venda, tipo_pagamento__carne=True).first()
    aparelho = venda.itens_venda.first()
    imei = aparelho.imei if aparelho else None

    cliente = venda.cliente
    contrato = loja.contrato
    comprovantes = getattr(cliente, "comprovantes", None)
    foto_cliente_comprovantes = getattr(comprovantes, "foto_cliente", None)

    primeira_parcela = pagamento_carne.data_primeira_parcela if pagamento_carne else None
    parcelas = pagamento_carne.parcelas if pagamento_carne else 0
    parcelas_meses = []

    if primeira_parcela and parcelas:
        for i in range(parcelas):
            mes = primeira_parcela.month + i
            ano = primeira_parcela.year
            if mes > 12:
                mes -= 12
                ano += 1
            data_vencimento = primeira_parcela.replace(month=mes, year=ano)
            parcelas_meses.append(data_vencimento.strftime('%d/%m/%Y'))

    ultima_parcela = parcelas_meses[-1] if parcelas_meses else None

    return {
        'venda_id': venda.id,
        'status_contrato': venda.status_contrato,
        'valor_total': str(valor_total),
        'tipo_pagamento': 'Carnê' if pagamento_carne else 'À vista',
        'cliente': {
            'nome': cliente.nome,
            'cpf': cliente.cpf,
            'rg': cliente.rg,
            'nascimento': cliente.nascimento.isoformat() if cliente.nascimento else None,
            'endereco': cliente.endereco,
            'telefone': cliente.telefone,
            'telefone_secundario': cliente.telefone_secundario,
        },
        'comprovantes': {
            'foto_cliente': (
                foto_cliente_comprovantes.url if foto_cliente_comprovantes else None
            ),
        },
        'data_atual': timezone.now().date().isoformat(),
        'loja': {
            'nome': loja.nome,
            'cnpj': loja.cnpj,
            'endereco': loja.endereco,
            'contrato': contrato,
        },
        'aparelho': {
            'nome': aparelho.produto.nome if aparelho else None,
            'imei': imei,
        },
        'valor_parcela': str(pagamento_carne.valor_parcela) if pagamento_carne else None,
        'quantidade_parcelas': parcelas,
        'parcelas_meses': parcelas_meses,
        'primeira_parcela': primeira_parcela.strftime('%d/%m/%Y') if primeira_parcela else None,
        'ultima_parcela': ultima_parcela,
        'documento_assinado_url': (
            venda.documento_assinado.url if venda.documento_assinado else None
        ),
    }


def _normalizar_rg(valor):
    return re.sub(r'[^0-9A-Za-z]', '', (valor or '')).upper()


def _normalizar_cpf(valor):
    return re.sub(r'[^0-9]', '', (valor or ''))


def _coletar_campo_aceite(dados):
    for campo in ("concorda_contrato", "aceite_contrato", "aceito", "concorda"):
        if campo in dados:
            return dados.get(campo)
    return None


def _valor_booleano(valor):
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False
    return str(valor).strip().lower() in {"1", "true", "t", "sim", "yes", "on"}


def _validar_confirmacao_contrato(venda, dados):
    cpf = (dados.get("cpf") or "").strip()
    if not cpf:
        return False, 'Informe o CPF.'

    nascimento_raw = dados.get("nascimento") or dados.get("data_nascimento")
    if not nascimento_raw:
        return False, 'Informe a data de nascimento.'

    nascimento = parse_date(str(nascimento_raw).strip())
    if not nascimento:
        return False, 'Data de nascimento invalida. Use o formato YYYY-MM-DD.'

    if _normalizar_cpf(cpf) != _normalizar_cpf(venda.cliente.cpf):
        return False, 'CPF informado nao confere com o cadastro.'

    if nascimento != venda.cliente.nascimento:
        return False, 'Data de nascimento informada nao confere com o cadastro.'

    if not _valor_booleano(_coletar_campo_aceite(dados)):
        return False, 'Voce precisa concordar com o contrato para concluir.'

    return True, None


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@throttle_classes([LimitePublicoThrottle])
def contrato_publico(request, token):
    venda = get_object_or_404(Venda, contrato_publico_uuid=token)

    if request.method == "GET":
        payload = _montar_payload_contrato(venda, venda.loja)
        return Response(payload)

    confirmacao_valida, erro = _validar_confirmacao_contrato(venda, request.data)
    if not confirmacao_valida:
        return Response({"detail": erro}, status=400)

    venda.status_contrato = Venda.CONTRATO_STATUS_ASSINADO
    venda.save(update_fields=["status_contrato"])

    return Response(
        {
            "detail": "Concordancia com o contrato registrada com sucesso.",
            "status_contrato": venda.status_contrato,
        },
        status=201,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([LimitePublicoThrottle])
def buscar_lojas_by_username(request):
    """Lojas do usuário antes do login. Usuário inexistente responde igual a um sem
    loja (lista vazia), para a rota não servir para descobrir quem tem conta."""
    username = request.query_params.get("username")
    if not username:
        return Response({"error": "Username não fornecido"}, status=400)
    return Response({"lojas": lojas_para_login(username)})
