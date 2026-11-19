"""Validações e normalizações da criação/edição de solicitações de crédito."""
import base64
from io import BytesIO
import json
import logging
import re

from django.db.models import Q
import qrcode
import secrets
import string

from produtos.models import Marca, Parcelamento
from vendas.models import Cliente, Loja


logger = logging.getLogger(__name__)


def gerar_qrcode_instalacao(cliente_id, loja_id=None, device_id=None):
    """
    Gera um QR code contendo dados de instalação do app.
    
    Args:
        cliente_id: ID do cliente
        loja_id: ID da loja (opcional)
        device_id: ID do dispositivo (opcional)
    
    Returns:
        Tuple: (qr_base64, codigo_instalacao)
    """
    from django.utils import timezone
    
    # Gerar código de instalação (token aleatório, 16 caracteres)
    caracteres = string.ascii_uppercase + string.digits
    codigo_instalacao = ''.join(secrets.choice(caracteres) for _ in range(16))
    
    # Montar dados para o QR code
    qr_data = {
        'cliente_id': cliente_id,
        'timestamp': timezone.now().isoformat(),
        'device_id': device_id or '',
        'loja_id': loja_id or '',
        'codigo_instalacao': codigo_instalacao
    }
    
    # Converter para JSON string
    qr_string = json.dumps(qr_data, ensure_ascii=False)
    
    # Gerar QR code (mesmo formato do web)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4
    )
    qr.add_data(qr_string)
    qr.make(fit=True)
    img = qr.make_image()
    
    # Converter para base64
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    return qr_base64, codigo_instalacao


def _avisos_solicitacoes_existentes(
    *, cpf=None, rg=None, nome=None, telefone=None, telefone_secundario=None,
    exclude_cliente_id=None
):
    filtros = Q()
    if cpf:
        filtros |= Q(cpf=cpf)
    if rg:
        filtros |= Q(rg=rg)
    if nome:
        filtros |= Q(nome__iexact=nome)
    telefones = [numero for numero in [telefone, telefone_secundario] if numero]
    if telefones:
        filtros |= Q(telefone__in=telefones) | Q(telefone_secundario__in=telefones)

    if not filtros:
        return None

    qs = Cliente.objects.filter(filtros).select_related("analise_credito")
    if exclude_cliente_id:
        qs = qs.exclude(pk=exclude_cliente_id)

    if not qs.exists():
        return None

    detalhes = []
    for cliente in qs[:5]:
        analise = getattr(cliente, "analise_credito", None)
        if analise:
            detalhes.append(
                f"Solicitacao #{analise.id} (Cliente {cliente.nome}, status {analise.get_status_display()})"
            )
        else:
            detalhes.append(f"Cliente #{cliente.id} ({cliente.nome})")

    total = qs.count()
    sufixo = f" +{total - len(detalhes)}" if total > len(detalhes) else ""
    mensagem = "Existem solicitacoes de credito com dados ja cadastrados (CPF, RG, Nome ou Telefones). "
    mensagem += "Encontradas: " + "; ".join(detalhes) + sufixo
    return mensagem


def _validar_parcelamento(form_analise_credito, somente_se_alterado=False):
    """
    Valida se o numero de parcelas escolhido existe em Parcelamento para a marca
    do produto. Vale para qualquer produto, nao so iPhone: gravar uma combinacao
    sem Parcelamento correspondente cria uma solicitacao que trava depois na
    aprovacao do analista (o select de parcelas fica sem a opcao e volta vazio).

    Com `somente_se_alterado=True` a checagem so roda quando produto ou numero de
    parcelas mudaram no POST, para nao bloquear a edicao de solicitacoes antigas
    que ja foram gravadas com um parcelamento hoje inexistente.

    Retorna dict de erros (formato compativel com form.errors) ou None se valido.
    """
    produto = form_analise_credito.cleaned_data.get("produto")
    if not produto:
        return None

    if somente_se_alterado:
        alterados = set(form_analise_credito.changed_data)
        if not alterados & {"produto", "numero_parcelas"}:
            return None

    marca = getattr(produto, "marca", None)
    if not marca:
        return {
            "produto": [
                "Produto sem marca vinculada. Configure a marca do produto antes de criar a solicitacao."
            ]
        }

    numero_parcelas = form_analise_credito.cleaned_data.get("numero_parcelas")

    parcelamentos_marca = Parcelamento.objects.filter(marca=marca)

    if not parcelamentos_marca.exists():
        return {
            "numero_parcelas": [
                f"Nenhum parcelamento cadastrado para a marca '{marca.nome}'. "
                "Solicite ao administrador que cadastre os parcelamentos da marca antes de criar a solicitacao."
            ]
        }

    if numero_parcelas:
        try:
            numero_parcelas_int = int(numero_parcelas)
        except (TypeError, ValueError):
            return {"numero_parcelas": ["Numero de parcelas invalido."]}

        if parcelamentos_marca.filter(qtd_vezes=numero_parcelas_int).exists():
            return None

        return {
            "numero_parcelas": [
                f"Parcelamento de {numero_parcelas}x nao cadastrado para a marca '{marca.nome}'. "
                "Solicite ao administrador que cadastre o parcelamento correspondente."
            ]
        }

    return None


