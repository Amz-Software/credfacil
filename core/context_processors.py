from urllib import request

from django.urls import reverse

from vendas.models import Loja


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
            "label": "Caixa",
            "url_name": "vendas:caixa_list",
            "icon": "bx bx-money",
            "permission": "vendas.view_caixa",
            "section": "Vendas",
        },
        {
            "label": "Solicitações de Crédito",
            "url_name": "vendas:cliente_list",
            "icon": "bx bx-id-card",
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
            "permission": "vendas.can_view_produtos_vendidos",
            "section": "Vendas",
        },
        {
            "label": "Gráfico de Vendas",
            "url_name": "vendas:grafico",
            "icon": "bx bx-line-chart",
            "permission": "vendas.can_view_all_dashboard",
            "section": "Vendas",
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
                    "permission": "vendas.view_pagamento",
                },
                {
                    "label": "Relatório de Situações",
                    "url_name": "financeiro:relatorio_contas_a_receber_avancado",
                    "permission": "vendas.view_pagamento",
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
                {
                    "label": "Relatório de Saídas",
                    "url_name": "financeiro:relatorio_saidas",
                    "permission": "vendas.can_generate_report_sale",
                },
            ],
        },
        # {
        #     "label": "Fechamentos Mensais",
        #     "url_name": "financeiro:caixa_mensal_list",
        #     "icon": "bx bx-calendar-check",
        #     "permission": "financeiro.view_caixamensal",
        #     "section": "Financeiro",
        # },
        # {
        #     "label": "Gastos Fixos",
        #     "url_name": "financeiro:gasto_fixo_list",
        #     "icon": "bx bx-money-withdraw",
        #     "permission": "financeiro.view_gastofixo",
        #     "section": "Financeiro",
        # },
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
            "label": "Parcelamentos",
            "url_name": "produtos:parcelamentos",
            "icon": "bx bx-credit-card",
            "permission": "produtos.view_parcelamento",
            "section": "Catálogo",
        },
        # ── ESTOQUE (desativado — manter para referência futura) ────────
        # {
        #     "label": "Estoque",
        #     "icon": "bx bx-box",
        #     "permission": "estoque.view_estoque",
        #     "section": "Estoque",
        #     "sub_items": [
        #         {"label": "Ver Estoque", "url_name": "estoque:estoque_list", "permission": "estoque.view_estoque"},
        #         {"label": "Estoque IMEI", "url_name": "estoque:estoque_imei_list", "permission": "estoque.view_estoqueimei"},
        #         {"label": "Ver Entradas", "url_name": "estoque:entrada_list", "permission": "estoque.view_entradaestoque"},
        #         {"label": "Adicionar Entrada", "url_name": "estoque:estoque_entrada", "permission": "estoque.add_entradaestoque"},
        #         {"label": "Fornecedores", "url_name": "estoque:fornecedores", "permission": "estoque.view_fornecedor"},
        #     ],
        # },
        # ── ASSISTÊNCIA (desativado — manter para referência futura) ────
        # {
        #     "label": "Assistência",
        #     "icon": "bx bx-wrench",
        #     "permission": "assistencia.view_assistencia",
        #     "section": "Assistência",
        #     "sub_items": [
        #         {"label": "Caixa Assistência", "url_name": "assistencia:caixa_assistencia_list", "permission": "assistencia.view_assistencia"},
        #         {"label": "Ordens de Serviço", "url_name": "assistencia:ordem_servico_list", "permission": "assistencia.view_ordemservico"},
        #     ],
        # },
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

    current_path = request.path

    filtered_items = []
    sections = {}

    for item in items:
        item["active"] = False
        if "sub_items" in item:
            visible_sub_items = []
            for sub_item in item["sub_items"]:
                sub_item["url"] = reverse(sub_item["url_name"])
                if sub_item.get("permission") in request.user.get_all_permissions():
                    visible_sub_items.append(sub_item)
                    if sub_item["url"] == current_path:
                        item["active"] = True
                        sub_item["active"] = True
                    else:
                        sub_item["active"] = False
            item["sub_items"] = visible_sub_items
            if visible_sub_items:
                filtered_items.append(item)
        else:
            item["url"] = reverse(item["url_name"]) if "url_name" in item else None
            if item.get("permission") in request.user.get_all_permissions():
                filtered_items.append(item)
                if item["url"] == current_path:
                    item["active"] = True
            elif "header" in item:
                filtered_items.append(item)

    for item in filtered_items:
        section = item["section"]
        if section not in sections:
            sections[section] = []
        sections[section].append(item)

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
