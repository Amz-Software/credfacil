"""Telefones do cliente, tentativas de contato e status de contato da cobrança.

- O telefone principal do cadastro nunca é trocado; outros números entram com a origem.
- Referência nunca recebe aviso de cobrança (para_aviso não a devolve).
- Bloqueio só existe quando a equipe confirma; falta de resposta não é bloqueio.
"""
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from crm.models import Conversa, Mensagem, TelefoneCliente, TentativaContato
from crm.telefone import mesmo_telefone, somente_digitos

Origem = TelefoneCliente.Origem
Situacao = TelefoneCliente.Situacao
Resultado = TentativaContato.Resultado

MIN_DIGITOS = 10
MAX_DIGITOS = 15
CODIGO_SEM_WHATSAPP = 131026
SITUACOES_RUINS = {Situacao.SEM_WHATSAPP, Situacao.INVALIDO, Situacao.BLOQUEADO}
RESULTADO_PARA_SITUACAO = {
    Resultado.SEM_WHATSAPP: Situacao.SEM_WHATSAPP,
    Resultado.NUMERO_INVALIDO: Situacao.INVALIDO,
    Resultado.BLOQUEIO_CONFIRMADO: Situacao.BLOQUEADO,
}
RESULTADOS_DE_REFERENCIA = {Resultado.REFERENCIA_SEM_SUCESSO, Resultado.REFERENCIA_AJUDOU}
FALHAS_DE_REFERENCIA = {Resultado.REFERENCIA_SEM_SUCESSO, Resultado.NUMERO_INVALIDO, Resultado.SEM_WHATSAPP,
                        Resultado.NAO_ATENDEU}
# Ordem de preferência para avisos: principal do cadastro, número usado no atendimento, secundário, C4M/outro.
PRIORIDADE = {'principal': 0, Origem.ATENDIMENTO: 1, 'secundario': 2, Origem.C4M: 3, Origem.OUTRO: 4}


class ErroContato(Exception):
    """Mensagem pronta para a tela."""


class Status:
    CONTATO_REALIZADO = 'CONTATO_REALIZADO'
    AGUARDANDO_RETORNO = 'AGUARDANDO_RETORNO'
    CONTATO_ALTERNATIVO = 'CONTATO_ALTERNATIVO'
    REFERENCIA_SEM_SUCESSO = 'REFERENCIA_SEM_SUCESSO'
    NUMERO_INVALIDO = 'NUMERO_INVALIDO'
    SEM_WHATSAPP = 'SEM_WHATSAPP'
    BLOQUEIO_CONFIRMADO = 'BLOQUEIO_CONFIRMADO'
    NAO_LOCALIZADO = 'NAO_LOCALIZADO'
    SEM_TENTATIVA = 'SEM_TENTATIVA'

    ROTULOS = {
        CONTATO_REALIZADO: 'Contato realizado',
        AGUARDANDO_RETORNO: 'Aguardando retorno',
        CONTATO_ALTERNATIVO: 'Contato alternativo',
        REFERENCIA_SEM_SUCESSO: 'Referência sem sucesso',
        NUMERO_INVALIDO: 'Número inválido',
        SEM_WHATSAPP: 'Sem WhatsApp',
        BLOQUEIO_CONFIRMADO: 'Bloqueio confirmado',
        NAO_LOCALIZADO: 'Não localizado',
        SEM_TENTATIVA: 'Ainda sem tentativa',
    }


def normalizar(numero: str | None) -> str:
    digitos = somente_digitos(numero)
    if not MIN_DIGITOS <= len(digitos) <= MAX_DIGITOS:
        raise ErroContato('Informe o telefone com DDD (10 a 15 dígitos).')
    return digitos


def _achar(telefones, numero: str) -> TelefoneCliente | None:
    return next((t for t in telefones if mesmo_telefone(t.telefone, numero)), None)


def _referencias(cliente) -> list[tuple[str, str]]:
    """Referências da análise (ContatoAdicional e InformacaoPessoal): (número, nome)."""
    refs = []
    for relacao, campo_nome in (('contato_adicional', 'nome_adicional'), ('informacao_pessoal', 'nome')):
        ref = getattr(cliente, relacao, None)
        if ref is not None and somente_digitos(ref.contato):
            refs.append((somente_digitos(ref.contato), getattr(ref, campo_nome, None) or ''))
    return refs


