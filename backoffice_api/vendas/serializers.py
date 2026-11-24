"""Serializers de leitura das vendas: lista, detalhe, produtos vendidos e busca global."""
import os
import re
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from backoffice_api.models import RegistroAuditoria
from vendas.models import AnaliseCreditoCliente, Cliente, Pagamento, Parcela, ProdutoVenda, Venda

from .regras import (
    CAMPOS_DOCUMENTO,
    acoes_disponiveis,
    pagamento_carne,
    situacao_da_venda,
)

LIMITE_HISTORICO = 50
CAMPOS_FORA_DO_HISTORICO = {'modificado_em', 'modificado_por', 'criado_em', 'criado_por'}
ACOES_FORA_DA_LINHA_DO_TEMPO = {'venda_documento_acessado', 'venda_pdf_gerado'}
TIPOS_HISTORICO = {'+': 'criacao', '~': 'alteracao', '-': 'exclusao'}


def mascarar_cpf(cpf: str | None) -> str:
    """`***.456.789-**` para listas (LGPD); CPF completo só no detalhe."""
    digitos = re.sub(r'\D', '', cpf or '')
    if len(digitos) != 11:
        return '***' if digitos else ''
    return f'***.{digitos[3:6]}.{digitos[6:9]}-**'


def nome_do_usuario(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or user.get_username()


def caminho_api(nome: str, **kwargs) -> str:
    """Caminho relativo de um endpoint deste módulo (a SPA usa o proxy do mesmo domínio)."""
    return reverse(f'backoffice_api:vendas:{nome}', kwargs=kwargs)


# --- referências curtas -------------------------------------------------------------

class ReferenciaVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class UsuarioDaVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.SerializerMethodField()

    def get_nome(self, user) -> str | None:
        return nome_do_usuario(user)


# --- lista ------------------------------------------------------------------------

class VendaListaSerializer(serializers.ModelSerializer):
    numero = serializers.IntegerField(source='pk', read_only=True)
    cliente = ReferenciaVendaSerializer(read_only=True)
    cpf_mascarado = serializers.SerializerMethodField()
    loja = ReferenciaVendaSerializer(read_only=True, allow_null=True)
    vendedor = UsuarioDaVendaSerializer(read_only=True)
    modificado_por = UsuarioDaVendaSerializer(read_only=True, allow_null=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    situacao = serializers.SerializerMethodField()
    origem = serializers.SerializerMethodField()
    tem_iphone = serializers.BooleanField(source='possui_iphone', read_only=True)
    documentos_completos = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = [
            'id', 'numero', 'data_venda', 'cliente', 'cpf_mascarado', 'loja', 'vendedor',
            'total', 'situacao', 'origem', 'tem_iphone', 'comodato', 'is_deleted', 'is_trocado',
            'documentos_completos', 'status_contrato', 'modificado_por', 'modificado_em',
        ]
        read_only_fields = fields

    def get_cpf_mascarado(self, venda) -> str:
        return mascarar_cpf(venda.cliente.cpf)

    def get_situacao(self, venda) -> str:
        return situacao_da_venda(venda)

    def get_origem(self, venda) -> str:
        return 'analise' if venda.veio_de_analise else 'manual'

    def get_documentos_completos(self, venda) -> bool:
        return bool(venda.documento_assinado) or venda.status_contrato == Venda.CONTRATO_STATUS_ASSINADO


# --- detalhe ----------------------------------------------------------------------

class ProdutoDaVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    codigo = serializers.IntegerField(allow_null=True)
    is_iphone = serializers.BooleanField()


class ItemVendaSerializer(serializers.ModelSerializer):
    produto = ProdutoDaVendaSerializer(read_only=True)
    valor_total = serializers.SerializerMethodField()

    class Meta:
        model = ProdutoVenda
        fields = ['id', 'produto', 'imei', 'quantidade', 'valor_unitario', 'valor_desconto', 'valor_total']
        read_only_fields = fields

    def get_valor_total(self, item) -> Decimal:
        return serializers.DecimalField(max_digits=12, decimal_places=2).to_representation(
            item.calcular_valor_total()
        )


def situacao_da_parcela(parcela, hoje) -> str:
    if parcela.pago:
        return 'paga'
    return 'atrasada' if parcela.data_vencimento < hoje else 'a_vencer'


class ParcelaDaVendaSerializer(serializers.ModelSerializer):
    situacao = serializers.SerializerMethodField()
    valor_restante = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Parcela
        fields = [
            'id', 'numero_parcela', 'valor', 'desconto', 'valor_pago', 'valor_restante',
            'data_vencimento', 'data_pagamento', 'pago', 'pagamento_efetuado', 'situacao',
        ]
        read_only_fields = fields

    def get_situacao(self, parcela) -> str:
        return situacao_da_parcela(parcela, timezone.localdate())


class TipoPagamentoDaVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    carne = serializers.BooleanField()
    parcelas = serializers.BooleanField()
    caixa = serializers.BooleanField()
    financeira = serializers.BooleanField()


class ResumoParcelasVendaSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    pagas = serializers.IntegerField()
    atrasadas = serializers.IntegerField()
    a_vencer = serializers.IntegerField()
    valor_pago = serializers.DecimalField(max_digits=12, decimal_places=2)
    valor_atrasado = serializers.DecimalField(max_digits=12, decimal_places=2)
    valor_a_vencer = serializers.DecimalField(max_digits=12, decimal_places=2)
    proximo_vencimento = serializers.DateField(allow_null=True)


def resumir_parcelas(pagamento) -> dict:
    """Pagas, atrasadas e a vencer a partir das parcelas já carregadas (prefetch)."""
    hoje = timezone.localdate()
    parcelas = list(pagamento.parcelas_pagamento.all())
    pagas = [p for p in parcelas if p.pago]
    abertas = [] if pagamento.devolucao else [p for p in parcelas if not p.pago]
    atrasadas = [p for p in abertas if p.data_vencimento < hoje]
    a_vencer = [p for p in abertas if p.data_vencimento >= hoje]
    return ResumoParcelasVendaSerializer({
        'total': len(parcelas),
        'pagas': len(pagas),
        'atrasadas': len(atrasadas),
        'a_vencer': len(a_vencer),
        'valor_pago': sum((p.valor_pago_efetivo for p in pagas), Decimal('0')),
        'valor_atrasado': sum((p.valor_restante for p in atrasadas), Decimal('0')),
        'valor_a_vencer': sum((p.valor_restante for p in a_vencer), Decimal('0')),
        'proximo_vencimento': min((p.data_vencimento for p in a_vencer), default=None),
    }).data


class PagamentoDaVendaSerializer(serializers.ModelSerializer):
    tipo_pagamento = TipoPagamentoDaVendaSerializer(read_only=True)
    valor_parcela = serializers.SerializerMethodField()
    resumo = serializers.SerializerMethodField()
    parcelas_lista = ParcelaDaVendaSerializer(source='parcelas_pagamento', many=True, read_only=True)

    class Meta:
        model = Pagamento
        fields = [
            'id', 'tipo_pagamento', 'valor', 'parcelas', 'valor_parcela', 'data_primeira_parcela',
            'porcentagem_desconto', 'bloqueado', 'desativado', 'devolucao', 'quitado', 'resumo',
            'parcelas_lista',
        ]
        read_only_fields = fields

    def get_valor_parcela(self, pagamento) -> Decimal | None:
        if not pagamento.parcelas:
            return None
        return serializers.DecimalField(max_digits=12, decimal_places=2).to_representation(
            pagamento.valor_parcela
        )

    @extend_schema_field(ResumoParcelasVendaSerializer)
    def get_resumo(self, pagamento) -> dict:
        return resumir_parcelas(pagamento)


class ClienteDaVendaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = [
            'id', 'nome', 'cpf', 'rg', 'nascimento', 'telefone', 'telefone_secundario', 'email',
            'cep', 'endereco', 'bairro', 'cidade',
        ]
        read_only_fields = fields


class AnaliseOrigemDaVendaSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    produto = ReferenciaVendaSerializer(read_only=True)
    aprovado_por = UsuarioDaVendaSerializer(read_only=True, allow_null=True)

    class Meta:
        model = AnaliseCreditoCliente
        fields = [
            'id', 'status', 'status_display', 'data_analise', 'data_aprovacao', 'aprovado_por',
            'produto', 'numero_parcelas', 'data_pagamento', 'entrada_informada', 'analise_online', 'comodato',
            'segunda_compra',
        ]
        read_only_fields = fields


class DocumentoDaVendaSerializer(serializers.Serializer):
    campo = serializers.CharField()
    rotulo = serializers.CharField()
    presente = serializers.BooleanField()
    nome_arquivo = serializers.CharField(allow_null=True)
    url = serializers.CharField(allow_null=True)


class ImpressosDaVendaSerializer(serializers.Serializer):
    nota = serializers.CharField()
    contrato = serializers.CharField()
    carne = serializers.CharField(allow_null=True)
    promissoria = serializers.CharField(allow_null=True)


class AcoesDaVendaSerializer(serializers.Serializer):
    editar = serializers.BooleanField()
    edicao_especial = serializers.BooleanField()
    trocar_produto = serializers.BooleanField()
    cancelar = serializers.BooleanField()
    enviar_documentos = serializers.BooleanField()


class AlteracaoCampoVendaSerializer(serializers.Serializer):
    campo = serializers.CharField()
    de = serializers.JSONField(allow_null=True)
    para = serializers.JSONField(allow_null=True)


class EventoHistoricoVendaSerializer(serializers.Serializer):
    origem = serializers.ChoiceField(choices=['alteracao', 'acao'])
    data = serializers.DateTimeField()
    usuario = serializers.CharField(allow_null=True)
    tipo = serializers.CharField()
    descricao = serializers.CharField(allow_blank=True)
    motivo = serializers.CharField(allow_blank=True)
    campos = AlteracaoCampoVendaSerializer(many=True)


def _valor_historico(campo: str, valor):
    if campo in CAMPOS_DOCUMENTO:
        return bool(valor)
    if valor is None or isinstance(valor, (bool, int)):
        return valor
    return str(valor)


def _mudancas(registro, anterior) -> list[dict]:
    if anterior is None:
        return []
    delta = registro.diff_against(anterior)
    return [
        {'campo': m.field, 'de': _valor_historico(m.field, m.old), 'para': _valor_historico(m.field, m.new)}
        for m in delta.changes
        if m.field not in CAMPOS_FORA_DO_HISTORICO
    ]


def linha_do_tempo(venda) -> list[dict]:
    """Alterações do simple_history + ações auditadas (com motivo), da mais recente à mais antiga."""
    registros = list(
        venda.history.select_related('history_user').order_by('-history_date', '-history_id')[
            : LIMITE_HISTORICO + 1
        ]
    )
    eventos = [
        {
            'origem': 'alteracao',
            'data': registro.history_date,
            'usuario': nome_do_usuario(registro.history_user),
            'tipo': TIPOS_HISTORICO.get(registro.history_type, 'alteracao'),
            'descricao': registro.history_change_reason or '',
            'motivo': '',
            'campos': _mudancas(registro, registros[indice + 1] if indice + 1 < len(registros) else None),
        }
        for indice, registro in enumerate(registros[:LIMITE_HISTORICO])
    ]
    auditoria = (
        RegistroAuditoria.objects.filter(objeto_tipo=Venda._meta.label_lower, objeto_id=str(venda.pk))
        .exclude(acao__in=ACOES_FORA_DA_LINHA_DO_TEMPO)
        .order_by('-criado_em')[:LIMITE_HISTORICO]
    )
    eventos += [
        {
            'origem': 'acao', 'data': r.criado_em, 'usuario': r.usuario_nome or None, 'tipo': r.acao,
            'descricao': r.descricao, 'motivo': r.motivo, 'campos': [],
        }
        for r in auditoria
    ]
    eventos.sort(key=lambda evento: evento['data'], reverse=True)
    return EventoHistoricoVendaSerializer(eventos[:LIMITE_HISTORICO], many=True).data


class VendaDetalheSerializer(VendaListaSerializer):
    cliente = ClienteDaVendaSerializer(read_only=True)
    criado_por = UsuarioDaVendaSerializer(read_only=True, allow_null=True)
    itens = ItemVendaSerializer(source='itens_venda', many=True, read_only=True)
    pagamentos = PagamentoDaVendaSerializer(many=True, read_only=True)
    valor_total_pagamentos = serializers.SerializerMethodField()
    valor_entrada = serializers.SerializerMethodField()
    analise_origem = serializers.SerializerMethodField()
    documentos = serializers.SerializerMethodField()
    impressos = serializers.SerializerMethodField()
    acoes = serializers.SerializerMethodField()
    historico = serializers.SerializerMethodField()

    class Meta(VendaListaSerializer.Meta):
        fields = VendaListaSerializer.Meta.fields + [
            'observacao', 'repasse_logista', 'valor_total_pagamentos', 'valor_entrada', 'caixa',
            'criado_por', 'criado_em', 'itens', 'pagamentos', 'analise_origem', 'documentos',
            'impressos', 'acoes', 'historico',
        ]
        read_only_fields = fields

    def _decimal(self, valor) -> str:
        return serializers.DecimalField(max_digits=12, decimal_places=2).to_representation(valor or 0)

    def get_valor_total_pagamentos(self, venda) -> Decimal:
        pagamentos = venda.pagamentos.all()
        return self._decimal(sum((p.valor for p in pagamentos if not p.tipo_pagamento.nao_contabilizar), Decimal('0')))

    def get_valor_entrada(self, venda) -> Decimal:
        pagamentos = venda.pagamentos.all()
        return self._decimal(sum(
            (p.valor for p in pagamentos if p.tipo_pagamento.nome.upper() == 'ENTRADA'), Decimal('0'),
        ))

    @extend_schema_field(AnaliseOrigemDaVendaSerializer(allow_null=True))
    def get_analise_origem(self, venda) -> dict | None:
        analises = list(venda.analises_credito_venda.all())
        return AnaliseOrigemDaVendaSerializer(analises[0]).data if analises else None

    @extend_schema_field(DocumentoDaVendaSerializer(many=True))
    def get_documentos(self, venda) -> list:
        documentos = []
        for campo, rotulo in CAMPOS_DOCUMENTO.items():
            arquivo = getattr(venda, campo)
            presente = bool(arquivo and arquivo.name)
            documentos.append({
                'campo': campo,
                'rotulo': rotulo,
                'presente': presente,
                'nome_arquivo': os.path.basename(arquivo.name) if presente else None,
                'url': caminho_api('venda-arquivo', pk=venda.pk, campo=campo) if presente else None,
            })
        return DocumentoDaVendaSerializer(documentos, many=True).data

    @extend_schema_field(ImpressosDaVendaSerializer)
    def get_impressos(self, venda) -> dict:
        tem_carne = pagamento_carne(venda) is not None
        carne = caminho_api('venda-carne-pdf', pk=venda.pk)
        return {
            'nota': caminho_api('venda-nota-pdf', pk=venda.pk),
            'contrato': caminho_api('venda-contrato-pdf', pk=venda.pk),
            'carne': f'{carne}?tipo=carne' if tem_carne else None,
            'promissoria': f'{carne}?tipo=promissoria' if tem_carne else None,
        }

    @extend_schema_field(AcoesDaVendaSerializer)
    def get_acoes(self, venda) -> dict:
        request = self.context.get('request')
        return acoes_disponiveis(venda, request.user) if request else {}

    @extend_schema_field(EventoHistoricoVendaSerializer(many=True))
    def get_historico(self, venda) -> list:
        return linha_do_tempo(venda)


# --- produtos vendidos e busca -------------------------------------------------------

class VendaDoProdutoVendidoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    data_venda = serializers.DateTimeField()
    situacao = serializers.CharField()


class ProdutoVendidoSerializer(serializers.ModelSerializer):
    venda = serializers.SerializerMethodField()
    produto = ProdutoDaVendaSerializer(read_only=True)
    cliente = serializers.SerializerMethodField()
    cpf_mascarado = serializers.SerializerMethodField()
    loja = serializers.SerializerMethodField()
    vendedor = serializers.SerializerMethodField()
    valor_total = serializers.SerializerMethodField()

    class Meta:
        model = ProdutoVenda
        fields = [
            'id', 'venda', 'produto', 'imei', 'quantidade', 'valor_unitario', 'valor_desconto',
            'valor_total', 'cliente', 'cpf_mascarado', 'loja', 'vendedor',
        ]
        read_only_fields = fields

    @extend_schema_field(VendaDoProdutoVendidoSerializer)
    def get_venda(self, item) -> dict:
        venda = item.venda
        return VendaDoProdutoVendidoSerializer(
            {'id': venda.pk, 'data_venda': venda.data_venda, 'situacao': situacao_da_venda(venda)}
        ).data

    @extend_schema_field(ReferenciaVendaSerializer)
    def get_cliente(self, item) -> dict:
        return {'id': item.venda.cliente_id, 'nome': item.venda.cliente.nome}

    def get_cpf_mascarado(self, item) -> str:
        return mascarar_cpf(item.venda.cliente.cpf)

    @extend_schema_field(ReferenciaVendaSerializer(allow_null=True))
    def get_loja(self, item) -> dict | None:
        loja = item.venda.loja
        return {'id': loja.pk, 'nome': loja.nome} if loja else None

    def get_vendedor(self, item) -> str | None:
        return nome_do_usuario(item.venda.vendedor)

    def get_valor_total(self, item) -> Decimal:
        return serializers.DecimalField(max_digits=12, decimal_places=2).to_representation(
            item.calcular_valor_total()
        )


class ResultadoBuscaVendaSerializer(serializers.Serializer):
    tipo = serializers.CharField()
    id = serializers.IntegerField()
    titulo = serializers.CharField()
    descricao = serializers.CharField()
    situacao = serializers.CharField()
    rota = serializers.CharField()


def resultado_de_busca(venda) -> dict:
    data = timezone.localtime(venda.data_venda).strftime('%d/%m/%Y') if venda.data_venda else ''
    partes = [venda.cliente.nome, mascarar_cpf(venda.cliente.cpf), venda.loja.nome if venda.loja else '', data]
    return {
        'tipo': 'venda',
        'id': venda.pk,
        'titulo': f'Venda #{venda.pk}',
        'descricao': ' · '.join(p for p in partes if p),
        'situacao': situacao_da_venda(venda),
        'rota': f'/vendas/{venda.pk}',
    }


class ImeiDisponivelVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    imei = serializers.CharField()
    produto = ReferenciaVendaSerializer()
    loja = ReferenciaVendaSerializer(allow_null=True)


class OpcoesTrocaVendaSerializer(serializers.Serializer):
    itens = ItemVendaSerializer(many=True)
    produtos_disponiveis = ReferenciaVendaSerializer(many=True)
