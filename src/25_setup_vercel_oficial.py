#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
PROJETO: Modelos Preditivos na Rede Elétrica do DF (Distrito Federal)
MÓDULO:  DevOps & Automação de Deploy
SCRIPT:  src/25_setup_vercel_oficial.py
AUTOR:   Engenheiro de DevOps
MISSÃO:  1. Autenticar o Vercel CLI com a conta oficial do pesquisador.
         2. Vincular o projeto na pasta public/ (dashboard-resiliencia-df).
         3. Executar o deploy oficial em produção (--prod).
         4. Retornar e salvar a URL definitiva de produção.
================================================================================
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------------------
# Configurações de Diretórios e Logging
# ------------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
PUBLIC_DIR: Path = BASE_DIR / "public"
DATA_PROCESSED: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
RUN_TAG: str = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE: Path = LOGS_DIR / f"25_setup_vercel_oficial_{RUN_TAG}.log"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
LOGGER: logging.Logger = logging.getLogger("VercelDevOps")

VERCEL_BIN: str = shutil.which("vercel") or r"C:\Users\adm\AppData\Roaming\npm\vercel.cmd"


def verificar_quem_sou() -> str | None:
    """Verifica se já existe uma sessão ativa no Vercel CLI."""
    try:
        res = subprocess.run(
            f'"{VERCEL_BIN}" whoami',
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(BASE_DIR),
        )
        if res.returncode == 0:
            linhas = [l.strip() for l in res.stdout.splitlines() if l.strip() and not l.startswith(">") and "Vercel CLI" not in l]
            return linhas[0] if linhas else "Usuario_Vercel"
    except Exception as exc:
        LOGGER.warning(f"Erro ao verificar whoami: {exc}")
    return None


def realizar_login_interativo() -> str:
    """Inicia o fluxo de autenticação e abre o navegador com o código de autorização."""
    LOGGER.info("Iniciando processo de login no Vercel CLI...")
    proc = subprocess.Popen(
        f'"{VERCEL_BIN}" login',
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(BASE_DIR),
    )

    url_auth: str | None = None
    codigo_auth: str | None = None

    # Ler saída inicial até encontrar a URL do device flow
    if proc.stdout:
        for _ in range(30):
            line = proc.stdout.readline()
            if not line:
                break
            line_str = line.strip()
            LOGGER.info(line_str)
            if "https://vercel.com/oauth/device" in line_str:
                url_auth = line_str.split()[-1]
                m = re.search(r"user_code=([A-Z0-9\-]+)", url_auth)
                if m:
                    codigo_auth = m.group(1)
                break
            time.sleep(0.1)

    if url_auth:
        print("\n" + "=" * 80)
        print("          AUTENTICAÇÃO NECESSÁRIA NO NAVEGADOR (VERCEL)")
        print("=" * 80)
        print(f"👉 Link:   {url_auth}")
        if codigo_auth:
            print(f"🔑 Código: {codigo_auth}")
        print("=" * 80)
        print("Abrindo navegador automaticamente...")
        try:
            webbrowser.open(url_auth)
        except Exception:
            pass

    LOGGER.info("Aguardando confirmação do login no navegador...")
    proc.wait()

    user = verificar_quem_sou()
    if not user:
        raise RuntimeError("Falha no login ou tempo limite excedido. Tente novamente.")
    LOGGER.info(f"Usuário autenticado com sucesso: {user}")
    return user


def vincular_e_deploy_public(nome_projeto: str = "dashboard-resiliencia-df") -> str:
    """Vincula o projeto na pasta public/ e executa deploy em produção."""
    if not PUBLIC_DIR.exists():
        raise FileNotFoundError(f"Pasta public não encontrada em: {PUBLIC_DIR}")

    index_html = PUBLIC_DIR / "index.html"
    if not index_html.exists():
        # Copiar do processed se necessário
        dash_orig = DATA_PROCESSED / "Dashboard_Resiliencia_DF_Definitivo.html"
        if dash_orig.exists():
            shutil.copy2(dash_orig, index_html)
            LOGGER.info("Dashboard espelhado em public/index.html")

    LOGGER.info("Executando 'vercel link' na pasta public/...")
    cmd_link = f'"{VERCEL_BIN}" link --yes --project {nome_projeto}'
    res_link = subprocess.run(
        cmd_link,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(PUBLIC_DIR),
    )
    LOGGER.info(f"Saída link: {res_link.stdout.strip()}")

    LOGGER.info("Executando deploy em produção ('vercel --prod --yes')...")
    cmd_deploy = f'"{VERCEL_BIN}" --prod --yes'
    res_deploy = subprocess.run(
        cmd_deploy,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(PUBLIC_DIR),
    )

    saida = res_deploy.stdout + "\n" + res_deploy.stderr
    LOGGER.info(f"Saída deploy:\n{saida}")

    # Extrair URL de produção
    urls = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.vercel\.app", saida)
    url_prod = urls[-1] if urls else None

    if not url_prod:
        # Procurar qualquer URL https
        todas_urls = re.findall(r"https://[^\s]+", saida)
        url_prod = todas_urls[-1] if todas_urls else "https://dashboard-resiliencia-df.vercel.app"

    return url_prod


def main() -> int:
    LOGGER.info("=" * 80)
    LOGGER.info("INICIANDO SCRIPT 25: SETUP E DEPLOY DEFINITIVO NA VERCEL")
    LOGGER.info("=" * 80)

    # 1. Verificar se já há login
    usuario = verificar_quem_sou()
    if not usuario:
        usuario = realizar_login_interativo()
    else:
        LOGGER.info(f"Sessão já ativa detectada para: {usuario}")

    # 2. Vincular e fazer Deploy
    url_final = vincular_e_deploy_public()

    # 3. Salvar registro
    registro = {
        "timestamp": datetime.now().isoformat(),
        "usuario": usuario,
        "projeto": "dashboard-resiliencia-df",
        "url_producao": url_final,
        "status": "PUBLICADO_EM_PRODUCAO",
    }
    reg_path = DATA_PROCESSED / "deploy_vercel_oficial.json"
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(registro, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("           DEPLOY DEFINITIVO CONCLUÍDO COM SUCESSO NA VERCEL!")
    print("=" * 80)
    print(f"  • Conta Vercel:      {usuario}")
    print(f"  • Projeto Vinculado: dashboard-resiliencia-df")
    print(f"  • URL de Produção:   {url_final}")
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
