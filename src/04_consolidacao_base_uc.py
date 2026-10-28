"""04_consolidacao_base_uc.py

Etapa E3: Consolidacao da Base de Unidades Consumidoras (UC) da BDGD (MT e BT).
Aplica a Regra de Deduplicacao E2:
1. Filtro Primario (Cascata R3):
   - Prioriza SIT_ATIV == 'AT'; se ausente, fallback para todas as linhas.
   - Desempata pela maxima DAT_CON.
2. Resolucao de Empates (Ambiguos):
   - Caso A (Topologia Divergente em PAC, RAMAL, PN_CON, UNI_TR_MT):
     Preserva todas as conexoes fisicas adicionando sufixo sequencial ao COD_ID (_1, _2, ...).
   - Caso B (Topologia Identica):
     Aglutina em 1 unica linha somando o consumo de 24 meses (ENE e DEM) e aplicando
     .first() para as demais colunas cadastrais.

Saidas:
- data/processed/UCMT_consolidada_{RUN_TAG}.csv
- data/processed/UCBT_consolidada_{RUN_TAG}.csv
- logs/04_consolidacao_base_uc_{RUN_TAG}.log
"""

from __future__ import annotations

import gc
import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio

# Constantes de execucao
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
CHUNK_SIZE = 100000

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"04_consolidacao_base_uc_{RUN_TAG}.log"
CSV_SAIDA_MT = PROCESSED_DIR / f"UCMT_consolidada_{RUN_TAG}.csv"
CSV_SAIDA_BT = PROCESSED_DIR / f"UCBT_consolidada_{RUN_TAG}.csv"

COLUNAS_TOPOL_PADRAO = ["PAC", "RAMAL", "PN_CON", "UNI_TR_MT"]
COLUNAS_ENE = [f"ENE_{i:02d}" for i in range(1, 13)]
COLUNAS_DEM = [f"DEM_{i:02d}" for i in range(1, 13)]
COLUNAS_CONSUMO_PADRAO = COLUNAS_ENE + COLUNAS_DEM

LOGGER = logging.getLogger("04_consolidacao")


def verificar_arquivos_saida() -> None:
    """Garante que nenhum arquivo com RUN_TAG ja exista antes de iniciar."""
    for caminho in (LOG_PATH, CSV_SAIDA_MT, CSV_SAIDA_BT):
        if caminho.exists():
            print(f"ERRO: Arquivo de saida ja existente: {caminho}", file=sys.stderr)
            sys.exit(1)


def setup_logging() -> None:
    """Configura logging simultaneo no console e em arquivo com codificacao UTF-8."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def obter_gdb() -> Path:
    """Localiza dinamicamente o arquivo .gdb dentro de data/raw/."""
    gdbs = list(RAW_DIR.glob("*.gdb"))
    if not gdbs:
        LOGGER.error("Nenhum arquivo .gdb encontrado em %s", RAW_DIR)
        sys.exit(1)
    if len(gdbs) > 1:
        LOGGER.warning("Multiplos .gdb encontrados, utilizando o primeiro: %s", gdbs[0])
    return gdbs[0]


def parse_data_br(val: Any) -> datetime | None:
    """Converte valores de data no padrao DD/MM/YYYY para datetime com seguranca."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s in ("<NA>", "None", "nan", "NaT"):
        return None
    s = s[:10]
    try:
        return datetime.strptime(s, "%d/%m/%Y")
    except (ValueError, TypeError):
        return None


