import os
import json
from datetime import datetime
from typing import Any

def build_prompt(template_path: str, **kwargs) -> str:
    """
    Generic prompt builder. 
    Loads a file and injects any number of variables provided via keyword arguments.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found at: {template_path}")

    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    try:
        # .format(**kwargs) unpacks the dictionary into named arguments
        return template.format(**kwargs)
    except KeyError as e:
        # This helps you debug if your .txt file has a {variable} 
        # that you forgot to pass into the function
        raise KeyError(f"Missing variable in prompt build: {e}")

def print_section(head: str = "", msg: str = "", symbol: str = "*"):
    symbol_patt = 50*f"{symbol}"
    print("\n", f"{symbol_patt}")
    print(f"  {head} : {msg}")
    print(f"{symbol_patt}")

def safe_json_string(text: str) -> str:
    """
    Convierte texto a string JSON seguro escapando comillas dobles.
    """
    import re
    if not text:
        return ""
    
    # json.dumps() escapa todo correctamente y DEVUELVE UN STRING CON COMILLAS
    text = json.dumps(text, ensure_ascii=False)
    
    if not text:
        return ""
    
    # 1. Eliminar marcadores markdown (#, ##, ###, ---, etc.)
    text = re.sub(r'#{1,6}\s*', '', text)  # Elimina #, ##, ###
    text = re.sub(r'-{2,}', '', text)      # Elimina ---, etc.
    text = re.sub(r'\*\*', '', text)       # Elimina **
    text = re.sub(r'__', '', text)         # Elimina __
    
    return text.strip('"')  # Elimina las comillas añadidas por json.dumps

def split_text(content: str, chunk_size: int = 400, chunk_overlap: int = 40) -> list[str]:
    """
    Divide texto en chunks recursivamente por secciones/párrafos/oraciones.

    Reemplaza a langchain_text_splitters.RecursiveCharacterTextSplitter
    sin agregar dependencias externas.

    Args:
        content: Texto a dividir.
        chunk_size: Tamaño máximo por chunk en caracteres.
        chunk_overlap: Solapamiento entre chunks consecutivos (solo cuando
                       se corta forzosamente sin encontrar separador).

    Returns:
        Lista de fragmentos de texto.
    """
    import re

    if not content or not content.strip():
        return []

    separators = [r"\n## ", r"\n### ", r"\n\n", r"\n", r"\. "]
    chunks: list[str] = []
    start = 0

    while start < len(content):
        end = min(start + chunk_size, len(content))

        # Buscar el último separador dentro del chunk
        found_sep = False
        for sep in separators:
            matches = list(re.finditer(sep, content[start:end]))
            if matches:
                end = start + matches[-1].end()
                found_sep = True
                break

        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(content):
            break

        # Con separador → avanzamos justo después del separador
        # Sin separador → retrocedemos chunk_overlap para preservar contexto
        if found_sep:
            start = end
        else:
            start = max(end - chunk_overlap, start + 1)
            if start >= end:
                break

    return chunks or [content.strip()]


class DateTimeEncoder(json.JSONEncoder):
    """JSONEncoder que maneja datetime objects."""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Aquí puedes añadir más tipos si es necesario
        return super().default(obj)

