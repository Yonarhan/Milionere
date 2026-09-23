"""Chamada ao Claude em modo headless (`claude -p`), usando a assinatura já logada nesta máquina.

--safe-mode: não carrega CLAUDE.md, hooks, skills nem plugins (o roteirista não herda o modo caveman).
Cada chamada é uma conversa nova: o juiz nunca vê o raciocínio do roteirista.
"""

import json
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

CLAUDE = shutil.which("claude") or "claude"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402


class ErroLLM(RuntimeError):
    pass


_FLAGS: list[str] | None = None


def _flags_opcionais() -> list[str]:
    """--safe-mode e --no-session-persistence só existem em versões novas do Claude Code: usa se tiver."""
    global _FLAGS
    if _FLAGS is None:
        try:
            ajuda = subprocess.run([CLAUDE, "--help"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            ajuda = ""
        _FLAGS = [f for f in ("--safe-mode", "--no-session-persistence") if f in ajuda]
    return _FLAGS


def chamar(prompt: str, schema: dict, ler_arquivos_em: Path | None = None, timeout: int = 600,
           modelo: str | None = None) -> dict:
    """Manda o prompt e devolve o JSON validado pelo schema. Com ler_arquivos_em, o modelo pode abrir
    (só ler) arquivos daquela pasta, por exemplo imagens para o juiz visual."""
    if caminhos.LLM != "claude-cli":
        raise ErroLLM(f"MILIONERE_LLM={caminhos.LLM!r} ainda não implementado (fase 1: API). Use claude-cli.")
    cmd = [CLAUDE, "-p", *_flags_opcionais(), "--output-format", "json", "--json-schema", json.dumps(schema)]
    if ler_arquivos_em:
        cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", str(ler_arquivos_em)]
    else:
        cmd += ["--tools", ""]
    if modelo:
        cmd += ["--model", modelo]
    ultimo = ""
    for _ in range(2):
        with tempfile.TemporaryDirectory() as vazio:  # roda fora do projeto: nada de CLAUDE.md por perto
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", cwd=vazio, timeout=timeout)
        try:
            saida = json.loads(proc.stdout)
        except json.JSONDecodeError:
            ultimo = (proc.stdout + proc.stderr)[-1500:]
            continue
        if saida.get("is_error") or "structured_output" not in saida:
            ultimo = json.dumps(saida, ensure_ascii=False)[:1500]
            continue
        return saida["structured_output"]
    raise ErroLLM(f"claude -p falhou duas vezes: {ultimo}")