def _validar_marca_produto_solicitacao(request_data, produto):
    marca_id_raw = request_data.get("marca")

    if marca_id_raw in (None, ""):
        return {"marca": ["Este campo e obrigatorio."]}

    try:
        marca_id = int(marca_id_raw)
    except (TypeError, ValueError):
        return {"marca": ["Informe um id de marca valido."]}

    if not Marca.objects.filter(id=marca_id).exists():
        return {"marca": ["Marca informada nao encontrada."]}

    if not produto:
        return None

    if not produto.marca_id:
        return {"produto": ["O produto informado nao possui marca vinculada."]}

    if produto.marca_id != marca_id:
        return {
            "produto": [
                "O produto informado nao pertence a marca selecionada."
            ]
        }

    return None


def _normalizar_campos_opcionais_solicitacao(request_data):
    """
    Normaliza aliases de campos opcionais aceitos no payload de solicitacao.
    Isso evita erro de validacao quando o frontend envia nomes por bloco.
    """
    # Nao usar request_data.copy() em multipart, pois QueryDict.copy()
    # faz deepcopy e pode falhar com arquivos abertos (InMemory/TemporaryUploadedFile).
    if hasattr(request_data, "dict"):
        data = request_data.dict()
    elif isinstance(request_data, dict):
        data = request_data.copy()
    else:
        data = dict(request_data)

    aliases = {
        "obteve_contato_adicional": "obteve_contato",
        "contato_adicional.obteve_contato_adicional": "obteve_contato",
        "informacao_pessoal.obteve_contato_pessoal": "obteve_contato_pessoal",
    }

    for alias_key, target_key in aliases.items():
        alias_value = data.get(alias_key)
        target_value = data.get(target_key)
        if alias_value not in (None, "") and target_value in (None, ""):
            data[target_key] = alias_value

    def _to_bool_choice_str(value):
        if isinstance(value, bool):
            return "True" if value else "False"
        if value is None:
            return None

        value_str = str(value).strip().lower()
        if value_str == "":
            return None
        if value_str in ("1", "true"):
            return "True"
        if value_str in ("0", "false"):
            return "False"
        return value

    bool_fields = [
        "recebe_auxilio",
        "analise_online",
        "restricao",
        "obteve_contato",
        "obteve_contato_pessoal",
    ]

    for field_name in bool_fields:
        if field_name in data:
            data[field_name] = _to_bool_choice_str(data.get(field_name))

    return data


def _resolver_loja_solicitacao(request, payload_data):
    """
    Resolve a loja para criacao de solicitacao com prioridade:
    1) sessao (loja_id)
    2) payload/query param `loja`
    3) fallback do usuario autenticado
    """
    user = request.user

    session_loja_id = request.session.get("loja_id")
    if session_loja_id:
        loja = Loja.objects.filter(id=session_loja_id).first()
        if loja:
            return loja, None

    loja_raw = payload_data.get("loja")
    if loja_raw in (None, ""):
        loja_raw = request.query_params.get("loja")

    if loja_raw not in (None, ""):
        try:
            loja_id = int(loja_raw)
        except (TypeError, ValueError):
            return None, "Parametro loja invalido."

        loja = Loja.objects.filter(id=loja_id).first()
        if not loja:
            return None, "Loja informada nao encontrada."

        if user.has_perm("vendas.can_view_all_stores"):
            return loja, None

        user_lojas = getattr(user, "lojas", None)
        has_access = False
        if user_lojas is not None and user_lojas.filter(id=loja_id).exists():
            has_access = True
        if getattr(user, "loja_id", None) == loja_id:
            has_access = True

        if not has_access:
            return None, "Sem acesso a loja informada."

        return loja, None

    if getattr(user, "loja_id", None):
        loja = Loja.objects.filter(id=user.loja_id).first()
        if loja:
            return loja, None

    user_lojas = getattr(user, "lojas", None)
    if user_lojas is not None:
        lojas_ids = list(user_lojas.values_list("id", flat=True))
        if len(lojas_ids) == 1:
            loja = Loja.objects.filter(id=lojas_ids[0]).first()
            if loja:
                return loja, None

    return None, "Loja nao encontrada na sessao."


MIN_DIGITOS_BUSCA_CPF = 3


def _filtro_busca_solicitacao(termo: str) -> Q:
    """Busca por nome ou CPF. O CPF é gravado só com dígitos, então a máscara
    do termo é ignorada; poucos dígitos não disparam a busca por CPF."""
    filtro = Q(nome__icontains=termo)
    digitos = re.sub(r"\D", "", termo)
    if len(digitos) >= MIN_DIGITOS_BUSCA_CPF:
        filtro |= Q(cpf__contains=digitos)
    return filtro
