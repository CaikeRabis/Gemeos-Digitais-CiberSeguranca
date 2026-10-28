"""analise_ambiguos_cascata.py

Analise detalhada dos 102 grupos ambiguos em UCBT_tab apos aplicacao
da regra candidata R3_cascata_AT_e_DAT_CON_MAX sobre a amostra estratificada.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Configuracao de caminhos e RUN_TAG
BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

LOG_PATH = LOGS_DIR / f"ambiguos_cascata_{RUN_TAG}.log"
CSV_LINHAS = PROCESSED_DIR / f"ambiguos_cascata_linhas_{RUN_TAG}.csv"
CSV_COLUNAS = PROCESSED_DIR / f"ambiguos_cascata_colunas_{RUN_TAG}.csv"

INPUT_CSV = PROCESSED_DIR / "amostra_grupos_duplicados_20261017_172116.csv"

LOGGER = logging.getLogger("ambiguos_cascata")


def verificar_arquivos_saida() -> None:
    """Garante que nenhum arquivo com RUN_TAG ja exista antes de iniciar."""
    for caminho in (LOG_PATH, CSV_LINHAS, CSV_COLUNAS):
        if caminho.exists():
            raise FileExistsError(f"Arquivo ja existente: {caminho}")


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


def classificar_coluna(col: str) -> str:
    """Classifica a coluna como numerica de consumo/carga ou cadastro."""
    prefixos_consumo = ("ENE_", "DEM_", "DIC_", "FIC_")
    if col.startswith(prefixos_consumo) or col == "CAR_INST":
        return "numérica de consumo/carga"
    return "cadastro"


def salvar_csv_sem_sobrescrever(df: pd.DataFrame, caminho: Path) -> None:
    """Grava o DataFrame em CSV usando modo exclusivo 'x' e encoding utf-8-sig."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        raise FileExistsError(f"Arquivo ja existente: {caminho}")
    with caminho.open("x", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)


