"""Pipeline Milionere: roteiro → validação → imagens → voz/legenda → vídeo → post.

Os módulos se importam pelo nome curto (`import biblia`), porque também rodam como script.
Ao importar como pacote (ex.: pelo worker do Django/Celery), a pasta entra no sys.path.
Configuração e caminhos: `caminhos.py` (variáveis MILIONERE_* ou `.env` na raiz).
"""

import sys
from pathlib import Path

_PASTA = str(Path(__file__).resolve().parent)
if _PASTA not in sys.path:
    sys.path.insert(0, _PASTA)
