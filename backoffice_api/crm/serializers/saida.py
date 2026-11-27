"""Serializers de saída do CRM (somente leitura; leem os dicionários de `apresentacao.py`)."""
from rest_framework import serializers

from .base import CrmSerializer

VALOR = {'max_digits': 14, 'decimal_places': 2}


class UsuarioMiniSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class EtiquetaMiniSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    cor = serializers.CharField()


# --- conversa -------------------------------------------------------------------------------

class LembreteSerializer(CrmSerializer):
    em = serializers.DateTimeField()
    texto = serializers.CharField(allow_blank=True)
    para = UsuarioMiniSerializer(allow_null=True)
    vencido = serializers.BooleanField()


class MotivoTransferenciaSerializer(CrmSerializer):
    texto = serializers.CharField()
    silenciosa = serializers.BooleanField()
    criado_em = serializers.DateTimeField()


class UltimaMensagemSerializer(CrmSerializer):
    em = serializers.DateTimeField(allow_null=True)
    previa = serializers.CharField(allow_blank=True, help_text='Texto curto; mídia sem legenda vira "📷 Foto", "🎤 Áudio"...')
    tipo = serializers.CharField(allow_blank=True)
    direcao = serializers.CharField(allow_blank=True, help_text='ENTRADA (cliente) ou SAIDA (equipe/automático).')


class JanelaSerializer(CrmSerializer):
    aberta = serializers.BooleanField(help_text='Texto livre e mídia só com a janela de 24 h aberta.')
    expira_em = serializers.DateTimeField(allow_null=True)


class ConversaItemSerializer(CrmSerializer):
    id = serializers.IntegerField()
    telefone = serializers.CharField()
    telefone_formatado = serializers.CharField()
    contato_nome = serializers.CharField(allow_blank=True)
    apelido = serializers.CharField(allow_blank=True)
    nome_exibicao = serializers.CharField()
    modo = serializers.CharField(help_text='AUTOMATICO, AGUARDANDO ou HUMANO.')
    modo_display = serializers.CharField()
    situacao = serializers.CharField(help_text='ABERTA, PENDENTE ou RESOLVIDA.')
    situacao_display = serializers.CharField()
    assumida_por = UsuarioMiniSerializer(allow_null=True)
    nao_lidas = serializers.IntegerField()
    ultima_mensagem = UltimaMensagemSerializer()
    janela = JanelaSerializer()
    etiquetas = EtiquetaMiniSerializer(many=True)
    lembrete = LembreteSerializer(allow_null=True)
    tem_programada = serializers.BooleanField()
    motivo_transferencia = MotivoTransferenciaSerializer(allow_null=True)
    total_clientes = serializers.IntegerField()


class ContadoresSerializer(CrmSerializer):
    minhas = serializers.IntegerField()
    sem_dono = serializers.IntegerField()
    automatico = serializers.IntegerField()
    todas = serializers.IntegerField()


class ListaConversasSerializer(CrmSerializer):
    """Envelope de paginação padrão + `contadores` das filas."""

    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    results = ConversaItemSerializer(many=True)
    contadores = ContadoresSerializer()


class BloqueioSerializer(CrmSerializer):
    motivo = serializers.CharField(help_text='OUTRO_DONO, JANELA_FECHADA ou NAO_ASSUMIDA.')
    mensagem = serializers.CharField()


class AcoesSerializer(CrmSerializer):
    assumir = serializers.BooleanField()
    puxar = serializers.BooleanField()
    atribuir = serializers.BooleanField()
    devolver = serializers.BooleanField()
    resolver = serializers.BooleanField()
    resolver_e_devolver = serializers.BooleanField()
    reabrir = serializers.BooleanField()
    marcar_pendente = serializers.BooleanField()
    enviar_abertura = serializers.BooleanField()


class ConversaEstadoSerializer(ConversaItemSerializer):
    clientes_nomes = serializers.ListField(
        child=serializers.CharField(), help_text='Clientes vinculados ao número que o usuário pode ver.')
    pode_responder = serializers.BooleanField()
    bloqueio = BloqueioSerializer(allow_null=True)
    acoes = AcoesSerializer()


# --- painel do cliente ----------------------------------------------------------------------

class SolicitacaoPainelSerializer(CrmSerializer):
    cliente_id = serializers.IntegerField(source='id')
    status = serializers.CharField()
    status_display = serializers.CharField()
    produto = serializers.CharField(allow_blank=True)
    data = serializers.DateTimeField(allow_null=True)


class VendaPainelSerializer(CrmSerializer):
    id = serializers.IntegerField()
    data = serializers.DateTimeField()
    valor_total = serializers.DecimalField(**VALOR)
    cancelada = serializers.BooleanField()


