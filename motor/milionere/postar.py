"""Posta no YouTube os vídeos de videos_prontos/ pela API oficial (grátis), usando o .txt que o pipeline gera.

Preenche título com hashtags, descrição (créditos só se a licença exigir), tags, "não é para crianças" e
"conteúdo alterado ou sintético = Sim"; sem comentário (o dono comenta e fixa à mão). Guarda o que já postou em
producao/postados.json para nunca postar duas vezes.

Configuração (uma vez):
    1. motor/segredos/youtube_cliente.json  <- o JSON do "ID do cliente OAuth" (app para computador) do Google Cloud
    2. python postar.py --autorizar            <- abre o login do Google e grava motor/segredos/youtube_token.json

Uso:
    python postar.py videos_prontos/2026-09-24_historia-davi-golias.mp4                 # publica agora
    python postar.py <video.mp4> --agendar "2026-09-25 19:00"                            # agenda (horário de Brasília)
    python postar.py <video.mp4> --privado                                               # sobe privado (teste)
    python postar.py --pendentes --limite 1   # sobe privado o mais antigo pronto, sem aviso e não postado (cron 3/3h)
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import caminhos  # noqa: E402
import cta  # noqa: E402

SEGREDOS = caminhos.RAIZ / "motor" / "segredos"
CLIENTE = SEGREDOS / "youtube_cliente.json"
TOKEN = SEGREDOS / "youtube_token.json"
POSTADOS = caminhos.PRODUCAO / "postados.json"
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload",
           "https://www.googleapis.com/auth/youtube.force-ssl"]  # force-ssl: editar título/descrição de vídeo já enviado
BRASILIA = timezone(timedelta(hours=-3))
CATEGORIA = "22"  # Pessoas e blogs


def credenciais(autorizar: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred = Credentials.from_authorized_user_file(str(TOKEN), ESCOPOS) if TOKEN.exists() else None
    if cred and cred.valid:
        return cred
    if cred and cred.expired and cred.refresh_token:
        try:
            cred.refresh(Request())
            TOKEN.write_text(cred.to_json(), encoding="utf-8")
            return cred
        except Exception as e:  # noqa: BLE001  (token revogado ou expirado: precisa autorizar de novo)
            if not autorizar:
                sys.exit(f"token do YouTube não renovou ({e}); rode: python postar.py --autorizar")
    if not autorizar:
        sys.exit("sem autorização do YouTube; rode: python postar.py --autorizar")
    if not CLIENTE.exists():
        sys.exit(f"falta {CLIENTE} (o JSON do ID do cliente OAuth baixado do Google Cloud)")
    fluxo = InstalledAppFlow.from_client_secrets_file(str(CLIENTE), ESCOPOS)
    # WSL: o navegador do Windows alcança o localhost do Linux; abra a URL impressa se não abrir sozinho
    cred = fluxo.run_local_server(port=8765, open_browser=False, prompt="consent",
                                  authorization_prompt_message="Abra no navegador e autorize:\n{url}\n")
    SEGREDOS.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(cred.to_json(), encoding="utf-8")
    TOKEN.chmod(0o600)
    return cred


def ler_post(txt: Path) -> dict:
    """Seções do .txt do pipeline: TÍTULO:, DESCRIÇÃO:, COMENTÁRIO FIXADO:, CRÉDITOS (...):, etc."""
    secoes, atual = {}, None
    for linha in txt.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([^a-z:()]+?)(?: \(.*\))?:\s*$", linha.strip())
        if m and m.group(1).isupper():
            atual = m.group(1).strip()
            secoes[atual] = []
        elif atual:
            secoes[atual].append(linha)
    texto = {k: "\n".join(v).strip() for k, v in secoes.items()}
    # créditos só quando a licença exige (CC BY, ex.: Kevin MacLeod); imagem de IA e Bíblia em domínio público, não
    creditos = "\n".join(l for l in texto.get("CRÉDITOS", "").splitlines() if "CC BY" in l).strip()
    hashtags = list(dict.fromkeys(re.findall(r"#\w+", texto["DESCRIÇÃO"])))
    hashtags = ["#shorts"] + [h for h in hashtags if h.lower() != "#shorts"]
    # no Shorts as hashtags vão no título (até 100 caracteres); a descrição fica só com o texto
    titulo = texto["TÍTULO"].strip()
    for h in hashtags:
        if len(f"{titulo} {h}") <= 100:
            titulo = f"{titulo} {h}"
    descricao = re.sub(r"[ \t]*#\w+", "", texto["DESCRIÇÃO"])
    descricao = re.sub(r"\n{3,}", "\n\n", descricao).strip() + (f"\n\n{creditos}" if creditos else "")
    tags = [h.lstrip("#") for h in hashtags if h.lower() != "#shorts"]
    return {"titulo": titulo, "descricao": descricao[:5000], "tags": tags,
            "comentario": texto.get("COMENTÁRIO FIXADO", "")}


def postados() -> dict:
    return json.loads(POSTADOS.read_text(encoding="utf-8")) if POSTADOS.exists() else {}


def postar(video: Path, agendar: datetime | None = None, privado: bool = False) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    ja = postados()
    if video.name in ja:
        print(f"já tratado: {video.name} ({ja[video.name].get('id') or 'postado à mão / fora da automação'})")
        return ja[video.name].get("id")
    post = ler_post(video.with_suffix(".txt"))
    status = {"privacyStatus": "private" if (privado or agendar) else "public",
              "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": True}  # voz e imagens de IA (política do YouTube)
    if agendar:
        status["publishAt"] = agendar.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    yt = build("youtube", "v3", credentials=credenciais())
    corpo = {"snippet": {"title": post["titulo"], "description": post["descricao"], "tags": post["tags"],
                         "categoryId": CATEGORIA, "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
             "status": status}
    envio = yt.videos().insert(part="snippet,status", body=corpo,
                               media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True, chunksize=8 << 20))
    resp = None
    while resp is None:
        progresso, resp = envio.next_chunk()
        if progresso:
            print(f"  enviando {progresso.progress() * 100:.0f}%", flush=True)
    vid = resp["id"]
    print(f"postado: https://youtu.be/{vid} ({status['privacyStatus']}"
          + (f", publica em {agendar:%d/%m %H:%M}" if agendar else "") + ")")
    ja[video.name] = {"id": vid, "quando": datetime.now(BRASILIA).isoformat(timespec="seconds"),
                      "status": status["privacyStatus"], "publica_em": status.get("publishAt"),
                      "titulo": post["titulo"], "tipo_titulo": cta.tipo_titulo(post["titulo"])}  # metricas_youtube.py
    POSTADOS.write_text(json.dumps(ja, ensure_ascii=False, indent=2), encoding="utf-8")
    return vid


class CotaEsgotada(Exception):
    pass


def avisos_do_video(video: Path) -> list[str]:
    """Avisos que o pipeline gravou no roteiro (imagem reprovada, animação falhou...): vídeo com aviso não sobe
    sozinho, espera revisão humana."""
    slug = video.stem.split("_", 1)[1].removesuffix("_sem-musica")
    roteiros = sorted(caminhos.PRODUCAO.glob(f"roteiros/*_{slug}.json"))
    if not roteiros:
        return ["roteiro não encontrado"]
    return json.loads(roteiros[-1].read_text(encoding="utf-8"))[0].get("_avisos", [])


def postar_pendentes(limite: int = 6) -> list[str]:
    """Sobe como PRIVADO os vídeos prontos (versão com música) sem aviso e ainda não postados, do mais antigo ao
    mais novo. Para na cota diária da API (~6 uploads). Devolve os ids postados."""
    from googleapiclient.errors import HttpError

    ja, feitos = postados(), []
    for video in sorted((caminhos.RAIZ / "videos_prontos").glob("*.mp4")):
        if len(feitos) >= limite or video.stem.endswith("_sem-musica") or video.name in ja:
            continue
        if not video.with_suffix(".txt").exists():
            continue
        avisos = avisos_do_video(video)
        if avisos:
            print(f"  NÃO subiu {video.name} (revisar): {avisos}")
            continue
        try:
            feitos.append(postar(video, privado=True))
        except HttpError as e:
            if "quota" in str(e).lower():
                print("  cota diária da API do YouTube esgotada; o resto sobe amanhã")
                break
            print(f"  falhou {video.name}: {str(e)[:300]}")
    return feitos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?", type=Path)
    ap.add_argument("--autorizar", action="store_true", help="login no Google (uma vez)")
    ap.add_argument("--agendar", help='"AAAA-MM-DD HH:MM" no horário de Brasília')
    ap.add_argument("--privado", action="store_true")
    ap.add_argument("--pendentes", action="store_true", help="sobe (privado) os vídeos prontos sem aviso ainda não postados")
    ap.add_argument("--limite", type=int, default=6, help="com --pendentes: quantos no máximo (cron de 3 em 3h usa 1)")
    args = ap.parse_args()
    if args.pendentes:
        postar_pendentes(args.limite)
        return
    if args.autorizar:
        credenciais(autorizar=True)
        print(f"autorizado; token em {TOKEN}")
        return
    if not args.video:
        ap.error("informe o vídeo")
    quando = datetime.strptime(args.agendar, "%Y-%m-%d %H:%M").replace(tzinfo=BRASILIA) if args.agendar else None
    postar(args.video, quando, args.privado)


if __name__ == "__main__":
    main()
