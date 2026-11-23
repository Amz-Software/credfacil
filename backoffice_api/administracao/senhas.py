"""Senha temporária forte para a redefinição feita por um administrador."""
import secrets
import string

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

TAMANHO_SENHA_TEMPORARIA = 16
SIMBOLOS = '!@#$%&*?-_'
CLASSES = (string.ascii_uppercase, string.ascii_lowercase, string.digits, SIMBOLOS)
TENTATIVAS = 20


def _sortear() -> str:
    obrigatorios = [secrets.choice(classe) for classe in CLASSES]
    alfabeto = ''.join(CLASSES)
    resto = [secrets.choice(alfabeto) for _ in range(TAMANHO_SENHA_TEMPORARIA - len(obrigatorios))]
    caracteres = obrigatorios + resto
    secrets.SystemRandom().shuffle(caracteres)
    return ''.join(caracteres)


def gerar_senha_temporaria(user) -> str:
    """Senha aleatória com maiúscula, minúscula, número e símbolo, aprovada pela política."""
    for _ in range(TENTATIVAS):
        senha = _sortear()
        try:
            validate_password(senha, user)
        except ValidationError:
            continue
        return senha
    raise RuntimeError('Não foi possível gerar uma senha temporária válida.')
