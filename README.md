# CredFacil — backoffice e API

Backoffice em Django (templates) e API REST (DRF) consumida pela SPA do vendedor
(`front-connect-magic`). Arquitetura, modelos, fluxos de venda e endpoints estão
documentados em [CLAUDE.md](CLAUDE.md).

## Rodar os testes

Use Python 3.12 (mesma versão do `Dockerfile`):

```bash
python manage.py test
```

O deploy (`.github/workflows/deploy.yml`) só roda depois que os testes passam.
