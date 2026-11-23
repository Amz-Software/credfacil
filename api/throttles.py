"""Limites de requisição (DRF) dos endpoints públicos da API.

As views de classe declaram `throttle_classes = [ScopedRateThrottle]` e
`throttle_scope`. As views de função (`@api_view`) não repassam
`throttle_scope`, então usam estas subclasses com o escopo fixo. As taxas ficam
em `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']` (THROTTLE_PUBLICO / THROTTLE_LOGIN).
"""
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle


class _EscopoFixoThrottle(ScopedRateThrottle):
    escopo: str = ''

    def allow_request(self, request, view):
        self.scope = self.escopo
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return SimpleRateThrottle.allow_request(self, request, view)


class LimitePublicoThrottle(_EscopoFixoThrottle):
    """Escopo `publico`: busca de lojas no login, contrato público."""
    escopo = 'publico'
