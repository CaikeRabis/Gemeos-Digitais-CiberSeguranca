"""03i_medicao_populacao_completa.py

Diagnostico definitivo de COD_ID duplicados sobre a populacao completa da BDGD
para UCMT_tab e UCBT_tab, quantificando as hipoteses H1, H2, H3 e H4.
Processamento particionado em 20 baldes via hash CRC32 com estrito controle de memoria.
"""

from __future__ import annotations

import gc
import logging
import sys
import time
import zlib
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio

# Constantes de execucao
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
N_BALDES = 20
CHUNK_SIZE = 100000

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"03i_medicao_populacao_completa_{RUN_TAG}.log"
CSV_SAIDA = PROCESSED_DIR / f"populacao_ambiguos_{RUN_TAG}.csv"

COLUNAS_TOPOL = ["PAC", "RAMAL", "PN_CON", "UNI_TR_MT"]
COLUNAS_ENE = [f"ENE_{i:02d}" for i in range(1, 13)]
COLUNAS_DEM = [f"DEM_{i:02d}" for i in range(1, 13)]
COLUNAS_CONSUMO = COLUNAS_ENE + COLUNAS_DEM
COLUNAS_ALVO = ["COD_ID", "SIT_ATIV", "DAT_CON"] + COLUNAS_TOPOL + COLUNAS_CONSUMO

LAYERS = ["UCMT_tab", "UCBT_tab"]

LOGGER = logging.getLogger("03i")


def verificar_arquivos_saida() -> None:
    """Garante que nenhum arquivo com RUN_TAG ja exista antes de iniciar."""
    for caminho in (LOG_PATH, CSV_SAIDA):
        if caminho.exists():
            print(f"ERRO: Arquivo ja existente: {caminho}", file=sys.stderr)
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


