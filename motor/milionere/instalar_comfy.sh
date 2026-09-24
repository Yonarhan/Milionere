#!/usr/bin/env bash
# Instala o ComfyUI + modelos de imagem para o pipeline automático (Linux/WSL com placa NVIDIA).
#
#   bash instalar_comfy.sh              -> ComfyUI + SDXL (Juggernaut) + IP-Adapter (personagens consistentes)
#   bash instalar_comfy.sh --animacao   -> também baixa o Wan 2.2 5B (GGUF) para animar cenas (movimento "ia")
#
# Pode rodar de novo: pula o que já foi baixado e retoma download interrompido.
set -euo pipefail

DEST="${COMFY_DIR:-$HOME/projects/milionere/ComfyUI}"
HF="https://huggingface.co"

baixar() {
  local url="$1" destino="$2"
  if [ -s "$destino" ]; then echo "ok  $(basename "$destino")"; return; fi
  mkdir -p "$(dirname "$destino")"
  echo "baixando $(basename "$destino")"
  curl -L --fail --retry 3 -C - -o "$destino.part" "$url"
  mv "$destino.part" "$destino"
}

if [ ! -d "$DEST/.git" ]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI "$DEST"
fi
cd "$DEST"

if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
  uv pip install --python .venv/bin/python -r requirements.txt
fi

if [ ! -d custom_nodes/ComfyUI_IPAdapter_plus ]; then
  git clone --depth 1 https://github.com/cubiq/ComfyUI_IPAdapter_plus custom_nodes/ComfyUI_IPAdapter_plus
fi

baixar "$HF/RunDiffusion/Juggernaut-XL-v9/resolve/main/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors" \
  models/checkpoints/juggernautXL_v9.safetensors
baixar "$HF/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors" \
  models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors
baixar "$HF/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors" \
  models/ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors
baixar "$HF/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors" \
  models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors

if [ "${1:-}" = "--flux" ]; then
  # Flux schnell (Apache 2.0): obedece muito melhor ação e várias pessoas que o SDXL. GGUF Q4 cabe em 8GB.
  if [ ! -d custom_nodes/ComfyUI-GGUF ]; then
    git clone --depth 1 https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
    uv pip install --python .venv/bin/python -r custom_nodes/ComfyUI-GGUF/requirements.txt
  fi
  baixar "$HF/city96/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q4_K_S.gguf" models/unet/flux1-schnell-Q4_K_S.gguf
  baixar "$HF/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors" \
    models/text_encoders/t5xxl_fp8_e4m3fn.safetensors
  baixar "$HF/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" models/text_encoders/clip_l.safetensors
  # VAE do Flux (mesmo arquivo; o repositório oficial exige login)
  baixar "$HF/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" models/vae/flux_ae.safetensors
fi

if [ "${1:-}" = "--animacao" ]; then
  if [ ! -d custom_nodes/ComfyUI-GGUF ]; then
    git clone --depth 1 https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
    uv pip install --python .venv/bin/python -r custom_nodes/ComfyUI-GGUF/requirements.txt
  fi
  # Wan 2.2 I2V 14B (GGUF Q3, 2 especialistas) + LoRA lightx2v de 4 passos: o que animar.py usa
  Q="$HF/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main"
  K="$HF/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22_Lightx2v"
  baixar "$Q/HighNoise/Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf" models/unet/Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf
  baixar "$Q/LowNoise/Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf" models/unet/Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf
  baixar "$K/Wan_2_2_I2V_A14B_HIGH_lightx2v_4step_lora_260412_rank_64_fp16.safetensors" \
    models/loras/wan22_i2v_high_lightx2v_4step.safetensors
  baixar "$K/Wan_2_2_I2V_A14B_LOW_lightx2v_4step_lora_260412_rank_64_fp16.safetensors" \
    models/loras/wan22_i2v_low_lightx2v_4step.safetensors
  baixar "$HF/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
    models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
  baixar "$HF/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" \
    models/vae/wan_2.1_vae.safetensors
  # nó do milionere: salva o texto codificado em disco (o encoder sai da RAM antes do modelo de vídeo)
  ln -sf "$(dirname "$(readlink -f "$0")")/comfy_nodes/milionere_condicionamento.py" custom_nodes/
fi

echo "ComfyUI pronto em $DEST"
