"""Organização do CRM: etiquetas, notas, lembretes, programadas, respostas rápidas, clientes."""
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from crm.models import Conversa, Etiqueta, Mensagem, MensagemProgramada, Nota, RespostaRapida
from crm.services import avisos
from crm.services.conversas import ConflitoCRM, exigir_resposta_liberada, nota_automatica
from crm.telefone import chave_telefone, sufixo_busca

LIMITE_NOTA = 2000
LIMITE_LEMBRETE = 200
LIMITE_APELIDO = 60
PROGRAMADA_MINIMO = timedelta(minutes=5)
PROGRAMADA_MAXIMO = timedelta(days=30)
MAX_SOLICITACOES_PAINEL = 5
MAX_VENDAS_PAINEL = 5
MAX_SUGERIDOS = 5
MARCADOR = re.compile(r'\{(\w+)\}')


def definir_etiquetas(conversa: Conversa, ids: list[int]) -> None:
    """Substitui o conjunto; só aplica etiqueta ativa (ou que já estava na conversa)."""
    atuais = set(conversa.etiquetas.values_list('id', flat=True))
    pedidas = {int(i) for i in ids}
    validas = set(Etiqueta.objects.filter(Q(ativo=True) | Q(id__in=atuais), id__in=pedidas).values_list('id', flat=True))
    if validas != pedidas:
        raise ConflitoCRM('Alguma etiqueta não existe ou foi desativada.')
    conversa.etiquetas.set(validas)
    avisos.emitir(conversa, 'conversa_atualizada')


def criar_nota(conversa: Conversa, usuario, texto: str) -> Nota:
    texto = (texto or '').strip()
    if not texto:
        raise ConflitoCRM('Escreva a nota.')
    if len(texto) > LIMITE_NOTA:
        raise ConflitoCRM(f'A nota passa de {LIMITE_NOTA} caracteres.')
    nota = Nota.objects.create(conversa=conversa, usuario=usuario, texto=texto)
    avisos.emitir(conversa, 'conversa_atualizada')
    return nota


def apagar_nota(nota: Nota, usuario) -> None:
    if nota.automatica:
        raise ConflitoCRM('Notas automáticas não podem ser apagadas.')
    if nota.usuario_id != usuario.pk:
        raise ConflitoCRM('Só quem escreveu a nota pode apagá-la.')
    nota.apagada_em, nota.apagada_por = timezone.now(), usuario
    nota.save(update_fields=['apagada_em', 'apagada_por'])
    avisos.emitir(nota.conversa, 'conversa_atualizada')


def definir_lembrete(conversa: Conversa, usuario, quando, texto: str = '', para=None) -> None:
    from crm.permissoes import pode_acessar

    if quando is None or quando <= timezone.now():
        raise ConflitoCRM('Escolha uma data no futuro para o lembrete.')
    texto = (texto or '').strip()
    if len(texto) > LIMITE_LEMBRETE:
        raise ConflitoCRM(f'O lembrete passa de {LIMITE_LEMBRETE} caracteres.')
    destino = para or usuario
    if not pode_acessar(destino):
        raise ConflitoCRM('O destino do lembrete não tem acesso ao CRM.')
    Conversa.objects.filter(pk=conversa.pk).update(
        lembrete_em=quando, lembrete_texto=texto, lembrete_para=destino,
        lembrete_criado_por=usuario, lembrete_avisado_em=None,
    )
    avisos.emitir(conversa, 'conversa_atualizada')


def concluir_lembrete(conversa: Conversa) -> None:
    Conversa.objects.filter(pk=conversa.pk).update(
        lembrete_em=None, lembrete_texto='', lembrete_para=None, lembrete_criado_por=None, lembrete_avisado_em=None,
    )
    avisos.emitir(conversa, 'conversa_atualizada')


def programar(conversa: Conversa, usuario, texto: str, quando) -> MensagemProgramada:
    exigir_resposta_liberada(conversa, usuario)
    texto = (texto or '').strip()
    agora = timezone.now()
    if not texto:
        raise ConflitoCRM('Escreva a mensagem a programar.')
    if len(texto) > 4096:
        raise ConflitoCRM('A mensagem passa de 4096 caracteres.')
    if quando is None or not (agora + PROGRAMADA_MINIMO <= quando <= agora + PROGRAMADA_MAXIMO):
        raise ConflitoCRM('Programe entre 5 minutos e 30 dias à frente.')
    programada = MensagemProgramada.objects.create(conversa=conversa, criado_por=usuario, texto=texto, enviar_em=quando)
    avisos.emitir(conversa, 'conversa_atualizada')
    return programada


