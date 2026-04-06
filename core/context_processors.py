


from urllib import request

from django.urls import reverse

from vendas.models import Loja


def menu_items(request):
    items = [
        {
            "label": "Menu Principal",
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
        {          
            "label": "Caixa",
            "icon": "bx bx-cart",
            "permission": "vendas.view_caixa",
            "url_name": "vendas:caixa_list",
            "section": "Vendas"
        },
        {          
            "label": "Gráfico",
            "icon": "bx bx-chart",
            "permission": "vendas.can_view_all_dashboard",
            "url_name": "vendas:grafico",
            "section": "Gráfico"
        },
        # {
        #     "label": "Estoque",
        #     "icon": "bx bx-box",
        #     "permission": "estoque.view_estoque",
        #     "sub_items": [
        #         {
        #             "label": "Ver Estoque",
        #             "url_name": "estoque:estoque_list",
        #             "permission": "estoque.view_estoque"
        #         },
        #         {
        #             "label": "Estoque IMEI",
        #             "url_name": "estoque:estoque_imei_list",
        #             "permission": "estoque.view_estoqueimei"  
        #         },
        #         {
        #             "label": "Ver Entradas",
        #             "url_name": "estoque:entrada_list",
        #             "permission": "estoque.view_entradaestoque"
        #         },
        #         {
        #             "label": "Adicionar Entrada",
        #             "url_name": "estoque:estoque_entrada",
        #             "permission": "estoque.add_entradaestoque"
        #         },
        #         {
        #             "label": "Fornecedores",
        #             "url_name": "estoque:fornecedores",
        #             "permission": "estoque.view_fornecedor"
        #         }
        #     ],
        #     "section": "Estoque"
        # },   
        {
            "label": "Vendas",
            "icon": "bx bx-box",
            "permission": "vendas.view_venda",
            "section": "Vendas",
            "sub_items": [
                {
                    "label": "Solicitações de Crédito",
                    "url_name": "vendas:cliente_list",
                    "permission": "vendas.view_cliente"
                },
                {
                    "label": "Vendas",
                    "url_name": "vendas:venda_list",
                    "permission": "vendas.view_venda"
                },
                {
                    "label": "Produtos Vendidos",
                    "url_name": "vendas:produto_vendido_list",
                    "permission": "vendas.can_view_produtos_vendidos"
                },
                # {
                #     "label": "Tipo pagamento",
                #     "url_name": "vendas:tipos_pagamento",
                #     "permission": "vendas.view_tipopagamento"
                # },
            ],
        },
        {
            "label": "Financeiro",
            "icon": "bx bx-dollar-circle",
            "permission": "financeiro.view_caixamensal",
            "section": "Financeiro",
            "sub_items": [
                {
                    "label": "Caixa",
                    "url_name": "vendas:caixa_list",
                    "permission": "auth.view_user"
                },
                # {
                #     "label": "Caixa Total",
                #     "url_name": "vendas:caixa_total",
                #     "permission": "vendas.view_caixa"
                # },
                {
                    "label": "Relatório de Solicitações",
                    "url_name": "vendas:form_solicitacao_relatorio",
                    "permission": "vendas.can_generate_report_sale"
                },
                {
                    "label": "Relatório de Vendas",
                    "url_name": "vendas:venda_relatorio",
                    "permission": "vendas.can_generate_report_sale"
                },
                {
                    "label": "Relatório de Saidas",
                    "url_name": "financeiro:relatorio_saidas",
                    "permission": "vendas.can_generate_report_sale"
                },
                {
                    "label": "Contas a Receber",
                    "url_name": "financeiro:contas_a_receber_list",
                    "permission": "vendas.view_pagamento"
                },
                {
                    "label": "Relatório Contas a Receber",
                    "url_name": "financeiro:relatorio_contas_a_receber",
                    "permission": "vendas.view_pagamento"
                },
                {
                    "label": "Relatório Situações",
                    "url_name": "financeiro:relatorio_contas_a_receber_avancado",
                    "permission": "vendas.view_pagamento"
                },
                {
                    "label": "Fechamentos Mensais",
                    "url_name": "financeiro:caixa_mensal_list",
                    "permission": "financeiro.view_caixamensal"
                },
                {
                    "label": "Gastos Fixos",
                    "url_name": "financeiro:gasto_fixo_list",
                    "permission": "financeiro.view_gastofixo"
                }
            ]
        },
        {
            "label": "Produtos",
            "icon": "bx bx-box",
            "permission": "produtos.view_produto",
            "section": "Produtos",
            "sub_items": [
                {
                    "label": "Produtos",
                    "url_name": "produtos:produtos",
                    "permission": "produtos.view_produto",
                },
                {
                    "label": "Marcas",
                    "url_name": "produtos:marcas",
                    "permission": "produtos.view_marca",
                },
                {
                    "label": "Parcelamentos",
                    "url_name": "produtos:parcelamentos",
                    "permission": "produtos.view_parcelamento",
                },
            ],
        },
        # {
        #     "label": "Assistência",
        #     "icon": "bx bx-wrench",
        #     "permission": "assistencia.view_assistencia",
        #     "section": "Assistência",
        #     "sub_items": [
        #         {
        #             "label": "Caixa Assistência",
        #             "url_name": "assistencia:caixa_assistencia_list",
        #             "permission": "assistencia.view_assistencia"
        #         },
        #         {
        #             "label": "Ordens de Serviço",
        #             "url_name": "assistencia:ordem_servico_list",
        #             "permission": "assistencia.view_ordemservico"
        #         }
        #     ]
        # },
        {
            "label": "Usuários",
            "icon": "bx bx-user",
            "permission": "auth.view_user",
            "section": "Configurações",
            "sub_items": [
                {
                    "label": "Usuários",
                    "url_name": "accounts:user_list",
                    "permission": "accounts.view_user"
                },
                {
                    "label": "Grupos",
                    "url_name": "accounts:group_list",
                    "permission": "auth.view_group"
                },
                {
                    "label": "Permissões",
                    "url_name": "accounts:permissions_list",
                    "permission": "auth.view_permission"
                },
            ]
        },
        {
            "label": "Lojas",
            "url_name": "vendas:loja_list",
            "icon": "bx bx-store",
            "permission": "vendas.view_loja",
            "section": "Configurações",
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
            "icon": "bx bx-user",
            "permission": "accounts.view_own_user",
            "section": "Configurações",
        }, 

    ]
  

    current_path = request.path


    filtered_items = []
    sections = {}

    for item in items:
        item['active'] = False
        if 'sub_items' in item:
            visible_sub_items = []
            for sub_item in item['sub_items']:
                sub_item['url'] = reverse(sub_item['url_name'])
                if sub_item.get('permission') in request.user.get_all_permissions():
                    visible_sub_items.append(sub_item)
                    if sub_item['url'] == current_path:
                        item['active'] = True
                        sub_item['active'] = True
                    else:
                        sub_item['active'] = False
            item['sub_items'] = visible_sub_items
            if visible_sub_items:
                filtered_items.append(item)
        else:
            item['url'] = reverse(item['url_name']) if 'url_name' in item else None
            if item.get('permission') in request.user.get_all_permissions():
                filtered_items.append(item)
                if item['url'] == current_path:
                    item['active'] = True
            elif 'header' in item:
                filtered_items.append(item)


    for item in filtered_items:
        section = item['section']
        if section not in sections:
            sections[section] = []
        sections[section].append(item)


    return {'menu_items': sections}


def loja(request):
    loja_id = request.session.get('loja_id', None)
    
    loja = Loja.objects.filter(pk=loja_id).first()
    if loja:
        return {'loja_atual': loja}
    return {}


def notificacoes_usuario(request):
    if request.user.is_authenticated:
        return {
            "notificacoes_nao_lidas": request.user.notifications.unread()[:5]
        }
    return {}
