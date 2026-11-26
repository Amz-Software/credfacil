"""Transições da análise de crédito: status, aplicativo, iCloud e IMEI."""
import logging

from django.db import transaction
from django.utils import timezone

from estoque.models import EstoqueImei
from vendas.models import AnaliseCreditoCliente

from .erros import NAO_ENCONTRADO, PROIBIDO, ErroDeNegocio
from .notificacoes import GRUPOS_ANALISE, GRUPOS_ANALISE_E_VENDAS, notificar_grupos

logger = logging.getLogger(__name__)

GRUPO_ANALISTA = 'ANALISTA'
APP_PENDENTE = 'P'
APP_CONFIRMACAO_PENDENTE = 'C'
APP_INSTALADO = 'I'
DIGITOS_IMEI_VENDEDOR = 4


def _nome(texto: str | None, padrao: str) -> str:
    return (texto or padrao).capitalize()


def _registrar_modificacao(analise: AnaliseCreditoCliente, usuario) -> None:
    analise.modificado_por = usuario
    analise.modificado_em = timezone.now()
    analise.save()


def exigir_analista(usuario, mensagem: str) -> None:
    if not usuario.groups.filter(name=GRUPO_ANALISTA).exists():
        raise ErroDeNegocio(mensagem, codigo=PROIBIDO)


def analise_do_cliente(cliente) -> AnaliseCreditoCliente:
    analise = getattr(cliente, 'analise_credito', None)
    if analise is None:
        raise ErroDeNegocio('Análise não encontrada para este cliente.', codigo=NAO_ENCONTRADO)
    return analise


def digitos_imei(valor, limite: int = DIGITOS_IMEI_VENDEDOR) -> str:
    """Só os dígitos do valor informado, cortados em `limite` (padrão: 4)."""
    return ''.join(filter(str.isdigit, str(valor or '')))[:limite]


# ─── Status da análise ──────────────────────────────────────────────────────

def aprovar_analise(analise: AnaliseCreditoCliente, usuario) -> AnaliseCreditoCliente:
    analise.aprovar(user=usuario)
    _registrar_modificacao(analise, usuario)
    return analise


def reprovar_analise(analise: AnaliseCreditoCliente, usuario) -> AnaliseCreditoCliente:
    analise.reprovar()
    _registrar_modificacao(analise, usuario)
    return analise


def cancelar_analise(
    analise: AnaliseCreditoCliente, usuario, *, desfazer_venda: bool = False,
) -> AnaliseCreditoCliente:
    """Cancela a análise.

    Com `desfazer_venda=True` (fluxo da API/SPA) também cancela a venda gerada
    (soft delete) e devolve o IMEI ao estoque; o backoffice só muda o status.
    """
    with transaction.atomic():
        analise.cancelar()
        _registrar_modificacao(analise, usuario)
        if not desfazer_venda:
            return analise

        venda = analise.venda
        if venda and not venda.is_deleted:
            venda.is_deleted = True
            venda.save(user=usuario)
        if analise.imei:
            analise.imei.vendido = False
            analise.imei.save(user=usuario)
    return analise


# ─── Aplicativo (Android) ──────────────────────────────────────────────────

def atualizar_status_aplicativo(analise: AnaliseCreditoCliente, novo_status) -> AnaliseCreditoCliente:
    if novo_status not in dict(AnaliseCreditoCliente.STATUS_APP_CHOICES):
        raise ErroDeNegocio('Status inválido.')
    analise.status_aplicativo = novo_status
    analise.save()
    return analise


def marcar_instalacao_pendente(analise: AnaliseCreditoCliente) -> AnaliseCreditoCliente:
    """Vendedor indicou que instalou o app: aguarda a confirmação."""
    return atualizar_status_aplicativo(analise, APP_CONFIRMACAO_PENDENTE)


