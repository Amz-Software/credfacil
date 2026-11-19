from django.urls import reverse

from vendas.models import Loja


RAIZ = "/"


def _corresponde(caminho: str, url: str | None) -> bool:
    """A tela pertence ao item: mesma URL ou subcaminho dela (detalhe, edição...).

    A raiz só vale para a própria página inicial.
    """
    if not url:
        return False
    if caminho == url or url == RAIZ:
        return caminho == url
    base = url if url.endswith("/") else f"{url}/"
    return caminho.startswith(base)


def _marcar_item_ativo(itens: list[dict], caminho: str) -> None:
    """Marca como ativo o item (e o pai, se for subitem) com a URL mais longa que contém o caminho."""
    candidatos = [
        (item, sub_item)
        for item in itens
        for sub_item in (item.get("sub_items") or [None])
    ]
    for item, sub_item in candidatos:
        item["active"] = False
        if sub_item is not None:
            sub_item["active"] = False

    correspondentes = [
        (item, sub_item)
        for item, sub_item in candidatos
        if _corresponde(caminho, (sub_item or item).get("url"))
    ]
    if not correspondentes:
        return
    item, sub_item = max(correspondentes, key=lambda par: len((par[1] or par[0])["url"]))
    item["active"] = True
    if sub_item is not None:
        sub_item["active"] = True


