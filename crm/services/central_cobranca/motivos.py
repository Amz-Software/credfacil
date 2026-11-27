"""Motivos de um cliente ficar fora de um envio (agenda da régua e disparos) e o telefone que receberia."""
from crm.services import contatos
from crm.telefone import somente_digitos


class Motivo:
    BOM_PAGADOR = 'bom_pagador'
    PAGAMENTO_INFORMADO = 'pagamento_informado'
    JA_AVISADO_HOJE = 'ja_avisado_hoje'
    LIMITE_DIARIO = 'limite_diario'
    SEM_TELEFONE = 'sem_telefone_valido'
    SO_REFERENCIA = 'so_referencia'
    ANTES_DA_ATIVACAO = 'antes_da_ativacao'
    REGUA_PAUSADA = 'regua_pausada'
    PAUSADA_POR_QUALIDADE = 'pausada_por_qualidade'
    DOMINGO_FERIADO = 'domingo_feriado'
    FORA_DO_HORARIO = 'fora_do_horario'
    ETAPA_SEM_MODELO = 'etapa_sem_modelo'
    AVISO_RECENTE = 'aviso_recente_48h'
    MESMO_CLIENTE = 'mesmo_cliente'
    PARCELA_PAGA = 'parcela_paga'
    PARCELA_INDISPONIVEL = 'parcela_indisponivel'
    RECUSADO_PELA_META = 'recusado_pela_meta'

    ROTULOS = {
        BOM_PAGADOR: 'Bom pagador (sem lembrete antecipado)',
        PAGAMENTO_INFORMADO: 'Pagamento informado, aguardando baixa',
        JA_AVISADO_HOJE: 'Já recebe outro aviso no dia',
        LIMITE_DIARIO: 'Teto diário atingido (fica para o próximo dia)',
        SEM_TELEFONE: 'Sem telefone válido',
        SO_REFERENCIA: 'Só tem número de referência',
        ANTES_DA_ATIVACAO: 'Antes da data de ativação da régua',
        REGUA_PAUSADA: 'Régua pausada',
        PAUSADA_POR_QUALIDADE: 'Pausada pela qualidade do número na Meta',
        DOMINGO_FERIADO: 'Domingo ou feriado',
        FORA_DO_HORARIO: 'Horário de envio encerrado',
        ETAPA_SEM_MODELO: 'Etapa sem mensagem aprovada',
        AVISO_RECENTE: 'Recebeu aviso nas últimas 48 h',
        MESMO_CLIENTE: 'Cliente já recebe por outra parcela',
        PARCELA_PAGA: 'Parcela paga',
        PARCELA_INDISPONIVEL: 'Parcela fora do crediário em aberto',
        RECUSADO_PELA_META: 'A Meta recusou o envio',
    }


def rotulo(motivo: str) -> str:
    return Motivo.ROTULOS.get(motivo, motivo)


def telefone_para_aviso(cliente) -> tuple[str, str]:
    """(dígitos do número que receberia, motivo se nenhum). Não grava nada; referência nunca recebe."""
    telefone = contatos.para_aviso_sem_gravar(cliente)
    if telefone is not None:
        return telefone.telefone, ''
    return '', Motivo.SO_REFERENCIA if contatos.tem_referencia(cliente) else Motivo.SEM_TELEFONE


def mascarar(numero: str) -> str:
    """(91) *****-0000: DDD e os 4 últimos dígitos."""
    digitos = somente_digitos(numero)
    if digitos.startswith('55') and len(digitos) > 11:
        digitos = digitos[2:]
    if len(digitos) < 10:
        return ''
    return f'({digitos[:2]}) {"*" * (len(digitos) - 6)}-{digitos[-4:]}'
