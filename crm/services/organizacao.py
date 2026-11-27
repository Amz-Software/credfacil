"""Organização do CRM: etiquetas, notas, lembretes, programadas, respostas rápidas, clientes."""
import logging
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
logger = logging.getLogger(__name__)


def definir_etiquetas(conversa: Conversa, ids: list[int]) -> None:
    """Substitui o conjunto; só aplica etiqueta ativa (ou que já estava na conversa)."""
    atuais = set(conversa.etiquetas.values_list('id', flat=True))
    pedidas = {int(i) for i in ids if i is not None}
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


PROGRAMADA_TRAVADA = timedelta(minutes=10)


def recuperar_programadas_travadas() -> int:
    """ENVIANDO há muito tempo (o worker caiu no meio) vira ERRO, com nota e aviso."""
    travadas = MensagemProgramada.objects.filter(
        status=MensagemProgramada.Status.ENVIANDO, enviar_em__lt=timezone.now() - PROGRAMADA_TRAVADA,
        mensagem__isnull=True,
    ).select_related('conversa', 'criado_por')
    total = 0
    for programada in travadas:
        if MensagemProgramada.objects.filter(pk=programada.pk, status=MensagemProgramada.Status.ENVIANDO).update(
                status=MensagemProgramada.Status.ERRO, erro='O envio foi interrompido. Programe de novo.'):
            nota_automatica(programada.conversa, 'A mensagem programada foi interrompida e não saiu.')
            avisos.notificar_usuario(programada.criado_por, 'Uma mensagem programada não foi enviada',
                                     programada.conversa)
            total += 1
    return total


def enviar_programadas_vencidas() -> int:
    """Cron: AGENDADA → ENVIANDO por compare-and-set; envia se a janela está aberta e em HUMANO."""
    enviadas = 0
    vencidas = MensagemProgramada.objects.filter(
        status=MensagemProgramada.Status.AGENDADA, enviar_em__lte=timezone.now(),
    ).select_related('conversa', 'criado_por')
    for programada in vencidas:
        try:
            enviadas += _enviar_programada(programada)
        except Exception:  # noqa: BLE001 — uma programada com problema não segura as outras
            logger.exception('Falha ao enviar a programada %s.', programada.pk)
    return enviadas


def _enviar_programada(programada: MensagemProgramada) -> int:
    from crm.services import envio

    travou = MensagemProgramada.objects.filter(
        pk=programada.pk, status=MensagemProgramada.Status.AGENDADA,
    ).update(status=MensagemProgramada.Status.ENVIANDO)
    if not travou:
        return 0
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
        return 0
    return 1


def avisar_lembretes_vencidos() -> int:
    avisados = 0
    agora = timezone.now()
    vencidos = Conversa.objects.filter(lembrete_em__lte=agora, lembrete_avisado_em__isnull=True)
    for conversa in vencidos.select_related('lembrete_para'):
        try:
            if Conversa.objects.filter(pk=conversa.pk, lembrete_avisado_em__isnull=True).update(lembrete_avisado_em=agora):
                texto = conversa.lembrete_texto or 'retornar a conversa'
                avisos.notificar_usuario(conversa.lembrete_para, f'Lembrete: {texto} ({conversa.nome_exibicao})', conversa)
                avisos.emitir(conversa, 'conversa_atualizada')
                avisados += 1
        except Exception:  # noqa: BLE001
            logger.exception('Falha ao avisar o lembrete da conversa %s.', conversa.pk)
    return avisados


def definir_apelido(conversa: Conversa, apelido: str) -> None:
    apelido = (apelido or '').strip()
    if len(apelido) > LIMITE_APELIDO:
        raise ConflitoCRM(f'O apelido passa de {LIMITE_APELIDO} caracteres.')
    Conversa.objects.filter(pk=conversa.pk).update(apelido=apelido)
    avisos.emitir(conversa, 'conversa_atualizada')


def _lojas_do_usuario(usuario) -> set[int]:
    lojas = set(usuario.lojas.values_list('id', flat=True)) | set(usuario.lojas_gerenciadas.values_list('id', flat=True))
    if getattr(usuario, 'loja_id', None):
        lojas.add(usuario.loja_id)
    return lojas


def _ve_todas_as_lojas(usuario) -> bool:
    return usuario.has_perm('vendas.view_all_analise_credito') or usuario.has_perm('vendas.can_view_all_stores')


def pode_ver_cliente(usuario, cliente, lojas: set[int] | None = None) -> bool:
    """Mesmo escopo do resto do sistema: permissão de cliente e loja do usuário."""
    if not usuario.has_perm('vendas.view_cliente'):
        return False
    if _ve_todas_as_lojas(usuario):
        return True
    return cliente.loja_id in (lojas if lojas is not None else _lojas_do_usuario(usuario))


def nomes_dos_clientes(conversa: Conversa, usuario) -> list[str]:
    """Nome dos clientes vinculados à conversa que o usuário pode ver (cabeçalho, abaixo do nome no WhatsApp)."""
    lojas = _lojas_do_usuario(usuario)
    return [c.nome for c in conversa.clientes.all() if pode_ver_cliente(usuario, c, lojas)]


