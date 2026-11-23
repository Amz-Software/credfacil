"""Regras de segurança da administração de usuários e grupos.

- Ninguém concede o que não possui: grupos e permissões diretas só entram se estiverem
  contidos nas permissões efetivas de quem edita (superusuário pode tudo).
- Ninguém altera quem tem mais acesso: o alvo precisa ter permissões contidas nas de
  quem edita, não ser superusuário nem staff (para quem não é), e não ser o próprio usuário.
- As permissões do alvo são lidas direto do banco (diretas + grupos), mesmo se ele estiver
  inativo: `get_all_permissions()` devolve vazio para inativo e abriria brecha para
  reativar/redefinir a senha de um administrador desativado.
"""
from django.contrib.auth.models import Group, Permission
from django.db.models import QuerySet

from backoffice_api.nucleo.erros import PROIBIDO_ACESSO, ErroBackoffice
from backoffice_api.nucleo.permissoes import PermissaoNegada

MENSAGEM_SI_MESMO = 'Use "Meu perfil" para alterar os seus próprios dados.'
MENSAGEM_SUPERUSUARIO = 'Somente um superusuário pode alterar outro superusuário.'
MENSAGEM_STAFF = 'Somente usuários da equipe técnica (staff) podem alterar este usuário.'
MENSAGEM_MAIS_ACESSO = 'Este usuário tem permissões que você não possui. Peça a um administrador com mais acesso.'
MENSAGEM_GRUPO_MAIS_ACESSO = 'Este grupo tem permissões que você não possui. Peça a um administrador com mais acesso.'


def codigo_permissao(permissao: Permission) -> str:
    return f'{permissao.content_type.app_label}.{permissao.codename}'


def codigos_de(permissoes: QuerySet) -> set[str]:
    return {f'{app}.{codename}' for app, codename in permissoes.values_list('content_type__app_label', 'codename')}


def permissoes_efetivas(user) -> set[str]:
    """Permissões diretas + de grupos, independentemente de `is_active`; superusuário = todas."""
    if user.is_superuser:
        return codigos_de(Permission.objects.all())
    diretas = codigos_de(user.user_permissions.all())
    return diretas | codigos_de(Permission.objects.filter(group__in=user.groups.all()))


def motivo_para_nao_gerenciar(editor, alvo, minhas: set[str]) -> str | None:
    """None se `editor` pode alterar `alvo`; senão, a mensagem do bloqueio."""
    if alvo.pk == editor.pk:
        return MENSAGEM_SI_MESMO
    if editor.is_superuser:
        return None
    if alvo.is_superuser:
        return MENSAGEM_SUPERUSUARIO
    if alvo.is_staff and not editor.is_staff:
        return MENSAGEM_STAFF
    if permissoes_efetivas(alvo) - minhas:
        return MENSAGEM_MAIS_ACESSO
    return None


def exigir_pode_gerenciar(editor, alvo, minhas: set[str]) -> None:
    motivo = motivo_para_nao_gerenciar(editor, alvo, minhas)
    if motivo:
        raise PermissaoNegada(motivo)


def permissoes_alem_das_minhas(codigos: set[str], editor, minhas: set[str]) -> list[str]:
    if editor.is_superuser:
        return []
    return sorted(codigos - minhas)


def validar_concessao(editor, minhas: set[str], *, grupos=None, permissoes=None) -> None:
    """403 com `campos` se algum grupo ou permissão estiver fora das permissões de quem edita."""
    if editor.is_superuser:
        return
    campos: dict[str, list[str]] = {}
    if grupos:
        consulta = Group.objects.filter(pk__in=[g.pk for g in grupos]).prefetch_related('permissions__content_type')
        for grupo in consulta:
            if {codigo_permissao(p) for p in grupo.permissions.all()} - minhas:
                campos.setdefault('grupos', []).append(
                    f'Você não pode conceder o grupo "{grupo.name}": ele tem permissões que você não possui.'
                )
    if permissoes:
        fora = permissoes_alem_das_minhas(codigos_de(Permission.objects.filter(pk__in=[p.pk for p in permissoes])),
                                          editor, minhas)
        if fora:
            campos['permissoes'] = [f'Você não pode conceder permissões que não possui: {", ".join(fora)}.']
    if campos:
        raise ErroBackoffice(
            'Você não pode conceder acessos que não possui.',
            codigo=PROIBIDO_ACESSO, status_http=403, campos=campos,
        )


def mesclar_lojas(atuais: set[int], enviadas: set[int], escopo: set[int] | None) -> set[int]:
    """Vínculos finais: os enviados + os atuais fora do escopo de quem edita (que ele não vê)."""
    if escopo is None:
        return set(enviadas)
    return set(enviadas) | (set(atuais) - escopo)