def cancelar_programada(programada: MensagemProgramada, usuario) -> MensagemProgramada:
    alterou = MensagemProgramada.objects.filter(
        pk=programada.pk, status=MensagemProgramada.Status.AGENDADA,
    ).update(status=MensagemProgramada.Status.CANCELADA, cancelada_por=usuario)
    if not alterou:
        raise ConflitoCRM('A mensagem já saiu ou foi cancelada.')
    programada.refresh_from_db()
    avisos.emitir(programada.conversa, 'conversa_atualizada')
    return programada


def enviar_programadas_vencidas() -> int:
    """Cron: AGENDADA → ENVIANDO por compare-and-set; envia se a janela está aberta e em HUMANO."""
    from crm.services import envio

    enviadas = 0
    vencidas = MensagemProgramada.objects.filter(
        status=MensagemProgramada.Status.AGENDADA, enviar_em__lte=timezone.now(),
    ).select_related('conversa', 'criado_por')
    for programada in vencidas:
        travou = MensagemProgramada.objects.filter(
            pk=programada.pk, status=MensagemProgramada.Status.AGENDADA,
        ).update(status=MensagemProgramada.Status.ENVIANDO)
        if not travou:
            continue
        conversa = programada.conversa
        motivo = ''
        if conversa.modo != Conversa.Modo.HUMANO:
            motivo = 'a conversa não está mais com a equipe'
        elif not conversa.janela_aberta():
            motivo = 'a janela de 24 h fechou'
        mensagem = None
        if not motivo:
            mensagem = envio.enviar_texto(conversa, programada.texto, usuario=programada.criado_por,
                                          origem=Mensagem.Origem.PROGRAMADA, exigir_trava=False)
            if mensagem.status == Mensagem.Status.ERRO:
                motivo = mensagem.erro
        programada.mensagem = mensagem
        programada.status = MensagemProgramada.Status.ERRO if motivo else MensagemProgramada.Status.ENVIADA
        programada.erro = motivo
        programada.save(update_fields=['mensagem', 'status', 'erro'])
        if motivo:
            nota_automatica(conversa, f'A mensagem programada não foi enviada: {motivo}.')
            avisos.notificar_usuario(programada.criado_por,
                                     f'Mensagem programada para {conversa.nome_exibicao} não foi enviada', conversa)
        else:
            enviadas += 1
    return enviadas


def avisar_lembretes_vencidos() -> int:
    avisados = 0
    agora = timezone.now()
    vencidos = Conversa.objects.filter(lembrete_em__lte=agora, lembrete_avisado_em__isnull=True)
    for conversa in vencidos.select_related('lembrete_para'):
        if Conversa.objects.filter(pk=conversa.pk, lembrete_avisado_em__isnull=True).update(lembrete_avisado_em=agora):
            texto = conversa.lembrete_texto or 'retornar a conversa'
            avisos.notificar_usuario(conversa.lembrete_para, f'Lembrete: {texto} ({conversa.nome_exibicao})', conversa)
            avisos.emitir(conversa, 'conversa_atualizada')
            avisados += 1
    return avisados


def definir_apelido(conversa: Conversa, apelido: str) -> None:
    apelido = (apelido or '').strip()
    if len(apelido) > LIMITE_APELIDO:
        raise ConflitoCRM(f'O apelido passa de {LIMITE_APELIDO} caracteres.')
    Conversa.objects.filter(pk=conversa.pk).update(apelido=apelido)
    avisos.emitir(conversa, 'conversa_atualizada')


def vincular_cliente(conversa: Conversa, cliente_id: int, vincular: bool = True) -> None:
    from vendas.models import Cliente

    cliente = Cliente.objects.filter(pk=cliente_id).first()
    if cliente is None:
        raise ConflitoCRM('Cliente não encontrado.')
    (conversa.clientes.add if vincular else conversa.clientes.remove)(cliente)
    avisos.emitir(conversa, 'conversa_atualizada')