def resolver_grupo_duplicados(
    cid: str,
    linhas: list[dict[str, Any]],
    cols_topol: list[str],
    cols_consumo: list[str],
) -> tuple[list[dict[str, Any]], str]:
    """Aplica a regra E2 a um grupo de linhas do mesmo COD_ID duplicado.

    Retorna: (linhas_resolvidas, classificacao_caso)
    """
    # -------------------------------------------------------------------------
    # Filtro Primario (Cascata R3):
    # 1. Prioriza SIT_ATIV == 'AT'; se ausente usa todas (fallback)
    # 2. Desempata pela maxima DAT_CON
    # -------------------------------------------------------------------------
    ats = [r for r in linhas if str(r.get("SIT_ATIV", "")).strip() == "AT"]
    cand = ats if ats else linhas

    cand_datas = [
        (parse_data_br(r.get("DAT_CON")), r)
        for r in cand
        if parse_data_br(r.get("DAT_CON")) is not None
    ]

    if not cand_datas:
        rem = cand
    else:
        max_d = max(d for d, _ in cand_datas)
        rem = [r for d, r in cand_datas if d == max_d]

    # Se restou exatamente 1 linha: caso resolvido pela cascata R3
    if len(rem) == 1:
        return [rem[0]], "R3_RESOLVIDO"

    # -------------------------------------------------------------------------
    # Resolucao de Empates (Ambiguos > 1 linha):
    # Verifica divergencia topologica (PAC, RAMAL, PN_CON, UNI_TR_MT)
    # -------------------------------------------------------------------------
    topol_diverge = False
    for c_top in cols_topol:
        valores_distintos = set(
            str(r.get(c_top, "")).strip()
            for r in rem
            if pd.notna(r.get(c_top)) and str(r.get(c_top, "")).strip() not in ("", "<NA>", "None", "nan")
        )
        if len(valores_distintos) > 1:
            topol_diverge = True
            break

    if topol_diverge:
        # Caso A (Topologia Divergente):
        # Preserva todas as conexoes fisicas adicionando sufixo sequencial ao COD_ID (_1, _2, ...)
        linhas_sufixadas: list[dict[str, Any]] = []
        for i, r in enumerate(rem, start=1):
            r_copy = dict(r)
            r_copy["COD_ID"] = f"{cid}_{i}"
            linhas_sufixadas.append(r_copy)
        return linhas_sufixadas, "CASO_A_TOPOLOGIA_DIVERGENTE"
    else:
        # Caso B (Topologia Identica):
        # Aglutina o grupo em 1 unica linha:
        # - .sum() para as colunas de consumo (ENE e DEM)
        # - .first() para as demais colunas cadastrais
        r_merged = dict(rem[0])
        for c in cols_consumo:
            val_sum = 0.0
            for r in rem:
                v = r.get(c)
                if pd.notna(v):
                    try:
                        val_sum += float(str(v).replace(",", "."))
                    except (ValueError, TypeError):
                        pass
            r_merged[c] = val_sum
        return [r_merged], "CASO_B_TOPOLOGIA_IDENTICA"


