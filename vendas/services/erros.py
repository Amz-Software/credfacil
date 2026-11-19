"""Erro de regra de negócio com a mensagem pronta para o usuário."""

INVALIDO = 'invalido'
PROIBIDO = 'proibido'
NAO_ENCONTRADO = 'nao_encontrado'

STATUS_HTTP = {INVALIDO: 400, PROIBIDO: 403, NAO_ENCONTRADO: 404}


class ErroDeNegocio(Exception):
    """Regra violada.

    `codigo` indica o tipo (inválido/proibido/não encontrado → 400/403/404 na API);
    `corrigir_na_edicao` diz se o backoffice deve levar o usuário à tela de edição
    da solicitação (o dado que falta é editável lá) em vez da listagem.
    """

    def __init__(self, mensagem: str, *, codigo: str = INVALIDO, corrigir_na_edicao: bool = False):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.corrigir_na_edicao = corrigir_na_edicao

    @property
    def status_http(self) -> int:
        return STATUS_HTTP.get(self.codigo, 400)
