"""Autoatendimento de pagamentos pelo WhatsApp: menu → CPF → nascimento → resumo.

Mesma regra da consulta pública (CPF + data de nascimento). Só responde a quem
pediu (atendimento, não cobrança ativa). Na dúvida ou após 3 tentativas, vai
para a equipe (princípio 6 da arquitetura).
"""
import re
from datetime import date, datetime, timedelta

from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, Mensagem
from crm.services import pagamentos
from crm.telefone import somente_digitos

EXPIRACAO = timedelta(minutes=30)
MAX_TENTATIVAS = 3
MAX_OPCOES_INVALIDAS = 2
MAX_CLIENTES_VINCULADOS = 5
CHAVE_IA = 'ia'  # mesma chave de crm.services.assistente.identidade (que importa este módulo)

MENU, CPF, NASCIMENTO = 'MENU', 'CPF', 'NASCIMENTO'
INTENCAO_PAGAMENTO = re.compile(
    r'\b(parcelas?|pagamentos?|boletos?|pix|faturas?|d[ée]bitos?|segunda via|2[ªa] via|carn[êe]|presta[çc](ão|ões))\b',
    re.IGNORECASE,
)
INTENCAO_ATENDENTE = re.compile(r'\b(atendente|humano|pessoa|falar com algu[ée]m)\b', re.IGNORECASE)
TEXTOS_SAIR = {'0', 'sair', 'encerrar', 'tchau'}

OPCOES = ('Responda com o número:\n'
          '1️⃣ Ver minhas parcelas e pagamentos\n'
          '2️⃣ Falar com um atendente')
PEDE_CPF = 'Para consultar suas parcelas, digite o seu *CPF* (só os números).'
CPF_INVALIDO = 'Esse CPF não parece válido. Digite os 11 números do seu CPF.'
PEDE_NASCIMENTO = 'Agora, para confirmar que é você, digite sua *data de nascimento* (ex.: 17/05/1990).'
DATA_INVALIDA = 'Não entendi a data. Digite no formato dia/mês/ano, por exemplo 17/05/1990.'
NAO_ENCONTRADO = 'Não encontramos parcelas para esse CPF e data de nascimento. Vamos tentar de novo: digite o seu CPF.'
DEPOIS_DO_RESUMO = '\n\nDigite *1* para consultar de novo ou *2* para falar com um atendente.'
CHAMANDO_EQUIPE = 'Certo! Já chamei alguém da nossa equipe. Em instantes vamos te responder por aqui.'
FALHOU_IDENTIFICAR = 'Não consegui confirmar seus dados. Vou chamar alguém da equipe para te ajudar.'
ARQUIVO_RECEBIDO = 'Recebemos sua mensagem. Um atendente vai continuar o atendimento por aqui.'
ATE_LOGO = 'Tudo bem! Quando precisar, é só mandar uma mensagem. 👋'


def cpf_valido(cpf: str) -> bool:
    digitos = somente_digitos(cpf)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * peso for d, peso in zip(digitos[:tamanho], range(tamanho + 1, 1, -1)))
        verificador = (soma * 10) % 11 % 10
        if verificador != int(digitos[tamanho]):
            return False
    return True


def ler_data(texto: str) -> date | None:
    limpo = texto.strip()
    for formato in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d', '%d%m%Y'):
        try:
            data = datetime.strptime(limpo, formato).date()
        except ValueError:
            continue
        return data if 1900 <= data.year <= date.today().year else None
    return None


def _estado(conversa: Conversa) -> dict:
    contexto = conversa.contexto or {}
    desde = contexto.get('desde')
    if not contexto.get('etapa') or not desde:
        return {}
    try:
        inicio = datetime.fromisoformat(desde)
    except ValueError:
        return {}
    return contexto if timezone.now() - inicio <= EXPIRACAO else {}


def _salvar(conversa: Conversa, etapa: str | None, **dados) -> None:
    # Preserva o estado do assistente de IA (identificação e tentativas), que o menu não usa.
    preservado = {k: v for k, v in (conversa.contexto or {}).items() if k == CHAVE_IA}
    etapa_menu = {} if etapa is None else {'etapa': etapa, 'desde': timezone.now().isoformat(), **dados}
    contexto = {**preservado, **etapa_menu}
    Conversa.objects.filter(pk=conversa.pk).update(contexto=contexto)
    conversa.contexto = contexto


def _responder(conversa: Conversa, texto: str, origem: str = '') -> None:
    from crm.services import envio

    envio.enviar_texto(conversa, texto, usuario=None, autor=Mensagem.Autor.AUTOMATICO, origem=origem,
                       exigir_trava=False)


def _transferir(conversa: Conversa, texto_cliente: str, nota: str) -> None:
    from crm.services.conversas import transferir

    if texto_cliente:
        _responder(conversa, texto_cliente)
    _salvar(conversa, None)
    transferir(conversa, nota, silenciosa=not texto_cliente)