def consolidar_ucmt(gdb_path: Path) -> dict[str, Any]:
    """Processa e consolida UCMT_tab diretamente em memoria (6.275 linhas)."""
    t0 = time.time()
    LOGGER.info("================================================================================")
    LOGGER.info("INICIANDO CONSOLIDACAO DA CAMADA: UCMT_tab")
    LOGGER.info("================================================================================")

    info = pyogrio.read_info(gdb_path, layer="UCMT_tab")
    total_features = int(info["features"])
    cols_layer = list(info["fields"])
    cols_topol = [c for c in COLUNAS_TOPOL_PADRAO if c in cols_layer]
    cols_consumo = [c for c in COLUNAS_CONSUMO_PADRAO if c in cols_layer]

    LOGGER.info("UCMT_tab: %d features | %d colunas", total_features, len(cols_layer))
    LOGGER.info("Colunas topologicas avaliadas: %s", cols_topol)
    LOGGER.info("Colunas de consumo somadas em caso de empate: %s", cols_consumo)

    df_mt = pyogrio.read_dataframe(gdb_path, layer="UCMT_tab", read_geometry=False)
    contagens = Counter(df_mt["COD_ID"].astype(str))
    dups_set = {cid for cid, cnt in contagens.items() if cnt > 1}

    LOGGER.info("UCMT_tab: %d COD_IDs duplicados identificados.", len(dups_set))

    # Separar duplicados e unicos
    mask_dups = df_mt["COD_ID"].astype(str).isin(dups_set)
    df_dups = df_mt.loc[mask_dups]
    df_unicos = df_mt.loc[~mask_dups]

    # Agrupar duplicados por COD_ID
    grupos_dups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_dups.to_dict("records"):
        grupos_dups[str(r["COD_ID"]).strip()].append(r)

    linhas_resolvidas: list[dict[str, Any]] = []
    stats = Counter()

    for cid, linhas in grupos_dups.items():
        res, caso = resolver_grupo_duplicados(cid, linhas, cols_topol, cols_consumo)
        linhas_resolvidas.extend(res)
        stats[caso] += 1

    df_resolvidos = pd.DataFrame(linhas_resolvidas)[cols_layer]
    df_consolidada = pd.concat([df_unicos[cols_layer], df_resolvidos], ignore_index=True)

    # Gravar CSV consolidado
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_consolidada.to_csv(CSV_SAIDA_MT, index=False, encoding="utf-8-sig")

    t_mt = time.time() - t0
    LOGGER.info("UCMT_tab consolidada em %.2fs:", t_mt)
    LOGGER.info("  - Linhas originais: %d", total_features)
    LOGGER.info("  - Linhas unicas preservadas: %d", len(df_unicos))
    LOGGER.info("  - Grupos duplicados processados: %d", len(grupos_dups))
    LOGGER.info("    * R3 Resolvidos: %d", stats["R3_RESOLVIDO"])
    LOGGER.info("    * Caso A (Topologia Divergente): %d", stats["CASO_A_TOPOLOGIA_DIVERGENTE"])
    LOGGER.info("    * Caso B (Topologia Identica): %d", stats["CASO_B_TOPOLOGIA_IDENTICA"])
    LOGGER.info("  - Linhas geradas a partir dos duplicados: %d", len(df_resolvidos))
    LOGGER.info("  - Linhas FINAIS no arquivo CSV: %d", len(df_consolidada))
    LOGGER.info("Arquivo gravado: %s", CSV_SAIDA_MT)

    return {
        "layer": "UCMT_tab",
        "linhas_originais": total_features,
        "linhas_unicas": len(df_unicos),
        "grupos_duplicados": len(grupos_dups),
        "r3_resolvidos": stats["R3_RESOLVIDO"],
        "caso_a_topol_div": stats["CASO_A_TOPOLOGIA_DIVERGENTE"],
        "caso_b_topol_ident": stats["CASO_B_TOPOLOGIA_IDENTICA"],
        "linhas_finais": len(df_consolidada),
        "arquivo": CSV_SAIDA_MT,
    }


