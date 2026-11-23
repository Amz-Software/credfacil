"""Serializers de leitura de contas a receber (lista, detalhe, parcelas, comprovantes)."""
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from vendas.models import ComprovanteParcela, Contato, Pagamento, Parcela, StatusPagamento

from .constantes import ROTULOS_SITUACAO, SITUACOES
from .resumo import (
    estado_da_conta,
    flags_anotadas,
    flags_calculadas,
    rotulo_do_estado,
    tem_parcela_vencida_em_aberto,
    totais_do_detalhe,
    valores_da_conta,
)

DINHEIRO = {'max_digits': 14, 'decimal_places': 2}


def mascarar_cpf(cpf: str | None) -> str:
    """CPF das listas (LGPD): `***.456.789-**`."""
    digitos = ''.join(ch for ch in (cpf or '') if ch.isdigit())
    if len(digitos) != 11:
        return '***'
    return f'***.{digitos[3:6]}.{digitos[6:9]}-**'


def nome_do_usuario(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or user.get_username()


def _hoje(contexto: dict):
    return contexto.get('hoje') or timezone.localdate()


def _parcelas(pagamento: Pagamento) -> list:
    """Parcelas do prefetch (sem nova consulta)."""
    return list(pagamento.parcelas_pagamento.all())


def _primeiro_item(pagamento: Pagamento):
    itens = list(pagamento.venda.itens_venda.all())
    return itens[0] if itens else None


class IdNomeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class StatusPagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusPagamento
        fields = ['id', 'nome', 'cor_hex']


class StatusPagamentoMarcadoSerializer(StatusPagamentoSerializer):
    ativo = serializers.BooleanField()

    class Meta(StatusPagamentoSerializer.Meta):
        fields = StatusPagamentoSerializer.Meta.fields + ['ativo']


class SituacaoSerializer(serializers.Serializer):
    chave = serializers.CharField()
    rotulo = serializers.CharField()
    ativo = serializers.BooleanField()


class SituacoesFlagsSerializer(serializers.Serializer):
    """As 10 situações de cobrança como booleanos (lista)."""

    lembrete = serializers.BooleanField()
    bo = serializers.BooleanField()
    flag_atrasado = serializers.BooleanField()
    sem_conexao = serializers.BooleanField()
    roubo = serializers.BooleanField()
    sem_contato = serializers.BooleanField()
    mais_prazo = serializers.BooleanField()
    bloqueado = serializers.BooleanField()
    desativado = serializers.BooleanField()
    devolucao = serializers.BooleanField()


class ProdutoItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    nome = serializers.CharField(allow_null=True)
    imei = serializers.CharField(allow_null=True)


class ValoresContaSerializer(serializers.Serializer):
    valor_atrasado = serializers.DecimalField(**DINHEIRO)
    ultimo_vencimento_atrasado = serializers.DateField(allow_null=True)
    valor_pago_ultimo = serializers.DecimalField(**DINHEIRO)
    ultimo_pagamento = serializers.DateField(allow_null=True)
    valor_a_vencer = serializers.DecimalField(**DINHEIRO)
    proximo_vencimento = serializers.DateField(allow_null=True)
    valor_total_parcelas = serializers.DecimalField(**DINHEIRO)
    valor_quitado = serializers.DecimalField(**DINHEIRO)
    parcelas_pagas = serializers.IntegerField()
    parcelas_totais = serializers.IntegerField()
    situacao_parcela_aberta = serializers.ChoiceField(choices=['em_dia', 'atrasado', 'pago_parcialmente'])


class ClienteListaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    cpf = serializers.SerializerMethodField()
    telefone = serializers.CharField()
    telefone_secundario = serializers.CharField()

    def get_cpf(self, cliente) -> str:
        return mascarar_cpf(cliente.cpf)


def _produto(pagamento: Pagamento) -> dict:
    item = _primeiro_item(pagamento)
    if item is None:
        return {'id': None, 'nome': None, 'imei': None}
    return {'id': item.produto_id, 'nome': item.produto.nome, 'imei': item.imei or None}


class ContaAReceberListaSerializer(serializers.ModelSerializer):
    cliente = ClienteListaSerializer(source='venda.cliente')
    loja = IdNomeSerializer(source='venda.loja', allow_null=True)
    venda_id = serializers.IntegerField()
    produto = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()
    estado_rotulo = serializers.SerializerMethodField()
    situacoes = SituacoesFlagsSerializer(source='*')
    status_pagamento = StatusPagamentoSerializer(source='statuses', many=True)
    valores = serializers.SerializerMethodField()
    quantidade_parcelas = serializers.IntegerField(source='parcelas', allow_null=True)

    class Meta:
        model = Pagamento
        fields = [
            'id', 'valor', 'quantidade_parcelas', 'quitado', 'venda_id', 'cliente', 'loja', 'produto',
            'estado', 'estado_rotulo', 'situacoes', 'status_pagamento', 'valores',
        ]

    @extend_schema_field(ProdutoItemSerializer)
    def get_produto(self, pagamento) -> dict:
        return _produto(pagamento)

    def get_estado(self, pagamento) -> str:
        return estado_da_conta(pagamento, flags_anotadas(pagamento))

    def get_estado_rotulo(self, pagamento) -> str:
        return rotulo_do_estado(self.get_estado(pagamento))

    @extend_schema_field(ValoresContaSerializer)
    def get_valores(self, pagamento) -> dict:
        valores = valores_da_conta(pagamento, _parcelas(pagamento), _hoje(self.context))
        return ValoresContaSerializer(valores).data


class ComprovanteSerializer(serializers.ModelSerializer):
    parcela_id = serializers.IntegerField(read_only=True)
    nome_arquivo = serializers.CharField(read_only=True)
    extensao = serializers.CharField(read_only=True)
    is_imagem = serializers.BooleanField(read_only=True)
    is_pdf = serializers.BooleanField(read_only=True)
    criado_por = serializers.SerializerMethodField()
    url_arquivo = serializers.SerializerMethodField()

    class Meta:
        model = ComprovanteParcela
        fields = [
            'id', 'parcela_id', 'nome_arquivo', 'extensao', 'is_imagem', 'is_pdf',
            'observacao', 'criado_em', 'criado_por', 'url_arquivo',
        ]

    def get_criado_por(self, comprovante) -> str | None:
        return nome_do_usuario(comprovante.criado_por)

    def get_url_arquivo(self, comprovante) -> str:
        """Endpoint autenticado da própria API (nunca o caminho de /mediafiles/)."""
        return reverse('backoffice_api:financeiro:comprovante-arquivo', args=[comprovante.pk])


class ParcelaSerializer(serializers.ModelSerializer):
    valor_restante = serializers.DecimalField(read_only=True, **DINHEIRO)
    atrasada = serializers.SerializerMethodField()
    modificado_por = serializers.SerializerMethodField()
    comprovantes = ComprovanteSerializer(many=True, read_only=True)

    class Meta:
        model = Parcela
        fields = [
            'id', 'pagamento_id', 'numero_parcela', 'valor', 'valor_pago', 'desconto', 'valor_restante',
            'data_vencimento', 'data_pagamento', 'pago', 'pagamento_efetuado', 'pagamento_efetuado_em',
            'atrasada', 'modificado_em', 'modificado_por', 'comprovantes',
        ]

    def get_atrasada(self, parcela) -> bool:
        return not parcela.pago and parcela.data_vencimento < _hoje(self.context)

    def get_modificado_por(self, parcela) -> str | None:
        return nome_do_usuario(parcela.modificado_por)


class ContatoSerializer(serializers.ModelSerializer):
    criado_por = serializers.SerializerMethodField()

    class Meta:
        model = Contato
        fields = ['id', 'data', 'observacao', 'criado_em', 'modificado_em', 'criado_por']

    def get_criado_por(self, contato) -> str | None:
        return nome_do_usuario(contato.criado_por)


class ReferenciaSerializer(serializers.Serializer):
    nome = serializers.CharField(allow_null=True)
    contato = serializers.CharField(allow_null=True)
    endereco = serializers.CharField(allow_null=True)
    obteve_contato = serializers.BooleanField()


class ClienteDetalheSerializer(serializers.Serializer):
    """Cliente com CPF completo (só no detalhe)."""

    id = serializers.IntegerField()
    nome = serializers.CharField()
    cpf = serializers.CharField()
    email = serializers.CharField(allow_null=True)
    telefone = serializers.CharField()
    telefone_secundario = serializers.CharField()
    nascimento = serializers.DateField()
    rg = serializers.CharField()
    cep = serializers.CharField()
    endereco = serializers.CharField()
    bairro = serializers.CharField()
    cidade = serializers.CharField()
    informacao_pessoal = serializers.SerializerMethodField()
    contato_adicional = serializers.SerializerMethodField()

    @extend_schema_field(ReferenciaSerializer(allow_null=True))
    def get_informacao_pessoal(self, cliente) -> dict | None:
        info = cliente.informacao_pessoal
        if info is None:
            return None
        return {'nome': info.nome, 'contato': info.contato, 'endereco': info.endereco,
                'obteve_contato': info.obteve_contato}

    @extend_schema_field(ReferenciaSerializer(allow_null=True))
    def get_contato_adicional(self, cliente) -> dict | None:
        info = cliente.contato_adicional
        if info is None:
            return None
        return {'nome': info.nome_adicional, 'contato': info.contato, 'endereco': info.endereco_adicional,
                'obteve_contato': info.obteve_contato}


class VendaResumoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    data_venda = serializers.DateTimeField()
    is_deleted = serializers.BooleanField()
    status_contrato = serializers.CharField()
    produto = serializers.SerializerMethodField()

    @extend_schema_field(ProdutoItemSerializer)
    def get_produto(self, venda) -> dict:
        return _produto(self.context['pagamento'])


class TotaisDetalheSerializer(serializers.Serializer):
    valor = serializers.DecimalField(**DINHEIRO)
    total_pago = serializers.DecimalField(**DINHEIRO)
    valor_pendente = serializers.DecimalField(**DINHEIRO)
    parcelas_pagas = serializers.IntegerField()
    parcelas_totais = serializers.IntegerField()
    total_valor_original = serializers.DecimalField(**DINHEIRO)
    total_valor_pago = serializers.DecimalField(**DINHEIRO)
    aguardando_quitacao = serializers.IntegerField()


class AlteracaoSerializer(serializers.Serializer):
    campo = serializers.CharField()
    rotulo = serializers.CharField()
    de = serializers.JSONField(allow_null=True)
    para = serializers.JSONField(allow_null=True)


class HistoricoSerializer(serializers.Serializer):
    data = serializers.DateTimeField()
    usuario = serializers.CharField(allow_null=True)
    objeto = serializers.ChoiceField(choices=['pagamento', 'parcela'])
    objeto_id = serializers.IntegerField()
    numero_parcela = serializers.IntegerField(allow_null=True)
    tipo = serializers.ChoiceField(choices=['criacao', 'alteracao', 'remocao'])
    alteracoes = AlteracaoSerializer(many=True)


class ContaAReceberDetalheSerializer(serializers.ModelSerializer):
    """Detalhe; o contexto traz `todos_status` e `historico` calculados pela view."""

    tipo_pagamento = IdNomeSerializer()
    loja = IdNomeSerializer(allow_null=True)
    venda = serializers.SerializerMethodField()
    cliente = ClienteDetalheSerializer(source='venda.cliente')
    estado = serializers.SerializerMethodField()
    estado_rotulo = serializers.SerializerMethodField()
    situacoes = serializers.SerializerMethodField()
    status_pagamento = serializers.SerializerMethodField()
    totais = serializers.SerializerMethodField()
    pode_gerar_bo = serializers.SerializerMethodField()
    parcelas = ParcelaSerializer(source='parcelas_pagamento', many=True)
    contatos = ContatoSerializer(source='venda.cliente.contatos', many=True)
    historico = serializers.SerializerMethodField()
    quantidade_parcelas = serializers.IntegerField(source='parcelas', allow_null=True)

    class Meta:
        model = Pagamento
        fields = [
            'id', 'valor', 'quantidade_parcelas', 'data_primeira_parcela', 'porcentagem_desconto', 'quitado',
            'tipo_pagamento', 'loja', 'venda', 'cliente', 'estado', 'estado_rotulo', 'situacoes',
            'status_pagamento', 'totais', 'pode_gerar_bo', 'parcelas', 'contatos', 'historico',
        ]

    @extend_schema_field(VendaResumoSerializer)
    def get_venda(self, pagamento) -> dict:
        return VendaResumoSerializer(pagamento.venda, context={**self.context, 'pagamento': pagamento}).data

    def get_estado(self, pagamento) -> str:
        return estado_da_conta(pagamento, flags_calculadas(_parcelas(pagamento), _hoje(self.context)))

    def get_estado_rotulo(self, pagamento) -> str:
        return rotulo_do_estado(self.get_estado(pagamento))

    @extend_schema_field(SituacaoSerializer(many=True))
    def get_situacoes(self, pagamento) -> list:
        return [{'chave': chave, 'rotulo': ROTULOS_SITUACAO[chave], 'ativo': getattr(pagamento, chave)}
                for chave, _ in SITUACOES]

    @extend_schema_field(StatusPagamentoMarcadoSerializer(many=True))
    def get_status_pagamento(self, pagamento) -> list:
        marcados = {s.pk for s in pagamento.statuses.all()}
        return [{'id': s.pk, 'nome': s.nome, 'cor_hex': s.cor_hex, 'ativo': s.pk in marcados}
                for s in self.context.get('todos_status', [])]

    @extend_schema_field(TotaisDetalheSerializer)
    def get_totais(self, pagamento) -> dict:
        return TotaisDetalheSerializer(totais_do_detalhe(pagamento, _parcelas(pagamento))).data

    def get_pode_gerar_bo(self, pagamento) -> bool:
        return tem_parcela_vencida_em_aberto(_parcelas(pagamento), _hoje(self.context))

    @extend_schema_field(HistoricoSerializer(many=True))
    def get_historico(self, pagamento) -> list:
        return HistoricoSerializer(self.context.get('historico', []), many=True).data
