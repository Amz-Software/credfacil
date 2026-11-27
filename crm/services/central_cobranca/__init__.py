"""Central de cobrança: teto diário e saúde do número (teto), janela de envio (janela), agenda da
régua (agenda), histórico de avisos (historico) e disparos manuais (disparos, envio_disparos).

Os módulos daqui não são importados neste `__init__`: `crm.services.cobranca` usa `janela` e `teto`,
e `agenda`/`disparos` usam `cobranca` (sem import circular).
"""