def validar_vendedor_pode_confirmar_instalacao(analise: AnaliseCreditoCliente) -> None:
    """A confirmação do vendedor só vale uma vez: repetir não pode retroceder o status.

    Com o app já instalado ('I'), gravar 'C' de novo obrigaria a analista a
    confirmar outra vez; com 'C', só repetiria o aviso aos analistas.
    """
    if analise.status_aplicativo == APP_INSTALADO:
        raise ErroDeNegocio('A instalação do aplicativo já foi confirmada pela analista.')
    if analise.status_aplicativo == APP_CONFIRMACAO_PENDENTE:
        raise ErroDeNegocio('Você já confirmou a instalação. Aguarde a analista validar.')


def confirmar_instalacao_vendedor(analise: AnaliseCreditoCliente, usuario, *, digitos: str = '') -> AnaliseCreditoCliente:
    """Vendedor confirmou a instalação (leitura do QR code): avisa analistas para informarem o IMEI."""
    validar_vendedor_pode_confirmar_instalacao(analise)
    if digitos:
        analise.imei_ultimos_digitos_vendedor = digitos
    analise.status_aplicativo = APP_CONFIRMACAO_PENDENTE
    analise.save()

    cliente = analise.cliente
    description = f'Aguardando analista informar IMEI. Loja: {_nome(cliente.loja.nome, "Loja")}.'
    if digitos:
        description += f' IMEI termina em {digitos}.'
    notificar_grupos(
        grupos=GRUPOS_ANALISE, autor=usuario, instance=analise, target=cliente,
        verb=f'Vendedor confirmou instalação do app para cliente {_nome(cliente.nome, "Cliente")}.',
        description=description,
    )
    return analise


def confirmar_instalacao_analista(
    analise: AnaliseCreditoCliente, usuario, *, target_url: str | None = None,
) -> AnaliseCreditoCliente:
    exigir_analista(usuario, 'Apenas analistas podem confirmar a instalação.')
    if not analise.imei:
        raise ErroDeNegocio('IMEI deve estar informado para confirmar a instalação.')
    if analise.status_aplicativo != APP_CONFIRMACAO_PENDENTE:
        raise ErroDeNegocio(
            'Status do aplicativo deve estar "Aguardando Confirmação" para confirmar a instalação.'
        )

    analise.status_aplicativo = APP_INSTALADO
    analise.save()

    # O popup do VENDEDOR (event=instalacao_confirmada) é disparado pelo signal
    # ao detectar status_aplicativo -> 'I'. Aqui notificamos apenas admin/analista.
    cliente = analise.cliente
    notificar_grupos(
        grupos=GRUPOS_ANALISE, autor=usuario, instance=analise, target=cliente,
        verb=f'Analista confirmou instalação do app para cliente {_nome(cliente.nome, "Cliente")}.',
        description=(
            f'IMEI {analise.imei.imei} da loja {_nome(cliente.loja.nome, "Loja")}. '
            'Venda liberada para geração.'
        ),
        target_url=target_url,
    )
    return analise


# ─── iCloud (iPhone) ───────────────────────────────────────────────────────

def configurar_icloud(analise: AnaliseCreditoCliente, usuario, imei_ultimos_digitos) -> AnaliseCreditoCliente:
    """Vendedor confirma a configuração inicial do iPhone com os 4 últimos dígitos do IMEI."""
    digitos = digitos_imei(imei_ultimos_digitos)
    if len(digitos) != DIGITOS_IMEI_VENDEDOR:
        raise ErroDeNegocio('Informe os 4 últimos dígitos do IMEI para confirmar.')

    analise.imei_ultimos_digitos_vendedor = digitos
    analise.icloud_configurado_vendedor = True
    analise.save()

    cliente = analise.cliente
    notificar_grupos(
        grupos=GRUPOS_ANALISE, autor=usuario, instance=analise, target=cliente,
        verb=f'Vendedor confirmou configuração inicial para cliente {_nome(cliente.nome, "Cliente")}',
        description=(
            f'iPhone da loja {_nome(cliente.loja.nome, "Loja")}. IMEI termina em {digitos}. '
            'Aguardando analista informar IMEI.'
        ),
    )
    return analise