def _menu(conversa: Conversa) -> None:
    # A boas-vindas configurada promete um atendente; no menu a saudação é neutra.
    empresa = ConfiguracaoCRM.obter().nome_empresa.strip()
    saudacao = f'Olá! Aqui é o atendimento da {empresa}.' if empresa else 'Olá!'
    texto = f'{saudacao} Como podemos ajudar?\n\n{OPCOES}'
    _responder(conversa, texto, origem=Mensagem.Origem.BOAS_VINDAS)
    Conversa.objects.filter(pk=conversa.pk).update(boas_vindas_em=timezone.now())
    _salvar(conversa, MENU, invalidas=0)


def _ultimo_texto(pendentes: list[Mensagem]) -> str | None:
    """Texto da última mensagem do lote; None se o lote trouxe arquivo, áudio etc."""
    relevantes = [m for m in pendentes if m.tipo not in (Mensagem.Tipo.REACAO, Mensagem.Tipo.FIGURINHA)]
    if not relevantes:
        return ''
    ultima = relevantes[-1]
    return ultima.texto.strip() if ultima.tipo == Mensagem.Tipo.TEXTO else None


def _buscar_e_responder(conversa: Conversa, cpf: str, nascimento: date, tentativas: int) -> None:
    from vendas.models import Cliente

    clientes = list(Cliente.objects.filter(cpf=cpf, nascimento=nascimento))
    itens = pagamentos.resumo_dos_clientes(clientes) if clientes else []
    if not clientes:
        if tentativas + 1 >= MAX_TENTATIVAS:
            _transferir(conversa, FALHOU_IDENTIFICAR,
                        f'Autoatendimento: o cliente não conseguiu se identificar em {MAX_TENTATIVAS} tentativas.')
            return
        _responder(conversa, NAO_ENCONTRADO)
        _salvar(conversa, CPF, tentativas=tentativas + 1)
        return
    conversa.clientes.add(*clientes[:MAX_CLIENTES_VINCULADOS])
    _responder(conversa, pagamentos.texto_resumo(clientes[0].nome, itens) + DEPOIS_DO_RESUMO)
    _salvar(conversa, MENU, invalidas=0)


def tratar(conversa: Conversa, pendentes: list[Mensagem]) -> None:
    texto = _ultimo_texto(pendentes)
    if texto is None:
        _transferir(conversa, ARQUIVO_RECEBIDO, 'Autoatendimento: o cliente mandou arquivo ou áudio.')
        return
    if not texto:
        return
    estado = _estado(conversa)
    etapa = estado.get('etapa')
    minusculo = texto.lower()

    if minusculo in TEXTOS_SAIR and etapa:
        _responder(conversa, ATE_LOGO)
        _salvar(conversa, None)
        return
    if (minusculo == '2' and etapa in (None, MENU)) or INTENCAO_ATENDENTE.search(texto):
        _transferir(conversa, CHAMANDO_EQUIPE, 'O cliente pediu para falar com um atendente.')
        return

    if etapa is None:
        if minusculo == '1' or INTENCAO_PAGAMENTO.search(texto):
            _responder(conversa, PEDE_CPF)
            _salvar(conversa, CPF, tentativas=0)
        else:
            _menu(conversa)
        return

    if etapa == MENU:
        if minusculo == '1' or INTENCAO_PAGAMENTO.search(texto):
            _responder(conversa, PEDE_CPF)
            _salvar(conversa, CPF, tentativas=0)
            return
        invalidas = estado.get('invalidas', 0) + 1
        if invalidas >= MAX_OPCOES_INVALIDAS:
            _transferir(conversa, CHAMANDO_EQUIPE, 'Autoatendimento: o cliente escreveu algo fora do menu.')
            return
        _responder(conversa, f'Não entendi. {OPCOES}')
        _salvar(conversa, MENU, invalidas=invalidas)
        return

    tentativas = estado.get('tentativas', 0)
    if etapa == CPF:
        if not cpf_valido(texto):
            if tentativas + 1 >= MAX_TENTATIVAS:
                _transferir(conversa, FALHOU_IDENTIFICAR,
                            f'Autoatendimento: CPF inválido em {MAX_TENTATIVAS} tentativas.')
                return
            _responder(conversa, CPF_INVALIDO)
            _salvar(conversa, CPF, tentativas=tentativas + 1)
            return
        _responder(conversa, PEDE_NASCIMENTO)
        _salvar(conversa, NASCIMENTO, tentativas=tentativas, cpf=somente_digitos(texto))
        return

    if etapa == NASCIMENTO:
        nascimento = ler_data(texto)
        if nascimento is None:
            _responder(conversa, DATA_INVALIDA)
            _salvar(conversa, NASCIMENTO, tentativas=tentativas, cpf=estado.get('cpf', ''))
            return
        _buscar_e_responder(conversa, estado.get('cpf', ''), nascimento, tentativas)
