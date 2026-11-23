"""Criação e edição da solicitação de crédito (cliente + análise) pela API."""
import logging

from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiExample
from rest_framework import status
from rest_framework.response import Response

from api.serializers import ClienteSolicitacaoSerializer, SolicitacaoCreditoInputSerializer
from core.uploads import erros_de_upload
from vendas.forms import (
    AnaliseCreditoClienteForm,
    ClienteForm,
    ComprovantesClienteForm,
    ContatoAdicionalForm,
    erro_pelo_menos_um_contato,
    InformacaoPessoalForm,
    user_is_analista_or_admin,
)
from vendas.models import Loja

from .solicitacoes_regras import (
    _avisos_solicitacoes_existentes,
    _normalizar_campos_opcionais_solicitacao,
    _resolver_loja_solicitacao,
    _validar_marca_produto_solicitacao,
    _validar_parcelamento,
)


logger = logging.getLogger(__name__)


class CadastroDeSolicitacaoMixin:
    # Sem docstring: o drf-spectacular usaria o texto como descrição das operações.
    # Usa os auxiliares definidos em SolicitacaoCreditoViewSet.


    def _payload_tem_apenas_arquivos_de_fotos_comprovantes(self, request):
        campos_arquivo = set(request.FILES.keys())
        return bool(campos_arquivo) and campos_arquivo <= self.CAMPOS_FOTO_COMPROVANTES


    def _payload_tem_apenas_telefones(self, request):
        if request.FILES:
            return False
        campos = set(request.data.keys())
        return bool(campos) and campos <= {"telefone", "telefone_secundario"}


    def _atualizar_telefones_cliente(self, request, cliente):
        if not self._usuario_pode_acessar_cliente(request, cliente):
            return Response({"detail": "Acao nao autorizada para esta loja."}, status=status.HTTP_403_FORBIDDEN)

        valores = {
            "telefone": cliente.telefone,
            "telefone_secundario": cliente.telefone_secundario,
        }
        errors = {}
        for campo in request.data.keys():
            telefone = (request.data.get(campo) or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if campo == "telefone" and not telefone:
                errors[campo] = ["Informe o telefone principal."]
            elif telefone and not telefone.isdigit():
                errors[campo] = ["Telefone deve conter apenas numeros."]
            elif telefone and (len(telefone) < 10 or len(telefone) > 11):
                errors[campo] = ["Telefone deve ter entre 10 e 11 digitos."]
            else:
                valores[campo] = telefone

        if (
            valores["telefone_secundario"]
            and valores["telefone"] == valores["telefone_secundario"]
        ):
            errors["telefone_secundario"] = ["O telefone secundario deve ser diferente do principal."]

        if errors:
            return Response(
                {"detail": "Erros de validacao.", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente.telefone = valores["telefone"]
        cliente.telefone_secundario = valores["telefone_secundario"]
        cliente.save(user=request.user)
        return Response(ClienteSolicitacaoSerializer(cliente).data)


    def _resposta_se_arquivo_invalido(self, request):
        """400 com o erro por campo quando algum arquivo não é imagem/PDF ou passa de 10 MB."""
        erros = erros_de_upload(request.FILES)
        if not erros:
            return None
        return Response({"detail": "Erros de validacao.", "errors": erros}, status=status.HTTP_400_BAD_REQUEST)


    def _atualizar_fotos_comprovantes(self, request, cliente):
        if not self._usuario_pode_acessar_cliente(request, cliente):
            return Response({"detail": "Acao nao autorizada para esta loja."}, status=status.HTTP_403_FORBIDDEN)

        if not request.FILES:
            return Response(
                {"detail": "Envie ao menos um arquivo para atualizar as fotos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        comprovantes = cliente.comprovantes
        campos_atualizados = []
        for campo in self.CAMPOS_FOTO_COMPROVANTES:
            arquivo = request.FILES.get(campo)
            if arquivo:
                setattr(comprovantes, campo, arquivo)
                campos_atualizados.append(campo)

        if not campos_atualizados:
            return Response(
                {"detail": "Nenhum campo de foto valido foi enviado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        comprovantes.save(user=request.user)
        return Response(ClienteSolicitacaoSerializer(cliente).data)


    @transaction.atomic
    @extend_schema(
        request=SolicitacaoCreditoInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo",
                value={
                    "marca": 1,
                    "nome": "Fulano",
                    "telefone": "11999999999",
                    "telefone_secundario": "11988888888",
                    "cpf": "12345678900",
                    "nascimento": "1990-01-01",
                    "rg": "1234567",
                    "cep": "01001000",
                    "endereco": "Rua A",
                    "bairro": "Centro",
                    "cidade": "Sao Paulo",
                    "profissao": "Vendedor",
                    "quantidade_dependentes": 0,
                    "recebe_auxilio": False,
                    "total_renda": "3500.00",
                    "nome_adicional": "Beltrano",
                    "contato": "11988887777",
                    "endereco_adicional": "Rua B",
                    "nome_pessoal": "Ciclano",
                    "contato_pessoal": "11977776666",
                    "endereco_pessoal": "Rua C",
                    "documento_identificacao_frente": "file",
                    "documento_identificacao_verso": "file",
                    "comprovante_residencia": "file",
                    "foto_cliente": "file",
                    "produto": 1,
                    "numero_parcelas": "6",
                    "data_pagamento": "10",
                    "analise_online": False,
                },
            )
        ],
    )
    def create(self, request):
        arquivo_invalido = self._resposta_se_arquivo_invalido(request)
        if arquivo_invalido:
            return arquivo_invalido
        payload_data = _normalizar_campos_opcionais_solicitacao(request.data)
        loja, loja_error = _resolver_loja_solicitacao(request, payload_data)

        if loja_error:
            return Response(
                {
                    "detail": "Erros de validacao.",
                    "errors": {"loja": [loja_error]},
                },
                status=400,
            )

        form_cliente = ClienteForm(payload_data, user=request.user)
        form_adicional = ContatoAdicionalForm(payload_data, user=request.user)
        form_informacao = InformacaoPessoalForm(payload_data, user=request.user)
        form_comprovantes = ComprovantesClienteForm(payload_data, request.FILES, user=request.user)
        form_analise_credito = AnaliseCreditoClienteForm(
            payload_data, user=request.user, loja=loja
        )

        if not all(
            [
                form_cliente.is_valid(),
                form_adicional.is_valid(),
                form_informacao.is_valid(),
                form_comprovantes.is_valid(),
                form_analise_credito.is_valid(),
            ]
        ):
            errors = {
                "cliente": form_cliente.errors,
                "contato_adicional": form_adicional.errors,
                "informacao_pessoal": form_informacao.errors,
                "comprovantes": form_comprovantes.errors,
                "analise_credito": form_analise_credito.errors,
            }
            return Response({"detail": "Erros de validacao.", "errors": errors}, status=400)

        aviso = _avisos_solicitacoes_existentes(
            cpf=form_cliente.cleaned_data.get("cpf"),
            rg=form_cliente.cleaned_data.get("rg"),
            nome=form_cliente.cleaned_data.get("nome"),
            telefone=form_cliente.cleaned_data.get("telefone"),
            telefone_secundario=form_cliente.cleaned_data.get("telefone_secundario"),
        )

        contato_adicional_val = form_adicional.cleaned_data.get("contato")
        contato_pessoal_val = form_informacao.cleaned_data.get("contato_pessoal")
        endereco_adicional_val = (form_adicional.cleaned_data.get("endereco_adicional") or "").strip().lower()
        endereco_pessoal_val = (form_informacao.cleaned_data.get("endereco_pessoal") or "").strip().lower()
        nome_adicional_val = (form_adicional.cleaned_data.get("nome_adicional") or "").strip().lower()
        nome_pessoal_val = (form_informacao.cleaned_data.get("nome_pessoal") or "").strip().lower()

        conflito = False
        conflito_erros = {}
        if contato_adicional_val and contato_pessoal_val and contato_adicional_val == contato_pessoal_val:
            conflito = True
            conflito_erros["contato"] = "Contato Adicional nao pode ser igual ao Contato de Informacoes Pessoais."
            conflito_erros["contato_pessoal"] = "Contato de Informacoes Pessoais nao pode ser igual ao Contato Adicional."
        if endereco_adicional_val and endereco_pessoal_val and endereco_adicional_val == endereco_pessoal_val:
            conflito = True
            conflito_erros["endereco_adicional"] = "Endereco Adicional nao pode ser igual ao Endereco de Informacoes Pessoais."
            conflito_erros["endereco_pessoal"] = "Endereco de Informacoes Pessoais nao pode ser igual ao Endereco Adicional."
        if nome_adicional_val and nome_pessoal_val and nome_adicional_val == nome_pessoal_val:
            conflito = True
            conflito_erros["nome_adicional"] = "Nome Adicional nao pode ser igual ao Nome de Informacoes Pessoais."
            conflito_erros["nome_pessoal"] = "Nome de Informacoes Pessoais nao pode ser igual ao Nome Adicional."

        if conflito:
            return Response(
                {"detail": "Informacoes Pessoais e Contato Adicional nao podem ser iguais.", "errors": conflito_erros},
                status=400,
            )

        # Pelo menos um dos dois contatos deve estar completo (nome+contato+endereco).
        erro_contato = erro_pelo_menos_um_contato(form_adicional, form_informacao)
        if erro_contato:
            return Response(
                {
                    "detail": erro_contato,
                    "errors": {"contato": erro_contato, "contato_pessoal": erro_contato},
                },
                status=400,
            )

        # Validação de marca e parcelamento do produto escolhido
        erro_marca = _validar_marca_produto_solicitacao(
            payload_data,
            form_analise_credito.cleaned_data.get("produto"),
        )
        if erro_marca:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_marca}},
                status=400,
            )

        erro_parcelamento = _validar_parcelamento(form_analise_credito)
        if erro_parcelamento:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_parcelamento}},
                status=400,
            )

        comprovantes = form_comprovantes.save()
        contato_adicional = form_adicional.save()
        informacao = form_informacao.save()

        cliente = form_cliente.save(commit=False)
        cliente.criado_por = request.user
        cliente.modificado_por = request.user
        cliente.loja = loja
        cliente.contato_adicional = contato_adicional
        cliente.informacao_pessoal = informacao
        cliente.comprovantes = comprovantes
        cliente.save()

        analise = form_analise_credito.save(commit=False)
        analise.cliente = cliente
        analise.loja = loja
        analise.criado_por = request.user
        analise.modificado_por = request.user
        analise.save(user=request.user)

        payload = ClienteSolicitacaoSerializer(cliente).data
        if aviso:
            payload["warning"] = aviso
        return Response(payload, status=201)


    @transaction.atomic
    @extend_schema(
        request=SolicitacaoCreditoInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo update",
                value={
                    "marca": 1,
                    "nome": "Fulano",
                    "telefone": "11999999999",
                    "telefone_secundario": "11988888888",
                    "cpf": "12345678900",
                    "nascimento": "1990-01-01",
                    "rg": "1234567",
                    "cep": "01001000",
                    "endereco": "Rua A",
                    "bairro": "Centro",
                    "cidade": "Sao Paulo",
                    "profissao": "Vendedor",
                    "quantidade_dependentes": 0,
                    "recebe_auxilio": False,
                    "total_renda": "3500.00",
                    "nome_adicional": "Beltrano",
                    "contato": "11988887777",
                    "endereco_adicional": "Rua B",
                    "nome_pessoal": "Ciclano",
                    "contato_pessoal": "11977776666",
                    "endereco_pessoal": "Rua C",
                    "documento_identificacao_frente": "file",
                    "documento_identificacao_verso": "file",
                    "comprovante_residencia": "file",
                    "foto_cliente": "file",
                    "produto": 1,
                    "numero_parcelas": "6",
                    "data_pagamento": "10",
                    "analise_online": False,
                },
            )
        ],
    )
    def update(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        arquivo_invalido = self._resposta_se_arquivo_invalido(request)
        if arquivo_invalido:
            return arquivo_invalido
        user = request.user

        is_analista = user.groups.filter(name="ANALISTA").exists()
        venda_gerada = cliente.analise_credito.venda is not None

        if self._payload_tem_apenas_telefones(request):
            return self._atualizar_telefones_cliente(request, cliente)

        if (
            cliente.analise_credito.status != "EA"
            and not is_analista
            and not user.has_perm("vendas.change_status_analise")
            and self._payload_tem_apenas_arquivos_de_fotos_comprovantes(request)
        ):
            return self._atualizar_fotos_comprovantes(request, cliente)

        if not is_analista and not user.has_perm("vendas.change_status_analise") and not cliente.analise_credito.status == "EA":
            return Response(
                {"detail": "Somente solicitacoes em analise podem ser editadas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ANALISTA/ADMIN (ou permissão de editar venda finalizada) podem editar
        # mesmo depois da venda gerada; VENDEDOR/GERENTE só antes disso.
        if venda_gerada and not (
            user_is_analista_or_admin(user) or user.has_perm("vendas.can_edit_finished_sale")
        ):
            return Response(
                {"detail": "Somente ANALISTA/ADMIN podem editar solicitacoes com venda gerada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        loja_id = request.session.get("loja_id")
        loja = Loja.objects.filter(id=loja_id).first() if loja_id else None

        payload_data = _normalizar_campos_opcionais_solicitacao(request.data)

        form_cliente = ClienteForm(payload_data, instance=cliente, user=user)
        form_adicional = ContatoAdicionalForm(payload_data, instance=cliente.contato_adicional, user=user)
        form_informacao = InformacaoPessoalForm(payload_data, instance=cliente.informacao_pessoal, user=user)
        form_comprovantes = ComprovantesClienteForm(
            payload_data, request.FILES, instance=cliente.comprovantes, user=user
        )
        form_analise_credito = AnaliseCreditoClienteForm(
            payload_data, instance=cliente.analise_credito, user=user, loja=loja
        )

        if not all(
            [
                form_cliente.is_valid(),
                form_adicional.is_valid(),
                form_informacao.is_valid(),
                form_comprovantes.is_valid(),
                form_analise_credito.is_valid(),
            ]
        ):
            errors = {
                "cliente": form_cliente.errors,
                "contato_adicional": form_adicional.errors,
                "informacao_pessoal": form_informacao.errors,
                "comprovantes": form_comprovantes.errors,
                "analise_credito": form_analise_credito.errors,
            }
            return Response({"detail": "Erros de validacao.", "errors": errors}, status=400)

        # Trava: depois que a venda é GERADA, a aba "Produto" da solicitação fica
        # imutável para QUALQUER usuário (inclusive quem tem can_edit_finished_sale).
        # As demais abas continuam editáveis para quem tem permissão.
        if venda_gerada:
            CAMPOS_ABA_PRODUTO = ["produto", "data_pagamento", "numero_parcelas", "entrada_informada"]
            campos_bloqueados = [
                campo
                for campo in CAMPOS_ABA_PRODUTO
                if campo in payload_data and campo in form_analise_credito.changed_data
            ]
            if campos_bloqueados:
                return Response(
                    {
                        "detail": "As informações de Produto não podem ser alteradas após a venda ter sido gerada.",
                        "campos_bloqueados": campos_bloqueados,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        aviso = _avisos_solicitacoes_existentes(
            cpf=form_cliente.cleaned_data.get("cpf"),
            rg=form_cliente.cleaned_data.get("rg"),
            nome=form_cliente.cleaned_data.get("nome"),
            telefone=form_cliente.cleaned_data.get("telefone"),
            telefone_secundario=form_cliente.cleaned_data.get("telefone_secundario"),
            exclude_cliente_id=cliente.pk,
        )

        contato_adicional_val = form_adicional.cleaned_data.get("contato")
        contato_pessoal_val = form_informacao.cleaned_data.get("contato_pessoal")
        endereco_adicional_val = (form_adicional.cleaned_data.get("endereco_adicional") or "").strip().lower()
        endereco_pessoal_val = (form_informacao.cleaned_data.get("endereco_pessoal") or "").strip().lower()
        nome_adicional_val = (form_adicional.cleaned_data.get("nome_adicional") or "").strip().lower()
        nome_pessoal_val = (form_informacao.cleaned_data.get("nome_pessoal") or "").strip().lower()

        conflito = False
        conflito_erros = {}
        if contato_adicional_val and contato_pessoal_val and contato_adicional_val == contato_pessoal_val:
            conflito = True
            conflito_erros["contato"] = "Contato Adicional nao pode ser igual ao Contato de Informacoes Pessoais."
            conflito_erros["contato_pessoal"] = "Contato de Informacoes Pessoais nao pode ser igual ao Contato Adicional."
        if endereco_adicional_val and endereco_pessoal_val and endereco_adicional_val == endereco_pessoal_val:
            conflito = True
            conflito_erros["endereco_adicional"] = "Endereco Adicional nao pode ser igual ao Endereco de Informacoes Pessoais."
            conflito_erros["endereco_pessoal"] = "Endereco de Informacoes Pessoais nao pode ser igual ao Endereco Adicional."
        if nome_adicional_val and nome_pessoal_val and nome_adicional_val == nome_pessoal_val:
            conflito = True
            conflito_erros["nome_adicional"] = "Nome Adicional nao pode ser igual ao Nome de Informacoes Pessoais."
            conflito_erros["nome_pessoal"] = "Nome de Informacoes Pessoais nao pode ser igual ao Nome Adicional."

        if conflito:
            return Response(
                {"detail": "Informacoes Pessoais e Contato Adicional nao podem ser iguais.", "errors": conflito_erros},
                status=400,
            )

        # Pelo menos um dos dois contatos deve estar completo (nome+contato+endereco).
        erro_contato = erro_pelo_menos_um_contato(form_adicional, form_informacao)
        if erro_contato:
            return Response(
                {
                    "detail": erro_contato,
                    "errors": {"contato": erro_contato, "contato_pessoal": erro_contato},
                },
                status=400,
            )

        # Validação de marca e parcelamento do produto escolhido
        erro_marca = _validar_marca_produto_solicitacao(
            payload_data,
            form_analise_credito.cleaned_data.get("produto"),
        )
        if erro_marca:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_marca}},
                status=400,
            )

        erro_parcelamento = _validar_parcelamento(form_analise_credito, somente_se_alterado=True)
        if erro_parcelamento:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_parcelamento}},
                status=400,
            )

        contato_adicional = form_adicional.save()
        informacao = form_informacao.save()
        comprovantes = form_comprovantes.save()
        form_analise_credito.save()

        cliente_obj = form_cliente.save(commit=False)
        cliente_obj.contato_adicional = contato_adicional
        cliente_obj.comprovantes = comprovantes
        cliente_obj.save(user=user)

        payload = ClienteSolicitacaoSerializer(cliente_obj).data
        if aviso:
            payload["warning"] = aviso
        return Response(payload)


    def partial_update(self, request, pk=None):
        return self.update(request, pk=pk)
