"""Formatos de resposta dos relatórios (prévia e catálogo); descrevem também o esquema OpenAPI."""
from rest_framework import serializers

MAX_DIGITOS = 14


def _dinheiro(**kwargs) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=MAX_DIGITOS, decimal_places=2, **kwargs)


def _textos(**kwargs) -> serializers.ListField:
    return serializers.ListField(child=serializers.CharField(), **kwargs)


# ── Comodato (repasse 0 ao lojista: todo o valor fica com a IPX) ────────────

class TotaisComodatoSerializer(serializers.Serializer):
    comodato_quantidade = serializers.IntegerField(help_text='Registros de vendas de comodato.')
    comodato_valor = _dinheiro(help_text='Valor principal do relatório nas vendas de comodato.')
    demais_quantidade = serializers.IntegerField(help_text='Registros das demais vendas (comuns).')
    demais_valor = _dinheiro(help_text='Valor principal do relatório nas demais vendas.')


class TotaisRepasseComodatoSerializer(TotaisComodatoSerializer):
    comodato_ipx = _dinheiro(help_text='Valor financiado das vendas de comodato: fica com a IPX (repasse 0).')
    demais_repasse = _dinheiro(help_text='Repasse ao lojista, só das vendas comuns.')


# ── Vendas e solicitações ───────────────────────────────────────────────────

class LinhaVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    loja = serializers.CharField()
    cliente = serializers.CharField()
    data_venda = serializers.DateTimeField()
    vendedor = serializers.CharField()
    parcelas = serializers.IntegerField()
    produtos = _textos()
    status_solicitacao = serializers.CharField(allow_null=True)
    status_solicitacao_rotulo = serializers.CharField()
    segunda_compra = serializers.BooleanField()
    restricao_serasa = serializers.BooleanField(allow_null=True)
    consulta_serasa = serializers.CharField()
    analise_online = serializers.BooleanField(allow_null=True)
    tipo = serializers.CharField()
    valor_entrada = _dinheiro()
    valor_repasse = _dinheiro()
    valor_total = _dinheiro()
    valor_juros = _dinheiro()
    pagamento_bloqueado = serializers.BooleanField()
    comodato = serializers.BooleanField()


class TotaisVendasSerializer(TotaisRepasseComodatoSerializer):
    total_vendas = serializers.IntegerField()
    total_entrada = _dinheiro()
    total_repasse = _dinheiro()
    total_valor = _dinheiro()
    total_juros = _dinheiro()


class LinhaSolicitacaoSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text='Id do cliente.')
    cliente = serializers.CharField(help_text='Nome do cliente (só na prévia; o PDF mantém as colunas da folha).')
    analise_id = serializers.IntegerField(allow_null=True)
    loja = serializers.CharField()
    data_solicitacao = serializers.DateTimeField()
    vendedor = serializers.CharField()
    status_solicitacao = serializers.CharField(allow_null=True)
    status_solicitacao_rotulo = serializers.CharField()
    parcelas = serializers.CharField(allow_null=True)
    produto = serializers.CharField()
    restricao_serasa = serializers.BooleanField(allow_null=True)
    consulta_serasa = serializers.CharField()
    analise_online = serializers.BooleanField(allow_null=True)
    tipo = serializers.CharField()
    venda_gerada = serializers.BooleanField()
    valor_entrada = _dinheiro()
    valor_repasse = _dinheiro()
    valor_total = _dinheiro()
    valor_juros = _dinheiro()
    comodato = serializers.BooleanField(help_text='Solicitação de aparelho de comodato.')


class TotaisSolicitacoesSerializer(TotaisRepasseComodatoSerializer):
    total_solicitacoes = serializers.IntegerField()
    total_entrada = _dinheiro()
    total_repasse = _dinheiro()
    total_valor = _dinheiro()
    total_juros = _dinheiro()


# ── Contas a receber, situações e parcelas ──────────────────────────────────

class LinhaContaSerializer(serializers.Serializer):
    pagamento_id = serializers.IntegerField()
    parcela_id = serializers.IntegerField(allow_null=True, help_text='Preenchido no modo "parcelas pagas".')
    loja = serializers.CharField()
    data_venda = serializers.DateTimeField()
    cliente = serializers.CharField()
    produto = serializers.CharField()
    imei = serializers.CharField(allow_blank=True)
    situacoes = _textos()
    contatos = _textos()
    valor_atrasado = _dinheiro(allow_null=True)
    primeiro_vencimento = serializers.DateField(allow_null=True)
    valor_pago = _dinheiro(allow_null=True)
    ultimo_pagamento = serializers.DateField(allow_null=True)
    proxima_parcela = _dinheiro(allow_null=True)
    valor_a_vencer = _dinheiro(allow_null=True)
    proximo_vencimento = serializers.DateField(allow_null=True)
    valor_total = _dinheiro(allow_null=True)
    parcelas_totais = serializers.IntegerField(allow_null=True)
    parcelas_pagas = serializers.IntegerField(allow_null=True)
    valor_quitado = _dinheiro(allow_null=True)
    comodato = serializers.BooleanField()


