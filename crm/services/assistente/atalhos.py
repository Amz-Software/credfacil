"""Serviços do menu com resposta fixa, resolvidos pelo código sem chamar a IA.

Pedido do cliente: nesses serviços o bot não pede dados nem conversa; ou passa direto para a
equipe, ou manda a chave PIX e encerra. Os demais serviços (e qualquer texto livre) seguem
para o assistente de IA, com o roteiro do prompt.

Vale quando a última mensagem do cliente é a escolha de um serviço: o toque na lista do menu
(chega o título) ou só o número, com o menu enviado há pouco tempo neste atendimento.
"""
from datetime import timedelta

from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, EncaminhamentoIA, Mensagem
from crm.services import expediente
from crm.services.assistente import identidade, menu, pix_empresa
from crm.services.assistente.ferramentas import Turno, executar

VALIDADE_DO_MENU = timedelta(minutes=30)
Assunto = EncaminhamentoIA.Assunto

PASSANDO = 'Certo! Já estou te passando para um atendente, só um instante. 😊'
PASSOU_FORA_DO_HORARIO = 'Certo! Já deixei seu atendimento com a nossa equipe. {fora_horario}'
NOVO_APARELHO = 'Que bom que você quitou! 🎉 Já estou te passando para um atendente, que vai te ajudar com o novo aparelho.'
NOVO_APARELHO_FORA = ('Que bom que você quitou! 🎉 Já deixei seu pedido de novo aparelho com a nossa equipe. '
                      '{fora_horario}')
PIX = 'Nossa chave PIX é o *CNPJ* da {empresa}: vou mandar logo abaixo, sozinha, pra você copiar.'
PIX_CONSULTA = ('\n\nPra ver o valor das suas parcelas, é só acessar {link} e informar seu CPF e data de '
                'nascimento.')
PIX_FIM = '\n\nSe precisar de mais alguma coisa, é só mandar mensagem por aqui. 😊'

# Serviço → (assunto da transferência, nota para a equipe). Atraso só transfere no horário comercial.
TRANSFERENCIAS = {
    menu.DESBLOQUEIO: (Assunto.DESBLOQUEIO, 'Cliente escolheu "Desbloquear o aparelho" no menu.'),
    menu.ATRASO: (Assunto.ATRASO, 'Cliente escolheu "Parcela em atraso" no menu (horário comercial).'),
    menu.NOVO_APARELHO: (Assunto.NOVO_APARELHO, 'Cliente diz que já quitou e quer tirar um novo aparelho.'),
    menu.ATENDENTE: (Assunto.ATENDENTE, 'Cliente escolheu "Falar com um atendente" no menu.'),
}


def _ultima_entrada(conversa: Conversa) -> Mensagem | None:
    return (Mensagem.objects.filter(conversa=conversa, direcao=Mensagem.Direcao.ENTRADA)
            .exclude(tipo=Mensagem.Tipo.REACAO).order_by('-criado_em', '-id').first())


def _menu_recente(conversa: Conversa, antes_de) -> bool:
    desde = timezone.now() - VALIDADE_DO_MENU
    encerrada = identidade.encerrada_em(conversa)
    if encerrada and encerrada > desde:
        desde = encerrada
    return Mensagem.objects.filter(conversa=conversa, direcao=Mensagem.Direcao.SAIDA, dados__menu=True,
                                   criado_em__gte=desde, criado_em__lte=antes_de).exists()


def servico_escolhido(conversa: Conversa) -> int | None:
    entrada = _ultima_entrada(conversa)
    if entrada is None or entrada.tipo != Mensagem.Tipo.TEXTO:
        return None
    numero = menu.numero_do_servico(entrada.texto)
    if numero is None:
        return None
    eh_titulo = not entrada.texto.strip().rstrip('.').isdigit()
    return numero if eh_titulo or _menu_recente(conversa, entrada.criado_em) else None


def _aviso_de_transferencia(servico: int) -> str:
    if expediente.aberto():
        return NOVO_APARELHO if servico == menu.NOVO_APARELHO else PASSANDO
    fora = ' '.join(ConfiguracaoCRM.obter().mensagem_fora_horario.split())
    modelo = NOVO_APARELHO_FORA if servico == menu.NOVO_APARELHO else PASSOU_FORA_DO_HORARIO
    return modelo.format(fora_horario=fora).strip()


def _transferir(turno: Turno, servico: int) -> list[str]:
    assunto, nota = TRANSFERENCIAS[servico]
    executar(turno, 'transferir_para_atendente', {'assunto': assunto, 'motivo': nota})
    return [_aviso_de_transferencia(servico)] if turno.transferiu else []


def _pix(turno: Turno) -> list[str] | None:
    chave = pix_empresa.chave()
    if not chave:
        return None  # sem chave cadastrada: a IA segue e transfere
    empresa = ConfiguracaoCRM.obter().nome_empresa.strip() or 'IPX'
    link = pix_empresa.link_consulta()
    texto = PIX.format(empresa=empresa) + (PIX_CONSULTA.format(link=link) if link else '') + PIX_FIM
    turno.encerrar = 'Cliente pediu a chave PIX: enviados a chave (CNPJ) e o link de consulta das parcelas.'
    return [texto, chave]


def resolver(conversa: Conversa, turno: Turno) -> list[str] | None:
    """Textos a enviar (na ordem) quando o serviço tem resposta fixa; None para seguir com a IA."""
    servico = servico_escolhido(conversa)
    if servico == menu.PIX:
        return _pix(turno)
    if servico == menu.ATRASO and not expediente.aberto():
        return None  # fora do horário a IA identifica, mostra a parcela, manda o link e a chave e encerra
    if servico in TRANSFERENCIAS:
        return _transferir(turno, servico)
    return None