class ProximaParcelaSerializer(CrmSerializer):
    numero = serializers.IntegerField()
    valor = serializers.DecimalField(**VALOR)
    vencimento = serializers.DateField()


class PagamentoPainelSerializer(CrmSerializer):
    pagamento_id = serializers.IntegerField()
    venda_id = serializers.IntegerField()
    produto = serializers.CharField()
    parcelas_abertas = serializers.IntegerField()
    total_aberto = serializers.DecimalField(**VALOR)
    parcelas_atrasadas = serializers.IntegerField()
    total_atrasado = serializers.DecimalField(**VALOR)
    em_confirmacao = serializers.IntegerField()
    proxima = ProximaParcelaSerializer(allow_null=True)
    link_publico = serializers.CharField(default='', allow_blank=True,
                                         help_text='Página pública de pagamento com PIX (vazio sem endereço público).')


class ClientePainelSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    cpf = serializers.CharField(allow_blank=True, help_text='Sempre mascarado (***.456.789-**).')
    telefone = serializers.CharField(allow_blank=True)
    solicitacoes = SolicitacaoPainelSerializer(many=True)
    vendas = VendaPainelSerializer(many=True, help_text='Só com vendas.view_venda.')
    pagamentos = PagamentoPainelSerializer(many=True, help_text='Só com vendas.view_pagamento.')


class ClienteSugeridoSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    telefone = serializers.CharField(allow_blank=True)


class PainelSerializer(CrmSerializer):
    clientes = ClientePainelSerializer(many=True)
    sugeridos = ClienteSugeridoSerializer(many=True)


class NotaSerializer(CrmSerializer):
    id = serializers.IntegerField()
    texto = serializers.CharField()
    autor = UsuarioMiniSerializer(allow_null=True)
    automatica = serializers.BooleanField()
    tipo = serializers.CharField(help_text='GERAL ou TRANSFERENCIA.')
    silenciosa = serializers.BooleanField()
    criado_em = serializers.DateTimeField()
    pode_apagar = serializers.BooleanField()


class ProgramadaSerializer(CrmSerializer):
    id = serializers.IntegerField()
    texto = serializers.CharField()
    enviar_em = serializers.DateTimeField()
    status = serializers.CharField(help_text='AGENDADA, ENVIANDO, ENVIADA, CANCELADA ou ERRO.')
    criado_por = UsuarioMiniSerializer(allow_null=True)
    erro = serializers.CharField(allow_blank=True)


class ConversaDetalheSerializer(ConversaEstadoSerializer):
    painel = PainelSerializer()
    notas = NotaSerializer(many=True)
    programadas = ProgramadaSerializer(many=True)


# --- mensagens ------------------------------------------------------------------------------

class RespondeASerializer(CrmSerializer):
    id = serializers.IntegerField()
    tipo = serializers.CharField()
    texto = serializers.CharField(allow_blank=True)
    autor = serializers.CharField()


class MidiaSerializer(CrmSerializer):
    status = serializers.CharField(help_text='PENDENTE, OK, ERRO ou EXPIRADA. URL só com OK.')
    mime = serializers.CharField(allow_blank=True)
    nome_original = serializers.CharField(allow_blank=True)
    tamanho_bytes = serializers.IntegerField(allow_null=True)
    duracao_s = serializers.IntegerField(allow_null=True)
    largura = serializers.IntegerField(allow_null=True)
    altura = serializers.IntegerField(allow_null=True)
    voz = serializers.BooleanField()
    tem_miniatura = serializers.BooleanField()
    url = serializers.CharField(allow_null=True)
    url_miniatura = serializers.CharField(allow_null=True)


class MensagemSerializer(CrmSerializer):
    id = serializers.IntegerField()
    direcao = serializers.CharField(help_text='ENTRADA ou SAIDA.')
    autor = serializers.CharField(help_text='CLIENTE, AUTOMATICO, HUMANO ou SISTEMA.')
    autor_display = serializers.CharField()
    autor_nome = serializers.CharField()
    tipo = serializers.CharField()
    tipo_display = serializers.CharField()
    texto = serializers.CharField(allow_blank=True)
    status = serializers.CharField(help_text='RECEBIDO, PENDENTE, ENVIADO, ENTREGUE, LIDO ou ERRO.')
    status_display = serializers.CharField()
    erro = serializers.CharField(allow_blank=True)
    origem = serializers.CharField(allow_blank=True, help_text='"", ABERTURA, BOAS_VINDAS ou PROGRAMADA.')
    criado_em = serializers.DateTimeField()
    responde_a = RespondeASerializer(allow_null=True)
    reacao_cliente = serializers.CharField(allow_blank=True)
    reacao_equipe = serializers.CharField(allow_blank=True)
    midia = MidiaSerializer(allow_null=True)
    dados = serializers.JSONField(help_text='localizacao, contatos e encaminhada, quando houver.')
    transcricao_status = serializers.CharField(allow_blank=True)
    pode_reenviar = serializers.BooleanField()


