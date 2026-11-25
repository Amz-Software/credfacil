"""Serializers do módulo de pagamentos online (PagBank) da API do backoffice."""
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.utils import timezone
from rest_framework import serializers

from pagamentos_online.models import Cobranca, ConfiguracaoPagamentoOnline, RegistroPagBank
from pagamentos_online.pagbank import cliente as pagbank
from pagamentos_online.servicos.planos import rotulo
from vendas.services.pix import qr_code_base64

from ..financeiro.serializers import nome_do_usuario


class ConfiguracaoSerializer(serializers.ModelSerializer):
    pagbank_configurado = serializers.SerializerMethodField()
    ambiente = serializers.SerializerMethodField()

    class Meta:
        model = ConfiguracaoPagamentoOnline
        fields = [
            'ativo', 'pix_ativo', 'boleto_ativo', 'cartao_ativo', 'taxa_boleto', 'taxa_cartao_percentual',
            'cartao_max_parcelas', 'validade_horas', 'boleto_dias_vencimento', 'email_padrao', 'uf_padrao',
            'url_app_cliente', 'redirecionar_paginas_antigas', 'modificado_em',
            'pagbank_configurado', 'ambiente',
        ]
        read_only_fields = ['modificado_em', 'pagbank_configurado', 'ambiente']
        extra_kwargs = {
            'taxa_boleto': {'min_value': 0, 'max_value': 50},
            'taxa_cartao_percentual': {'min_value': 0, 'max_value': 30},
            'cartao_max_parcelas': {'min_value': 1, 'max_value': 18},
            'validade_horas': {'min_value': 1, 'max_value': 720},
            'boleto_dias_vencimento': {'min_value': 1, 'max_value': 30},
        }

    def get_pagbank_configurado(self, _objeto) -> bool:
        return pagbank.configurado()

    def get_ambiente(self, _objeto) -> str:
        return pagbank.ambiente()

    def validate_uf_padrao(self, valor: str) -> str:
        valor = (valor or '').strip().upper()
        if len(valor) != 2 or not valor.isalpha():
            raise serializers.ValidationError('Informe a UF com 2 letras (ex.: PA).')
        return valor

    def validate_url_app_cliente(self, valor: str) -> str:
        """Só origem https (sem usuário, caminho, query ou fragmento): vira redirect, link ao cliente e host liberado no bot."""
        valor = (valor or '').strip().rstrip('/')
        if not valor:
            return valor
        try:
            URLValidator(schemes=['https'])(valor)
            partes = urlsplit(valor)
        except (DjangoValidationError, ValueError) as erro:
            raise serializers.ValidationError('Informe um endereço https:// válido.') from erro
        if partes.username or partes.password or partes.path or partes.query or partes.fragment or not partes.hostname:
            raise serializers.ValidationError('Informe só o endereço do app, ex.: https://vendas.exemplo.com.')
        return f'https://{partes.netloc.lower()}'

    def validate(self, attrs):
        atual = self.instance
        redirecionar = attrs.get('redirecionar_paginas_antigas', getattr(atual, 'redirecionar_paginas_antigas', False))
        url = attrs.get('url_app_cliente', getattr(atual, 'url_app_cliente', ''))
        if redirecionar and not url:
            raise serializers.ValidationError({'url_app_cliente': 'Informe o endereço do app antes de redirecionar.'})
        return attrs


class ItemSerializer(serializers.Serializer):
    parcela_id = serializers.IntegerField()
    numero = serializers.IntegerField(source='parcela.numero_parcela')
    valor = serializers.DecimalField(max_digits=10, decimal_places=2)
    desconto = serializers.DecimalField(max_digits=10, decimal_places=2)


class CobrancaSerializer(serializers.ModelSerializer):
    """`itens` = parcelas pagas pela cobrança; `qr_code_base64` (PNG) só no Pix pendente."""

    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    rotulo = serializers.SerializerMethodField()
    itens = serializers.SerializerMethodField()
    qr_code_base64 = serializers.SerializerMethodField()
    parcela_numero = serializers.IntegerField(source='parcela.numero_parcela', read_only=True)
    pagamento_id = serializers.IntegerField(source='parcela.pagamento_id', read_only=True)
    cliente_nome = serializers.CharField(source='parcela.pagamento.venda.cliente.nome', read_only=True)
    forma_rotulo = serializers.CharField(source='get_forma_display', read_only=True)
    status_rotulo = serializers.CharField(source='get_status_display', read_only=True)
    origem_rotulo = serializers.CharField(source='get_origem_display', read_only=True)
    criado_por = serializers.SerializerMethodField()

    class Meta:
        model = Cobranca
        fields = [
            'id', 'referencia', 'tipo', 'tipo_rotulo', 'rotulo', 'itens', 'parcela_id', 'parcela_numero', 'pagamento_id', 'cliente_nome',
            'forma', 'forma_rotulo', 'status', 'status_rotulo', 'origem', 'origem_rotulo',
            'valor_parcela', 'taxa', 'valor_total', 'valor_pago', 'pagamento_duplicado', 'acerto_manual',
            'pagbank_id', 'pagbank_pedido_id', 'pix_copia_cola', 'qr_code_base64', 'boleto_linha_digitavel', 'boleto_pdf_url',
            'link_pagamento', 'expira_em', 'paga_em', 'detalhes_pagamento', 'criado_em', 'criado_por',
        ]

    def get_criado_por(self, cobranca) -> str | None:
        return nome_do_usuario(cobranca.criado_por)

    def _itens(self, cobranca: Cobranca) -> list:
        return cobranca.itens_da_baixa()

    def get_itens(self, cobranca) -> list[dict]:
        return ItemSerializer(self._itens(cobranca), many=True).data

    def get_rotulo(self, cobranca) -> str:
        return rotulo(cobranca.tipo, [i.parcela.numero_parcela for i in self._itens(cobranca)])

    def get_qr_code_base64(self, cobranca) -> str | None:
        vencida = cobranca.expira_em <= timezone.now()
        if cobranca.forma != Cobranca.Forma.PIX or cobranca.status != Cobranca.Status.PENDENTE or vencida:
            return None
        return qr_code_base64(cobranca.pix_copia_cola) if cobranca.pix_copia_cola else None


class RegistroSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistroPagBank
        fields = ['id', 'tipo', 'ambiente', 'metodo', 'caminho', 'status_http', 'requisicao', 'resposta',
                  'cobranca_id', 'criado_em']


class GerarCobrancaSerializer(serializers.Serializer):
    forma = serializers.ChoiceField(choices=Cobranca.Forma.choices)
