"""Painel ao vivo do pipeline: abre no navegador e mostra cada etapa trabalhando.

Lê o log do pipeline e a pasta de imagens do vídeo; não mexe em nada.

Uso:
    python monitor.py                                  # acompanha producao/pipeline_agora.log
    python monitor.py --log producao/pipeline_x.log    # outro log (rode de motor/milionere/)
Abra http://localhost:8765 no navegador (do Windows também funciona).
"""

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from caminhos import PRODUCAO  # noqa: E402

MIDIA = PRODUCAO / "midia"
LOG = PRODUCAO / "pipeline_agora.log"
LINHA = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (.*)$")


def _seg(hhmmss: str) -> int:
    h, m, s = map(int, hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def estado() -> dict:
    linhas = LOG.read_text(encoding="utf-8", errors="replace").splitlines() if LOG.exists() else []
    e = {"tema": "", "estilo": "", "inicio": None, "fase": "espera", "tentativas": [], "falas": [], "slug": None,
         "total_cenas": 0, "juiz": {"reprovadas": {}, "aprovadas": [], "refacoes": 0, "rodando": False},
         "render": [], "fim": None, "erro": None, "eventos": []}
    for bruta in linhas:
        m = LINHA.match(bruta)
        if not m:
            if "Traceback" in bruta or bruta.startswith(("RuntimeError", "Exception")) or "Error:" in bruta:
                e["erro"] = (e["erro"] or "") + bruta + "\n"
            continue
        hora, msg = m.groups()
        msg = msg.strip()
        e["eventos"].append({"hora": hora, "msg": msg.strip()})
        e["inicio"] = e["inicio"] or _seg(hora)
        e["ultimo"] = _seg(hora)
        t = e["tentativas"]
        if msg.startswith("==="):
            partes = [p.strip() for p in msg.strip("= ").split("|")]
            e["tema"] = partes[1] if len(partes) > 1 else msg
            e["estilo"] = partes[-1].replace("estilo ", "")
        elif msg.startswith("roteiro: tentativa"):
            t.append({"n": len(t) + 1, "c1": "rodando", "c2": None, "motivo": "", "notas": {}, "entendeu": ""})
            e["fase"] = "roteiro"
        elif "camada 1 reprovou" in msg and t:
            t[-1].update(c1="reprovou", motivo=msg.split(":", 1)[1].strip())
        elif "camada 1 ok" in msg and t:
            t[-1].update(c1="ok", c2="rodando")
        elif "notas do juiz" in msg and t:
            try:
                t[-1]["notas"] = json.loads(msg.split(":", 1)[1].strip().replace("'", '"'))
            except ValueError:
                pass
        elif "o juiz entendeu" in msg and t:
            t[-1]["entendeu"] = msg.split(":", 1)[1].strip()
        elif "camada 2 reprovou" in msg and t:
            t[-1].update(c2="reprovou", motivo=msg.split(":", 1)[1].strip())
        elif msg.startswith("roteiro aprovado"):
            if t:
                t[-1]["c2"] = "ok"
            e["slug"] = re.sub(r"^\d{4}-\d\d-\d\d_", "", Path(msg.split("->")[1].strip()).stem)
        elif msg.startswith("«"):
            e["falas"].append(msg.strip("«» "))
        elif msg.startswith("imagens: gerando"):
            e["fase"] = "imagens"
            e["total_cenas"] = int(re.search(r"gerando (\d+)", msg).group(1))
            e["img_inicio"] = _seg(hora)
        elif msg.startswith("camada 3"):
            e["fase"] = "juiz"
            e["juiz"]["rodando"] = True
        elif re.match(r"cena \d+ reprovada", msg):
            n = int(re.search(r"cena (\d+)", msg).group(1))
            e["juiz"]["reprovadas"][n] = msg.split(":", 1)[1].strip()
        elif re.match(r"cena \d+ aprovada", msg):
            n = int(re.search(r"cena (\d+)", msg).group(1))
            e["juiz"]["reprovadas"].pop(n, None)
            e["juiz"]["aprovadas"].append(n)
        elif msg.startswith("refação"):
            e["juiz"]["refacoes"] += 1
            e["fase"] = "refacao"
        elif "todas as imagens aprovadas" in msg or "AVISO: sobraram" in msg:
            e["juiz"]["rodando"] = False
        elif msg.startswith("render"):
            e["fase"] = "render"
            e["render"].append({"nome": msg.replace("render ", ""), "c4": None})
        elif "camada 4" in msg and e["render"]:
            e["render"][-1]["c4"] = msg.split(":", 1)[1].strip()
        elif "FALHOU o render" in msg:
            e["erro"] = msg
        elif msg.startswith("FIM"):
            e["fase"] = "fim"
            e["fim"] = msg
        elif msg.startswith("DESISTI"):
            e["fase"] = "desistiu"
            e["erro"] = msg
        elif "videos_prontos" in msg:
            e.setdefault("videos", []).append(msg.split("(+")[0].strip())
    if not e["slug"] and e["eventos"] and MIDIA.exists():
        # log sem cabeçalho (retomada antiga): a pasta de imagens mexida por último é a do vídeo em andamento
        pastas = [p for p in MIDIA.iterdir() if p.is_dir() and not p.name.startswith("_")]
        if pastas:
            e["slug"] = max(pastas, key=lambda p: p.stat().st_mtime).name
            e["tema"] = e["tema"] or e["slug"]
            e["total_cenas"] = e["total_cenas"] or len(list((MIDIA / e["slug"]).glob("cena_*.png")))
    # progresso das imagens pelos arquivos (o print do ComfyUI chega atrasado no log)
    e["imagens"] = []
    if e["slug"] and (MIDIA / e["slug"]).exists():
        pasta = MIDIA / e["slug"]
        for arq in sorted(pasta.glob("cena_*.png")) + sorted((pasta / "opcoes").glob("cena_*.png")):
            e["imagens"].append({"nome": arq.name, "opcao": arq.parent.name == "opcoes",
                                 "url": f"/img?p={arq.relative_to(MIDIA)}&v={int(arq.stat().st_mtime)}",
                                 "mtime": arq.stat().st_mtime})
    principais = [i for i in e["imagens"] if not i["opcao"]]
    if e["fase"] == "imagens" and len(principais) >= 1 and e.get("img_inicio") is not None:
        feitas = len(principais)
        media = (max(i["mtime"] for i in principais) - min(i["mtime"] for i in principais)) / max(feitas - 1, 1)
        e["media_img"] = round(media) if feitas > 1 else None
        e["eta_img"] = round(media * (e["total_cenas"] - feitas)) if feitas > 1 else None
    agora = time.localtime()
    e["agora"] = agora.tm_hour * 3600 + agora.tm_min * 60 + agora.tm_sec
    e["eventos"] = e["eventos"][-60:]
    return e


PAGINA = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pipeline ao vivo</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--tx:#e6e8ee;--mut:#8b93a7;--ok:#3fb950;--bad:#f85149;--run:#d29922;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:16px;align-items:baseline}
h1{font-size:20px;margin:0}.mut{color:var(--mut)}.big{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums}
main{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:20px;padding:20px 24px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.etapa{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:12px;border-left:4px solid var(--line)}
.etapa.run{border-left-color:var(--run)}.etapa.ok{border-left-color:var(--ok)}.etapa.bad{border-left-color:var(--bad)}
.etapa h2{font-size:16px;margin:0 0 2px;display:flex;gap:8px;align-items:center}
.explica{color:var(--mut);font-size:13px;margin:0 0 8px}
.pill{font-size:12px;padding:1px 8px;border-radius:99px;background:var(--line)}
.pill.ok{background:#1f3d27;color:var(--ok)}.pill.bad{background:#4a1e1e;color:var(--bad)}.pill.run{background:#453715;color:var(--run)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--run);animation:p 1s infinite}@keyframes p{50%{opacity:.25}}
.tent{border-top:1px dashed var(--line);padding:8px 0;font-size:14px}.tent:first-of-type{border:0}
.notas{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}.nota{font-size:12px;padding:1px 7px;border-radius:6px;background:#1c2230}
.nota.b{color:var(--bad)}
.barra{height:10px;background:var(--line);border-radius:99px;overflow:hidden;margin:6px 0}.barra i{display:block;height:100%;background:var(--acc);transition:width .5s}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;margin-top:8px}
.th{position:relative;aspect-ratio:9/16;border-radius:6px;overflow:hidden;background:#0b0d11;border:2px solid var(--line)}
.th img{width:100%;height:100%;object-fit:cover}.th span{position:absolute;left:4px;top:3px;font-size:11px;background:#000a;padding:0 5px;border-radius:4px}
.th.ok{border-color:var(--ok)}.th.bad{border-color:var(--bad)}.th.vazio{display:grid;place-items:center;color:var(--mut);font-size:12px}
.falas{margin:6px 0 0;padding-left:20px;font-size:14px}.falas li{margin:2px 0}
.feed{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;height:calc(100vh - 130px);overflow:auto;font:12.5px/1.5 ui-monospace,Consolas,monospace;position:sticky;top:20px}
.feed div{padding:2px 0;border-bottom:1px solid #1d212b}.feed .h{color:var(--mut)}.feed .r{color:var(--bad)}.feed .a{color:var(--ok)}
.erro{background:#2a1215;border:1px solid var(--bad);border-radius:10px;padding:12px;white-space:pre-wrap;font:12px ui-monospace,monospace;margin-bottom:12px}
.fim{background:#12261a;border:1px solid var(--ok);border-radius:10px;padding:14px;margin-bottom:12px}
</style></head><body>
<header><h1>🎬 Pipeline ao vivo</h1><span id="tema" class="mut"></span><span style="flex:1"></span>
<span class="mut">tempo total</span><span id="tempo" class="big">--:--</span></header>
<main><section id="etapas"></section><aside><div class="mut" style="margin-bottom:6px">Diário do pipeline (o que ele está fazendo, ao vivo)</div><div class="feed" id="feed"></div></aside></main>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const mmss=s=>s==null?'--':`${Math.floor(s/60)}:${String(Math.round(s%60)).padStart(2,'0')}`;
const pill=(st,txt)=>`<span class="pill ${st}">${txt}</span>`;
function etapa(st,titulo,explica,corpo){const d=st==='run'?'<span class="dot"></span>':st==='ok'?'✅':st==='bad'?'❌':'⏳';
 return `<div class="etapa ${st}"><h2>${d} ${titulo}</h2><p class="explica">${explica}</p>${corpo||''}</div>`}
const ORDEM=['espera','roteiro','imagens','juiz','refacao','render','fim'];
function st(e,fase){const a=ORDEM.indexOf(e.fase),b=ORDEM.indexOf(fase);if(e.fase==='desistiu')return fase==='roteiro'?'bad':'';
 if(e.fase==='fim')return 'ok';return a>b?'ok':a===b?'run':''}
async function tick(){let e;try{e=await (await fetch('/estado')).json()}catch{return}
 $('#tema').textContent=e.tema?`${e.tema} · estilo ${e.estilo}`:'aguardando o pipeline começar…';
 if(e.inicio!=null){const fimS=e.fase==='fim'||e.fase==='desistiu'?e.ultimo:e.agora;$('#tempo').textContent=mmss(fimS-e.inicio)}
 let h='';
 if(e.erro)h+=`<div class="erro"><b>Deu problema:</b>\n${esc(e.erro)}</div>`;
 if(e.fim)h+=`<div class="fim"><b>🎉 ${esc(e.fim)}</b>${(e.videos||[]).map(v=>`<div class="mut">${esc(v)}</div>`).join('')}</div>`;
 // 1 roteiro
 let c='';for(const t of e.tentativas){const c1=t.c1==='ok'?pill('ok','regras ok'):t.c1==='reprovou'?pill('bad','regras reprovaram'):pill('run','escrevendo…');
  const c2=t.c2==='ok'?pill('ok','juiz aprovou'):t.c2==='reprovou'?pill('bad','juiz reprovou'):t.c2==='rodando'?pill('run','juiz lendo…'):'';
  const notas=Object.entries(t.notas||{}).map(([k,v])=>`<span class="nota ${v<4?'b':''}">${k} ${v}/5</span>`).join('');
  c+=`<div class="tent"><b>Tentativa ${t.n}</b> ${c1} ${c2}${notas?`<div class="notas">${notas}</div>`:''}
  ${t.entendeu?`<div class="mut" style="font-size:13px">O juiz entendeu: “${esc(t.entendeu)}”</div>`:''}
  ${t.motivo?`<div style="font-size:13px;color:#f0a7a2">Por quê: ${esc(t.motivo)}</div>`:''}</div>`}
 if(e.falas.length)c+=`<b style="font-size:14px">Roteiro aprovado (${e.falas.length} cenas):</b><ol class="falas">${e.falas.map(f=>`<li>${esc(f)}</li>`).join('')}</ol>`;
 h+=etapa(st(e,'roteiro'),'1. Roteiro',
  'O Claude escreve a narração cena por cena. Camada 1 = regras automáticas (nº de palavras, palavras proibidas). Camada 2 = um segundo Claude, independente, lê como espectador e dá notas; nota < 4 ou erro bíblico = reescreve (até 4 vezes).',c);
 // 2 imagens
 const princ=e.imagens.filter(i=>!i.opcao),tot=e.total_cenas||e.falas.length||0,pct=tot?Math.min(100,princ.length/tot*100):0;
 const rep=e.juiz.reprovadas,apr=new Set(e.juiz.aprovadas);
 let g='';for(let n=1;n<=tot;n++){const im=princ.find(i=>i.nome.startsWith(`cena_${String(n).padStart(2,'0')}`));
  const cls=rep[n]?'bad':(e.fase==='fim'||apr.has(n)||(!e.juiz.rodando&&ORDEM.indexOf(e.fase)>=5))?'ok':'';
  g+=im?`<div class="th ${cls}" title="${esc(e.falas[n-1]||'')}"><img src="${im.url}"><span>${n}</span></div>`:`<div class="th vazio">${n}</div>`}
 const ops=e.imagens.filter(i=>i.opcao);
 h+=etapa(st(e,'imagens'),`2. Imagens <span class="mut" style="font-weight:400">${princ.length}/${tot}</span>`,
  'A placa de vídeo (RTX 4060) desenha uma imagem por cena no ComfyUI. Cada uma leva por volta de 50 s.',
  `<div class="barra"><i style="width:${pct}%"></i></div><div class="mut" style="font-size:13px">${e.media_img?`média ${e.media_img}s por imagem · faltam ~${mmss(e.eta_img)}`:''}</div><div class="grade">${g}</div>`);
 // 3 juiz visual
 let j=Object.entries(rep).map(([n,p])=>`<div class="tent">${pill('bad','cena '+n)} ${esc(p)}</div>`).join('');
 if(ops.length)j+=`<div class="mut" style="font-size:13px;margin-top:6px">Opções novas geradas nas refações:</div><div class="grade">${ops.map(i=>`<div class="th"><img src="${i.url}"><span>${esc(i.nome.replace('cena_','').replace('.png',''))}</span></div>`).join('')}</div>`;
 const fj=ORDEM.indexOf(e.fase)>=5?'ok':(e.fase==='juiz'||e.fase==='refacao')?'run':'';
 h+=etapa(fj,`3. Juiz visual ${e.juiz.refacoes?`<span class="mut" style="font-weight:400">· ${e.juiz.refacoes} refação(ões)</span>`:''}`,
  'Um Claude olha cada imagem: conta dedos, confere rostos e corpos, procura texto ou objeto moderno e checa se a imagem combina com a fala. Imagem reprovada ganha 3 versões novas e ele escolhe a melhor.',j);
 // 4 render
 let r=e.render.map(x=>`<div class="tent">${x.c4?pill(x.c4.includes('ok')?'ok':'bad','camada 4: '+x.c4):pill('run','montando…')} ${esc(x.nome)}</div>`).join('');
 h+=etapa(st(e,'render'),'4. Narração e montagem','Voz, legenda sincronizada e imagens com movimento são juntadas pelo ffmpeg. Saem 2 versões: com música (YouTube) e sem música (TikTok). Camada 4 = confere a duração.',r);
 $('#etapas').innerHTML=h;
 const f=$('#feed'),preso=f.scrollTop+f.clientHeight>=f.scrollHeight-20;
 f.innerHTML=e.eventos.map(x=>`<div><span class="h">${x.hora}</span> <span class="${/reprov|DESISTI|FALHOU|AVISO/.test(x.msg)?'r':/ ok|aprovad|FIM/.test(x.msg)?'a':''}">${esc(x.msg)}</span></div>`).join('');
 if(preso)f.scrollTop=f.scrollHeight}
tick();setInterval(tick,2000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _enviar(self, corpo: bytes, tipo: str):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._enviar(PAGINA.encode(), "text/html; charset=utf-8")
        elif u.path == "/estado":
            self._enviar(json.dumps(estado(), ensure_ascii=False).encode(), "application/json")
        elif u.path == "/img":
            arq = (MIDIA / parse_qs(u.query).get("p", [""])[0]).resolve()
            if arq.is_relative_to(MIDIA.resolve()) and arq.suffix == ".png" and arq.exists():
                self._enviar(arq.read_bytes(), "image/png")
            else:
                self.send_error(404)
        else:
            self.send_error(404)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=LOG)
    ap.add_argument("--porta", type=int, default=8765)
    a = ap.parse_args()
    LOG = a.log.resolve()
    print(f"painel em http://localhost:{a.porta}  (lendo {LOG})")
    ThreadingHTTPServer(("127.0.0.1", a.porta), H).serve_forever()