class PaginaMensagensSerializer(CrmSerializer):
    results = MensagemSerializer(many=True)
    tem_mais_antigas = serializers.BooleanField()
    proximo_cursor = serializers.IntegerField(allow_null=True, help_text='Envie em ?antes= para a página anterior.')


# --- apoio da caixa de entrada --------------------------------------------------------------

class AtendenteSerializer(CrmSerializer):
    id = serializers.IntegerField(source='pk')
    nome = serializers.SerializerMethodField()

    def get_nome(self, usuario) -> str:
        return usuario.get_full_name() or usuario.username


class ClienteBuscaSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    cpf = serializers.CharField(allow_blank=True, help_text='Mascarado.')
    telefone = serializers.CharField(allow_blank=True)


class BuscaClientesSerializer(CrmSerializer):
    results = ClienteBuscaSerializer(many=True)
    busca_curta = serializers.BooleanField(help_text='Menos de 3 caracteres: nada é buscado.')


class AberturaDisponivelSerializer(CrmSerializer):
    chave = serializers.CharField()
    titulo = serializers.CharField()
    texto = serializers.CharField(allow_blank=True)
    usa_nome = serializers.BooleanField(help_text='O texto tem {nome}: peça o nome do cliente.')
    disponivel = serializers.BooleanField(help_text='Aprovada pela Meta e pronta para envio.')


class ConversaDoTelefoneSerializer(CrmSerializer):
    id = serializers.IntegerField()
    janela_aberta = serializers.BooleanField()
    assumida_por = serializers.CharField(allow_null=True)


class TelefoneDaContaSerializer(CrmSerializer):
    rotulo = serializers.CharField()
    telefone = serializers.CharField(help_text='Só dígitos, com 55.')
    telefone_formatado = serializers.CharField()
    conversa = ConversaDoTelefoneSerializer(allow_null=True, help_text='Conversa já existente com este número.')


class ParcelaDaContaSerializer(CrmSerializer):
    numero = serializers.IntegerField()
    valor = serializers.CharField(help_text='Valor restante formatado (R$).')
    vencimento = serializers.DateField()
    vencida = serializers.BooleanField()


class AberturaDaContaSerializer(CrmSerializer):
    chave = serializers.CharField()
    titulo = serializers.CharField()
    texto = serializers.CharField(allow_blank=True, help_text='Já preenchido com nome, valor e vencimento.')
    cobranca = serializers.BooleanField(help_text='Usa {valor}/{vencimento} da parcela.')
    disponivel = serializers.BooleanField()


class ClienteDaContaSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class AberturaContaSerializer(CrmSerializer):
    cliente = ClienteDaContaSerializer()
    parcela = ParcelaDaContaSerializer(allow_null=True)
    telefones = TelefoneDaContaSerializer(many=True)
    aberturas = AberturaDaContaSerializer(many=True)


class RespostaRapidaMiniSerializer(CrmSerializer):
    id = serializers.IntegerField()
    atalho = serializers.CharField()
    titulo = serializers.CharField()
    texto = serializers.CharField()


class TextoProntoSerializer(CrmSerializer):
    texto = serializers.CharField(allow_blank=True)
    avisos = serializers.ListField(child=serializers.CharField(), default=list)


class OpcaoSerializer(CrmSerializer):
    valor = serializers.CharField()
    rotulo = serializers.CharField()


class LimitesSerializer(CrmSerializer):
    texto = serializers.IntegerField()
    legenda = serializers.IntegerField()
    arquivo_bytes = serializers.IntegerField()
    nota = serializers.IntegerField()
    apelido = serializers.IntegerField()
    lembrete = serializers.IntegerField()


class ContextoSerializer(CrmSerializer):
    simulado = serializers.BooleanField(help_text='WhatsApp simulado: nada sai para a Meta.')
    pode_gerenciar = serializers.BooleanField()
    ve_clientes = serializers.BooleanField()
    ve_pagamentos = serializers.BooleanField()
    filas = OpcaoSerializer(many=True)
    ordens = OpcaoSerializer(many=True)
    situacoes = OpcaoSerializer(many=True)
    cores_etiqueta = OpcaoSerializer(many=True)
    limites = LimitesSerializer()
