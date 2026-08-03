from django.test import SimpleTestCase

from api.serializers import ClienteSolicitacaoSerializer, SolicitacaoCreditoInputSerializer
from vendas.forms import ClienteForm, ClienteTelefoneForm


class ClienteTelefoneFormTests(SimpleTestCase):
    def cliente_data(self, **overrides):
        data = {
            'nome': 'Cliente Teste',
            'telefone': '(85) 99999-1111',
            'cpf': '123.456.789-00',
            'nascimento': '1990-01-01',
            'rg': '1234567',
            'cep': '60000000',
            'endereco': 'Rua Teste',
            'bairro': 'Centro',
            'cidade': 'Fortaleza',
            'profissao': 'Vendedor',
            'quantidade_dependentes': '0',
            'recebe_auxilio': 'False',
            'total_renda': '3000.00',
        }
        data.update(overrides)
        return data

    def test_telefone_principal_e_obrigatorio_e_secundario_e_opcional(self):
        form = ClienteForm(data=self.cliente_data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.fields['telefone'].required)
        self.assertFalse(form.fields['telefone_secundario'].required)
        self.assertEqual(form.cleaned_data['telefone'], '85999991111')
        self.assertEqual(form.cleaned_data['telefone_secundario'], '')

    def test_telefone_secundario_e_normalizado_quando_informado(self):
        form = ClienteForm(data=self.cliente_data(telefone_secundario='(85) 98888-2222'))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['telefone_secundario'], '85988882222')

    def test_telefones_devem_ser_diferentes(self):
        form = ClienteForm(
            data=self.cliente_data(telefone_secundario='(85) 99999-1111')
        )

        self.assertFalse(form.is_valid())
        self.assertIn('telefone_secundario', form.errors)

    def test_formulario_reduzido_permite_editar_os_dois_telefones(self):
        form = ClienteTelefoneForm()

        self.assertTrue(form.fields['telefone'].required)
        self.assertFalse(form.fields['telefone'].disabled)
        self.assertFalse(form.fields['telefone_secundario'].required)
        self.assertFalse(form.fields['telefone_secundario'].disabled)


class ClienteTelefoneApiContractTests(SimpleTestCase):
    def test_resposta_da_solicitacao_expoe_telefone_secundario(self):
        self.assertIn('telefone_secundario', ClienteSolicitacaoSerializer().fields)

    def test_entrada_mantem_apenas_telefone_principal_obrigatorio(self):
        fields = SolicitacaoCreditoInputSerializer().fields

        self.assertTrue(fields['telefone'].required)
        self.assertFalse(fields['telefone_secundario'].required)
        self.assertTrue(fields['telefone_secundario'].allow_blank)
