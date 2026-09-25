#!/usr/bin/env bash
# Deixa um pod da RunPod (template "ComfyUI - CUDA 12.8") pronto para o motor, sem Network Volume: baixa só o que o
# motor usa de fato. Pode rodar de novo à vontade: o que já existe não é baixado outra vez.
#
#   bash instalar_pod.sh
#
# Depois, no PC: MILIONERE_COMFY_URL=https://<id-do-pod>-8188.proxy.runpod.net no .env (o id muda se o pod for novo).
#
# O que fica no pod (~47 GB):
#   Wan 2.2 I2V 14B fp8 + LoRA lightx2v 4 passos  -> animação (animar.py, remoto)
#   Z-Image Turbo Q6 GGUF + Qwen3 4B fp8 + VAE      -> imagens (estilos cinema_zimage e espaco_zimage)
set -euo pipefail

COMFY="${COMFY:-$(dirname "$(find / -name main.py -path '*ComfyUI/main.py' 2>/dev/null | head -1)")}"
[ -f "$COMFY/main.py" ] || { echo "ComfyUI não encontrado"; exit 1; }
cd "$COMFY"
echo "ComfyUI em: $COMFY"

# nó GGUF (o Z-Image vai em GGUF, igual ao do gospel)
if [ ! -d custom_nodes/ComfyUI-GGUF ]; then
  git clone --depth 1 https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
  pip install -q -r custom_nodes/ComfyUI-GGUF/requirements.txt
fi

baixar() {  # baixar <url> <destino>: pula se já existe com tamanho > 0
  if [ -s "$2" ]; then echo "ok   $(basename "$2")"; return; fi
  mkdir -p "$(dirname "$2")"
  echo "baixando $(basename "$2")"
  wget -q --show-progress -O "$2.parcial" "$1" && mv "$2.parcial" "$2"
}

HF=https://huggingface.co
WAN=$HF/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files
ZI=$HF/Comfy-Org/z_image_turbo/resolve/main/split_files
M=models

baixar $WAN/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors $M/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
baixar $WAN/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors  $M/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors
baixar $WAN/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors             $M/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
baixar $WAN/vae/wan_2.1_vae.safetensors                                       $M/vae/wan_2.1_vae.safetensors
baixar $WAN/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors  $M/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors
baixar $WAN/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors   $M/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors

baixar $HF/jayn7/Z-Image-Turbo-GGUF/resolve/main/z_image_turbo-Q6_K.gguf     $M/unet/z_image_turbo-Q6_K.gguf
baixar $ZI/text_encoders/qwen_3_4b_fp8_mixed.safetensors                      $M/text_encoders/qwen_3_4b_fp8_mixed.safetensors
baixar $ZI/vae/ae.safetensors                                                 $M/vae/z_image_ae.safetensors

# (re)liga o ComfyUI para carregar o nó GGUF e os modelos novos
pkill -f "ComfyUI/main.py" 2>/dev/null || pkill -f " main.py" 2>/dev/null || true
sleep 3
nohup python main.py --listen 0.0.0.0 --port 8188 > /workspace/comfy.log 2>&1 &
echo "ComfyUI subindo (log em /workspace/comfy.log)"
for _ in $(seq 1 60); do
  if curl -s -o /dev/null http://127.0.0.1:8188/system_stats; then echo "PRONTO: ComfyUI no ar"; df -h /workspace | tail -1; exit 0; fi
  sleep 2
done
echo "ComfyUI não respondeu em 2 min: veja tail -50 /workspace/comfy.log"
exit 1