def salvar_csv_sem_sobrescrever(df: pd.DataFrame, caminho: Path) -> None:
    """Grava o DataFrame em CSV usando modo exclusivo 'x' e encoding utf-8-sig."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        LOGGER.error("Tentativa de sobrescrever arquivo existente: %s", caminho)
        sys.exit(1)
    with caminho.open("x", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)


def processar_camada(gdb_path: Path, layer: str) -> dict[str, Any]:
    """Executa o pipeline completo de extracao e classificacao por baldes para uma camada."""
    t0_layer = time.time()
    LOGGER.info("================================================================================")
    LOGGER.info("INICIANDO PROCESSAMENTO DA CAMADA: %s", layer)
    LOGGER.info("================================================================================")

    info = pyogrio.read_info(gdb_path, layer=layer)
    total_features = int(info["features"])
    campos_disponiveis = set(info["fields"])
    cols_leitura = [c for c in COLUNAS_ALVO if c in campos_disponiveis]
    cols_ausentes = [c for c in COLUNAS_ALVO if c not in campos_disponiveis]

    LOGGER.info("Total de features na camada: %d", total_features)
    LOGGER.info("Colunas solicitadas que existem na camada (%d): %s", len(cols_leitura), cols_leitura)
    if cols_ausentes:
        LOGGER.info("Colunas ausentes na camada (preenchidas com default) (%d): %s", len(cols_ausentes), cols_ausentes)

    # -------------------------------------------------------------------------
    # Passo 1: Leitura exclusiva de COD_ID para identificar duplicados
    # -------------------------------------------------------------------------
    LOGGER.info("Passo 1: Identificando COD_IDs duplicados...")
    t0_passo1 = time.time()
    df_ids = pyogrio.read_dataframe(gdb_path, layer=layer, columns=["COD_ID"], read_geometry=False)
    contagens = Counter(df_ids["COD_ID"].astype(str))
    dups_set = {cid for cid, cnt in contagens.items() if cnt > 1}
    del df_ids
    del contagens
    gc.collect()

    n_duplicados = len(dups_set)
    LOGGER.info(
        "Passo 1 concluido em %.2fs: %d COD_IDs duplicados identificados.",
        time.time() - t0_passo1,
        n_duplicados,
    )

    if n_duplicados == 0:
        LOGGER.info("Nenhum COD_ID duplicado na camada %s.", layer)
        return {
            "LAYER": layer,
            "TOTAL_GRUPOS": 0,
            "R3_RESOLVIDOS": 0,
            "R3_AMBIGUOS": 0,
            "H1_COMPLEMENTAR": 0,
            "H2_SOBREPOSTO": 0,
            "H3_ZERADO_DORMENTE": 0,
            "H4_DIV_TOPOLOGICA": 0,
        }

    # Precomputar mapa de balde para os IDs duplicados (CRC32 % 20)
    dups_bucket_map = {cid: zlib.crc32(cid.encode("utf-8")) % N_BALDES for cid in dups_set}

    # -------------------------------------------------------------------------
    # Passo 2: Leitura em chunks de 100.000 linhas e distribuicao por baldes
    # -------------------------------------------------------------------------
    LOGGER.info("Passo 2: Lendo dados em chunks de %d e particionando em %d baldes...", CHUNK_SIZE, N_BALDES)
    t0_passo2 = time.time()
    baldes: dict[int, list[pd.DataFrame]] = {b: [] for b in range(N_BALDES)}
    linhas_duplicadas_lidas = 0

    for skip in range(0, total_features, CHUNK_SIZE):
        t_chk = time.time()
        chunk = pyogrio.read_dataframe(
            gdb_path,
            layer=layer,
            columns=cols_leitura,
            read_geometry=False,
            skip_features=skip,
            max_features=CHUNK_SIZE,
        )

        chunk_cod_id_str = chunk["COD_ID"].astype(str)
        mask = chunk_cod_id_str.isin(dups_set)
        qtd_chunk_dups = int(mask.sum())

        if qtd_chunk_dups > 0:
            sub_chunk = chunk.loc[mask].copy()
            sub_chunk["COD_ID"] = chunk_cod_id_str.loc[mask]
            sub_chunk["_balde"] = sub_chunk["COD_ID"].map(dups_bucket_map)

            # Preencher colunas ausentes
            for c in cols_ausentes:
                sub_chunk[c] = np.nan

            for b_idx, df_b in sub_chunk.groupby("_balde"):
                baldes[int(b_idx)].append(df_b.drop(columns=["_balde"]))

            linhas_duplicadas_lidas += qtd_chunk_dups
            del sub_chunk

        del chunk
        del chunk_cod_id_str
        del mask
        gc.collect()

        LOGGER.info(
            "Chunk features %d-%d (%.2fs): %d linhas de duplicados retidas (acumulado: %d)",
            skip,
            min(skip + CHUNK_SIZE, total_features),
            time.time() - t_chk,
            qtd_chunk_dups,
            linhas_duplicadas_lidas,
        )

    del dups_set
    del dups_bucket_map
    gc.collect()

    LOGGER.info(
        "Passo 2 concluido em %.2fs: %d linhas totais distribuidas nos %d baldes.",
        time.time() - t0_passo2,
        linhas_duplicadas_lidas,
        N_BALDES,
    )

    # -------------------------------------------------------------------------
    # Passo 3: Pipeline Logico (Por Balde, 0 a 19): R3 + Classificacao H1..H4
    # -------------------------------------------------------------------------
    LOGGER.info("Passo 3: Processando cascata R3 e hipoteses H1-H4 por balde...")
    t0_passo3 = time.time()

    total_grupos = 0
    r3_resolvidos = 0
    r3_ambiguos = 0
    h1_complementar = 0
    h2_sobreposto = 0
    h3_zerado = 0
    h4_div_topol = 0

    for b in range(N_BALDES):
        t_b = time.time()
        dfs_balde = baldes[b]
        baldes[b] = []  # Liberar referencia da lista

        if not dfs_balde:
            LOGGER.info("Balde %02d/%d: vazio.", b, N_BALDES)
            continue

        df_balde = pd.concat(dfs_balde, ignore_index=True)
        del dfs_balde
        gc.collect()

        # Converter colunas de consumo para float (nulos/vazios preenchidos com 0.0)
        df_consumo_b = pd.DataFrame(index=df_balde.index)
        for c in COLUNAS_CONSUMO:
            s = df_balde[c].astype(str).str.replace(",", ".", regex=False)
            df_consumo_b[c] = pd.to_numeric(s, errors="coerce").fillna(0.0)

        # Agrupar por COD_ID
        grupos_balde = df_balde.groupby("COD_ID", sort=False)
        n_cids_b = len(grupos_balde)
        total_grupos += n_cids_b

        b_resolvidos = 0
        b_ambiguos = 0
        b_h1 = 0
        b_h2 = 0
        b_h3 = 0
        b_h4 = 0

        for cid, g in grupos_balde:
            idx_list = g.index.tolist()
            linhas = [r._asdict() for r in g.itertuples(index=True)]

            # -----------------------------------------------------------------
            # Cascata R3:
            # 1. Filtra SIT_ATIV == 'AT'
            # 2. Se > 1, subset ativo = ats; se 0, fallback cand = todas
            # 3. Desempata por DAT_CON maxima
            # -----------------------------------------------------------------
            ats = [r for r in linhas if str(r.get("SIT_ATIV")) == "AT"]
            cand = ats if ats else linhas
            cand_datas = [
                (parse_data_br(r.get("DAT_CON")), r)
                for r in cand
                if parse_data_br(r.get("DAT_CON")) is not None
            ]

            if not cand_datas:
                # Sem datas validas -> todas as candidatas permanecem
                rem = cand
            else:
                max_d = max(d for d, _ in cand_datas)
                cand_max = [r for d, r in cand_datas if d == max_d]
                rem = cand_max

            if len(rem) == 1:
                b_resolvidos += 1
            else:
                b_ambiguos += 1
                rem_indices = [r["Index"] for r in rem]

                # -------------------------------------------------------------
                # H4: Divergencia Topologica em PAC, RAMAL, PN_CON, UNI_TR_MT
                # -------------------------------------------------------------
                sub_rem_df = df_balde.loc[rem_indices]
                div_topol = False
                for c_top in COLUNAS_TOPOL:
                    valores_distintos = set(
                        str(v).strip()
                        for v in sub_rem_df[c_top]
                        if pd.notna(v) and str(v).strip() not in ("", "<NA>", "None", "nan")
                    )
                    if len(valores_distintos) > 1:
                        div_topol = True
                        break

                if div_topol:
                    b_h4 += 1

                # -------------------------------------------------------------
                # H1, H2, H3: Analise de Consumo (24 meses de ENE e DEM)
                # -------------------------------------------------------------
                matriz_consumo = df_consumo_b.loc[rem_indices].to_numpy(dtype=float)
                # meses com consumo positivo por linha
                pos_por_linha = (matriz_consumo > 0).sum(axis=1)
                linhas_com_consumo = [
                    matriz_consumo[i] for i in range(len(rem_indices)) if pos_por_linha[i] > 0
                ]

                if len(linhas_com_consumo) == 0:
                    # Ambas/todas as linhas com 24 meses zerados -> H3 (dormente/zerado)
                    b_h3 += 1
                elif len(linhas_com_consumo) == 1:
                    # Uma linha com consumo e a(s) outra(s) com 24 meses zerados -> H3 (dormente)
                    b_h3 += 1
                else:
                    # Pelo menos 2 linhas possuem consumo positivo
                    # Avaliar sobreposicao positiva simultanea entre os pares de linhas com consumo
                    max_sobreposicao = 0
                    for i_a, i_b in combinations(range(len(linhas_com_consumo)), 2):
                        sob = int(((linhas_com_consumo[i_a] > 0) & (linhas_com_consumo[i_b] > 0)).sum())
                        if sob > max_sobreposicao:
                            max_sobreposicao = sob

                    if max_sobreposicao > 0:
                        b_h2 += 1
                    else:
                        b_h1 += 1

        r3_resolvidos += b_resolvidos
        r3_ambiguos += b_ambiguos
        h1_complementar += b_h1
        h2_sobreposto += b_h2
        h3_zerado += b_h3
        h4_div_topol += b_h4

        LOGGER.info(
            "Balde %02d/%d (%.2fs): %d CIDs | R3 Resolv=%d, Amb=%d | H1=%d, H2=%d, H3=%d, H4=%d",
            b,
            N_BALDES,
            time.time() - t_b,
            n_cids_b,
            b_resolvidos,
            b_ambiguos,
            b_h1,
            b_h2,
            b_h3,
            b_h4,
        )

        del df_balde
        del df_consumo_b
        del grupos_balde
        gc.collect()

    t_total_layer = time.time() - t0_layer
    LOGGER.info(
        "CAMADA %s CONCLUIDA EM %.2fs: Total CIDs=%d | R3: Resolv=%d, Amb=%d | H1=%d, H2=%d, H3=%d, H4=%d",
        layer,
        t_total_layer,
        total_grupos,
        r3_resolvidos,
        r3_ambiguos,
        h1_complementar,
        h2_sobreposto,
        h3_zerado,
        h4_div_topol,
    )

    return {
        "LAYER": layer,
        "TOTAL_GRUPOS": total_grupos,
        "R3_RESOLVIDOS": r3_resolvidos,
        "R3_AMBIGUOS": r3_ambiguos,
        "H1_COMPLEMENTAR": h1_complementar,
        "H2_SOBREPOSTO": h2_sobreposto,
        "H3_ZERADO_DORMENTE": h3_zerado,
        "H4_DIV_TOPOLOGICA": h4_div_topol,
    }


def main() -> None:
    verificar_arquivos_saida()
    setup_logging()

    LOGGER.info("================================================================================")
    LOGGER.info("INICIANDO SCRIPT 03i: MEDICAO POPULACIONAL COMPLETA (RUN_TAG=%s)", RUN_TAG)
    LOGGER.info("================================================================================")

    gdb_path = obter_gdb()
    LOGGER.info("Base GDB identificada: %s", gdb_path)

    resultados_layers: list[dict[str, Any]] = []

    for layer in LAYERS:
        res = processar_camada(gdb_path, layer)
        resultados_layers.append(res)

    df_resultado = pd.DataFrame(resultados_layers)
    salvar_csv_sem_sobrescrever(df_resultado, CSV_SAIDA)

    LOGGER.info("================================================================================")
    LOGGER.info("RELATORIO FINAL CONSOLIDADO (POPULACAO TOTAL)")
    LOGGER.info("================================================================================")
    for _, row in df_resultado.iterrows():
        LOGGER.info(
            "[%s] Total Grupos: %d | Resolvidos R3: %d (%.2f%%) | Ambiguos R3: %d (%.2f%%)",
            row["LAYER"],
            row["TOTAL_GRUPOS"],
            row["R3_RESOLVIDOS"],
            100.0 * row["R3_RESOLVIDOS"] / row["TOTAL_GRUPOS"] if row["TOTAL_GRUPOS"] > 0 else 0.0,
            row["R3_AMBIGUOS"],
            100.0 * row["R3_AMBIGUOS"] / row["TOTAL_GRUPOS"] if row["TOTAL_GRUPOS"] > 0 else 0.0,
        )
        if row["R3_AMBIGUOS"] > 0:
            LOGGER.info(
                "  Distribuição dos Ambíguos em %s:",
                row["LAYER"],
            )
            LOGGER.info(
                "  - H1 (Complementar): %d (%.2f%%)",
                row["H1_COMPLEMENTAR"],
                100.0 * row["H1_COMPLEMENTAR"] / row["R3_AMBIGUOS"],
            )
            LOGGER.info(
                "  - H2 (Sobreposto Diferente): %d (%.2f%%)",
                row["H2_SOBREPOSTO"],
                100.0 * row["H2_SOBREPOSTO"] / row["R3_AMBIGUOS"],
            )
            LOGGER.info(
                "  - H3 (Zerado/Dormente): %d (%.2f%%)",
                row["H3_ZERADO_DORMENTE"],
                100.0 * row["H3_ZERADO_DORMENTE"] / row["R3_AMBIGUOS"],
            )
            LOGGER.info(
                "  - H4 (Divergência Topológica): %d (%.2f%%)",
                row["H4_DIV_TOPOLOGICA"],
                100.0 * row["H4_DIV_TOPOLOGICA"] / row["R3_AMBIGUOS"],
            )

    LOGGER.info("Resultado salvo com sucesso em: %s", CSV_SAIDA)
    LOGGER.info("Log registrado em: %s", LOG_PATH)
    LOGGER.info("Script 03i finalizado com exito.")


if __name__ == "__main__":
    main()