class TotaisContasSerializer(TotaisComodatoSerializer):
    modo = serializers.ChoiceField(choices=['parcelas', 'pagamentos'])
    quantidade = serializers.IntegerField()
    total_atrasado = _dinheiro()
    total_pago = _dinheiro()
    total_a_vencer = _dinheiro()
    total_proximo_vencimento = _dinheiro()
    total = _dinheiro()
    total_quitado = _dinheiro()


class UltimoContatoSerializer(serializers.Serializer):
    data = serializers.DateTimeField()
    observacao = serializers.CharField(allow_blank=True)


class LinhaSituacaoSerializer(serializers.Serializer):
    pagamento_id = serializers.IntegerField()
    loja = serializers.CharField()
    data_venda = serializers.DateTimeField()
    cliente = serializers.CharField()
    lembrete = serializers.BooleanField()
    contatos = _textos()
    imei = serializers.CharField(allow_blank=True)
    situacoes = _textos()
    status_pagamento = _textos()
    analista_ultimo_registro = serializers.CharField(allow_null=True)
    ultimo_contato = UltimoContatoSerializer(allow_null=True)
    comodato = serializers.BooleanField()


class TotaisQuantidadeSerializer(serializers.Serializer):
    quantidade = serializers.IntegerField()


class TotaisSituacoesSerializer(TotaisQuantidadeSerializer):
    comodato_quantidade = serializers.IntegerField()
    demais_quantidade = serializers.IntegerField()


class ParcelaGradeSerializer(serializers.Serializer):
    numero = serializers.IntegerField()
    valor = _dinheiro()
    vencimento = serializers.DateField(allow_null=True)
    situacao = serializers.ChoiceField(choices=['pago', 'atrasado', 'a_vencer'])


class LinhaParcelasSerializer(serializers.Serializer):
    pagamento_id = serializers.IntegerField()
    loja = serializers.CharField()
    cliente = serializers.CharField()
    aparelho = serializers.CharField()
    comodato = serializers.BooleanField()
    parcelas = ParcelaGradeSerializer(many=True)
    total = _dinheiro()
    total_pago = _dinheiro()
    total_atrasado = _dinheiro()
    total_a_vencer = _dinheiro()


class TotaisParcelasSerializer(TotaisComodatoSerializer):
    quantidade = serializers.IntegerField()
    maximo_parcelas = serializers.IntegerField()
    total = _dinheiro()
    total_pago = _dinheiro()
    total_atrasado = _dinheiro()
    total_a_vencer = _dinheiro()


# ── Catálogo ────────────────────────────────────────────────────────────────

class OpcaoFiltroSerializer(serializers.Serializer):
    valor = serializers.JSONField()
    rotulo = serializers.CharField()


class FiltroCatalogoSerializer(serializers.Serializer):
    nome = serializers.CharField()
    rotulo = serializers.CharField()
    tipo = serializers.ChoiceField(choices=['data', 'selecao', 'booleano', 'texto'])
    obrigatorio = serializers.BooleanField()
    multiplo = serializers.BooleanField()
    opcoes = OpcaoFiltroSerializer(many=True, allow_null=True)
    padrao = serializers.JSONField(required=False, allow_null=True)


class EnderecosRelatorioSerializer(serializers.Serializer):
    previa = serializers.CharField()
    pdf = serializers.CharField()
    excel = serializers.CharField(required=False)


class RelatorioCatalogoSerializer(serializers.Serializer):
    id = serializers.CharField()
    titulo = serializers.CharField()
    descricao = serializers.CharField()
    formatos = _textos()
    filtros = FiltroCatalogoSerializer(many=True)
    enderecos = EnderecosRelatorioSerializer()


def previa_serializer(nome: str, linha, totais) -> type[serializers.Serializer]:
    """Resposta da prévia: paginação padrão + totais do filtro inteiro."""
    return type(nome, (serializers.Serializer,), {
        'count': serializers.IntegerField(),
        'page': serializers.IntegerField(),
        'page_size': serializers.IntegerField(),
        'total_pages': serializers.IntegerField(),
        'results': linha(many=True),
        'totais': totais(),
        'filtros': serializers.DictField(help_text='Filtros aplicados (ids e datas ISO).'),
    })
