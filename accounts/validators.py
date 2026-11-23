"""Validadores de senha do projeto."""
from django.core.exceptions import ValidationError

MENSAGEM_REGRAS = (
    "A senha precisa ter pelo menos 10 caracteres, com letra maiúscula, "
    "letra minúscula, número e símbolo."
)


class SenhaForteValidator:
    """Exige letra maiúscula, letra minúscula, número e símbolo.

    O tamanho mínimo fica com o `MinimumLengthValidator` (configurado em 10).
    """

    def validate(self, password: str, user=None) -> None:
        faltando = []
        if not any(c.isupper() for c in password):
            faltando.append("uma letra maiúscula")
        if not any(c.islower() for c in password):
            faltando.append("uma letra minúscula")
        if not any(c.isdigit() for c in password):
            faltando.append("um número")
        if not any(not c.isalnum() and not c.isspace() for c in password):
            faltando.append("um símbolo (ex.: ! @ # $ %)")
        if faltando:
            raise ValidationError(
                "A senha precisa ter pelo menos " + ", ".join(faltando) + ".",
                code="senha_fraca",
            )

    def get_help_text(self) -> str:
        return MENSAGEM_REGRAS