def consolidar_ucbt(gdb_path: Path) -> dict[str, Any]:
    """Processa e consolida UCBT_tab em chunks via pyogrio (1.310.713 linhas)."""
    t0 = time.time()
    LOGGER.info("================================================================================")
    LOGGER.info("INICIANDO CONSOLIDACAO DA CAMADA: UCBT_tab")
    LOGGER.info("================================================================================")

    info = pyogrio.read_info(gdb_path, layer="UCBT_tab")
    total_features = int(info["features"])
    cols_layer = list(info["fields"])
    cols_topol = [c for c in COLUNAS_TOPOL_PADRAO if c in cols_layer]
    cols_consumo = [c for c in COLUNAS_CONSUMO_PADRAO if c in cols_layer]

    LOGGER.info("UCBT_tab: %d features | %d colunas", total_features, len(cols_layer))
    LOGGER.info("Colunas topologicas avaliadas: %s", cols_topol)
    LOGGER.info("Colunas de consumo somadas em caso de empate: %s", cols_consumo)

    # -------------------------------------------------------------------------
    # Passo 1: Identificar COD_IDs duplicados
    # -------------------------------------------------------------------------
    LOGGER.info("UCBT_tab - Passo 1: Identificando COD_IDs duplicados...")
    t_p1 = time.time()
    df_ids = pyogrio.read_dataframe(gdb_path, layer="UCBT_tab", columns=["COD_ID"], read_geometry=False)
    contagens = Counter(df_ids["COD_ID"].astype(str))
    dups_set = {cid for cid, cnt in contagens.items() if cnt > 1}
    del df_ids
    del contagens
    gc.collect()

    n_duplicados = len(dups_set)
    LOGGER.info("UCBT_tab - Passo 1 concluido em %.2fs: %d COD_IDs duplicados identificados.", time.time() - t_p1, n_duplicados)

    # -------------------------------------------------------------------------
    # Passo 2: Extrair todas as linhas correspondentes aos duplicados
    # -------------------------------------------------------------------------
    LOGGER.info("UCBT_tab - Passo 2: Extraindo linhas de duplicados em chunks de %d...", CHUNK_SIZE)
    t_p2 = time.time()
    chunks_dups: list[pd.DataFrame] = []
    linhas_dups_coletadas = 0

    for skip in range(0, total_features, CHUNK_SIZE):
        chunk = pyogrio.read_dataframe(
            gdb_path,
            layer="UCBT_tab",
            read_geometry=False,
            skip_features=skip,
            max_features=CHUNK_SIZE,
        )
        chunk_cids = chunk["COD_ID"].astype(str)
        mask = chunk_cids.isin(dups_set)
        qtd = int(mask.sum())
        if qtd > 0:
            chunks_dups.append(chunk.loc[mask])
            linhas_dups_coletadas += qtd

        del chunk
        del chunk_cids
        del mask
        gc.collect()

    df_dups = pd.concat(chunks_dups, ignore_index=True)
    del chunks_dups
    gc.collect()

    LOGGER.info(
        "UCBT_tab - Passo 2 concluido em %.2fs: %d linhas de duplicados retidas para %d grupos.",
        time.time() - t_p2,
        len(df_dups),
        n_duplicados,
    )

    # -------------------------------------------------------------------------
    # Passo 3: Resolver os duplicados na memoria
    # -------------------------------------------------------------------------
    LOGGER.info("UCBT_tab - Passo 3: Agrupando e resolvendo duplicados na memoria...")
    t_p3 = time.time()

    grupos_dups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_dups.to_dict("records"):
        grupos_dups[str(r["COD_ID"]).strip()].append(r)

    del df_dups
    gc.collect()

    linhas_resolvidas: list[dict[str, Any]] = []
    stats = Counter()

    for cid, linhas in grupos_dups.items():
        res, caso = resolver_grupo_duplicados(cid, linhas, cols_topol, cols_consumo)
        linhas_resolvidas.extend(res)
        stats[caso] += 1

    del grupos_dups
    gc.collect()

    df_resolvidos = pd.DataFrame(linhas_resolvidas)[cols_layer]
    del linhas_resolvidas
    gc.collect()

    n_resolvidos = len(df_resolvidos)
    LOGGER.info(
        "UCBT_tab - Passo 3 concluido em %.2fs: %d grupos resolvidos em %d linhas finais:",
        time.time() - t_p3,
        n_duplicados,
        n_resolvidos,
    )
    LOGGER.info("  * R3 Resolvidos (1 linha retida): %d", stats["R3_RESOLVIDO"])
    LOGGER.info("  * Caso A (Topologia Divergente, sufixos criados): %d grupos", stats["CASO_A_TOPOLOGIA_DIVERGENTE"])
    LOGGER.info("  * Caso B (Topologia Identica, soma de consumo e .first()): %d grupos", stats["CASO_B_TOPOLOGIA_IDENTICA"])

    # -------------------------------------------------------------------------
    # Passo 4: Gravar base final: escrever Resolvidos + stream de linhas unicas
    # -------------------------------------------------------------------------
    LOGGER.info("UCBT_tab - Passo 4: Gravando arquivo final em disco...")
    t_p4 = time.time()

    # Gravar DataFrame de duplicados resolvidos com cabecalho
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_resolvidos.to_csv(CSV_SAIDA_BT, index=False, encoding="utf-8-sig", mode="w")
    del df_resolvidos
    gc.collect()

    LOGGER.info("UCBT_tab: Cabecalho e %d linhas resolvidas gravados no CSV.", n_resolvidos)

    # Re-ler a base original em chunks, filtrando apenas linhas unicas (nao duplicadas)
    linhas_unicas_gravadas = 0

    for skip in range(0, total_features, CHUNK_SIZE):
        chunk = pyogrio.read_dataframe(
            gdb_path,
            layer="UCBT_tab",
            read_geometry=False,
            skip_features=skip,
            max_features=CHUNK_SIZE,
        )
        chunk_cids = chunk["COD_ID"].astype(str)
        mask_unicos = ~chunk_cids.isin(dups_set)
        chunk_limpo = chunk.loc[mask_unicos][cols_layer]
        qtd_unicos = len(chunk_limpo)

        if qtd_unicos > 0:
            chunk_limpo.to_csv(CSV_SAIDA_BT, index=False, header=False, encoding="utf-8-sig", mode="a")
            linhas_unicas_gravadas += qtd_unicos

        del chunk
        del chunk_cids
        del mask_unicos
        del chunk_limpo
        gc.collect()

    del dups_set
    gc.collect()

    total_linhas_finais = n_resolvidos + linhas_unicas_gravadas
    t_bt = time.time() - t0

    LOGGER.info("UCBT_tab consolidada em %.2fs:", t_bt)
    LOGGER.info("  - Linhas originais: %d", total_features)
    LOGGER.info("  - Linhas unicas gravadas: %d", linhas_unicas_gravadas)
    LOGGER.info("  - Linhas resolvidas gravadas: %d", n_resolvidos)
    LOGGER.info("  - Linhas FINAIS no arquivo CSV: %d", total_linhas_finais)
    LOGGER.info("Arquivo gravado: %s", CSV_SAIDA_BT)

    return {
        "layer": "UCBT_tab",
        "linhas_originais": total_features,
        "linhas_unicas": linhas_unicas_gravadas,
        "grupos_duplicados": n_duplicados,
        "r3_resolvidos": stats["R3_RESOLVIDO"],
        "caso_a_topol_div": stats["CASO_A_TOPOLOGIA_DIVERGENTE"],
        "caso_b_topol_ident": stats["CASO_B_TOPOLOGIA_IDENTICA"],
        "linhas_finais": total_linhas_finais,
        "arquivo": CSV_SAIDA_BT,
    }


