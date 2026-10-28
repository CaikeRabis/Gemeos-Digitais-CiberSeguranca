#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
PROJETO: Modelos Preditivos na Rede Elétrica do DF (Distrito Federal)
ETAPA:   Higienização e Limpeza de Repositório (Pré-Deploy Vercel & Commit)
SCRIPT:  src/22_limpeza_repositorio.py
AUTOR:   Engenheiro de DevOps e Arquiteto de Software
MISSÃO:  1. Identificar e remover mapas HTML e PNG intermediários/antigos gerados
            durante as etapas de exploração e calibração das Zonas 1 e 2.
         2. Preservar estritamente o mapa oficial definitivo:
            data/processed/Dashboard_Resiliencia_DF_Definitivo.html.
         3. Limpar arquivos temporários de teste, backups (.bak) e resíduos de scratch.
         4. Emitir relatório contábil de arquivos removidos e espaço em disco liberado.
================================================================================
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OPENDSS_DIR = PROCESSED_DIR / "opendss"
SCRATCH_DIR = BASE_DIR / "scratch"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOGS_DIR / f"22_limpeza_repositorio_{RUN_TAG}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
LOGGER = logging.getLogger("LimpezaRepositorio")

# Arquivo único definitivo a ser preservado em data/processed
MAPA_DEFINITIVO_NOME = "Dashboard_Resiliencia_DF_Definitivo.html"


def executar_limpeza() -> Tuple[List[str], int]:
    """Varre e remove artefatos visuais intermediários e arquivos temporários."""
    LOGGER.info("=" * 80)
    LOGGER.info("INICIANDO PROTOCOLO DE HIGIENIZAÇÃO DO REPOSITÓRIO")
    LOGGER.info(f"Diretório Base: {BASE_DIR}")
    LOGGER.info(f"Mapa Preservado: {MAPA_DEFINITIVO_NOME}")
    LOGGER.info("=" * 80)

    arquivos_removidos: List[str] = []
    total_bytes_liberados: int = 0

    # 1. Limpeza de Mapas HTML intermediários em data/processed
    padroes_html = [
        "Mapa_Interativo_*.html",
        "Dashboard_Resiliencia_DF.html",  # Versão intermediária preliminar
    ]
    for padrao in padroes_html:
        for f in PROCESSED_DIR.glob(padrao):
            if f.name == MAPA_DEFINITIVO_NOME:
                continue
            tam = f.stat().st_size
            try:
                f.unlink()
                arquivos_removidos.append(f"data/processed/{f.name}")
                total_bytes_liberados += tam
                LOGGER.info(f"Removido HTML intermediário: {f.name} ({tam/1024:.1f} KB)")
            except Exception as e:
                LOGGER.warning(f"Não foi possível remover {f.name}: {e}")

    # 2. Limpeza de Mapas Estáticos PNG intermediários em data/processed
    padroes_png = [
        "Mapa_Auditoria_*.png",
        "mapa_topologia.png",
        "validacao_visual_subrede_hrc.png",
    ]
    for padrao in padroes_png:
        for f in PROCESSED_DIR.glob(padrao):
            tam = f.stat().st_size
            try:
                f.unlink()
                arquivos_removidos.append(f"data/processed/{f.name}")
                total_bytes_liberados += tam
                LOGGER.info(f"Removido PNG intermediário: {f.name} ({tam/1024:.1f} KB)")
            except Exception as e:
                LOGGER.warning(f"Não foi possível remover {f.name}: {e}")

    # 3. Limpeza de arquivos de backup (.bak) em opendss
    for f in OPENDSS_DIR.glob("*.bak"):
        tam = f.stat().st_size
        try:
            f.unlink()
            arquivos_removidos.append(f"opendss/{f.name}")
            total_bytes_liberados += tam
            LOGGER.info(f"Removido backup OpenDSS: {f.name} ({tam/1024:.1f} KB)")
        except Exception as e:
            LOGGER.warning(f"Não foi possível remover {f.name}: {e}")

    # 4. Limpeza de arquivos de scratch temporários
    if SCRATCH_DIR.exists():
        for f in SCRATCH_DIR.glob("*.*"):
            tam = f.stat().st_size
            try:
                f.unlink()
                arquivos_removidos.append(f"scratch/{f.name}")
                total_bytes_liberados += tam
                LOGGER.info(f"Removido arquivo de scratch: {f.name} ({tam/1024:.1f} KB)")
            except Exception as e:
                LOGGER.warning(f"Não foi possível remover {f.name}: {e}")

    mb_liberados = total_bytes_liberados / (1024.0 * 1024.0)
    LOGGER.info("=" * 80)
    LOGGER.info(f"HIGIENIZAÇÃO CONCLUÍDA: {len(arquivos_removidos)} arquivos removidos.")
    LOGGER.info(f"Espaço Total Liberado em Disco: {mb_liberados:.2f} MB ({total_bytes_liberados:,} bytes).")
    LOGGER.info("=" * 80)

    # Validar que o mapa definitivo permanece íntegro
    definitivo_path = PROCESSED_DIR / MAPA_DEFINITIVO_NOME
    if not definitivo_path.exists():
        LOGGER.critical(f"ALERTA: O mapa definitivo {MAPA_DEFINITIVO_NOME} não foi encontrado!")
    else:
        LOGGER.info(f"Integridade verificada: {definitivo_path.name} ({definitivo_path.stat().st_size:,} bytes).")

    return arquivos_removidos, total_bytes_liberados


def main() -> int:
    arquivos, bytes_liberados = executar_limpeza()
    mb = bytes_liberados / (1024.0 * 1024.0)
    print(f"""
================================================================================
               RELATÓRIO DE HIGIENIZAÇÃO DO REPOSITÓRIO
================================================================================
 Total de Arquivos Intermediários Removidos: {len(arquivos)}
 Espaço em Disco Liberado:                   {mb:.2f} MB ({bytes_liberados:,} bytes)
 Dashboard Definitivo Preservado:            {MAPA_DEFINITIVO_NOME}
================================================================================
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