def mascarar_cpf(cpf: str) -> str:
    digitos = ''.join(c for c in cpf or '' if c.isdigit())
    if len(digitos) != 11:
        return ''
    return f'***.{digitos[3:6]}.{digitos[6:9]}-**'


def vincular_cliente(conversa: Conversa, cliente_id: int, vincular: bool = True, usuario=None) -> None:
    from vendas.models import Cliente

    cliente = Cliente.objects.filter(pk=cliente_id).first()
    if cliente is None or (usuario is not None and vincular and not pode_ver_cliente(usuario, cliente)):
        raise ConflitoCRM('Cliente não encontrado ou fora das suas lojas.')
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


def clientes_sugeridos(conversa: Conversa, usuario=None):
    """Clientes cujo telefone casa com o número da conversa (comparação pela chave)."""
    from vendas.models import Cliente

    if usuario is not None and not usuario.has_perm('vendas.view_cliente'):
        return []

    sufixo = sufixo_busca(conversa.telefone)
    if not sufixo:
        return []
    chave = chave_telefone(conversa.telefone)
    candidatos = Cliente.objects.filter(Q(telefone__endswith=sufixo) | Q(telefone_secundario__endswith=sufixo))
    if usuario is not None and not _ve_todas_as_lojas(usuario):
        candidatos = candidatos.filter(loja_id__in=_lojas_do_usuario(usuario))
    vinculados = set(conversa.clientes.values_list('id', flat=True))
    return [c for c in candidatos[:50]
            if c.pk not in vinculados
            and chave in (chave_telefone(c.telefone), chave_telefone(c.telefone_secundario))][:MAX_SUGERIDOS]


def painel(conversa: Conversa, usuario) -> dict:
    """Dados dos clientes vinculados que o usuário pode ver; vendas só com view_venda."""
    from vendas.models import AnaliseCreditoCliente, Venda

    from crm.services import pagamentos

    lojas = _lojas_do_usuario(usuario)
    ve_vendas = usuario.has_perm('vendas.view_venda')
    ve_pagamentos = usuario.has_perm('vendas.view_pagamento')
    resultado = []
    for cliente in conversa.clientes.all():
        if not pode_ver_cliente(usuario, cliente, lojas):
            continue
        analise = AnaliseCreditoCliente.objects.filter(cliente=cliente).select_related('produto').first()
        solicitacoes = []
        if analise:
            solicitacoes.append({
                'id': cliente.pk, 'status': analise.status, 'status_display': analise.get_status_display(),
                'produto': analise.produto.nome if analise.produto_id else '', 'data': analise.data_analise,
            })
        vendas = Venda.objects.filter(cliente=cliente).order_by('-data_venda')[:MAX_VENDAS_PAINEL] if ve_vendas else []
        resultado.append({
            'id': cliente.pk, 'nome': cliente.nome, 'cpf': mascarar_cpf(cliente.cpf), 'telefone': cliente.telefone,
            'vinculado': True, 'solicitacoes': solicitacoes[:MAX_SOLICITACOES_PAINEL],
            'vendas': [{'id': v.pk, 'data': v.data_venda, 'valor_total': v.pagamentos_valor_total,
                        'cancelada': v.is_deleted} for v in vendas],
            'pagamentos': pagamentos.resumo_do_cliente(cliente) if ve_pagamentos else [],
        })
    sugeridos = [{'id': c.pk, 'nome': c.nome, 'telefone': c.telefone} for c in clientes_sugeridos(conversa, usuario)]
    return {'clientes': resultado, 'sugeridos': sugeridos}


MIN_BUSCA_CLIENTE = 3
MAX_BUSCA_CLIENTE = 10


def buscar_clientes(usuario, termo: str) -> list[dict]:
    """Busca por CPF (dígitos) ou nome, no mesmo escopo de lojas do resto do sistema."""
    from vendas.models import Cliente

    termo = (termo or '').strip()
    digitos = ''.join(c for c in termo if c.isdigit())
    if not usuario.has_perm('vendas.view_cliente'):
        return []
    if len(digitos) >= MIN_BUSCA_CLIENTE:
        clientes = Cliente.objects.filter(cpf__contains=digitos)
    elif len(termo) >= MIN_BUSCA_CLIENTE:
        clientes = Cliente.objects.filter(nome__icontains=termo)
    else:
        return []
    if not _ve_todas_as_lojas(usuario):
        clientes = clientes.filter(loja_id__in=_lojas_do_usuario(usuario))
    return [{'id': c.pk, 'nome': c.nome, 'cpf': mascarar_cpf(c.cpf), 'telefone': c.telefone}
            for c in clientes.order_by('nome')[:MAX_BUSCA_CLIENTE]]


def texto_resumo_pagamentos(usuario, cliente_id: int) -> str:
    from crm.services import pagamentos
    from vendas.models import Cliente

    cliente = Cliente.objects.filter(pk=cliente_id).first()
    if cliente is None or not pode_ver_cliente(usuario, cliente):
        raise ConflitoCRM('Cliente não encontrado ou fora das suas lojas.')
    if not usuario.has_perm('vendas.view_pagamento'):
        raise ConflitoCRM('Você não tem permissão para ver pagamentos.')
    return pagamentos.texto_resumo(cliente.nome, pagamentos.resumo_do_cliente(cliente))


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
