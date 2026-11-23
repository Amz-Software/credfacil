"""Cenários de teste do módulo de crédito."""
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from produtos.models import Marca, Parcelamento, Produto
from vendas.models import (
    AnaliseCreditoCliente,
    Cliente,
    ComprovantesCliente,
    InformacaoPessoal,
    ContatoAdicional,
    PreAnaliseRapida,
    TipoPagamento,
)

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario  # noqa: F401

BASE = '/api/bo/v1/credito'
MEDIA_TESTE = tempfile.mkdtemp(prefix='credfacil-bo-credito-')

PERMISSOES_ANALISTA = (
    'vendas.view_cliente',
    'vendas.change_cliente',
    'vendas.change_status_analise',
    'vendas.change_analisecreditocliente',
    'vendas.add_venda',
)


def pdf(nome: str = 'doc.pdf') -> SimpleUploadedFile:
    return SimpleUploadedFile(nome, b'%PDF-1.4 conteudo de teste', content_type='application/pdf')


def png(nome: str = 'foto.png') -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
    return SimpleUploadedFile(nome, buffer.getvalue(), content_type='image/png')


def criar_produto(*, nome='Galaxy', is_iphone=False, parcelas=(10,)) -> Produto:
    marca = Marca.objects.create(nome=f'Marca {nome}')
    for qtd in parcelas:
        Parcelamento.objects.create(
            marca=marca, qtd_vezes=qtd, porcentagem_juros=Decimal('20'), porcentagem_desconto=Decimal('5'),
        )
    return Produto.objects.create(
        nome=nome, valor=Decimal('1200.00'), entrada_cliente=Decimal('200.00'), marca=marca, is_iphone=is_iphone,
    )


def criar_solicitacao(loja, produto, *, nome='Maria Silva', cpf='12345678901', status='EA', criado_por=None,
                      com_arquivos=True, **analise) -> Cliente:
    comprovantes = ComprovantesCliente.objects.create(
        documento_identificacao_frente=pdf('frente.pdf') if com_arquivos else None,
        documento_identificacao_verso=pdf('verso.pdf') if com_arquivos else None,
        foto_cliente=pdf('foto.pdf') if com_arquivos else None,
        consulta_serasa=pdf('serasa.pdf') if com_arquivos else None,
    )
    cliente = Cliente.objects.create(
        nome=nome, telefone='91999999999', cpf=cpf, nascimento=date(1990, 1, 1), rg='1234567',
        cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', profissao='Vendedor',
        loja=loja, comprovantes=comprovantes,
        contato_adicional=ContatoAdicional.objects.create(
            nome_adicional='Ref Um', contato='91988887777', endereco_adicional='Rua B',
        ),
        informacao_pessoal=InformacaoPessoal.objects.create(nome='Ref Dois', contato='91977776666', endereco='Rua C'),
    )
    AnaliseCreditoCliente.objects.create(
        cliente=cliente, produto=produto, loja=loja, status=status, criado_por=criado_por,
        data_pagamento='10', numero_parcelas='10', **analise,
    )
    return cliente


def criar_pre_analise(loja, *, nome='João Souza', cpf='98765432100', status='P', criado_por=None) -> PreAnaliseRapida:
    return PreAnaliseRapida.objects.create(
        nome_completo=nome, cpf=cpf, loja=loja, status=status, criado_por=criado_por,
        foto_rg_frente=png('rg_frente.png'), foto_rg_verso=png('rg_verso.png'),
    )


def criar_tipos_pagamento() -> None:
    TipoPagamento.objects.get_or_create(nome='ENTRADA', defaults={'caixa': True})
    TipoPagamento.objects.get_or_create(nome='IPX', defaults={'parcelas': True})


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class CenarioCredito(TestCase):
    """Duas lojas, um analista da loja A, um admin global e um vendedor da loja A."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TESTE, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.loja_a = criar_loja('Loja A')
        self.loja_b = criar_loja('Loja B')
        self.produto = criar_produto()
        self.vendedor = criar_usuario(
            'vendedor', permissoes=('vendas.view_cliente', 'vendas.change_cliente'),
            grupos=('VENDEDOR',), lojas=(self.loja_a,),
        )
        self.analista = criar_usuario(
            'analista', permissoes=PERMISSOES_ANALISTA, grupos=('ANALISTA',), lojas=(self.loja_a,),
        )
        self.admin = criar_usuario(
            'admin', permissoes=PERMISSOES_ANALISTA + ('vendas.view_all_analise_credito',), grupos=('ADMINISTRADOR',),
        )
        self.sem_permissao = criar_usuario('semperm', lojas=(self.loja_a,))
        self.sol_a = criar_solicitacao(self.loja_a, self.produto, criado_por=self.vendedor)
        self.sol_b = criar_solicitacao(self.loja_b, self.produto, nome='Pedro Lima', cpf='55566677788')

    def url(self, cliente_id=None, acao=None) -> str:
        if cliente_id is None:
            return f'{BASE}/solicitacoes/'
        return f'{BASE}/solicitacoes/{cliente_id}/' + (f'{acao}/' if acao else '')

    def logar(self, user):
        return cliente_logado(user)