def _candidatos_do_cadastro(cliente) -> list[tuple[str, str, str]]:
    candidatos = [(cliente.telefone, Origem.CADASTRO, ''), (cliente.telefone_secundario, Origem.CADASTRO, '')]
    candidatos += [(numero, Origem.REFERENCIA, nome) for numero, nome in _referencias(cliente)]
    return [(somente_digitos(n), o, nome) for n, o, nome in candidatos if len(somente_digitos(n)) >= MIN_DIGITOS]


def _do_cadastro_atual(cliente, telefone: TelefoneCliente) -> bool:
    return mesmo_telefone(telefone.telefone, cliente.telefone) or \
        mesmo_telefone(telefone.telefone, cliente.telefone_secundario)


def _rebaixar_antigos(cliente, telefones: list[TelefoneCliente]) -> None:
    """Número que saiu do cadastro pode ter outro dono: deixa de receber aviso até a equipe confirmar."""
    for telefone in telefones:
        if telefone.origem == Origem.CADASTRO and not _do_cadastro_atual(cliente, telefone):
            telefone.origem, telefone.situacao = Origem.OUTRO, Situacao.NAO_VERIFICADO
            telefone.observacao = 'Número antigo do cadastro.'
            telefone.save(update_fields=['origem', 'situacao', 'observacao', 'atualizado_em'])


def sincronizar(cliente) -> list[TelefoneCliente]:
    """Garante uma linha para cada número do cadastro e das referências (idempotente)."""
    telefones = list(TelefoneCliente.objects.filter(cliente=cliente))
    _rebaixar_antigos(cliente, telefones)
    for digitos, origem, nome in _candidatos_do_cadastro(cliente):
        if _achar(telefones, digitos):
            continue
        try:
            with transaction.atomic():
                telefones.append(TelefoneCliente.objects.create(
                    cliente=cliente, telefone=digitos, origem=origem, nome_contato=(nome or '')[:100]))
        except IntegrityError:
            telefones = list(TelefoneCliente.objects.filter(cliente=cliente))  # criado por outra thread
    return telefones


def telefones_para_leitura(cliente) -> list[TelefoneCliente]:
    """Como `sincronizar`, sem gravar nada (telas e relatórios): números faltantes vêm sem pk."""
    telefones = list(cliente.telefones_crm.all())
    agora = timezone.now()
    for digitos, origem, nome in _candidatos_do_cadastro(cliente):
        if not _achar(telefones, digitos):
            telefones.append(TelefoneCliente(cliente=cliente, telefone=digitos, origem=origem, nome_contato=nome,
                                             criado_em=agora, atualizado_em=agora))
    return telefones


def papel(cliente, telefone: TelefoneCliente) -> str:
    """'principal', 'secundario' ou a origem (ATENDIMENTO, C4M, REFERENCIA, OUTRO)."""
    if telefone.origem != Origem.CADASTRO:
        return telefone.origem
    return 'principal' if mesmo_telefone(telefone.telefone, cliente.telefone) else 'secundario'


def utilizavel(telefone: TelefoneCliente) -> bool:
    """Pode receber aviso de cobrança: nunca referência; fora do cadastro, só depois de validado."""
    if telefone.origem == Origem.REFERENCIA or telefone.situacao in SITUACOES_RUINS:
        return False
    if telefone.origem != Origem.CADASTRO:
        return telefone.situacao == Situacao.VALIDO
    return True


def utilizaveis(cliente, telefones: list[TelefoneCliente] | None = None) -> list[TelefoneCliente]:
    telefones = sincronizar(cliente) if telefones is None else telefones
    validos = [t for t in telefones if utilizavel(t)]
    return sorted(validos, key=lambda t: (PRIORIDADE.get(papel(cliente, t), 9), -t.atualizado_em.timestamp()))


def para_aviso(cliente) -> TelefoneCliente | None:
    opcoes = utilizaveis(cliente)
    return opcoes[0] if opcoes else None


def registrar_numero_do_atendimento(cliente, numero: str) -> bool:
    """Cliente confirmou a identidade falando de outro número: registra sem trocar o principal.

    Devolve True quando o número é diferente do cadastro.
    """
    digitos = somente_digitos(numero)
    if not digitos or mesmo_telefone(digitos, cliente.telefone) or mesmo_telefone(digitos, cliente.telefone_secundario):
        return False
    # CPF + nascimento não provam que o número é do cliente: fica registrado, mas só recebe
    # aviso de cobrança depois que a equipe marcar como confirmado.
    if _achar(sincronizar(cliente), digitos) is None:
        hoje = timezone.localdate().strftime('%d/%m/%Y')
        try:
            TelefoneCliente.objects.create(
                cliente=cliente, telefone=digitos, origem=Origem.ATENDIMENTO, situacao=Situacao.NAO_VERIFICADO,
                observacao=f'Usado no WhatsApp em {hoje} por quem informou CPF e nascimento do cliente.')
        except IntegrityError:
            pass
    return True


