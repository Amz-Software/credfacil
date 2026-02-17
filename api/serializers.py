from rest_framework import serializers

from financeiro.models import Repasse
from vendas.models import (
    AnaliseCreditoCliente,
    Cliente,
    ContatoAdicional,
    InformacaoPessoal,
    ComprovantesCliente,
    Loja,
    Venda,
)
from produtos.models import Produto
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


class VendaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome", read_only=True)

    class Meta:
        model = Venda
        fields = ["id", "data_venda", "cliente", "cliente_nome", "repasse_logista", "is_deleted"]


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
            "restricao",
            "foto_cliente",
        ]


class AnaliseCreditoClienteSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    status_app_display = serializers.CharField(source="get_status_aplicativo_display", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_is_iphone = serializers.BooleanField(source="produto.is_iphone", read_only=True)
    imei_value = serializers.CharField(source="imei.imei", read_only=True)
    venda_gerada = serializers.SerializerMethodField()

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
            "imei",
            "imei_value",
            "imei_informado",
            "venda",
            "observacao",
            "email_icloud",
            "senha_icloud",
            "icloud_configurado_vendedor",
            "icloud_confirmado_analista",
            "venda_gerada",
        ]

    def get_venda_gerada(self, obj):
        return bool(obj.venda_id)


class ClienteSolicitacaoSerializer(serializers.ModelSerializer):
    loja_nome = serializers.CharField(source="loja.nome", read_only=True)
    contato_adicional = ContatoAdicionalSerializer(read_only=True)
    informacao_pessoal = InformacaoPessoalSerializer(read_only=True)
    comprovantes = ComprovantesClienteSerializer(read_only=True)
    analise_credito = AnaliseCreditoClienteSerializer(read_only=True)

    class Meta:
        model = Cliente
        fields = [
            "id",
            "loja",
            "loja_nome",
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


class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = "__all__"


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
    tipo_nome = serializers.CharField(source="tipo_pagamento.nome", read_only=True)

    class Meta:
        model = Pagamento
        fields = [
            "id",
            "tipo_pagamento",
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
    itens_venda = ProdutoVendaSerializer(many=True, read_only=True)
    pagamentos = PagamentoSerializer(many=True, read_only=True)

    class Meta:
        model = Venda
        fields = [
            "id",
            "loja",
            "cliente",
            "cliente_nome",
            "vendedor",
            "data_venda",
            "observacao",
            "repasse_logista",
            "documento_assinado",
            "foto_cliente",
            "imagem_imei",
            "is_deleted",
            "is_trocado",
            "itens_venda",
            "pagamentos",
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
    rg = serializers.CharField()
    cep = serializers.CharField()
    endereco = serializers.CharField()
    bairro = serializers.CharField()
    cidade = serializers.CharField()
    profissao = serializers.CharField()
    quantidade_dependentes = serializers.IntegerField()
    recebe_auxilio = serializers.BooleanField()
    total_renda = serializers.DecimalField(max_digits=10, decimal_places=2)

    nome_adicional = serializers.CharField()
    contato = serializers.CharField()
    endereco_adicional = serializers.CharField()
    obteve_contato = serializers.BooleanField(required=False)

    nome_pessoal = serializers.CharField()
    contato_pessoal = serializers.CharField()
    endereco_pessoal = serializers.CharField()
    obteve_contato_pessoal = serializers.BooleanField(required=False)

    documento_identificacao_frente = serializers.FileField()
    documento_identificacao_verso = serializers.FileField()
    comprovante_residencia = serializers.FileField()
    consulta_serasa = serializers.FileField(required=False)
    foto_cliente = serializers.FileField()
    restricao = serializers.BooleanField(required=False)

    produto = serializers.IntegerField()
    data_pagamento = serializers.CharField()
    numero_parcelas = serializers.CharField()
    analise_online = serializers.BooleanField(required=False)
    email_icloud = serializers.EmailField(required=False, allow_blank=True)
    senha_icloud = serializers.CharField(required=False, allow_blank=True)


class SolicitacaoImeiTelefoneInputSerializer(serializers.Serializer):
    telefone = serializers.CharField()
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

