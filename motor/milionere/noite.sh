#!/usr/bin/env bash
# Turno da noite (cron): gera vídeo atrás de vídeo até FIM_HORA. O upload é outro cron, 1 vídeo a cada 3h
# (postar.py --pendentes --limite 1), no ritmo em que o dono publica. Vídeo com aviso não sobe: fica pra revisão.
#
#   crontab: 0 20 * * * /home/rafael/projects/milionere/milionere/motor/milionere/noite.sh
#   FIM_HORA=6 noite.sh      # para de começar vídeo novo às 6h (padrão 7h)
#   FORMATOS=historia,personagem noite.sh
set -u
RAIZ=/home/rafael/projects/milionere/milionere
cd "$RAIZ" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"  # cron não carrega o PATH do shell (claude CLI)
export XDG_RUNTIME_DIR="/run/user/$(id -u)"  # systemd-run --user (teto de RAM do ComfyUI) precisa do barramento
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export MILIONERE_COMFY_MANTER=1  # ComfyUI fica no ar entre um vídeo e outro (não espera subir a cada vídeo)
FIM_HORA=${FIM_HORA:-7}
# só formatos com histórico de aprovação: história = 12/13 roteiros aprovados e as melhores views; parábola e
# provérbio reprovavam no juiz quase sempre (24/09) e ficam fora até o roteirista deles ser ajustado de dia
FORMATOS=${FORMATOS:-historia}
PY=motor/.venv-linux/bin/python
D=producao/noite
mkdir -p "$D"
exec 9>"$D/.turno.lock"
flock -n 9 || { echo "turno já rodando"; exit 0; }
exec >>"$D/turno_$(date +%F).log" 2>&1
echo "=== turno começou $(date '+%F %T') (para às ${FIM_HORA}h)"

falhas=0
while :; do
  h=$(date +%-H)
  if [ "$h" -ge "$FIM_HORA" ] && [ "$h" -lt 20 ]; then break; fi  # janela: 20h até FIM_HORA
  echo "--- vídeo começou $(date +%T)"
  timeout 6000 "$PY" motor/milionere/lote.py --qtd 1 --musica ambas --formatos "$FORMATOS" > "$D/ultimo_video.log" 2>&1
  cat "$D/ultimo_video.log" >> "$D/videos_$(date +%F).log"  # log inteiro: toda falha precisa ser analisável
  grep -E "===|LOTE|YouTube|NÃO subiu|DESISTI|FALHOU|AVISO|custo|Traceback|Error" "$D/ultimo_video.log" | cut -c1-300
  if grep -q "hit your session limit\|api_error_status\": 429\|rate_limit" "$D/ultimo_video.log"; then
    echo "limite de uso do Claude às $(date +%T); esperando 30 min"
    sleep 1800
    continue
  fi
  if grep -q "LOTE FIM.*: 0 arquivo" "$D/ultimo_video.log" || ! grep -q "LOTE FIM" "$D/ultimo_video.log"; then
    falhas=$((falhas + 1))
    echo "vídeo falhou ($falhas seguidas); esperando 10 min"
    [ "$falhas" -ge 4 ] && { echo "4 falhas seguidas: encerrando o turno"; break; }
    sleep 600
  else
    falhas=0
  fi
done

pkill -f "[m]ain.py --listen" && echo "ComfyUI desligado (libera a RAM pro dia)"
echo "=== turno terminou $(date '+%F %T')"
