"""Chamada ao Claude em modo headless (`claude -p`), usando a assinatura já logada nesta máquina.

--safe-mode: não carrega CLAUDE.md, hooks, skills nem plugins (o roteirista não herda o modo caveman).
Cada chamada é uma conversa nova: o juiz nunca vê o raciocínio do roteirista.
"""

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import sys
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

CLAUDE = shutil.which("claude") or "claude"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
# camada trocável do juiz visual: "claude" (padrão, uma imagem por chamada), "claude-lote" (várias por chamada)
# ou "ollama:<modelo>" (modelo aberto na GPU local)
JUIZ_VISUAL = os.environ.get("MILIONERE_JUIZ_VISUAL", "claude")
LIMITE_ESPERAS, LIMITE_ESPERA_S = 3, 90  # 429 (limite da assinatura): espera 90s, 180s, 270s antes de desistir

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import medidor  # noqa: E402

_provedor_job = ContextVar("provedor_llm_job", default=None)


@contextmanager
def usar_provedor(provedor: str):
    token = _provedor_job.set(provedor)
    try:
        yield
    finally:
        _provedor_job.reset(token)


class ErroLLM(RuntimeError):
    pass


import threading  # noqa: E402

# ligado pelo produtor quando o vídeo é cancelado no painel: a próxima chamada (e as tentativas que viriam) param na hora
CANCELADO = threading.Event()


def _conferir_cancelado() -> None:
    if CANCELADO.is_set():
        raise ErroLLM("cancelado no painel")


_FLAGS: list[str] | None = None


def _flags_opcionais() -> list[str]:
    """--safe-mode e --no-session-persistence só existem em versões novas do Claude Code: usa se tiver."""
    global _FLAGS
    if _FLAGS is None:
        try:
            ajuda = subprocess.run([CLAUDE, "--help"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            ajuda = ""
        _FLAGS = [f for f in ("--safe-mode", "--no-session-persistence", "--effort", "--system-prompt") if f in ajuda]
    return _FLAGS


# substitui as ~13 mil tokens de instruções do Claude Code que iam em toda chamada (medido: 18,1 mil -> 5,3 mil
# tokens de entrada numa chamada vazia). Consome bem menos do limite da assinatura.
SISTEMA = ("Você executa uma única tarefa de um pipeline automático de vídeos curtos e responde só no formato "
           "estruturado pedido, sem conversa.")
SISTEMA_ARQUIVOS = " Abra os arquivos citados com a ferramenta Read antes de responder."


def _rodar(cmd: list[str], entrada: str, cwd: str, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    """subprocess.run com timeout de verdade: no Windows o claude.CMD abre um node filho que o kill normal
    não derruba, e o run ficava esperando o filho terminar (30 min em vez de 10)."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", cwd=cwd, env=env)
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
    _conferir_cancelado()
    provedor = _provedor_job.get() or caminhos.LLM
    if provedor == "api":  # API direta da Anthropic: sem o overhead do Claude Code CLI
        import llm_api
        try:
            return llm_api.chamar(prompt, schema, ler_arquivos_em, modelo, papel)
        except Exception as e:
            raise ErroLLM(f"API: {e}") from e
    if provedor != "claude-cli":
        raise ErroLLM(f"MILIONERE_LLM={provedor!r} desconhecido (use claude-cli ou api)")
    cmd = [CLAUDE, "-p", *[f for f in _flags_opcionais() if f not in ("--effort", "--system-prompt")],
           "--output-format", "json", "--json-schema", json.dumps(schema)]
    if "--system-prompt" in _flags_opcionais():
        cmd += ["--system-prompt", SISTEMA + (SISTEMA_ARQUIVOS if ler_arquivos_em else "")]
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
    limites = 0
    tentativa = 0
    while tentativa < 2:
        tentativa += 1
        _conferir_cancelado()
        inicio = time.time()
        with tempfile.TemporaryDirectory() as vazio:  # roda fora do projeto: nada de CLAUDE.md por perto
            try:
                proc = _rodar(cmd, prompt, vazio, timeout, {**os.environ, "MAX_THINKING_TOKENS": caminhos.PENSAR_TOKENS})
            except subprocess.TimeoutExpired:
                raise ErroLLM(f"o claude -p passou de {timeout // 60} min sem responder ({papel}, modelo {modelo})") from None
        try:
            saida = json.loads(proc.stdout)
        except json.JSONDecodeError:
            ultimo = (proc.stdout + proc.stderr)[-1500:].strip() or                 f"o claude -p saiu com código {proc.returncode} sem escrever nada (confira o login: rode 'claude' no terminal)"
            continue
        medidor.llm(saida, time.time() - inicio)  # conta também as tentativas que falharam (foram pagas)
        if saida.get("is_error") or "structured_output" not in saida:
            # o motivo ("You've hit your session limit...") vem em result: primeiro, pra aparecer no painel
            ultimo = f"{saida.get('result', '')} | " + json.dumps(saida, ensure_ascii=False)[:1500]
            if saida.get("api_error_status") == 429 and limites < LIMITE_ESPERAS:
                # limite da assinatura: às vezes é só um pico. Espera e tenta de novo sem gastar uma das 2 tentativas
                limites += 1
                tentativa -= 1
                time.sleep(LIMITE_ESPERA_S * limites)
            continue
        return saida["structured_output"]
    raise ErroLLM(f"claude -p falhou duas vezes: {ultimo}")


def chamar_ollama(prompt: str, schema: dict, modelo: str, imagens: list[Path] | None = None, timeout: int = 600) -> dict:
    """Mesmo contrato de chamar(), mas num modelo aberto servido pelo Ollama (saída presa ao schema)."""
    msg = {"role": "user", "content": prompt}
    if imagens:
        msg["images"] = [base64.b64encode(Path(i).read_bytes()).decode() for i in imagens]
    corpo = json.dumps({"model": modelo, "messages": [msg], "format": schema, "stream": False,
                        # raciocínio ligado deixa o Qwen3-VL ~10x mais lento; MILIONERE_OLLAMA_THINK=1 liga
                        "think": os.environ.get("MILIONERE_OLLAMA_THINK") == "1",
                        "options": {"temperature": 0}}).encode()
    ultimo = ""
    for _ in range(2):
        req = urllib.request.Request(OLLAMA + "/api/chat", data=corpo, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            m = json.load(r)["message"]
        # Ollama 0.34 + Qwen3-VL com think=false devolve o JSON no campo "thinking" e "content" vazio
        texto = m.get("content") or m.get("thinking", "")
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            ultimo = texto[-1500:]
    raise ErroLLM(f"ollama ({modelo}) devolveu JSON inválido duas vezes: {ultimo}")
