from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from financeiro.models import Repasse
from vendas.models import Loja


class LojaApiTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", email="tester@example.com", password="123456")
        self.loja = Loja.objects.create(nome="Loja API")
        self.loja.usuarios.add(self.user)

    def _add_perm(self, app_label, codename):
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        self.user.user_permissions.add(perm)

    def test_loja_retrieve_exibe_flags_de_acesso_e_bloqueia_repasses_sem_permissao(self):
        self._add_perm("vendas", "view_loja")
        self.client.force_authenticate(self.user)

        url = reverse("loja-detail", args=[self.loja.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("acessos", response.data)
        self.assertFalse(response.data["acessos"]["pode_ver_repasse"])
        self.assertEqual(response.data["repasses"]["count"], 0)

    def test_loja_repasses_endpoint_respeita_permissoes(self):
        self._add_perm("vendas", "view_loja")
        self.client.force_authenticate(self.user)
        repasses_url = reverse("loja-repasses", args=[self.loja.id])

        forbidden_response = self.client.get(repasses_url)
        self.assertEqual(forbidden_response.status_code, status.HTTP_403_FORBIDDEN)

        self._add_perm("financeiro", "view_repasse")
        criador = User.objects.create_user(username="finance", email="finance@example.com", password="123456")
        Repasse.objects.create(
            loja=self.loja,
            valor="120.00",
            data=timezone.now(),
            status="pendente",
            criado_por=criador,
            atualizado_por=criador,
        )

        allowed_response = self.client.get(repasses_url)
        self.assertEqual(allowed_response.status_code, status.HTTP_200_OK)
        self.assertEqual(allowed_response.data["count"], 1)

        self._add_perm("financeiro", "add_repasse")
        create_response = self.client.post(
            repasses_url,
            {
                "valor": "250.00",
                "data": timezone.now().isoformat(),
                "status": "pendente",
                "observacao": "repasse api",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Repasse.objects.filter(loja=self.loja).count(), 2)
