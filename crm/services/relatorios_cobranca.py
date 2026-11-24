"""Relatórios da cobrança (proposta, item 5): quem não respondeu, bloqueados, referências sem
sucesso, não localizados, clientes a priorizar e os indicadores do painel.

Só consulta e agrega (nenhuma tela aqui). A população de um período é:
clientes com alguma tentativa de contato no período OU com parcela IPX em aberto e vencida;
opcionalmente só os que têm parcela IPX com o dia (1/10/20) ou a data de vencimento escolhidos.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.paginator import Page, Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from crm.models import Conversa, EncaminhamentoIA, Mensagem, TelefoneCliente, TentativaContato
from crm.services import contatos
from crm.services.assistente import anexos
from crm.services.cobranca import TIPO_CREDFACIL, _parcelas_abertas, clientes_em_atraso
from crm.services.contatos import Status
from crm.telefone import formatar_telefone

DIAS_PADRAO = 30
DIAS_VENCIMENTO = (1, 10, 20)
POR_PAGINA = 25
OBSERVACAO_COMPROVANTE_WHATSAPP = anexos.OBSERVACAO_COMPROVANTE
ASSUNTOS_NEGOCIACAO = (EncaminhamentoIA.Assunto.NEGOCIACAO, EncaminhamentoIA.Assunto.QUITACAO)
ORIGENS_ALTERNATIVAS = (TelefoneCliente.Origem.C4M, TelefoneCliente.Origem.ATENDIMENTO)
STATUS_ENTREGUE = (Mensagem.Status.ENTREGUE, Mensagem.Status.LIDO)
ZERO = Decimal('0.00')


class Relatorio:
    ALERTA = 'alerta'
    SEM_RESPOSTA = 'sem_resposta'
    BLOQUEADOS = 'bloqueados'
    REFERENCIAS = 'referencias'
    NAO_LOCALIZADOS = 'nao_localizados'
    PRIORIZAR = 'priorizar'
    TODOS = 'todos'

    ROTULOS = {
        ALERTA: 'Não pagou e não respondeu',
        SEM_RESPOSTA: 'Sem resposta',
        BLOQUEADOS: 'Bloqueados',
        REFERENCIAS: 'Referências sem sucesso',
        NAO_LOCALIZADOS: 'Não localizados',
        PRIORIZAR: 'Priorizar',
        TODOS: 'Todos',
    }

    # Falta de resposta não é bloqueio: "bloqueados" só com bloqueio confirmado pela equipe.
    REGRAS = {
        ALERTA: lambda f: f.alerta,
        SEM_RESPOSTA: lambda f: f.avisos > 0 and not f.respondeu,
        BLOQUEADOS: lambda f: f.bloqueado,
        REFERENCIAS: lambda f: f.referencia_sem_sucesso,
        NAO_LOCALIZADOS: lambda f: f.status == Status.NAO_LOCALIZADO,
        PRIORIZAR: lambda f: f.status == Status.CONTATO_ALTERNATIVO,
        TODOS: lambda f: True,
    }


@dataclass(frozen=True)
class Filtros:
    desde: date
    ate: date
    dia_vencimento: int | None = None
    data_vencimento: date | None = None
    status: str | None = None

    @classmethod
    def padrao(cls, hoje: date | None = None) -> 'Filtros':
        hoje = hoje or timezone.localdate()
        return cls(desde=hoje - timedelta(days=DIAS_PADRAO), ate=hoje)

    @property
    def inicio(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.desde, time.min))

    @property
    def fim(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.ate, time.max))

    @property
    def por_vencimento(self) -> bool:
        return bool(self.dia_vencimento or self.data_vencimento)


@dataclass(frozen=True)
class Linha:
    cliente_id: int
    nome: str
    telefone: str
    ficha: contatos.Ficha
    parcelas_atrasadas: int = 0
    total_atrasado: Decimal = ZERO
    conversa_id: int | None = None


@dataclass(frozen=True)
class Resultado:
    pagina: Page
    linhas: list
    contagens: dict
    total: int


@dataclass(frozen=True)
class Indicadores:
    avisos_enviados: int
    avisos_por_tipo: list
    avisos_entregues: int
    avisos_lidos: int
    clientes_responderam: int
    comprovantes_whatsapp: int
    pagamentos_identificados: int
    valor_identificado: Decimal
    negociacoes: int
    clientes_sem_retorno: int
    contatos_alternativos: int
    nao_localizados: int
    encaminhamentos: int
    encaminhamentos_por_assunto: list = field(default_factory=list)
    encaminhamentos_fora_do_horario: int = 0


# --- população -----------------------------------------------------------------------------------

def _filtro_vencimento(filtros: Filtros, prefixo: str) -> Q:
    """Q sobre a data de vencimento de uma parcela (prefixo = caminho até a Parcela)."""
    condicao = Q()
    if filtros.dia_vencimento:
        condicao &= Q(**{f'{prefixo}data_vencimento__day': filtros.dia_vencimento})
    if filtros.data_vencimento:
        condicao &= Q(**{f'{prefixo}data_vencimento': filtros.data_vencimento})
    return condicao


def _clientes_por_vencimento(filtros: Filtros) -> set[int]:
    from vendas.models import Parcela

    return set(Parcela.objects
               .filter(_filtro_vencimento(filtros, ''), pagamento__tipo_pagamento__nome__iexact=TIPO_CREDFACIL,
                       pagamento__venda__is_deleted=False)
               .values_list('pagamento__venda__cliente_id', flat=True))


def ids_da_populacao(filtros: Filtros, hoje: date | None = None) -> set[int]:
    hoje = hoje or timezone.localdate()
    com_tentativa = set(TentativaContato.objects.filter(criado_em__range=(filtros.inicio, filtros.fim))
                        .values_list('cliente_id', flat=True))
    atrasados = set(_parcelas_abertas().filter(data_vencimento__lt=hoje)
                    .values_list('pagamento__venda__cliente_id', flat=True))
    ids = com_tentativa | atrasados
    if filtros.por_vencimento:
        ids &= _clientes_por_vencimento(filtros)
    return ids


def _clientes(ids: set[int], filtros: Filtros) -> QuerySet:
    from vendas.models import Cliente

    tentativas = TentativaContato.objects.filter(criado_em__range=(filtros.inicio, filtros.fim))
    return (Cliente.objects.filter(pk__in=ids)
            .select_related('contato_adicional', 'informacao_pessoal')
            .prefetch_related('telefones_crm', Prefetch('tentativas_crm', queryset=tentativas))
            .order_by('nome', 'pk'))


def _no_escopo(clientes: QuerySet, usuario) -> QuerySet:
    """Mesmo escopo de loja do resto do sistema (organizacao.pode_ver_cliente)."""
    from crm.services.organizacao import _lojas_do_usuario, _ve_todas_as_lojas

    if usuario is None:
        return clientes
    if not usuario.has_perm('vendas.view_cliente'):
        return clientes.none()
    return clientes if _ve_todas_as_lojas(usuario) else clientes.filter(loja_id__in=_lojas_do_usuario(usuario))


def fichas(filtros: Filtros, hoje: date | None = None, usuario=None) -> list[tuple]:
    """[(cliente, ficha)] da população visível ao usuário (a ficha é o status de contato de cada um)."""
    clientes = list(_no_escopo(_clientes(ids_da_populacao(filtros, hoje), filtros), usuario))
    ids = [c.pk for c in clientes]
    escreveram = contatos.clientes_que_escreveram(ids, filtros.inicio, filtros.fim)
    atrasados = clientes_em_atraso(ids, hoje or timezone.localdate())
    return [(cliente, contatos.ficha(cliente, filtros.inicio, filtros.fim, escreveu=cliente.pk in escreveram,
                                     em_atraso=cliente.pk in atrasados))
            for cliente in clientes]


# --- relatórios ----------------------------------------------------------------------------------

def _aplicar(relatorio: str, status: str | None, itens: list[tuple]) -> list[tuple]:
    regra = Relatorio.REGRAS.get(relatorio, Relatorio.REGRAS[Relatorio.TODOS])
    selecionados = [(c, f) for c, f in itens if regra(f)]
    if status in Status.ROTULOS:
        selecionados = [(c, f) for c, f in selecionados if f.status == status]
    return selecionados


def contagens(itens: list[tuple]) -> dict:
    return {chave: sum(1 for _, f in itens if regra(f)) for chave, regra in Relatorio.REGRAS.items()}


def _centavos(valor) -> Decimal:
    """O SQLite devolve a soma sem as casas decimais: normaliza para centavos."""
    return Decimal(valor or 0).quantize(ZERO)


def _atrasos(ids: list[int], hoje: date) -> dict[int, tuple[int, Decimal]]:
    restante = ExpressionWrapper(
        F('valor') - Coalesce(F('desconto'), Value(ZERO)) - Coalesce(F('valor_pago'), Value(ZERO)),
        output_field=DecimalField(max_digits=12, decimal_places=2))
    linhas = (_parcelas_abertas().filter(data_vencimento__lt=hoje, pagamento__venda__cliente_id__in=ids)
              .values('pagamento__venda__cliente_id')
              .annotate(qtd=Count('pk'), total=Sum(restante)).order_by())
    return {item['pagamento__venda__cliente_id']: (item['qtd'], _centavos(item['total'])) for item in linhas}


def _conversas(ids: list[int]) -> dict[int, int]:
    """Conversa mais recente de cada cliente."""
    pares = (Conversa.clientes.through.objects.filter(cliente_id__in=ids)
             .order_by('cliente_id', F('conversa__ultima_mensagem_em').desc(nulls_last=True), '-conversa_id')
             .values_list('cliente_id', 'conversa_id'))
    resultado: dict[int, int] = {}
    for cliente_id, conversa_id in pares:
        resultado.setdefault(cliente_id, conversa_id)
    return resultado


def _linhas(pares: list[tuple], hoje: date) -> list[Linha]:
    ids = [cliente.pk for cliente, _ in pares]
    atrasos, conversas = _atrasos(ids, hoje), _conversas(ids)
    return [Linha(cliente_id=cliente.pk, nome=cliente.nome, telefone=formatar_telefone(cliente.telefone),
                  ficha=ficha_cliente, parcelas_atrasadas=atrasos.get(cliente.pk, (0, ZERO))[0],
                  total_atrasado=atrasos.get(cliente.pk, (0, ZERO))[1], conversa_id=conversas.get(cliente.pk))
            for cliente, ficha_cliente in pares]


def relatorio(nome: str, filtros: Filtros, pagina: int | str = 1, hoje: date | None = None,
              itens: list[tuple] | None = None) -> Resultado:
    """Uma página do relatório `nome` (Relatorio.*), com as contagens de todas as abas."""
    hoje = hoje or timezone.localdate()
    itens = fichas(filtros, hoje) if itens is None else itens
    selecionados = _aplicar(nome, filtros.status, itens)
    pagina_obj = Paginator(selecionados, POR_PAGINA).get_page(pagina)
    return Resultado(pagina=pagina_obj, linhas=_linhas(list(pagina_obj.object_list), hoje),
                     contagens=contagens(itens), total=len(selecionados))


# --- indicadores do painel -----------------------------------------------------------------------

def _avisos(filtros: Filtros) -> QuerySet:
    return (TentativaContato.objects.exclude(tipo__in=(TentativaContato.Tipo.MANUAL, TentativaContato.Tipo.ALERTA))
            .filter(_filtro_vencimento(filtros, 'parcela__'), criado_em__range=(filtros.inicio, filtros.fim)))


def _por_rotulo(linhas, campo: str, rotulos: dict) -> list[tuple[str, int]]:
    return [(rotulos.get(item[campo], item[campo]), item['qtd']) for item in linhas]


def _indicadores_de_avisos(filtros: Filtros) -> dict:
    avisos = _avisos(filtros)
    por_tipo = avisos.values('tipo').annotate(qtd=Count('pk')).order_by('-qtd', 'tipo')
    return {
        'avisos_enviados': avisos.count(),
        'avisos_por_tipo': _por_rotulo(por_tipo, 'tipo', dict(TentativaContato.Tipo.choices)),
        'avisos_entregues': avisos.filter(mensagem__status__in=STATUS_ENTREGUE).count(),
        'avisos_lidos': avisos.filter(mensagem__status=Mensagem.Status.LIDO).count(),
    }


def _indicadores_de_pagamento(filtros: Filtros) -> dict:
    from vendas.models import ComprovanteParcela, Parcela

    comprovantes = ComprovanteParcela.objects.filter(
        _filtro_vencimento(filtros, 'parcela__'), observacao=OBSERVACAO_COMPROVANTE_WHATSAPP,
        criado_em__range=(filtros.inicio, filtros.fim))
    avisadas = _avisos(filtros).exclude(parcela=None).values('parcela_id')
    pagas = Parcela.objects.filter(pk__in=avisadas, pago=True)
    return {
        'comprovantes_whatsapp': comprovantes.count(),
        'pagamentos_identificados': pagas.count(),
        'valor_identificado': _centavos(pagas.aggregate(total=Sum('valor'))['total']),
    }


def _indicadores_de_atendimento(filtros: Filtros, ids: set[int]) -> dict:
    periodo = Q(criado_em__range=(filtros.inicio, filtros.fim))
    encaminhamentos = EncaminhamentoIA.objects.filter(periodo)
    alternativos = TelefoneCliente.objects.filter(periodo, origem__in=ORIGENS_ALTERNATIVAS)
    if filtros.por_vencimento:
        encaminhamentos = encaminhamentos.filter(conversa__clientes__in=ids).distinct()
        alternativos = alternativos.filter(cliente_id__in=ids)
    por_assunto = (EncaminhamentoIA.objects.filter(pk__in=encaminhamentos.values('pk'))
                   .values('assunto').annotate(qtd=Count('pk')).order_by('-qtd', 'assunto'))
    return {
        'negociacoes': encaminhamentos.filter(assunto__in=ASSUNTOS_NEGOCIACAO).count(),
        'contatos_alternativos': alternativos.count(),
        'encaminhamentos': encaminhamentos.count(),
        'encaminhamentos_por_assunto': _por_rotulo(por_assunto, 'assunto', dict(EncaminhamentoIA.Assunto.choices)),
        'encaminhamentos_fora_do_horario': encaminhamentos.filter(fora_do_horario=True).count(),
    }


def indicadores(filtros: Filtros, hoje: date | None = None, itens: list[tuple] | None = None) -> Indicadores:
    hoje = hoje or timezone.localdate()
    itens = fichas(filtros, hoje) if itens is None else itens
    ids = {cliente.pk for cliente, _ in itens}
    return Indicadores(
        **_indicadores_de_avisos(filtros),
        **_indicadores_de_pagamento(filtros),
        **_indicadores_de_atendimento(filtros, ids),
        clientes_responderam=sum(1 for _, f in itens if f.respondeu),
        clientes_sem_retorno=sum(1 for _, f in itens if Relatorio.REGRAS[Relatorio.SEM_RESPOSTA](f)),
        nao_localizados=sum(1 for _, f in itens if f.status == Status.NAO_LOCALIZADO),
    )
