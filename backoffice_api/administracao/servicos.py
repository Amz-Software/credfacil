"""Criação e edição de usuários com as regras de concessão e de escopo de lojas."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from backoffice_api.nucleo.erros import PROIBIDO_ACESSO, ErroBackoffice

from .regras import codigos_de, mesclar_lojas, validar_concessao

User = get_user_model()
CAMPOS_LOJAS = ('lojas', 'lojas_gerenciadas')
TAMANHO_BASE_USUARIO = 140


def gerar_username(nome: str, sobrenome: str) -> str:
    """'nome.sobrenome' sem acentos (como o modelo), com sufixo numérico se já existir."""
    partes = [slugify(p).replace('-', '.') for p in (nome, sobrenome) if p]
    base = ('.'.join(p for p in partes if p) or 'usuario')[:TAMANHO_BASE_USUARIO]
    candidato, sufixo = base, 2
    while User.objects.filter(username__iexact=candidato).exists():
        candidato, sufixo = f'{base}{sufixo}', sufixo + 1
    return candidato


def retrato(user) -> dict:
    """Resumo do usuário para o antes/depois da auditoria."""
    return {
        'usuario': user.username,
        'nome': user.first_name,
        'sobrenome': user.last_name,
        'email': user.email,
        'grupos': sorted(user.groups.values_list('name', flat=True)),
        'permissoes': sorted(codigos_de(user.user_permissions.all())),
        'lojas': sorted(user.lojas.values_list('pk', flat=True)),
        'lojas_gerenciadas': sorted(user.lojas_gerenciadas.values_list('pk', flat=True)),
        'loja_principal': user.loja_id,
    }


def diferencas(antes: dict, depois: dict) -> dict:
    return {campo: {'antes': antes[campo], 'depois': depois[campo]} for campo in antes if antes[campo] != depois[campo]}


def _erro_escopo(campo: str, mensagem: str) -> ErroBackoffice:
    return ErroBackoffice(mensagem, codigo=PROIBIDO_ACESSO, status_http=403, campos={campo: [mensagem]})


def _validar_lojas(dados: dict, alvo, escopo: set[int] | None) -> None:
    """Só vincula lojas do escopo de quem edita (vínculos atuais fora dele podem ser reenviados)."""
    if escopo is None:
        return
    for campo in CAMPOS_LOJAS:
        if campo not in dados:
            continue
        atuais = set(getattr(alvo, campo).values_list('pk', flat=True)) if alvo else set()
        novas_fora = sorted(l.nome for l in dados[campo] if l.pk not in escopo and l.pk not in atuais)
        if novas_fora:
            raise _erro_escopo(campo, f'Lojas fora do seu escopo: {", ".join(novas_fora)}.')
    if 'loja_principal' in dados:
        nova = dados['loja_principal']
        atual = alvo.loja_id if alvo else None
        if nova is not None and nova.pk not in escopo and nova.pk != atual:
            raise _erro_escopo('loja_principal', 'A loja principal precisa ser uma loja do seu escopo.')
        if atual is not None and atual not in escopo and getattr(nova, 'pk', None) != atual:
            raise _erro_escopo('loja_principal',
                               'A loja principal atual está fora do seu escopo e não pode ser trocada por você.')


def _gravar_lojas(user, dados: dict, escopo: set[int] | None) -> None:
    for campo in CAMPOS_LOJAS:
        if campo in dados:
            atuais = set(getattr(user, campo).values_list('pk', flat=True))
            getattr(user, campo).set(mesclar_lojas(atuais, {l.pk for l in dados[campo]}, escopo))


@transaction.atomic
def criar_usuario(*, editor, minhas: set[str], dados: dict, escopo: set[int] | None):
    validar_concessao(editor, minhas, grupos=dados.get('grupos'), permissoes=dados.get('permissoes'))
    _validar_lojas(dados, None, escopo)
    if escopo is not None and not (dados.get('lojas') or dados.get('lojas_gerenciadas') or dados.get('loja_principal')):
        mensagem = 'Vincule o usuário a pelo menos uma loja do seu escopo.'
        raise ErroBackoffice(mensagem, campos={'lojas': [mensagem]})
    user = User(
        username=dados.get('username') or gerar_username(dados.get('first_name', ''), dados.get('last_name', '')),
        first_name=dados.get('first_name', ''),
        last_name=dados.get('last_name', ''),
        email=dados['email'],
        loja=dados.get('loja_principal'),
        is_active=True,
    )
    user.set_password(dados['senha'])
    user.save()
    user.groups.set(dados.get('grupos', []))
    user.user_permissions.set(dados.get('permissoes', []))
    _gravar_lojas(user, dados, escopo)
    return user


@transaction.atomic
def atualizar_usuario(*, editor, minhas: set[str], alvo, dados: dict, escopo: set[int] | None) -> dict:
    """Aplica a edição e devolve as diferenças (antes/depois) para a auditoria."""
    validar_concessao(editor, minhas, grupos=dados.get('grupos'), permissoes=dados.get('permissoes'))
    _validar_lojas(dados, alvo, escopo)
    antes = retrato(alvo)
    for origem, destino in (('username', 'username'), ('first_name', 'first_name'),
                            ('last_name', 'last_name'), ('email', 'email')):
        if origem in dados:
            setattr(alvo, destino, dados[origem])
    if 'loja_principal' in dados:
        alvo.loja = dados['loja_principal']
    alvo.save()
    if 'grupos' in dados:
        alvo.groups.set(dados['grupos'])
    if 'permissoes' in dados:
        alvo.user_permissions.set(dados['permissoes'])
    _gravar_lojas(alvo, dados, escopo)
    return diferencas(antes, retrato(alvo))
