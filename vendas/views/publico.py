"""Páginas públicas do cliente final: consulta e informe de pagamentos."""
from decimal import Decimal
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, FormView, RedirectView, View

from core.seguranca import limitar_por_ip

from vendas.forms import ClienteConsultaForm
from vendas.models import Loja, Pagamento, Parcela

from .vendas import gerar_qrcode_pix


logger = logging.getLogger(__name__)


@method_decorator(limitar_por_ip('publico'), name='post')
class ConsultaPagamentosView(FormView):
    """CPF + nascimento → pagamentos do cliente, com link pelo token público."""
    template_name = "publico/consulta_pagamentos.html"
    form_class = ClienteConsultaForm

    def form_valid(self, form):
        cpf = form.cleaned_data['cpf']
        dob = form.cleaned_data['date_of_birth']
        pagamentos = (
            Pagamento.objects
            .with_status_flags()
            .filter(
                venda__cliente__cpf=cpf,
                venda__cliente__nascimento=dob
            )
        )
        return self.render_to_response(
            self.get_context_data(form=form, pagamentos=pagamentos)
        )


class PagamentoDetailView(DetailView):
    """Página pública do pagamento, acessível só pelo token aleatório (UUID4)."""
    model = Pagamento
    template_name = 'publico/pagamento_detail.html'
    context_object_name = 'pagamento'
    slug_field = 'token_publico'
    slug_url_kwarg = 'token'
    query_pk_and_slug = False


class PagamentoLegadoView(RedirectView):
    """`/pagamento/<id>/` antigo: não mostra mais dados; manda para a consulta por CPF."""
    pattern_name = 'vendas:consulta_pagamentos'
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return super().get_redirect_url()

    def get_context_data(self, **kwargs):
        ctx       = super().get_context_data(**kwargs)
        pagamento = ctx['pagamento']
        
        # cálculo do desconto
        restantes = pagamento.parcelas_pagamento.filter(pago=False)
        total_restante    = sum(p.valor for p in restantes)
        total_pago        = sum(p.valor_pago_efetivo for p in pagamento.parcelas_pagamento.filter(pago=True))
        discount_pct      = getattr(pagamento, 'porcentagem_desconto', Decimal('0'))
        discount_amount   = (total_restante * discount_pct / Decimal('100')).quantize(Decimal('0.01'))
        total_com_desconto= (total_restante - discount_amount).quantize(Decimal('0.01'))

        confirmando_count = pagamento.parcelas_pagamento.filter(
            pagamento_efetuado=True,
            pago=False
        ).count()

        # dados da loja
        loja   = get_object_or_404(Loja, credfacil=True)
        chave  = loja.chave_pix
        cidade = "Belem"

        qr_items = []
        for parcela in pagamento.parcelas_pagamento.all().order_by('numero_parcela'):
            if not parcela.pago:
                txid   = f"{pagamento.pk:04d}{parcela.numero_parcela:02d}"
                valor  = f"{parcela.valor:.2f}"
                descricao = f"Parcela {parcela.numero_parcela} - Pagamento {pagamento.pk}"

                qr_b64 = gerar_qrcode_pix(
                    chave=chave,
                    valor=valor,
                    txid=txid,
                    nome_loja='credfacil',
                    cidade_loja=cidade,
                    descricao=descricao
                )
            else:
                qr_b64 = None

            qr_items.append({
                'parcela': parcela,
                'qr_b64': qr_b64,
            })

        # QR para quitação total com desconto
        if restantes:
            txid_qt = f"{pagamento.pk:04d}QT"
            valor_qt = f"{total_com_desconto:.2f}"
            descricao_qt = f"Quitacao total - Pagamento {pagamento.pk}"

            discount_qr_b64 = gerar_qrcode_pix(
                chave=chave,
                valor=valor_qt,
                txid=txid_qt,
                nome_loja='credfacil',
                cidade_loja=cidade,
                descricao=descricao_qt
            )
        else:
            discount_qr_b64 = None

        ctx.update({
            'qr_items': qr_items,
            'restantes_count': restantes.count(),
            'total_restante': total_restante,
            'total_pago': total_pago,
            'confirmando_count': confirmando_count,
            'discount_pct': discount_pct,
            'total_com_desconto': total_com_desconto,
            'discount_qr_b64': discount_qr_b64,
            'loja': loja,
        })
        return ctx


class InformarPagamentoView(View):
    def post(self, request, token, pk):
        parcela = get_object_or_404(Parcela, pk=pk, pagamento__token_publico=token)
        parcela.pagamento_efetuado = True
        parcela.pagamento_efetuado_em = timezone.now()
        parcela.data_pagamento = timezone.now().date()
        parcela.save(update_fields=['pagamento_efetuado', 'data_pagamento'])
        messages.success(request, "Pagamento informado e está em confirmação.")
        return redirect('vendas:pagamento_detail', token=parcela.pagamento.token_publico)


class InformarTodosPagamentosView(View):
    """
    View para o CLIENTE. Apenas informa que o pagamento foi efetuado,
    sem alterar valores ou confirmar o pagamento.
    """
    def post(self, request, token):
        pagamento = get_object_or_404(Pagamento, token_publico=token)
        
        # Pega todas as parcelas que ainda não foram informadas nem pagas
        parcelas_a_informar = pagamento.parcelas_pagamento.filter(
            pagamento_efetuado=False, 
            pago=False
        )
        
        # Atualiza todas de uma vez (bulk update)
        updated_count = parcelas_a_informar.update(
            pagamento_efetuado=True,
            pagamento_efetuado_em=timezone.now()
        )

        if updated_count > 0:
            messages.success(
                request,
                f"{updated_count} parcelas foram informadas para quitação e agora aguardam a confirmação do nosso time."
            )
        else:
            messages.warning(request, "Nenhuma parcela nova para informar.")

        return redirect('vendas:pagamento_detail', token=pagamento.token_publico)
