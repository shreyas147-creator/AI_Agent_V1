"""
LLM abstraction layer.
Backends: Ollama (default, easiest) or llama.cpp via subprocess.
Switch via env var: LLM_BACKEND=ollama|llamacpp
Model: OLLAMA_MODEL or LLAMACPP_MODEL_PATH
"""

import os
import json
import subprocess
import requests
from typing import Optional
import logging

logger = logging.getLogger(__name__)

LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:2b")
LLAMACPP_PATH = os.getenv("LLAMACPP_PATH", "./llama.cpp/main")
LLAMACPP_MODEL = os.getenv("LLAMACPP_MODEL_PATH", "./models/gemma-2b-q4_k_m.gguf")
LLAMACPP_CTX = int(os.getenv("LLAMACPP_CTX", "2048"))
LLAMACPP_THREADS = int(os.getenv("LLAMACPP_THREADS", "4"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))  # seconds


class LLMClient:
    """Abstract LLM interface. Swap backends without touching orchestrator."""

    def __init__(self):
        self.backend = LLM_BACKEND
        self._loaded = False
        self._check_backend()

    def _check_backend(self):
        if self.backend == "ollama":
            try:
                r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
                if r.status_code == 200:
                    self._loaded = True
                    logger.info(f"Ollama connected. Model: {OLLAMA_MODEL}")
            except Exception:
                logger.warning("Ollama not reachable — start with: ollama serve")
        elif self.backend == "llamacpp":
            self._loaded = os.path.exists(LLAMACPP_PATH) and os.path.exists(LLAMACPP_MODEL)
            if not self._loaded:
                logger.warning(f"llama.cpp binary or model not found")
        else:
            raise ValueError(f"Unknown LLM_BACKEND: {self.backend}")

    def is_loaded(self) -> bool:
        return self._loaded

    def generate(self, system_prompt: str, user_message: str) -> str:
        """
        Returns raw string from LLM. Caller parses JSON.
        Raises RuntimeError if LLM unreachable.
        """
        if self.backend == "ollama":
            return self._generate_ollama(system_prompt, user_message)
        elif self.backend == "llamacpp":
            return self._generate_llamacpp(system_prompt, user_message)
        raise RuntimeError("No LLM backend configured")

    def _generate_ollama(self, system_prompt: str, user_message: str) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,   # near-deterministic for JSON
                "top_p": 0.9,
                "num_predict": 512,
            },
        }
        try:
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=LLM_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"]
        except requests.exceptions.Timeout:
            raise RuntimeError("LLM timed out — model may be loading, retry in a moment")
        except Exception as e:
            raise RuntimeError(f"Ollama error: {e}")

    def _generate_llamacpp(self, system_prompt: str, user_message: str) -> str:
        # Build prompt in Gemma instruct format
        prompt = (
            f"<start_of_turn>system\n{system_prompt}<end_of_turn>\n"
            f"<start_of_turn>user\n{user_message}<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )

        cmd = [
            LLAMACPP_PATH,
            "-m", LLAMACPP_MODEL,
            "-p", prompt,
            "-n", "512",
            "--temp", "0.1",
            "-c", str(LLAMACPP_CTX),
            "-t", str(LLAMACPP_THREADS),
            "--no-display-prompt",
            "-ngl", "0",  # CPU only; set > 0 for GPU layers
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=LLM_TIMEOUT,
            )
            if result.returncode != 0:
                raise RuntimeError(f"llama.cpp error: {result.stderr}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError("llama.cpp timed out")
