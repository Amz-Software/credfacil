"""Filtros dos relatórios: validam a query string e descrevem o formulário do catálogo.

Cada relatório tem um serializer de filtros. O mesmo serializer valida `?param=`
(listas repetindo o parâmetro: `?lojas=1&lojas=2`) e gera a descrição dos campos
que a "Central de relatórios" usa para montar o formulário.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet
from rest_framework import serializers

from produtos.models import Marca, Produto
from vendas.models import AnaliseCreditoCliente, Loja, StatusPagamento

MENSAGEM_PERIODO = 'A data final deve ser igual ou posterior à inicial.'
MENSAGEM_FORA_DO_ESCOPO = 'Opção inválida ou fora do seu acesso.'
OPCOES_SERASA = (('true', 'Positiva'), ('false', 'Negativa'))
STATUS_SOLICITACAO = (('EA', 'Em Análise'), ('A', 'Aprovada'), ('R', 'Reprovada'), ('C', 'Cancelada'))


class OpcoesDeModelo(serializers.PrimaryKeyRelatedField):
    """Seleção de registros por id; `rotulo` é o atributo mostrado no formulário."""

    default_error_messages = {
        'does_not_exist': MENSAGEM_FORA_DO_ESCOPO,
        'incorrect_type': 'Informe o id numérico.',
    }

    def __init__(self, *, rotulo: str = 'nome', **kwargs):
        self.rotulo = rotulo
        super().__init__(**kwargs)


def multiplos_de_modelo(rotulo: str = 'nome', **kwargs) -> serializers.ManyRelatedField:
    return OpcoesDeModelo(many=True, required=False, queryset=Loja.objects.none(), rotulo=rotulo, **kwargs)


class BooleanoComRotulos(serializers.BooleanField):
    """Sim/Não com rótulos próprios; recebidos como argumento para sobreviver à cópia do DRF."""

    def __init__(self, *, rotulos_booleano: tuple[str, str] = ('Sim', 'Não'), **kwargs):
        self.rotulos_booleano = rotulos_booleano
        super().__init__(**kwargs)


def booleano(label: str, opcoes: tuple[str, str] = ('Sim', 'Não')) -> serializers.BooleanField:
    return BooleanoComRotulos(label=label, required=False, allow_null=True, rotulos_booleano=opcoes)


def vendedores_das_lojas(lojas: QuerySet) -> QuerySet:
    User = get_user_model()
    return (
        User.objects.filter(Q(loja__in=lojas) | Q(lojas__in=lojas) | Q(lojas_gerenciadas__in=lojas))
        .distinct()
        .order_by('first_name', 'last_name', 'username')
    )


def parcelas_cadastradas() -> list[tuple[str, str]]:
    """Quantidades de parcelas já usadas em solicitações (como nos formulários atuais)."""
    valores = (
        AnaliseCreditoCliente.objects.exclude(numero_parcelas__isnull=True).exclude(numero_parcelas='')
        .order_by('numero_parcelas').values_list('numero_parcelas', flat=True).distinct()
    )
    return [(valor, valor) for valor in sorted(set(valores), key=lambda v: (len(v), v))]


class FiltrosBase(serializers.Serializer):
    """Período, lojas e comodato, comuns a todos os relatórios.

    `lojas` aceita só lojas do escopo da requisição; vazio = todas as lojas do escopo.
    """

    periodo_obrigatorio = False

    data_inicial = serializers.DateField(label='Data inicial', required=False, allow_null=True)
    data_final = serializers.DateField(label='Data final', required=False, allow_null=True)
    lojas = multiplos_de_modelo(label='Lojas')
    # Venda de comodato: sem repasse ao lojista (todo o valor fica com a IPX).
    comodato = booleano('Comodato')

    def __init__(self, *args, lojas: QuerySet | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lojas_permitidas = lojas if lojas is not None else Loja.objects.none()
        self.fields['lojas'].child_relation.queryset = self.lojas_permitidas.order_by('nome')
        if self.periodo_obrigatorio:
            for nome in ('data_inicial', 'data_final'):
                self.fields[nome].required = True
                self.fields[nome].allow_null = False
        self.configurar_opcoes()

    def configurar_opcoes(self) -> None:
        """Ganchos dos filtros com opções que dependem das lojas ou do banco."""

    def validate(self, attrs):
        inicio, fim = attrs.get('data_inicial'), attrs.get('data_final')
        if inicio and fim and inicio > fim:
            raise serializers.ValidationError({'data_final': [MENSAGEM_PERIODO]})
        return attrs


class FiltrosVendasSerializer(FiltrosBase):
    produtos = multiplos_de_modelo(label='Produtos')
    marcas = multiplos_de_modelo(label='Marcas')
    iphone = booleano('iPhone', ('Somente iPhone', 'Sem iPhone'))
    vendedores = multiplos_de_modelo(label='Vendedores', rotulo='__str__')
    analise_serasa = serializers.MultipleChoiceField(label='Resultado Serasa', choices=OPCOES_SERASA, required=False)
    parcelas = serializers.MultipleChoiceField(label='Número de parcelas', choices=(), required=False)
    analise_online = booleano('Análise online')

    def configurar_opcoes(self) -> None:
        self.fields['produtos'].child_relation.queryset = Produto.objects.filter(ativo=True).order_by('nome')
        self.fields['marcas'].child_relation.queryset = Marca.objects.order_by('nome')
        self.fields['vendedores'].child_relation.queryset = vendedores_das_lojas(self.lojas_permitidas)
        self.fields['parcelas'].choices = parcelas_cadastradas()


class FiltrosSolicitacoesSerializer(FiltrosVendasSerializer):
    status_solicitacao = serializers.MultipleChoiceField(
        label='Status da solicitação', choices=STATUS_SOLICITACAO, required=False,
    )
    venda_realizada = booleano('Venda realizada')


def _choices_do_form(form_class, campo: str) -> list:
    return list(form_class.base_fields[campo].choices)


class FiltrosContasAReceberSerializer(FiltrosBase):
    periodo_obrigatorio = True

    status = serializers.MultipleChoiceField(label='Status', choices=(), allow_empty=False)
    status_pagamento = multiplos_de_modelo(label='Status do pagamento')

    def configurar_opcoes(self) -> None:
        from financeiro.forms import RelatorioContasAReceberForm

        self.fields['status'].choices = _choices_do_form(RelatorioContasAReceberForm, 'status')
        self.fields['status_pagamento'].child_relation.queryset = StatusPagamento.objects.order_by('nome')


class FiltrosSituacoesSerializer(FiltrosBase):
    situacoes = serializers.MultipleChoiceField(label='Situações', choices=(), required=False)
    status_pagamento = multiplos_de_modelo(label='Status do pagamento')

    def configurar_opcoes(self) -> None:
        from financeiro.forms import RelatorioContasAReceberAvancadoForm

        self.fields['situacoes'].choices = _choices_do_form(RelatorioContasAReceberAvancadoForm, 'situacoes')
        self.fields['status_pagamento'].child_relation.queryset = StatusPagamento.objects.order_by('nome')


class FiltrosParcelasSerializer(FiltrosBase):
    status = serializers.ChoiceField(label='Status', choices=(), required=False, default='todos')
    busca = serializers.CharField(label='Cliente ou CPF', required=False, allow_blank=True, max_length=100)

    def configurar_opcoes(self) -> None:
        from financeiro.forms import RelatorioParcelasForm

        self.fields['status'].choices = _choices_do_form(RelatorioParcelasForm, 'status')
        self.fields['data_inicial'].label = 'Vencimento de'
        self.fields['data_final'].label = 'Vencimento até'


# ── Descrição dos campos para o catálogo ────────────────────────────────────

def _opcoes_de_modelo(campo: OpcoesDeModelo) -> list[dict]:
    rotulo = campo.rotulo
    return [
        {'valor': obj.pk, 'rotulo': str(obj) if rotulo == '__str__' else getattr(obj, rotulo)}
        for obj in campo.get_queryset()
    ]


def descrever_campo(nome: str, campo: serializers.Field) -> dict:
    descricao = {
        'nome': nome,
        'rotulo': str(campo.label or nome),
        'obrigatorio': bool(campo.required),
        'multiplo': False,
        'opcoes': None,
    }
    if isinstance(campo, serializers.ManyRelatedField):
        return {**descricao, 'tipo': 'selecao', 'multiplo': True, 'opcoes': _opcoes_de_modelo(campo.child_relation)}
    if isinstance(campo, serializers.MultipleChoiceField):
        opcoes = [{'valor': valor, 'rotulo': str(rotulo)} for valor, rotulo in campo.choices.items()]
        return {**descricao, 'tipo': 'selecao', 'multiplo': True, 'opcoes': opcoes}
    if isinstance(campo, serializers.ChoiceField):
        opcoes = [{'valor': valor, 'rotulo': str(rotulo)} for valor, rotulo in campo.choices.items()]
        return {**descricao, 'tipo': 'selecao', 'opcoes': opcoes, 'padrao': campo.default}
    if isinstance(campo, serializers.BooleanField):
        sim, nao = getattr(campo, 'rotulos_booleano', ('Sim', 'Não'))
        return {**descricao, 'tipo': 'booleano', 'opcoes': [{'valor': True, 'rotulo': sim}, {'valor': False, 'rotulo': nao}]}
    if isinstance(campo, serializers.DateField):
        return {**descricao, 'tipo': 'data'}
    return {**descricao, 'tipo': 'texto'}


def descrever_filtros(filtros: FiltrosBase) -> list[dict]:
    return [descrever_campo(nome, campo) for nome, campo in filtros.fields.items()]


def filtros_para_auditoria(validados: dict) -> dict:
    """Filtros validados em formato JSON (ids no lugar de objetos, datas ISO)."""
    def converter(valor):
        if hasattr(valor, 'pk'):
            return valor.pk
        if hasattr(valor, 'isoformat'):
            return valor.isoformat()
        if isinstance(valor, (list, tuple, set)):
            return sorted((converter(v) for v in valor), key=str)
        return valor

    return {nome: converter(valor) for nome, valor in validados.items() if valor not in (None, '', [], set())}
