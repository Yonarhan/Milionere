#!/usr/bin/env bash
# Uma rodada da noite, em esteira: enquanto a GPU faz o vídeo N, o roteiro do vídeo N+1 é escrito em paralelo
# (pipeline --so-roteiro). Se a rodada N já tem roteiro pronto, ela pula direto para imagens + vídeo (--retomar).
# Limite de uso do Claude (429): espera 30 min e tenta de novo (até 4 vezes).
# Uso: rodada.sh <numero> <estilo>
set -u
cd /home/rafael/projects/milionere/milionere
N=$(printf "%02d" "$1"); P=$(printf "%02d" $(( 10#$1 + 1 ))); EST="$2"; D=producao/noite; F=$D/fila
PY=motor/.venv-linux/bin/python; PIPE=motor/milionere/pipeline.py
mkdir -p "$F"

# roteiro da próxima rodada, em paralelo (só LLM, não usa a GPU); pula se já existe ou se SEM_PROXIMO=1
if [ -s "$F/roteiro_$P.txt" ] || [ "${SEM_PROXIMO:-0}" = 1 ]; then BG=""; else
(
  timeout 3600 $PY $PIPE --formato historia --estilo "$EST" --so-roteiro > "$D/roteiro_$P.log" 2>&1
  grep -o 'roteiro pronto -> .*' "$D/roteiro_$P.log" | sed 's/roteiro pronto -> //' > "$F/roteiro_$P.txt"
  [ -s "$F/roteiro_$P.txt" ] || rm -f "$F/roteiro_$P.txt"
) &
BG=$!
fi

for tentativa in 1 2 3 4; do
  echo "rodada $N ($EST) tentativa $tentativa começou $(date +%T)"
  touch "$D/.inicio_$N"
  if [ -s "$F/roteiro_$N.txt" ]; then
    CMD=($PY $PIPE --retomar "$(cat "$F/roteiro_$N.txt")")
  else
    CMD=($PY $PIPE --formato historia --estilo "$EST" --qtd 1)
  fi
  timeout 6000 "${CMD[@]}" 2>&1 | tee producao/pipeline_agora.log > "$D/rodada_$N.log"
  echo "exit ${PIPESTATUS[0]}"
  if grep -q "hit your session limit\|api_error_status\": 429" "$D/rodada_$N.log"; then
    echo "limite de uso do Claude às $(date +%T); esperando 30 min"
    mv "$D/rodada_$N.log" "$D/rodada_${N}_limite_$tentativa.log"
    sleep 1800
    continue
  fi
  break
done
[ producao/comfy.log -nt "$D/.inicio_$N" ] && cp producao/comfy.log "$D/rodada_${N}_comfy.log"
EXTRA=(); [ -f "$D/roteiro_$N.log" ] && [ -s "$F/roteiro_$N.txt" ] && EXTRA=(--roteiro-log "$D/roteiro_$N.log")
[ -f "$D/rodada_$N.log" ] && $PY motor/milionere/metricas_rodada.py "$D/rodada_$N.log" --comfy "$D/rodada_${N}_comfy.log" "${EXTRA[@]}"
echo "rodada $N terminou $(date +%T); esperando o roteiro da rodada $P"
[ -n "$BG" ] && wait $BG
[ -s "$F/roteiro_$P.txt" ] && echo "roteiro $P pronto: $(cat "$F/roteiro_$P.txt")" || echo "sem roteiro $P na fila (desligado ou falhou; a rodada $P faz o roteiro completo)"