def adicionar_telefone(cliente, numero: str, origem: str, usuario, nome_contato: str = '',
                       observacao: str = '', situacao: str = Situacao.NAO_VERIFICADO) -> TelefoneCliente:
    digitos = normalizar(numero)
    if origem not in Origem.values or origem == Origem.CADASTRO:
        raise ErroContato('Escolha a origem do número (C4M, referência ou outro).')
    if situacao not in Situacao.values:
        raise ErroContato('Situação inválida.')
    if _achar(sincronizar(cliente), digitos):
        raise ErroContato('Este número já está na lista do cliente.')
    try:
        return TelefoneCliente.objects.create(
            cliente=cliente, telefone=digitos, origem=origem, situacao=situacao, criado_por=usuario,
            nome_contato=(nome_contato or '').strip()[:100], observacao=(observacao or '').strip()[:255])
    except IntegrityError as erro:
        raise ErroContato('Este número já está na lista do cliente.') from erro


def mudar_situacao(telefone: TelefoneCliente, situacao: str) -> TelefoneCliente:
    if situacao not in Situacao.values:
        raise ErroContato('Situação inválida.')
    telefone.situacao = situacao
    telefone.save(update_fields=['situacao', 'atualizado_em'])
    return telefone


def _validar_resultado(telefone: TelefoneCliente, resultado: str) -> None:
    if resultado not in Resultado.values or resultado in (Resultado.ENVIADO, Resultado.FALHOU):
        raise ErroContato('Escolha o resultado da tentativa.')
    eh_referencia = telefone.origem == Origem.REFERENCIA
    if resultado in RESULTADOS_DE_REFERENCIA and not eh_referencia:
        raise ErroContato('"Referência ajudou/não ajudou" só vale para número de referência.')
    if resultado == Resultado.RESPONDEU and eh_referencia:
        raise ErroContato('Para referência, use "Referência ajudou" ou "Referência não ajudou".')


def registrar_tentativa(telefone: TelefoneCliente, resultado: str, usuario,
                        canal: str = TentativaContato.Canal.LIGACAO, observacao: str = '') -> TentativaContato:
    _validar_resultado(telefone, resultado)
    if canal not in TentativaContato.Canal.values:
        raise ErroContato('Canal inválido.')
    tentativa = TentativaContato.objects.create(
        cliente=telefone.cliente, telefone=telefone, numero=telefone.telefone, tipo=TentativaContato.Tipo.MANUAL,
        canal=canal, resultado=resultado, observacao=(observacao or '').strip()[:255], usuario=usuario,
        respondido_em=timezone.now() if resultado == Resultado.RESPONDEU else None)
    nova = RESULTADO_PARA_SITUACAO.get(resultado)
    if resultado == Resultado.RESPONDEU:
        nova = Situacao.VALIDO
    if nova and telefone.situacao != nova:
        mudar_situacao(telefone, nova)
    return tentativa


# --- ganchos do fluxo de mensagens ---------------------------------------------------------------

def marcar_resposta(conversa: Conversa, quando: datetime | None = None) -> int:
    """Cliente escreveu: os avisos ainda sem resposta nesta conversa viram 'respondeu'."""
    return TentativaContato.objects.filter(mensagem__conversa=conversa, resultado=Resultado.ENVIADO).update(
        resultado=Resultado.RESPONDEU, respondido_em=quando or timezone.now())


def _falhou_em_outro_dia(tentativa: TentativaContato) -> bool:
    inicio_de_hoje = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()))
    return (TentativaContato.objects
            .filter(telefone=tentativa.telefone, resultado=Resultado.SEM_WHATSAPP, criado_em__lt=inicio_de_hoje)
            .exclude(pk=tentativa.pk).exists())