def main() -> None:
    verificar_arquivos_saida()
    setup_logging()

    LOGGER.info("Iniciando analise de ambiguos da cascata R3 (RUN_TAG=%s)", RUN_TAG)
    LOGGER.info("Arquivo de entrada: %s", INPUT_CSV)

    if not INPUT_CSV.exists():
        LOGGER.error("Arquivo de entrada nao encontrado: %s", INPUT_CSV)
        sys.exit(1)

    # Leitura dos dados brutos com dtype=str e encoding utf-8-sig
    df_raw = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", dtype=str)
    LOGGER.info("Linhas totais no CSV de amostra: %d", len(df_raw))

    # Filtrar apenas registros de UCBT_tab
    df_bt = df_raw[df_raw["tabela_origem"] == "UCBT_tab"].copy()
    LOGGER.info("Linhas filtradas para UCBT_tab: %d", len(df_bt))

    # Agrupar por COD_ID preservando todas as colunas
    grupos_bt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_bt.to_dict("records"):
        grupos_bt[str(r["COD_ID"])].append(r)

    total_grupos = len(grupos_bt)
    LOGGER.info("Total de COD_ID distintos em UCBT_tab: %d", total_grupos)
    if total_grupos != 10000:
        LOGGER.error("Esperado 10.000 COD_ID em UCBT_tab, encontrado: %d", total_grupos)
        sys.exit(1)

    # Passo 1: Reproduzir a cascata exatamente como no script 03h
    resolvidos = 0
    ambiguos = 0
    perdidos = 0

    grupos_ambiguos: dict[str, list[dict[str, Any]]] = {}

    for cid, linhas in grupos_bt.items():
        # R3 (Cascata sem perda): prioriza AT; se ausente usa todas; desempata por DAT_CON MAX
        ats = [r for r in linhas if str(r.get("SIT_ATIV")) == "AT"]
        cand = ats if ats else linhas
        cand_datas = [
            (parse_data_br(r.get("DAT_CON")), r)
            for r in cand
            if parse_data_br(r.get("DAT_CON")) is not None
        ]
        if not cand_datas:
            ambiguos += 1
            grupos_ambiguos[cid] = cand
        else:
            max_d = max(d for d, _ in cand_datas)
            cand_max = [r for d, r in cand_datas if d == max_d]
            if len(cand_max) == 1:
                resolvidos += 1
            else:
                ambiguos += 1
                grupos_ambiguos[cid] = cand_max

    LOGGER.info(
        "Passo 1 - Validacao da Cascata: resolvidos=%d, ambiguos=%d, perdidos=%d",
        resolvidos,
        ambiguos,
        perdidos,
    )

    if (resolvidos, ambiguos, perdidos) != (9898, 102, 0):
        LOGGER.error(
            "Resultado da cascata diverge do esperado (9898, 102, 0): (%d, %d, %d)",
            resolvidos,
            ambiguos,
            perdidos,
        )
        sys.exit(1)

    LOGGER.info("Validacao confirmada com sucesso: 9.898 resolvidos, 102 ambiguos, 0 perdidos.")

    # Passo 2: Caracterizar os 102 ambiguos
    colunas_excluir = {"tabela_origem", "colunas_que_variam", "colunas_que_divergem"}
    cols_avaliar = [c for c in df_bt.columns if c not in colunas_excluir]

    grupos_sit_dat_iguais = 0
    col_divergencias: dict[str, list[int]] = defaultdict(list)
    col_valores: dict[str, list[str]] = defaultdict(list)

    linhas_saida_ambiguos: list[dict[str, Any]] = []

    for cid, rem_linhas in grupos_ambiguos.items():
        # Identificar se SIT_ATIV e DAT_CON sao iguais entre remanescentes
        sits = set(str(r.get("SIT_ATIV", "<NA>")) for r in rem_linhas)
        dats = set(str(r.get("DAT_CON", "<NA>")) for r in rem_linhas)
        if len(sits) == 1 and len(dats) == 1:
            grupos_sit_dat_iguais += 1

        # Identificar colunas que divergem neste grupo
        cols_div_grupo: list[str] = []
        for c in cols_avaliar:
            vals = [str(r.get(c, "<NA>")) for r in rem_linhas]
            n_dist = len(set(vals))
            if n_dist > 1:
                cols_div_grupo.append(c)
                col_divergencias[c].append(n_dist)
                col_valores[c].extend(vals)

        str_cols_div = ", ".join(cols_div_grupo)

        # Montar linhas para o CSV de linhas dos ambiguos
        for r in rem_linhas:
            item: dict[str, Any] = {
                "tabela_origem": r.get("tabela_origem", "UCBT_tab"),
                "COD_ID": cid,
                "colunas_que_divergem": str_cols_div,
            }
            # Adicionar demais colunas preservando a ordem original
            for c in df_bt.columns:
                if c not in ("tabela_origem", "COD_ID", "colunas_que_divergem"):
                    item[c] = r.get(c, "")
            linhas_saida_ambiguos.append(item)

    LOGGER.info(
        "Passo 2 - Grupos com SIT_ATIV e DAT_CON iguais entre remanescentes: %d de %d (%.2f%%)",
        grupos_sit_dat_iguais,
        len(grupos_ambiguos),
        100.0 * grupos_sit_dat_iguais / len(grupos_ambiguos),
    )

    # Passo 3: Comparacao de referencia (ENE_01 e DEM_01)
    ene_01_iguais = sum(
        1
        for rem in grupos_ambiguos.values()
        if len(set(str(r.get("ENE_01", "<NA>")) for r in rem)) == 1
    )
    dem_01_iguais = sum(
        1
        for rem in grupos_ambiguos.values()
        if len(set(str(r.get("DEM_01", "<NA>")) for r in rem)) == 1
    )

    LOGGER.info(
        "Passo 3 - Comparacao de Referencia:"
    )
    LOGGER.info(
        "  - Grupos com ENE_01 igual entre todas as remanescentes: %d de %d",
        ene_01_iguais,
        len(grupos_ambiguos),
    )
    LOGGER.info(
        "  - Grupos com DEM_01 igual entre todas as remanescentes: %d de %d",
        dem_01_iguais,
        len(grupos_ambiguos),
    )

    # Construir tabela resumo de colunas divergentes
    registros_colunas: list[dict[str, Any]] = []
    # Ordenar por frequencia de divergencia decrescente, depois por nome
    for col, dist_list in sorted(
        col_divergencias.items(), key=lambda x: (-len(x[1]), x[0])
    ):
        tipo = classificar_coluna(col)
        n_grupos_div = len(dist_list)
        pct_grupos = round(100.0 * n_grupos_div / len(grupos_ambiguos), 2)
        media_dist = round(sum(dist_list) / n_grupos_div, 2)
        max_dist = max(dist_list)

        # 3 valores mais frequentes entre as linhas que divergem
        top3_list = Counter(col_valores[col]).most_common(3)
        top3_str = "; ".join(f"{val} ({cnt})" for val, cnt in top3_list)

        registros_colunas.append(
            {
                "coluna": col,
                "classificacao": tipo,
                "grupos_divergentes": n_grupos_div,
                "pct_grupos_divergentes": pct_grupos,
                "distintos_media": media_dist,
                "distintos_max": max_dist,
                "top_3_valores": top3_str,
            }
        )

    df_colunas = pd.DataFrame(registros_colunas)
    df_linhas = pd.DataFrame(linhas_saida_ambiguos)

    LOGGER.info(
        "Total de colunas divergentes identificadas: %d", len(df_colunas)
    )
    LOGGER.info(
        "Total de linhas remanescentes exportadas: %d", len(df_linhas)
    )

    # Gravacao dos arquivos CSV em data/processed com encoding utf-8-sig
    salvar_csv_sem_sobrescrever(df_linhas, CSV_LINHAS)
    LOGGER.info("CSV de linhas gravado com sucesso: %s", CSV_LINHAS)

    salvar_csv_sem_sobrescrever(df_colunas, CSV_COLUNAS)
    LOGGER.info("CSV de colunas gravado com sucesso: %s", CSV_COLUNAS)

    LOGGER.info("Processamento concluido com sucesso.")


if __name__ == "__main__":
    main()
