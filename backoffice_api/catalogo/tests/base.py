"""Apoio aos testes do catálogo: dados de catálogo e TestCase com hash de senha rápido."""
from decimal import Decimal

from django.test import TestCase, override_settings

from backoffice_api.models import RegistroAuditoria
from produtos.models import Marca, Parcelamento, Produto

URL = '/api/bo/v1/catalogo'
# Hash rápido: cada teste faz login pelo endpoint do backoffice.
HASH_RAPIDO = ['django.contrib.auth.hashers.MD5PasswordHasher']


@override_settings(PASSWORD_HASHERS=HASH_RAPIDO)
class CatalogoTestCase(TestCase):
    def assertErro(self, resposta, status: int, codigo: str, campo: str | None = None):
        self.assertEqual(resposta.status_code, status, resposta.content)
        erro = resposta.json()['erro']
        self.assertEqual(erro['codigo'], codigo)
        if campo:
            self.assertIn(campo, erro['campos'])
        return erro

    def assertAuditado(self, acao: str, objeto, **filtros) -> RegistroAuditoria:
        registro = RegistroAuditoria.objects.filter(
            acao=acao, objeto_tipo=objeto._meta.label_lower, objeto_id=str(objeto.pk), **filtros
        ).first()
        self.assertIsNotNone(registro, f'auditoria "{acao}" não gravada')
        return registro


def criar_marca(nome: str, *, lojas=(), ativo: bool = True) -> Marca:
    marca = Marca.objects.create(nome=nome, ativo=ativo)
    marca.lojas_permitidas.set(lojas)
    return marca


def criar_produto(nome: str, marca: Marca | None = None, **campos) -> Produto:
    padrao = {'valor': Decimal('1000.00'), 'entrada_cliente': Decimal('200.00')}
    return Produto.objects.create(nome=nome, marca=marca, **{**padrao, **campos})


def criar_parcelamento(marca, qtd_vezes: int, juros: str, desconto: str = '0') -> Parcelamento:
    return Parcelamento.objects.create(
        marca=marca, qtd_vezes=qtd_vezes,
        porcentagem_juros=Decimal(juros), porcentagem_desconto=Decimal(desconto),
    )


def ids(resposta) -> set[int]:
    return {item['id'] for item in resposta.json()['results']}