def menu_items(request):
    # Cada item da sidebar.
    #   - Itens simples (link direto): possuem "url_name".
    #   - Itens com submenu (dropdown): possuem "sub_items" (sem "url_name").
    #   - "section" define o cabeçalho/grupo onde o item aparece.
    # A visibilidade é controlada por "permission": um item simples só aparece
    # se o usuário tiver a permissão; um dropdown aparece se tiver ao menos um
    # sub-item visível.
    items = [
        # ── INÍCIO ──────────────────────────────────────────────────────
        {
            "label": "Página Inicial",
            "url_name": "vendas:index",
            "icon": "bx bx-home-circle",
            "permission": "vendas.view_loja",
            "section": "Início",
        },
        {
            "label": "Guia do Sistema",
            "url_name": "vendas:guia",
            "icon": "bx bx-book-open",
            "permission": "vendas.view_loja",
            "section": "Início",
        },
        # ── VENDAS (operação do dia a dia) ──────────────────────────────
        {
            "label": "Solicitações de Crédito",
            "url_name": "vendas:cliente_list",
            "icon": "bx bx-id-card",
            "permission": "vendas.view_cliente",
            "section": "Vendas",
        },
        {
            "label": "Análises Rápidas",
            "url_name": "vendas:pre_analise_rapida_list",
            "icon": "bx bx-bolt-circle",
            "permission": "vendas.view_cliente",
            "section": "Vendas",
        },
        {
            "label": "Vendas",
            "url_name": "vendas:venda_list",
            "icon": "bx bx-receipt",
            "permission": "vendas.view_venda",
            "section": "Vendas",
        },
        {
            "label": "Produtos Vendidos",
            "url_name": "vendas:produto_vendido_list",
            "icon": "bx bx-cart-alt",
            "permission": "vendas.view_produtovenda",
            "section": "Vendas",
        },
        {
            "label": "Gráfico de Vendas",
            "url_name": "vendas:grafico",
            "icon": "bx bx-line-chart",
            "permission": "vendas.can_view_all_dashboard",
            "section": "Vendas",
        },
        # ── ATENDIMENTO (CRM de WhatsApp; só no backoffice) ─────────────
        {
            "label": "CRM WhatsApp",
            "icon": "bx bxl-whatsapp",
            "permission": "crm.acessar_crm",
            "section": "Atendimento",
            "sub_items": [
                {
                    "label": "Conversas",
                    "url_name": "crm:caixa",
                    "permission": "crm.acessar_crm",
                },
                {
                    "label": "Configuração",
                    "url_name": "crm:configuracao",
                    "permission": "crm.gerenciar_crm",
                },
            ],
        },
        # ── FINANCEIRO ──────────────────────────────────────────────────
        {
            "label": "Contas a Receber",
            "icon": "bx bx-wallet",
            "permission": "vendas.view_pagamento",
            "section": "Financeiro",
            "sub_items": [
                {
                    "label": "Contas a Receber",
                    "url_name": "financeiro:contas_a_receber_list",
                    "permission": "vendas.view_pagamento",
                },
                {
                    "label": "Relatório de Contas a Receber",
                    "url_name": "financeiro:relatorio_contas_a_receber",
                    "permission": "vendas.can_genarate_report_payments",
                },
                {
                    "label": "Relatório de Situações",
                    "url_name": "financeiro:relatorio_contas_a_receber_avancado",
                    "permission": "vendas.can_genarate_report_payments",
                },
                {
                    "label": "Relatório de Parcelas",
                    "url_name": "financeiro:relatorio_parcelas",
                    "permission": "vendas.can_genarate_report_payments",
                },
            ],
        },
        {
            "label": "Relatórios",
            "icon": "bx bx-file",
            "permission": "vendas.can_generate_report_sale",
            "section": "Financeiro",
            "sub_items": [
                {
                    "label": "Relatório de Solicitações",
                    "url_name": "vendas:form_solicitacao_relatorio",
                    "permission": "vendas.can_generate_report_sale",
                },
                {
                    "label": "Relatório de Vendas",
                    "url_name": "vendas:venda_relatorio",
                    "permission": "vendas.can_generate_report_sale",
                },
            ],
        },
        # ── CATÁLOGO ────────────────────────────────────────────────────
        {
            "label": "Produtos",
            "url_name": "produtos:produtos",
            "icon": "bx bx-package",
            "permission": "produtos.view_produto",
            "section": "Catálogo",
        },
        {
            "label": "Marcas",
            "url_name": "produtos:marcas",
            "icon": "bx bx-purchase-tag",
            "permission": "produtos.view_marca",
            "section": "Catálogo",
        },
        {
            "label": "Tipos de Produto",
            "url_name": "produtos:tipos",
            "icon": "bx bx-category",
            "permission": "produtos.view_tipoproduto",
            "section": "Catálogo",
        },
        {
            "label": "Parcelamentos",
            "url_name": "produtos:parcelamentos",
            "icon": "bx bx-credit-card",
            "permission": "produtos.view_parcelamento",
            "section": "Catálogo",
        },
        # ── CONFIGURAÇÕES ───────────────────────────────────────────────
        {
            "label": "Lojas",
            "url_name": "vendas:loja_list",
            "icon": "bx bx-store",
            "permission": "vendas.view_loja",
            "section": "Configurações",
        },
        {
            "label": "Usuários e Acessos",
            "icon": "bx bx-group",
            "permission": "auth.view_user",
            "section": "Configurações",
            "sub_items": [
                {
                    "label": "Usuários",
                    "url_name": "accounts:user_list",
                    "permission": "accounts.view_user",
                },
                {
                    "label": "Grupos",
                    "url_name": "accounts:group_list",
                    "permission": "auth.view_group",
                },
                {
                    "label": "Permissões",
                    "url_name": "accounts:permissions_list",
                    "permission": "auth.view_permission",
                },
            ],
        },
        {
            "label": "Números Autenticadores",
            "url_name": "vendas:numeroautenticador_list",
            "icon": "bx bx-phone",
            "permission": "vendas.view_numeroautenticador",
            "section": "Configurações",
        },
        {
            "label": "Meu Perfil",
            "url_name": "accounts:my_profile_update",
            "icon": "bx bx-user-circle",
            "permission": "accounts.view_own_user",
            "section": "Configurações",
        },
    ]

    permissoes = request.user.get_all_permissions()
    filtered_items = []
    for item in items:
        if "sub_items" in item:
            item["sub_items"] = [
                {**sub_item, "url": reverse(sub_item["url_name"])}
                for sub_item in item["sub_items"]
                if sub_item.get("permission") in permissoes
            ]
            if item["sub_items"]:
                filtered_items.append(item)
        else:
            item["url"] = reverse(item["url_name"]) if "url_name" in item else None
            if item.get("permission") in permissoes or "header" in item:
                filtered_items.append(item)

    _marcar_item_ativo(filtered_items, request.path)

    sections = {}
    for item in filtered_items:
        sections.setdefault(item["section"], []).append(item)

    return {"menu_items": sections}


def loja(request):
    loja_id = request.session.get("loja_id", None)

    loja = Loja.objects.filter(pk=loja_id).first()
    if loja:
        return {"loja_atual": loja}
    return {}


def notificacoes_usuario(request):
    if request.user.is_authenticated:
        return {"notificacoes_nao_lidas": request.user.notifications.unread()[:5]}
    return {}