def main() -> None:
    verificar_arquivos_saida()
    setup_logging()

    LOGGER.info("================================================================================")
    LOGGER.info("INICIANDO SCRIPT 04: CONSOLIDACAO DA BASE DE UCs (RUN_TAG=%s)", RUN_TAG)
    LOGGER.info("================================================================================")

    gdb_path = obter_gdb()
    LOGGER.info("Base GDB identificada: %s", gdb_path)

    # Consolidar UCMT
    res_mt = consolidar_ucmt(gdb_path)

    # Consolidar UCBT
    res_bt = consolidar_ucbt(gdb_path)

    LOGGER.info("================================================================================")
    LOGGER.info("RESUMO FINAL DA CONSOLIDACAO (ETAPA E3 CONCLUIDA)")
    LOGGER.info("================================================================================")
    LOGGER.info(
        "UCMT: %d linhas originais -> %d linhas finais (Arquivo: %s)",
        res_mt["linhas_originais"],
        res_mt["linhas_finais"],
        res_mt["arquivo"],
    )
    LOGGER.info(
        "UCBT: %d linhas originais -> %d linhas finais (Arquivo: %s)",
        res_bt["linhas_originais"],
        res_bt["linhas_finais"],
        res_bt["arquivo"],
    )
    LOGGER.info("Processamento da Etapa E3 finalizado com sucesso absoluto.")


if __name__ == "__main__":
    main()
