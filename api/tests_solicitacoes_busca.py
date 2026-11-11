from datetime import date

from django.contrib.auth.models import Permission
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from vendas.models import Cliente, ComprovantesCliente, Loja


class BuscaSolicitacoesTests(APITestCase):
    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja Busca')
        self.user = User.objects.create_user(
            username='analista', email='analista@example.com', password='123456',
        )
        self.loja.usuarios.add(self.user)
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='vendas',
            codename__in=['view_cliente', 'view_all_analise_credito'],
        ))
        self.client.force_authenticate(User.objects.get(pk=self.user.pk))
        self.maria = self._criar_cliente('Maria Souza', '123.456.789-00')
        self.joao = self._criar_cliente('João Lima', '98765432100')

    def _criar_cliente(self, nome: str, cpf: str) -> Cliente:
        return Cliente.objects.create(
            nome=nome, cpf=cpf, telefone='91999999999',
            nascimento=date(1990, 1, 1), rg='123', cep='66000000',
            endereco='Rua A', bairro='Centro', cidade='Belém', loja=self.loja,
            comprovantes=ComprovantesCliente.objects.create(loja=self.loja),
        )

    def _ids_encontrados(self, termo: str) -> set[int]:
        response = self.client.get(reverse('solicitacao-list'), {'search': termo})
        self.assertEqual(response.status_code, 200)
        return {item['id'] for item in response.data['results']}

    def test_busca_por_cpf_sem_mascara(self):
        self.assertEqual(self._ids_encontrados('12345678900'), {self.maria.id})

    def test_busca_por_cpf_com_mascara(self):
        self.assertEqual(self._ids_encontrados('123.456.789-00'), {self.maria.id})

    def test_busca_por_parte_do_cpf(self):
        self.assertEqual(self._ids_encontrados('98765'), {self.joao.id})

    def test_busca_por_nome_continua_funcionando(self):
        self.assertEqual(self._ids_encontrados('maria'), {self.maria.id})