def confirmar_icloud_analista(analise: AnaliseCreditoCliente, usuario) -> AnaliseCreditoCliente:
    exigir_analista(usuario, 'Apenas analistas podem confirmar a configuração do iCloud.')
    if not analise.icloud_configurado_vendedor:
        raise ErroDeNegocio('Vendedor ainda não confirmou a configuração do iCloud.')

    analise.icloud_confirmado_analista = True
    analise.save()

    cliente = analise.cliente
    notificar_grupos(
        grupos=GRUPOS_ANALISE_E_VENDAS, autor=usuario, instance=analise, target=cliente,
        verb=f'Analista confirmou configuração iCloud para cliente {_nome(cliente.nome, "Cliente")}',
        description=f'iPhone da loja {_nome(cliente.loja.nome, "Loja")}. Aguardando IMEI para gerar venda.',
    )
    return analise


# ─── IMEI informado pelo analista ──────────────────────────────────────────

def validar_pode_informar_imei(analise: AnaliseCreditoCliente) -> None:
    """iPhone exige a configuração inicial do vendedor; Android, a instalação confirmada."""
    if analise.produto.is_iphone:
        if not analise.icloud_configurado_vendedor:
            raise ErroDeNegocio(
                'Só é possível informar IMEI após o vendedor confirmar a configuração inicial.'
            )
        return
    if analise.status_aplicativo != APP_CONFIRMACAO_PENDENTE:
        raise ErroDeNegocio(
            'Só é possível informar IMEI após o vendedor confirmar a instalação do aplicativo.'
        )


def _imei_em_estoque(analise: AnaliseCreditoCliente, imei: str, loja, usuario) -> tuple[EstoqueImei, bool]:
    """IMEI disponível no estoque da loja ou um novo registro. Devolve (imei, criado)."""
    existente = EstoqueImei.objects.filter(
        imei=imei, produto=analise.produto, loja=loja, vendido=False, cancelado=False,
    ).first()
    if existente:
        return existente, False
    novo = EstoqueImei(
        produto=analise.produto, imei=imei, loja=loja,
        vendido=False, aplicativo_instalado=False, cancelado=False,
    )
    try:
        novo.save(user=usuario)
    except Exception as erro:
        logger.exception('Falha ao criar o IMEI %s da análise %s', imei, analise.pk)
        raise ErroDeNegocio(
            'Não foi possível cadastrar o IMEI. Tente novamente.', corrigir_na_edicao=True,
        ) from erro
    return novo, True


def informar_imei(analise: AnaliseCreditoCliente, usuario, imei_informado, loja) -> tuple[AnaliseCreditoCliente, bool]:
    """Analista associa o IMEI (do estoque da `loja` ou novo) e libera a geração da venda.

    Devolve (análise, criado) — `criado` indica se o IMEI foi cadastrado agora.
    """
    exigir_analista(usuario, 'Apenas analistas podem informar o IMEI.')
    validar_pode_informar_imei(analise)
    imei = str(imei_informado or '').strip()
    if not imei:
        raise ErroDeNegocio('IMEI é obrigatório.', corrigir_na_edicao=True)
    if loja is None:
        raise ErroDeNegocio('Loja não encontrada para a análise.')

    estoque_imei, criado = _imei_em_estoque(analise, imei, loja, usuario)
    analise.imei = estoque_imei
    analise.imei_informado = imei
    if not analise.produto.is_iphone:
        analise.status_aplicativo = APP_INSTALADO
    analise.save()

    cliente = analise.cliente
    notificar_grupos(
        grupos=GRUPOS_ANALISE, autor=usuario, instance=analise, target=cliente,
        verb=f'Analista informou IMEI para cliente {_nome(cliente.nome, "Cliente")}.',
        description=(
            f'Imei {imei} da loja {_nome(loja.nome, "Loja")}. '
            'Venda liberada para geração pelo vendedor.'
        ),
    )
    return analise, criado
