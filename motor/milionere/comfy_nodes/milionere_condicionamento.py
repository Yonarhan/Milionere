"""Salva/carrega CONDITIONING em disco (milionere).

Serve para rodar o text encoder (umt5 6.4GB) num prompt separado, liberar a RAM e só depois carregar o modelo
de vídeo de 7GB — com 16GB de WSL os dois juntos não cabem.
"""
import os

import torch

import folder_paths


def _caminho(nome: str) -> str:
    pasta = os.path.join(folder_paths.get_output_directory(), "condicionamento")
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, os.path.basename(nome) + ".pt")


class SalvarCondicionamento:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"conditioning": ("CONDITIONING",), "nome": ("STRING", {"default": "cond"})}}

    RETURN_TYPES = ()
    FUNCTION = "salvar"
    OUTPUT_NODE = True
    CATEGORY = "milionere"

    def salvar(self, conditioning, nome):
        torch.save(conditioning, _caminho(nome))
        return {"ui": {"condicionamento": [nome]}}


class CarregarCondicionamento:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"nome": ("STRING", {"default": "cond"})}}

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "carregar"
    CATEGORY = "milionere"

    @classmethod
    def IS_CHANGED(cls, nome):
        caminho = _caminho(nome)
        return os.path.getmtime(caminho) if os.path.exists(caminho) else float("nan")

    def carregar(self, nome):
        return (torch.load(_caminho(nome), map_location="cpu", weights_only=False),)


NODE_CLASS_MAPPINGS = {"SalvarCondicionamento": SalvarCondicionamento,
                       "CarregarCondicionamento": CarregarCondicionamento}
