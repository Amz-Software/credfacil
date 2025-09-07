from django import template
import os

register = template.Library()

@register.filter
def is_image_file(file_field):
    """
    Verifica se o arquivo é uma imagem baseado na extensão
    """
    if not file_field or not file_field.name:
        return False
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
    file_extension = os.path.splitext(file_field.name.lower())[1]
    return file_extension in image_extensions

@register.filter
def get_file_extension(file_field):
    """
    Retorna a extensão do arquivo
    """
    if not file_field or not file_field.name:
        return ''
    
    return os.path.splitext(file_field.name.lower())[1]

@register.filter
def get_file_name(file_field):
    """
    Retorna o nome do arquivo sem o caminho
    """
    if not file_field or not file_field.name:
        return ''
    
    return os.path.basename(file_field.name)
