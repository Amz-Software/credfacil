from rest_framework import serializers

from financeiro.models import Repasse
from vendas.models import (
    AnaliseCreditoCliente,
    Cliente,
    ConsultaSerasaAcesso,
    ContatoAdicional,
    InformacaoPessoal,
    ComprovantesCliente,
    Loja,
    NumeroAutenticador,
    PreAnaliseRapida,
    Venda,
)
from produtos.models import Parcelamento, Produto, TipoProduto, Fabricante, Marca
from vendas.models import ProdutoVenda, Pagamento


class LojaSerializer(serializers.ModelSerializer):
    usuarios_detalhes = serializers.SerializerMethodField()
    gerentes_detalhes = serializers.SerializerMethodField()
    acessos = serializers.SerializerMethodField()

    class Meta:
        model = Loja
        fields = "__all__"

    def get_usuarios_detalhes(self, obj):
        return [
            {
                "id": usuario.id,
                "nome": usuario.get_full_name() or usuario.username,
                "email": usuario.email,
            }
            for usuario in obj.usuarios.all()
        ]

    def get_gerentes_detalhes(self, obj):
        return [
            {
                "id": gerente.id,
                "nome": gerente.get_full_name() or gerente.username,
                "email": gerente.email,
            }
            for gerente in obj.gerentes.all()
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not (user.is_superuser or user.groups.filter(name="ADMINISTRADOR").exists()):
            attrs.pop("pode_vender_iphone", None)
        return attrs

    def get_acessos(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user:
            return {}

        # Mapar permissões para os nomes esperados pelo frontend
        acessos = {
            "pode_editar_loja": user.has_perm("vendas.change_loja"),
            "pode_criar_loja": user.has_perm("vendas.add_loja"),
            "pode_deletar_loja": user.has_perm("vendas.delete_loja"),
            "pode_criar_repasse": user.has_perm("financeiro.add_repasse"),
            "pode_ver_repasse": user.has_perm("financeiro.view_repasse"),
            "can_view_all_stores": user.has_perm("vendas.can_view_all_stores"),
            "pode_criar_produto": user.has_perm("produtos.add_produto"),
            "pode_editar_produto": user.has_perm("produtos.change_produto"),
            "pode_deletar_produto": user.has_perm("produtos.delete_produto"),
            # Para criar uma solicitação consideramos permissão de criar cliente ou criar análise
            "pode_criar_solicitacao": (
                user.has_perm("vendas.add_cliente") or user.has_perm("vendas.add_analisecreditocliente")
            ),
            "pode_criar_venda": user.has_perm("vendas.add_venda"),
        }

        return acessos

    def update(self, instance, validated_data):
        if "credfacil" not in self.initial_data:
            validated_data["credfacil"] = instance.credfacil
        return super().update(instance, validated_data)


class LojaListSerializer(LojaSerializer):
    repasses_info = serializers.SerializerMethodField()

    class Meta(LojaSerializer.Meta):
        fields = "__all__"

    def get_repasses_info(self, obj):
        repasses, atrasados = obj.get_repasses_status()
        return {"repasses": repasses, "atrasados": atrasados}


class RepasseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repasse
        fields = ["id", "valor", "data", "status", "observacao", "criado_por", "criado_em"]


class RepasseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repasse
        fields = ["valor", "data", "status", "observacao"]

    def create(self, validated_data):
        request = self.context["request"]
        loja = self.context["loja"]
        user = request.user
        return Repasse.objects.create(
            loja=loja,
            criado_por=user,
            atualizado_por=user,
            **validated_data,
        )


class ContatoAdicionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContatoAdicional
        fields = ["id", "nome_adicional", "contato", "endereco_adicional", "obteve_contato"]


class InformacaoPessoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = InformacaoPessoal
        fields = ["id", "nome", "contato", "endereco", "obteve_contato"]


class ComprovantesClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComprovantesCliente
        fields = [
            "id",
            "documento_identificacao_frente",
            "documento_identificacao_frente_analise",
            "documento_identificacao_verso",
            "documento_identificacao_verso_analise",
            "comprovante_residencia",
            "comprovante_residencia_analise",
            "consulta_serasa",
            "consulta_serasa_analise",
            "consulta_serasa_2",
            "consulta_serasa_2_analise",
            "restricao",
            "foto_cliente",
        ]


class ConsultaSerasaAcessoSerializer(serializers.ModelSerializer):
    usuario_username = serializers.CharField(source="usuario.username", read_only=True, default=None)
    usuario_nome = serializers.SerializerMethodField()
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = ConsultaSerasaAcesso
        fields = [
            "id",
            "tipo",
            "tipo_display",
            "usuario",
            "usuario_username",
            "usuario_nome",
            "aberto_em",
            "ip_address",
        ]
        read_only_fields = fields

    def get_usuario_nome(self, obj):
        u = obj.usuario
        if not u:
            return None
        nome = (u.first_name or "").strip()
        sobrenome = (u.last_name or "").strip()
        full = f"{nome} {sobrenome}".strip()
        return full or u.username


class NumeroAutenticadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = NumeroAutenticador
        fields = ['id', 'numero', 'descricao', 'ativo', 'loja']


class AnaliseCreditoClienteSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    status_app_display = serializers.CharField(source="get_status_aplicativo_display", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_is_iphone = serializers.BooleanField(source="produto.is_iphone", read_only=True)
    marca = serializers.IntegerField(source="produto.marca_id", read_only=True)
    marca_nome = serializers.CharField(source="produto.marca.nome", read_only=True)
    imei_value = serializers.CharField(source="imei.imei", read_only=True)
    imei_ultimos_digitos_vendedor = serializers.CharField(read_only=True)
    venda_gerada = serializers.SerializerMethodField()
    numero_autenticador_detail = serializers.SerializerMethodField()

    class Meta:
        model = AnaliseCreditoCliente
        fields = [
            "id",
            "cliente",
            "loja",
            "data_analise",
            "data_aprovacao",
            "data_reprovacao",
            "data_cancelamento",
            "aprovado_por",
            "status",
            "status_display",
            "status_aplicativo",
            "status_app_display",
            "analise_online",
            "data_pagamento",
            "numero_parcelas",
            "produto",
            "produto_nome",
            "produto_is_iphone",
            "marca",
            "marca_nome",
            "imei",
            "imei_value",
            "imei_informado",
            "imei_ultimos_digitos_vendedor",
            "venda",
            "observacao",
            "entrada_informada",
            "email_icloud",
            "senha_icloud",
            "icloud_configurado_vendedor",
            "icloud_confirmado_analista",
            "codigo_reserva",
            "venda_gerada",
            "numero_autenticador",
            "numero_autenticador_detail",
        ]

    def get_venda_gerada(self, obj):
        return bool(obj.venda_id)

    def get_numero_autenticador_detail(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        user = request.user
        pode_ver = (
            user.is_superuser
            or user.groups.filter(name__in=["ANALISTA", "ADMINISTRADOR"]).exists()
        )
        if not pode_ver:
            return None
        if obj.numero_autenticador_id:
            return {
                "id": obj.numero_autenticador.id,
                "numero": obj.numero_autenticador.numero,
                "descricao": obj.numero_autenticador.descricao,
            }
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request:
            user = request.user
            pode_ver = (
                user.is_superuser
                or user.groups.filter(name__in=["ANALISTA", "ADMINISTRADOR"]).exists()
            )
            if not pode_ver:
                data.pop("numero_autenticador", None)
                data.pop("numero_autenticador_detail", None)
        return data


class ClienteSolicitacaoSerializer(serializers.ModelSerializer):
    loja_nome = serializers.CharField(source="loja.nome", read_only=True)
    contato_adicional = ContatoAdicionalSerializer(read_only=True)
    informacao_pessoal = InformacaoPessoalSerializer(read_only=True)
    comprovantes = ComprovantesClienteSerializer(read_only=True)
    analise_credito = AnaliseCreditoClienteSerializer(read_only=True)

    qr_code_aplicativo = serializers.SerializerMethodField()
    codigo_aplicativo = serializers.SerializerMethodField()

    def _get_loja_credfacil(self):
        if not hasattr(self, "_loja_credfacil_cache"):
            self._loja_credfacil_cache = Loja.objects.filter(credfacil=True).first()
        return self._loja_credfacil_cache

    def get_qr_code_aplicativo(self, obj):
        loja = self._get_loja_credfacil()
        if not loja or not loja.qr_code_aplicativo:
            return None
        request = self.context.get("request")
        url = loja.qr_code_aplicativo.url
        return request.build_absolute_uri(url) if request else url

    def get_codigo_aplicativo(self, obj):
        loja = self._get_loja_credfacil()
        return loja.codigo_aplicativo if loja else None

    class Meta:
        model = Cliente
        fields = [
            "id",
            "loja",
            "loja_nome",
            "qr_code_aplicativo",
            "codigo_aplicativo",
            "nome",
            "email",
            "telefone",
            "cpf",
            "nascimento",
            "rg",
            "cep",
            "endereco",
            "bairro",
            "cidade",
            "profissao",
            "quantidade_dependentes",
            "recebe_auxilio",
            "total_renda",
            "observacao_cliente",
            "contato_adicional",
            "informacao_pessoal",
            "comprovantes",
            "analise_credito",
        ]


class MarcaSerializer(serializers.ModelSerializer):
    lojas_permitidas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Loja.objects.all(),
        required=False,
    )

    class Meta:
        model = Marca
        fields = ["id", "nome", "cor", "icone", "ativo", "lojas_permitidas"]


class ParcelamentoSerializer(serializers.ModelSerializer):
    marca_nome = serializers.CharField(source="marca.nome", read_only=True)

    class Meta:
        model = Parcelamento
        fields = ["id", "marca", "marca_nome", "qtd_vezes", "porcentagem_juros", "porcentagem_desconto"]


class TipoProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoProduto
        fields = ["id", "nome"]


class FabricanteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fabricante
        fields = ["id", "nome"]


class ProdutoSerializer(serializers.ModelSerializer):
    tipo = TipoProdutoSerializer(read_only=True)
    marca = MarcaSerializer(read_only=True)
    tipo_id = serializers.PrimaryKeyRelatedField(
        source="tipo",
        queryset=TipoProduto.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    marca_id = serializers.PrimaryKeyRelatedField(
        source="marca",
        queryset=Marca.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = Produto
        fields = "__all__"
        read_only_fields = ["codigo"]


class ProdutoVendaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)

    class Meta:
        model = ProdutoVenda
        fields = [
            "id",
            "produto",
            "produto_nome",
            "imei",
            "valor_unitario",
            "quantidade",
            "valor_desconto",
        ]


class PagamentoSerializer(serializers.ModelSerializer):
    tipo_pagamento_nome = serializers.CharField(source="tipo_pagamento.nome", read_only=True)
    # Alias para compatibilidade
    tipo_nome = serializers.CharField(source="tipo_pagamento.nome", read_only=True)

    class Meta:
        model = Pagamento
        fields = [
            "id",
            "tipo_pagamento",
            "tipo_pagamento_nome",
            "tipo_nome",
            "valor",
            "parcelas",
            "data_primeira_parcela",
            "porcentagem_desconto",
            "bloqueado",
            "desativado",
            "devolucao",
            "quitado",
        ]


class VendaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome", read_only=True)
    vendedor_nome = serializers.SerializerMethodField()
    loja_nome = serializers.CharField(source="loja.nome", read_only=True)
    itens_venda = ProdutoVendaSerializer(many=True, read_only=True)
    pagamentos = PagamentoSerializer(many=True, read_only=True)
    
    # Campos calculados para facilitar exibição no frontend
    valor_total = serializers.SerializerMethodField()
    valor_total_pagamentos = serializers.SerializerMethodField()
    qtd_total_parcelas = serializers.SerializerMethodField()
    valor_entrada_cliente = serializers.SerializerMethodField()
    tem_iphone = serializers.BooleanField(read_only=True)

    def get_vendedor_nome(self, obj):
        if obj.vendedor:
            return obj.vendedor.get_full_name() or obj.vendedor.username
        return None
    
    def get_valor_total(self, obj):
        """Valor total calculado dos produtos (itens_venda)"""
        return str(obj.calcular_valor_total())
    
    def get_valor_total_pagamentos(self, obj):
        """Valor total dos pagamentos"""
        return str(obj.pagamentos_valor_total)
    
    def get_qtd_total_parcelas(self, obj):
        """Quantidade total de parcelas (soma de todos os pagamentos parcelados)"""
        return obj.qtd_total_parcelas()
    
    def get_valor_entrada_cliente(self, obj):
        """Valor da entrada paga pelo cliente"""
        return str(obj.valor_entrada_cliente)

    class Meta:
        model = Venda
        fields = [
            "id",
            "loja",
            "loja_nome",
            "cliente",
            "cliente_nome",
            "vendedor",
            "vendedor_nome",
            "data_venda",
            "observacao",
            "repasse_logista",
            "documento_assinado",
            "foto_cliente",
            "imagem_imei",
            "contrato_publico_uuid",
            "status_contrato",
            "is_deleted",
            "is_trocado",
            "itens_venda",
            "pagamentos",
            # Campos calculados
            "valor_total",
            "valor_total_pagamentos",
            "qtd_total_parcelas",
            "valor_entrada_cliente",
            "tem_iphone",
        ]


class ProdutoVendaInputSerializer(serializers.Serializer):
    produto = serializers.IntegerField()
    quantidade = serializers.IntegerField()
    valor_unitario = serializers.DecimalField(max_digits=10, decimal_places=2)
    valor_desconto = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    imei = serializers.IntegerField(required=False)


class PagamentoInputSerializer(serializers.Serializer):
    tipo_pagamento = serializers.IntegerField()
    valor = serializers.DecimalField(max_digits=10, decimal_places=2)
    parcelas = serializers.IntegerField()
    data_primeira_parcela = serializers.DateField()


class VendaCreateUpdateSerializer(serializers.Serializer):
    cliente = serializers.IntegerField()
    vendedor = serializers.IntegerField()
    observacao = serializers.CharField(required=False, allow_blank=True)
    itens = ProdutoVendaInputSerializer(many=True)
    pagamentos = PagamentoInputSerializer(many=True)


class VendaEdicaoEspecialInputSerializer(serializers.Serializer):
    itens = ProdutoVendaInputSerializer(many=True)
    pagamentos = PagamentoInputSerializer(many=True)


class VendaTrocaProdutoSerializer(serializers.Serializer):
    produto_atual = serializers.IntegerField()
    novo_produto = serializers.IntegerField()
    imei = serializers.IntegerField()
    motivo = serializers.CharField(required=False, allow_blank=True)


class VendaDocumentosSerializer(serializers.Serializer):
    documento_assinado = serializers.FileField(required=False)
    foto_cliente = serializers.FileField(required=False)
    imagem_imei = serializers.FileField(required=False)


class SolicitacaoCreditoInputSerializer(serializers.Serializer):
    nome = serializers.CharField()
    telefone = serializers.CharField()
    cpf = serializers.CharField()
    nascimento = serializers.DateField()
    rg = serializers.CharField(required=False, allow_blank=True)
    cep = serializers.CharField(required=False, allow_blank=True)
    endereco = serializers.CharField()
    bairro = serializers.CharField()
    cidade = serializers.CharField()
    profissao = serializers.CharField()
    quantidade_dependentes = serializers.IntegerField()
    recebe_auxilio = serializers.BooleanField()
    total_renda = serializers.DecimalField(max_digits=10, decimal_places=2)

    # Contato Adicional e Informação Pessoal aparecem ambos, mas apenas UM
    # precisa estar completo (validado na view). Por isso todos são opcionais aqui.
    nome_adicional = serializers.CharField(required=False, allow_blank=True)
    contato = serializers.CharField(required=False, allow_blank=True)
    endereco_adicional = serializers.CharField(required=False, allow_blank=True)
    obteve_contato = serializers.BooleanField(required=False)

    nome_pessoal = serializers.CharField(required=False, allow_blank=True)
    contato_pessoal = serializers.CharField(required=False, allow_blank=True)
    endereco_pessoal = serializers.CharField(required=False, allow_blank=True)
    obteve_contato_pessoal = serializers.BooleanField(required=False)

    documento_identificacao_frente = serializers.FileField()
    documento_identificacao_verso = serializers.FileField()
    comprovante_residencia = serializers.FileField(required=False, allow_null=True)
    consulta_serasa = serializers.FileField(required=False)
    consulta_serasa_2 = serializers.FileField(required=False)
    foto_cliente = serializers.FileField()
    restricao = serializers.BooleanField(required=False)

    def validate(self, attrs):
        analise_online = attrs.get("analise_online", False)
        if analise_online and not attrs.get("comprovante_residencia"):
            raise serializers.ValidationError(
                {"comprovante_residencia": ["Comprovante de residência é obrigatório para análise online."]}
            )
        return attrs

    marca = serializers.IntegerField()
    produto = serializers.IntegerField()
    data_pagamento = serializers.CharField()
    numero_parcelas = serializers.CharField()
    entrada_informada = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    analise_online = serializers.BooleanField(required=False)
    email_icloud = serializers.EmailField(required=False, allow_blank=True)
    senha_icloud = serializers.CharField(required=False, allow_blank=True)


class SolicitacaoImeiTelefoneInputSerializer(serializers.Serializer):
    telefone = serializers.CharField()
    marca = serializers.IntegerField()
    produto = serializers.IntegerField()
    data_pagamento = serializers.CharField()
    numero_parcelas = serializers.CharField()
    imei = serializers.IntegerField()


class InformarImeiAnaliseInputSerializer(serializers.Serializer):
    imei_informado = serializers.CharField()


# --- User / Group / Permission serializers ---
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "codename", "name", "content_type"]


class GroupSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all())

    class Meta:
        model = Group
        fields = ["id", "name", "permissions"]


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    # Accept lists of IDs on write
    groups = serializers.PrimaryKeyRelatedField(many=True, queryset=Group.objects.all(), required=False)
    user_permissions = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all(), required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "is_staff",
            "is_active",
            "is_superuser",
            "loja",
            "groups",
            "user_permissions",
            "password",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", [])
        perms = validated_data.pop("user_permissions", [])
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        if groups:
            user.groups.set(groups)
        if perms:
            user.user_permissions.set(perms)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", None)
        perms = validated_data.pop("user_permissions", None)

        for attr, val in validated_data.items():
            setattr(instance, attr, val)

        if password:
            instance.set_password(password)

        instance.save()

        if groups is not None:
            instance.groups.set(groups)
        if perms is not None:
            instance.user_permissions.set(perms)

        return instance

    def to_representation(self, instance):
        """
        Represent groups and user_permissions as nested objects on read,
        while still accepting lists of IDs on write.
        """
        ret = super().to_representation(instance)
        
        # Informações básicas de admin
        ret["is_admin"] = instance.is_superuser or instance.is_staff
        ret["is_superuser"] = instance.is_superuser
        ret["is_staff"] = instance.is_staff
        
        # Grupos do usuário
        ret["groups"] = GroupSerializer(instance.groups.all(), many=True).data
        ret["grupos_nomes"] = list(instance.groups.values_list('name', flat=True))
        
        # Permissões diretas do usuário
        ret["user_permissions"] = PermissionSerializer(instance.user_permissions.all(), many=True).data
        
        # TODAS as permissões efetivas (usuário + grupos)
        todas_permissoes = instance.get_all_permissions()
        ret["todas_permissoes"] = sorted(list(todas_permissoes))
        
        # Adicionar lojas acessíveis
        lojas_como_usuario = list(instance.lojas.values('id', 'nome', 'cnpj'))
        lojas_como_gerente = list(instance.lojas_gerenciadas.values('id', 'nome', 'cnpj'))
        loja_principal = None
        if instance.loja:
            loja_principal = {
                'id': instance.loja.id,
                'nome': instance.loja.nome,
                'cnpj': instance.loja.cnpj
            }
        
        ret["loja_principal"] = loja_principal
        ret["lojas_acesso"] = lojas_como_usuario
        ret["lojas_gerenciadas"] = lojas_como_gerente
        
        # Adicionar informações de permissões/acessos específicas
        ret["acessos"] = {
            # Admin
            "is_admin": ret["is_admin"],
            "is_superuser": instance.is_superuser,
            # Lojas
            "pode_ver_todas_lojas": instance.has_perm("vendas.can_view_all_stores"),
            "pode_criar_loja": instance.has_perm("vendas.add_loja"),
            "pode_editar_loja": instance.has_perm("vendas.change_loja"),
            "pode_deletar_loja": instance.has_perm("vendas.delete_loja"),
            "pode_ver_loja": instance.has_perm("vendas.view_loja"),
            # Repasses
            "pode_criar_repasse": instance.has_perm("financeiro.add_repasse"),
            "pode_ver_repasse": instance.has_perm("financeiro.view_repasse"),
            "pode_editar_repasse": instance.has_perm("financeiro.change_repasse"),
            "pode_deletar_repasse": instance.has_perm("financeiro.delete_repasse"),
            # Produtos
            "pode_criar_produto": instance.has_perm("produtos.add_produto"),
            "pode_editar_produto": instance.has_perm("produtos.change_produto"),
            "pode_deletar_produto": instance.has_perm("produtos.delete_produto"),
            "pode_ver_produto": instance.has_perm("produtos.view_produto"),
            # Solicitações/Clientes
            "pode_criar_solicitacao": (
                instance.has_perm("vendas.add_cliente") or instance.has_perm("vendas.add_analisecreditocliente")
            ),
            "pode_criar_cliente": instance.has_perm("vendas.add_cliente"),
            "pode_editar_cliente": instance.has_perm("vendas.change_cliente"),
            "pode_ver_cliente": instance.has_perm("vendas.view_cliente"),
            # Análise de Crédito
            "pode_criar_analise": instance.has_perm("vendas.add_analisecreditocliente"),
            "pode_editar_analise": instance.has_perm("vendas.change_analisecreditocliente"),
            "pode_ver_todas_analises": instance.has_perm("vendas.view_all_analise_credito"),
            "pode_mudar_status_analise": instance.has_perm("vendas.change_status_analise"),
            # Vendas
            "pode_criar_venda": instance.has_perm("vendas.add_venda"),
            "pode_editar_venda": instance.has_perm("vendas.change_venda"),
            "pode_deletar_venda": instance.has_perm("vendas.delete_venda"),
            "pode_ver_venda": instance.has_perm("vendas.view_venda"),
            "pode_ver_todas_vendas": instance.has_perm("vendas.can_view_all_sales"),
            "pode_editar_venda_finalizada": instance.has_perm("vendas.can_edit_finished_sale"),
            # Usuários
            "pode_criar_usuario": instance.has_perm("accounts.add_user"),
            "pode_editar_usuario": instance.has_perm("accounts.change_user"),
            "pode_deletar_usuario": instance.has_perm("accounts.delete_user"),
            "pode_ver_usuario": instance.has_perm("accounts.view_user"),
        }
        
        return ret


# Custom JWT Token Serializer para incluir informações do usuário e lojas no login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Serializer customizado para incluir informações do usuário e lojas no response do login JWT.
    """
    
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Adicionar dados do usuário no response
        user_serializer = UserSerializer(self.user)
        data['user'] = user_serializer.data
        
        return data



class PreAnaliseRapidaSerializer(serializers.ModelSerializer):
    """Leitura da pré-análise rápida (lista/detalhe)."""
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    loja_nome = serializers.CharField(source="loja.nome", read_only=True)
    criado_por_nome = serializers.SerializerMethodField()
    analisado_por_nome = serializers.SerializerMethodField()
    finalizada = serializers.BooleanField(read_only=True)

    class Meta:
        model = PreAnaliseRapida
        fields = [
            "id",
            "nome_completo",
            "cpf",
            "foto_rg_frente",
            "foto_rg_verso",
            "tem_comprovante_residencia",
            "possui_duas_referencias",
            "status",
            "status_display",
            "observacao",
            "loja",
            "loja_nome",
            "criado_por",
            "criado_por_nome",
            "analisado_por",
            "analisado_por_nome",
            "data_decisao",
            "cliente_gerado",
            "finalizada",
            "criado_em",
            "modificado_em",
        ]
        read_only_fields = [
            "status", "observacao", "analisado_por", "data_decisao",
            "cliente_gerado", "criado_por", "loja",
        ]

    def _nome_user(self, user):
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_criado_por_nome(self, obj):
        return self._nome_user(obj.criado_por)

    def get_analisado_por_nome(self, obj):
        return self._nome_user(obj.analisado_por)


class PreAnaliseRapidaInputSerializer(serializers.ModelSerializer):
    """Criação da pré-análise rápida pelo vendedor (multipart)."""

    class Meta:
        model = PreAnaliseRapida
        fields = [
            "nome_completo",
            "cpf",
            "foto_rg_frente",
            "foto_rg_verso",
            "tem_comprovante_residencia",
            "possui_duas_referencias",
        ]

    def validate_nome_completo(self, value):
        value = (value or "").strip()
        if len(value.split()) < 2:
            raise serializers.ValidationError("Informe o nome completo.")
        return value

    def validate_cpf(self, value):
        digitos = "".join(filter(str.isdigit, value or ""))
        if len(digitos) != 11:
            raise serializers.ValidationError("CPF inválido.")
        return value