def _primeiro_nome(texto: str) -> str:
    return texto.split()[0] if texto else ''


def previa_resposta(conversa: Conversa, resposta: RespostaRapida, usuario) -> dict:
    """Preenche os marcadores; sem valor vira vazio e entra em `avisos`."""
    from crm.models import ConfiguracaoCRM

    clientes = list(conversa.clientes.all()[:2])
    unico = clientes[0] if len(clientes) == 1 else None
    valores = {
        'primeiro_nome': _primeiro_nome(unico.nome if unico else conversa.contato_nome),
        'nome_cliente': unico.nome if unico else '',
        'empresa': ConfiguracaoCRM.obter().nome_empresa,
        'atendente': _primeiro_nome(usuario.get_full_name() or usuario.username),
    }
    avisos_faltando = []

    def trocar(match):
        chave = match.group(1)
        if chave not in valores:
            return match.group(0)
        if not valores[chave]:
            avisos_faltando.append(f'Sem valor para: {chave}')
        return valores[chave]

    return {'texto': MARCADOR.sub(trocar, resposta.texto), 'avisos': sorted(set(avisos_faltando))}


def clientes_sugeridos(conversa: Conversa):
    """Clientes cujo telefone casa com o número da conversa (comparação pela chave)."""
    from vendas.models import Cliente

    sufixo = sufixo_busca(conversa.telefone)
    if not sufixo:
        return []
    chave = chave_telefone(conversa.telefone)
    candidatos = Cliente.objects.filter(Q(telefone__endswith=sufixo) | Q(telefone_secundario__endswith=sufixo))
    vinculados = set(conversa.clientes.values_list('id', flat=True))
    return [c for c in candidatos[:50]
            if c.pk not in vinculados
            and chave in (chave_telefone(c.telefone), chave_telefone(c.telefone_secundario))][:MAX_SUGERIDOS]


def painel(conversa: Conversa) -> dict:
    from vendas.models import AnaliseCreditoCliente, Venda

    resultado = []
    for cliente in conversa.clientes.all().select_related('analise_credito__produto'):
        analise = AnaliseCreditoCliente.objects.filter(cliente=cliente).select_related('produto').first()
        solicitacoes = []
        if analise:
            solicitacoes.append({
                'id': cliente.pk, 'status': analise.status, 'status_display': analise.get_status_display(),
                'produto': analise.produto.nome if analise.produto_id else '', 'data': analise.data_analise,
            })
        vendas = Venda.objects.filter(cliente=cliente).order_by('-data_venda')[:MAX_VENDAS_PAINEL]
        resultado.append({
            'id': cliente.pk, 'nome': cliente.nome, 'cpf': cliente.cpf, 'telefone': cliente.telefone,
            'vinculado': True, 'solicitacoes': solicitacoes[:MAX_SOLICITACOES_PAINEL],
            'vendas': [{'id': v.pk, 'data': v.data_venda, 'valor_total': v.pagamentos_valor_total,
                        'cancelada': v.is_deleted} for v in vendas],
        })
    sugeridos = [{'id': c.pk, 'nome': c.nome, 'telefone': c.telefone} for c in clientes_sugeridos(conversa)]
    return {'clientes': resultado, 'sugeridos': sugeridos}


@transaction.atomic
def simular_recebida(telefone: str, nome: str, texto: str) -> Mensagem | None:
    import uuid

    from crm.services.conversas import EntradaNormalizada, receber_mensagem

    return receber_mensagem(EntradaNormalizada(
        telefone=telefone, wa_message_id=f'sim.in.{uuid.uuid4().hex}', tipo=Mensagem.Tipo.TEXTO,
        texto=texto, contato_nome=nome,
    ))


def simular_leitura(conversa: Conversa) -> int:
    alteradas = Mensagem.objects.filter(
        conversa=conversa, direcao=Mensagem.Direcao.SAIDA,
        status__in=[Mensagem.Status.ENVIADO, Mensagem.Status.ENTREGUE],
    ).update(status=Mensagem.Status.LIDO)
    avisos.emitir(conversa, 'mensagem_status')
    return alteradas
