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
  baixar "$HF/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/Wan2.2-TI2V-5B-Q5_K_M.gguf" \
    models/unet/Wan2.2-TI2V-5B-Q5_K_M.gguf
  baixar "$HF/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
    models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
  baixar "$HF/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors" \
    models/vae/wan2.2_vae.safetensors
fi

echo "ComfyUI pronto em $DEST"
