"""Analise de colunas divergentes e controle de duplicidades por balde de COD_ID."""

from __future__ import annotations

import logging
import sys
import zlib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyogrio

# Constantes principais
N_BALDES = 20
LOTE = 100000
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"colunas_dedup_por_balde_{RUN_TAG}.log"
CSV_COLUNAS = PROCESSED_DIR / f"colunas_divergentes_por_balde_{RUN_TAG}.csv"
CSV_CONTROLE = PROCESSED_DIR / f"controle_baldes_{RUN_TAG}.csv"

LOGGER = logging.getLogger("03g2")


def setup_logging() -> None:
    """Configura logging simultaneo em terminal e arquivo."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
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
    """Localiza o arquivo .gdb no diretorio raw."""
    gdbs = list(RAW_DIR.glob("*.gdb"))
    if len(gdbs) != 1:
        raise RuntimeError(f"Esperada exatamente 1 GDB em {RAW_DIR}, encontradas: {gdbs}")
    return gdbs[0]


def balde_cod_id(cod_id: Any, n_baldes: int = N_BALDES) -> int:
    """Calcula o indice do balde via zlib.crc32."""
    return zlib.crc32(str(cod_id).encode("utf-8")) % n_baldes


def grupo_inferido(coluna: str) -> str:
    """Classifica a coluna em grupo inferido conforme regras do projeto."""
    u = coluna.upper()
    if any(x in u for x in ("CTMT", "SUB", "PAC", "UNI_TR", "PN_CON")):
        return "vínculo de rede (inferido)"
    if "CLAS" in u or "CNAE" in u:
        return "cadastro de consumo (inferido)"
    if "CAR" in u or "DEM" in u:
        return "carga (inferido)"
    if any(x in u for x in ("SIT", "DAT", "VERS", "ATIV")):
        return "situação ou data (inferido)"
    return "outra (inferido)"


def salvar_csv_sem_sobrescrever(df: pd.DataFrame, caminho: Path) -> None:
    """Grava o DataFrame em CSV usando modo exclusivo para nao sobrescrever nada."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with caminho.open("x", encoding="utf-8", newline="") as f:
        df.to_csv(f, index=False)