def marcar_falha(mensagem: Mensagem, codigo: int | None) -> int:
    """A Meta não entregou um aviso. 131026 (sem WhatsApp, bloqueou, app antigo) pode ser passageiro:
    o número só sai da régua na segunda falha, em dias diferentes."""
    sem_whatsapp = codigo == CODIGO_SEM_WHATSAPP
    tentativas = list(TentativaContato.objects.filter(mensagem=mensagem).exclude(resultado=Resultado.RESPONDEU)
                      .select_related('telefone'))
    for tentativa in tentativas:
        tentativa.resultado = Resultado.SEM_WHATSAPP if sem_whatsapp else Resultado.FALHOU
        tentativa.save(update_fields=['resultado'])
        telefone = tentativa.telefone
        if sem_whatsapp and telefone and telefone.situacao not in SITUACOES_RUINS and _falhou_em_outro_dia(tentativa):
            mudar_situacao(telefone, Situacao.SEM_WHATSAPP)
    return len(tentativas)


# --- status de contato ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ficha:
    """Resumo de contato de um cliente num período (base dos relatórios)."""

    status: str
    respondeu: bool
    avisos: int
    tentativas: int
    ultima_tentativa: datetime | None
    bloqueado: bool
    referencia_sem_sucesso: bool
    alternativos: int

    @property
    def rotulo(self) -> str:
        return Status.ROTULOS[self.status]


def _referencias_esgotadas(refs: list[TelefoneCliente], tentativas: list[TentativaContato]) -> bool:
    """Toda referência foi tentada sem sucesso (sem referência, não há o que concluir)."""
    return bool(refs) and all(any(t.telefone_id == ref.pk and t.resultado in FALHAS_DE_REFERENCIA for t in tentativas)
               for ref in refs)


def _status(cliente, telefones, tentativas, respondeu: bool) -> str:
    """Um status por cliente, na ordem de prioridade da proposta (o mais útil para a equipe agir)."""
    if respondeu:
        return Status.CONTATO_REALIZADO
    usaveis = utilizaveis(cliente, telefones)
    if not usaveis:
        proprios = [t for t in telefones if t.origem != Origem.REFERENCIA]
        if any(t.situacao == Situacao.BLOQUEADO for t in proprios):
            return Status.BLOQUEIO_CONFIRMADO
        if _referencias_esgotadas([t for t in telefones if t.origem == Origem.REFERENCIA], tentativas):
            return Status.NAO_LOCALIZADO
        principal = next((t for t in proprios if papel(cliente, t) == 'principal'), None)
        return Status.NUMERO_INVALIDO if principal and principal.situacao == Situacao.INVALIDO \
            else Status.SEM_WHATSAPP
    tentados = {t.telefone_id for t in tentativas}
    if not tentados:
        return Status.SEM_TENTATIVA
    if any(t.pk not in tentados for t in usaveis):
        return Status.CONTATO_ALTERNATIVO
    if any(t.resultado == Resultado.REFERENCIA_SEM_SUCESSO for t in tentativas):
        return Status.REFERENCIA_SEM_SUCESSO
    return Status.AGUARDANDO_RETORNO


def clientes_que_escreveram(ids, desde: datetime, ate: datetime | None = None) -> set[int]:
    """Uma consulta só para muitos clientes (relatórios)."""
    entradas = Mensagem.objects.filter(conversa__clientes__in=list(ids), direcao=Mensagem.Direcao.ENTRADA,
                                       criado_em__gte=desde).exclude(tipo=Mensagem.Tipo.REACAO)
    if ate is not None:
        entradas = entradas.filter(criado_em__lt=ate)
    return set(entradas.values_list('conversa__clientes', flat=True).distinct())


def ficha(cliente, desde: datetime, ate: datetime | None = None, escreveu: bool | None = None) -> Ficha:
    """Status do cliente no período (só leitura). `escreveu` pode vir calculado em lote."""
    telefones = telefones_para_leitura(cliente)
    tentativas = [t for t in cliente.tentativas_crm.all()
                  if t.criado_em >= desde and (ate is None or t.criado_em < ate)]
    if escreveu is None:
        escreveu = cliente.pk in clientes_que_escreveram([cliente.pk], desde, ate)
    respondeu = escreveu or any(t.resultado == Resultado.RESPONDEU for t in tentativas)
    return Ficha(
        status=_status(cliente, telefones, tentativas, respondeu),
        respondeu=respondeu,
        avisos=sum(1 for t in tentativas if t.automatica),
        tentativas=len(tentativas),
        ultima_tentativa=max((t.criado_em for t in tentativas), default=None),
        bloqueado=any(t.situacao == Situacao.BLOQUEADO for t in telefones),
        referencia_sem_sucesso=any(t.resultado == Resultado.REFERENCIA_SEM_SUCESSO for t in tentativas),
        alternativos=max(len(utilizaveis(cliente, telefones)) - 1, 0),
    )
