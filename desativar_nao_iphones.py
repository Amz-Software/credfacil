import os
import django

# Certifique-se de usar o mesmo caminho de configurações que sua produção utiliza
# Caso seu settings seja local.py ou producao.py, ajuste aqui, exemplo 'credfacil.settings.producao'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from produtos.models import Produto

def inativar_produtos_nao_iphone():
    # Filtra produtos que estão ativos mas NÃO marcam a flag is_iphone como True
    produtos = Produto.objects.filter(is_iphone=False, ativo=True)
    
    total = produtos.count()
    print(f"Foram encontrados {total} produtos não-iPhone com status ativo.")
    
    if total > 0:
        # Executa uma única query de bloco (update em lote) no banco de dados, ignorando logs unitários, ganhando velocidade
        linhas_atualizadas = produtos.update(ativo=False)
        print(f"✅ Sucesso: {linhas_atualizadas} produtos foram desativados com sucesso!")
    else:
        print("🤷 Nenhuma alteração foi necessária. Você já não posui não-iPhones ativos.")

if __name__ == '__main__':
    inativar_produtos_nao_iphone()
