"""Views da API REST, por domínio. Os nomes são reexportados para api/urls.py e core/urls.py."""
from .comum import *  # noqa: F401,F403
from .publico import *  # noqa: F401,F403
from .solicitacoes_regras import *  # noqa: F401,F403
from .solicitacoes import *  # noqa: F401,F403
from .lojas import *  # noqa: F401,F403
from .usuarios import *  # noqa: F401,F403
from .produtos import *  # noqa: F401,F403
from .vendas import *  # noqa: F401,F403
from .repasses import *  # noqa: F401,F403
from .fotos import *  # noqa: F401,F403
from .numeros_autenticadores import *  # noqa: F401,F403
from .pre_analise import *  # noqa: F401,F403
