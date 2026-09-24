"""Chamada ao Claude em modo headless (`claude -p`), usando a assinatura já logada nesta máquina.

--safe-mode: não carrega CLAUDE.md, hooks, skills nem plugins (o roteirista não herda o modo caveman).
Cada chamada é uma conversa nova: o juiz nunca vê o raciocínio do roteirista.
"""

import json
import os
import sys
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CLAUDE = shutil.which("claude") or "claude"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import medidor  # noqa: E402


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
        _FLAGS = [f for f in ("--safe-mode", "--no-session-persistence", "--effort") if f in ajuda]
    return _FLAGS


def _rodar(cmd: list[str], entrada: str, cwd: str, timeout: int) -> subprocess.CompletedProcess:
    """subprocess.run com timeout de verdade: no Windows o claude.CMD abre um node filho que o kill normal
    não derruba, e o run ficava esperando o filho terminar (30 min em vez de 10)."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", cwd=cwd)
    try:
        out, err = p.communicate(entrada, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.kill()
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def chamar(prompt: str, schema: dict, ler_arquivos_em: Path | None = None, timeout: int = 600,
           modelo: str | None = None, papel: str = "roteirista") -> dict:
    """Manda o prompt e devolve o JSON validado pelo schema. Com ler_arquivos_em, o modelo pode abrir
    (só ler) arquivos daquela pasta, por exemplo imagens para o juiz visual."""
    if caminhos.LLM == "api":  # API direta da Anthropic: sem o overhead do Claude Code CLI
        import llm_api
        try:
            return llm_api.chamar(prompt, schema, ler_arquivos_em, modelo, papel)
        except Exception as e:
            raise ErroLLM(f"API: {e}") from e
    if caminhos.LLM != "claude-cli":
        raise ErroLLM(f"MILIONERE_LLM={caminhos.LLM!r} desconhecido (use claude-cli ou api)")
    cmd = [CLAUDE, "-p", *[f for f in _flags_opcionais() if f != "--effort"], "--output-format", "json", "--json-schema", json.dumps(schema)]
    if ler_arquivos_em:
        cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", str(ler_arquivos_em)]
    else:
        cmd += ["--tools", ""]
    modelo = modelo or (caminhos.MODELO_JUIZ if papel == "juiz" else caminhos.MODELO_ROTEIRO)
    if modelo:
        cmd += ["--model", modelo]
    if "--effort" in _flags_opcionais():  # não herda o esforço da sessão de quem roda (ex.: "high" no settings.json)
        cmd += ["--effort", caminhos.ESFORCO_JUIZ if papel == "juiz" else caminhos.ESFORCO_ROTEIRO]
    ultimo = ""
    for _ in range(2):
        inicio = time.time()
        with tempfile.TemporaryDirectory() as vazio:  # roda fora do projeto: nada de CLAUDE.md por perto
            try:
                proc = _rodar(cmd, prompt, vazio, timeout)
            except subprocess.TimeoutExpired:
                raise ErroLLM(f"o claude -p passou de {timeout // 60} min sem responder ({papel}, modelo {modelo})") from None
        try:
            saida = json.loads(proc.stdout)
        except json.JSONDecodeError:
            ultimo = (proc.stdout + proc.stderr)[-1500:]
            continue
        medidor.llm(saida, time.time() - inicio)  # conta também as tentativas que falharam (foram pagas)
        if saida.get("is_error") or "structured_output" not in saida:
            ultimo = json.dumps(saida, ensure_ascii=False)[:1500]
            continue
        return saida["structured_output"]
    raise ErroLLM(f"claude -p falhou duas vezes: {ultimo}")