def processar_camada(
    caminho_gdb: Path, camada: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Executa a contagem e agregacao por balde para a camada indicada."""
    info = pyogrio.read_info(caminho_gdb, layer=camada)
    total_features = int(info["features"])
    cols = list(info["fields"])
    id_col = "COD_ID"
    if id_col not in cols:
        raise ValueError(f"Coluna {id_col} nao encontrada em {camada}")
    cid_idx = cols.index(id_col)

    LOGGER.info("%s: iniciando Passagem 1 (leitura de %s em lotes de %d, total feicoes: %d)...",
                camada, id_col, LOTE, total_features)

    id_counts: Counter[str] = Counter()
    nulos_ou_vazios_cod_id = 0

    for n in range(0, total_features, LOTE):
        chunk = pyogrio.read_dataframe(
            caminho_gdb,
            layer=camada,
            columns=[id_col],
            read_geometry=False,
            skip_features=n,
            max_features=LOTE,
        )
        for val in chunk[id_col]:
            if pd.isna(val) or str(val).strip() in ("", "<NA>"):
                nulos_ou_vazios_cod_id += 1
            else:
                cid_str = str(val).strip()
                id_counts[cid_str] += 1

    LOGGER.info("%s: COD_ID nulos ou vazios (descartados dos baldes): %d", camada, nulos_ou_vazios_cod_id)
    LOGGER.info("%s: COD_ID distintos validos: %d", camada, len(id_counts))

    # Identifica COD_IDs repetidos e os particiona por balde
    repetidos_por_balde: dict[int, set[str]] = defaultdict(set)
    total_cids_repetidos = 0
    for cid, count in id_counts.items():
        if count > 1:
            total_cids_repetidos += 1
            b = balde_cod_id(cid, N_BALDES)
            repetidos_por_balde[b].add(cid)

    LOGGER.info("%s: total de COD_ID com repeticoes: %d", camada, total_cids_repetidos)

    # Acumuladores globais para colunas divergentes
    col_cids_variam: Counter[str] = Counter()
    col_dist_vals_sum: Counter[str] = Counter()
    col_dist_vals_max: Counter[str] = Counter()
    col_null_count: Counter[str] = Counter()
    col_total_count: Counter[str] = Counter()

    linhas_controle: list[dict[str, Any]] = []
    totais_camada = {
        "repeticoes": 0,
        "cod_id_com_linhas_divergentes": 0,
        "linhas_identicas": 0,
        "grupos_linhas_identicas": 0,
        "cod_id_distintos": len(id_counts),
        "total_features": total_features,
    }

    # Passagem 2: Processa balde a balde
    for balde in range(N_BALDES):
        rep_balde = repetidos_por_balde[balde]
        LOGGER.info("%s | Balde %02d/%02d: relendo tabela em lotes (%d COD_ID repetidos)...",
                    camada, balde, N_BALDES - 1, len(rep_balde))

        rows_by_cid: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        exact_rows: Counter[tuple[str, ...]] = Counter()

        if rep_balde:
            for n in range(0, total_features, LOTE):
                chunk = pyogrio.read_dataframe(
                    caminho_gdb,
                    layer=camada,
                    read_geometry=False,
                    skip_features=n,
                    max_features=LOTE,
                )
                mask = chunk[id_col].astype(str).isin(rep_balde)
                if not mask.any():
                    continue
                q = chunk.loc[mask].astype("string")
                for row in q.itertuples(index=False, name=None):
                    cid = str(row[cid_idx])
                    r_str = tuple("<NA>" if pd.isna(x) else str(x) for x in row)
                    rows_by_cid[cid].append(r_str)
                    exact_rows[r_str] += 1

        # Metricas do balde
        repeticoes_b = sum(len(v) - 1 for v in rows_by_cid.values())
        linhas_identicas_b = sum(c - 1 for c in exact_rows.values() if c > 1)
        grupos_identicos_b = sum(1 for c in exact_rows.values() if c > 1)

        cids_divergentes_b = 0
        balde_null = Counter()
        balde_total = Counter()

        for cid, r_list in rows_by_cid.items():
            vals_per_col: dict[str, set[str]] = defaultdict(set)
            for r in r_list:
                for idx, val in enumerate(r):
                    col_name = cols[idx]
                    vals_per_col[col_name].add(val)
                    balde_total[col_name] += 1
                    if val in ("<NA>", "", "None", "nan"):
                        balde_null[col_name] += 1

            cid_diverge = False
            for col_name, val_set in vals_per_col.items():
                if len(val_set) > 1:
                    cid_diverge = True
                    col_cids_variam[col_name] += 1
                    col_dist_vals_sum[col_name] += len(val_set)
                    if len(val_set) > col_dist_vals_max[col_name]:
                        col_dist_vals_max[col_name] = len(val_set)

            if cid_diverge:
                cids_divergentes_b += 1

        for c in cols:
            col_null_count[c] += balde_null[c]
            col_total_count[c] += balde_total[c]

        totais_camada["repeticoes"] += repeticoes_b
        totais_camada["cod_id_com_linhas_divergentes"] += cids_divergentes_b
        totais_camada["linhas_identicas"] += linhas_identicas_b
        totais_camada["grupos_linhas_identicas"] += grupos_identicos_b

        linhas_controle.append({
            "tabela": camada,
            "balde": balde,
            "cod_id_repetidos": len(rep_balde),
            "linhas_duplicadas": sum(len(v) for v in rows_by_cid.values()),
            "repeticoes": repeticoes_b,
            "cod_id_com_linhas_divergentes": cids_divergentes_b,
            "linhas_identicas_redundantes": linhas_identicas_b,
            "grupos_linhas_identicas": grupos_identicos_b,
        })

        LOGGER.info(
            "%s | Balde %02d concluido: repeticoes=%d, divergentes=%d, identicas=%d",
            camada, balde, repeticoes_b, cids_divergentes_b, linhas_identicas_b
        )

        # Descartando as estruturas do balde antes do proximo
        rows_by_cid.clear()
        exact_rows.clear()
        del rows_by_cid
        del exact_rows

    registros_colunas: list[dict[str, Any]] = []
    for c in cols:
        afetados = col_cids_variam[c]
        media_dist = round(col_dist_vals_sum[c] / afetados, 4) if afetados > 0 else 0.0
        max_dist = col_dist_vals_max[c]
        pct_nulos = round(100.0 * col_null_count[c] / col_total_count[c], 4) if col_total_count[c] > 0 else 0.0
        registros_colunas.append({
            "tabela": camada,
            "coluna": c,
            "cod_id_em_que_varia": afetados,
            "media_valores_distintos": media_dist,
            "max_valores_distintos": max_dist,
            "pct_nulos_ou_vazios_duplicatas": pct_nulos,
            "grupo_inferido": grupo_inferido(c),
        })

    return registros_colunas, linhas_controle, totais_camada


def main() -> None:
    """Ponto de entrada do processamento."""
    setup_logging()
    LOGGER.info("Iniciando analise por balde | RUN_TAG=%s", RUN_TAG)

    for path in (CSV_COLUNAS, CSV_CONTROLE):
        if path.exists():
            raise FileExistsError(f"Arquivo de saida ja existe: {path}")

    caminho_gdb = obter_gdb()
    LOGGER.info("GDB localizada: %s", caminho_gdb.name)

    todas_colunas: list[dict[str, Any]] = []
    todas_controle: list[dict[str, Any]] = []
    totais_por_tabela: dict[str, dict[str, int]] = {}

    for camada in ("UCMT_tab", "UCBT_tab"):
        cols_res, ctrl_res, totais = processar_camada(caminho_gdb, camada)
        todas_colunas.extend(cols_res)
        todas_controle.extend(ctrl_res)
        totais_por_tabela[camada] = totais

        LOGGER.info(
            "%s | Totais sobre 20 baldes: repeticoes=%d, COD_ID divergentes=%d, linhas identicas=%d",
            camada, totais["repeticoes"], totais["cod_id_com_linhas_divergentes"], totais["linhas_identicas"]
        )

    # Validacao obrigatoria
    esperado = {
        "UCMT_tab": {"repeticoes": 666, "cod_id_com_linhas_divergentes": 645, "linhas_identicas": 0},
        "UCBT_tab": {"repeticoes": 126926, "cod_id_com_linhas_divergentes": 124224, "linhas_identicas": 0},
    }

    valido = True
    for t, esp in esperado.items():
        obt = totais_por_tabela[t]
        for metrica, val_esp in esp.items():
            if obt[metrica] != val_esp:
                LOGGER.error(
                    "DIVERGENCIA em %s na metrica %s: obtido=%d, esperado=%d",
                    t, metrica, obt[metrica], val_esp
                )
                valido = False

    if not valido:
        LOGGER.error("Validacao falhou! Registros por balde em controle_baldes.")
        # Salva controle para diagnostico
        salvar_csv_sem_sobrescrever(pd.DataFrame(todas_controle), CSV_CONTROLE)
        raise RuntimeError("Validacao de repeticoes / divergencias / identicas falhou.")

    # Geracao dos CSVs
    LOGGER.info("Gravando %s...", CSV_COLUNAS.name)
    salvar_csv_sem_sobrescrever(pd.DataFrame(todas_colunas), CSV_COLUNAS)

    LOGGER.info("Gravando %s...", CSV_CONTROLE.name)
    salvar_csv_sem_sobrescrever(pd.DataFrame(todas_controle), CSV_CONTROLE)

    LOGGER.info("Processamento e validacao concluidos com sucesso | RUN_TAG=%s", RUN_TAG)


if __name__ == "__main__":
    main()
