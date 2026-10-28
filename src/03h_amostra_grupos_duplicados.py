"""03h_amostra_grupos_duplicados.py

Amostra linhas completas de COD_ID repetidos em UCMT_tab e UCBT_tab,
para analise de parcelas de consumo vs versoes de cadastro e avaliacao
de regras candidatas de desempate sem escolha de regra definitiva.
"""

from __future__ import annotations

import logging
import random
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyogrio

# Constantes de execucao
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
N_BALDES = 20
LOTE = 100000
AMOSTRA_BALDE = 500
SEED = 42

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"amostra_grupos_duplicados_{RUN_TAG}.log"
CSV_AMOSTRA = PROCESSED_DIR / f"amostra_grupos_duplicados_{RUN_TAG}.csv"
CSV_COMBINACOES = PROCESSED_DIR / f"combinacoes_valores_{RUN_TAG}.csv"
CSV_REGRAS = PROCESSED_DIR / f"regras_candidatas_amostra_{RUN_TAG}.csv"
CSV_CONTROLE = PROCESSED_DIR / f"controle_amostra_{RUN_TAG}.csv"

LOGGER = logging.getLogger("03h")


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
    """Retorna o caminho unico da base GDB presente no diretorio raw."""
    gdbs = list(RAW_DIR.glob("*.gdb"))
    if len(gdbs) != 1:
        raise RuntimeError(f"Esperada exatamente 1 GDB em {RAW_DIR}, encontradas: {gdbs}")
    return gdbs[0]


def salvar_csv_sem_sobrescrever(df: pd.DataFrame, caminho: Path) -> None:
    """Grava o DataFrame em CSV usando modo exclusivo 'x' e encoding utf-8-sig."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        raise FileExistsError(f"Arquivo ja existente: {caminho}")
    with caminho.open("x", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)


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


def formatar_tabela_lado_a_lado(
    tabela: str,
    cod_id: str,
    linhas_df: pd.DataFrame,
    colunas: list[str],
    colunas_var: list[str],
) -> str:
    """Monta representacao textual com as colunas e linhas do grupo duplicado lado a lado."""
    n_linhas = len(linhas_df)
    blocos = [
        "=" * 105,
        f"AMOSTRA GRUPO DUPLICADO [{tabela}] | COD_ID: {cod_id} ({n_linhas} linhas na origem)",
        f"Colunas que variam ({len(colunas_var)}): {', '.join(colunas_var) if colunas_var else 'Nenhuma'}",
        "-" * 105,
    ]

    col_w = 18
    val_w = 24
    status_w = 12

    headers = ["COLUNA"] + [f"LINHA {i + 1}" for i in range(n_linhas)] + ["STATUS"]
    cabecalho = f"{headers[0]:<{col_w}} | " + " | ".join(f"{h:<{val_w}}" for h in headers[1:-1]) + f" | {headers[-1]:<{status_w}}"
    blocos.append(cabecalho)
    blocos.append("-" * 105)

    for c in colunas:
        valores = [
            str(linhas_df.iloc[i][c]) if not pd.isna(linhas_df.iloc[i][c]) else "<NA>"
            for i in range(n_linhas)
        ]
        status = "* DIVERGE *" if c in colunas_var else "IGUAL"
        linha_txt = (
            f"{c:<{col_w}} | "
            + " | ".join(f"{v[:val_w]:<{val_w}}" for v in valores)
            + f" | {status:<{status_w}}"
        )
        blocos.append(linha_txt)

    blocos.append("=" * 105 + "\n")
    return "\n".join(blocos)


def passo_1_leitura_metadados(
    gdb: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, str]]:
    """Passo 1: Le metadados, mapeia colunas citadas case-insensitively e testa DAT_CON."""
    LOGGER.info("=== PASSO 1: Leitura de Metadados e Mapeamento de Colunas ===")
    info_mt = pyogrio.read_info(gdb, layer="UCMT_tab")
    info_bt = pyogrio.read_info(gdb, layer="UCBT_tab")

    cols_mt = list(info_mt["fields"])
    cols_bt = list(info_bt["fields"])

    LOGGER.info("UCMT_tab: %d colunas, %d feicoes", len(cols_mt), int(info_mt["features"]))
    LOGGER.info("UCBT_tab: %d colunas, %d feicoes", len(cols_bt), int(info_bt["features"]))

    colunas_citadas = [
        "COD_ID", "PAC", "RAMAL", "PN_CON", "UNI_TR_MT", "CTMT", "SUB",
        "ENE_01", "ENE_02", "ENE_03", "ENE_04", "ENE_05", "ENE_06",
        "ENE_07", "ENE_08", "ENE_09", "ENE_10", "ENE_11", "ENE_12",
        "DIC_01", "FIC_01", "DEM_01", "DEM_CONT", "SIT_ATIV", "DAT_CON",
        "CLAS_SUB", "CAR_INST",
    ]

    map_mt: dict[str, str] = {}
    map_bt: dict[str, str] = {}
    mt_upper = {c.upper(): c for c in cols_mt}
    bt_upper = {c.upper(): c for c in cols_bt}

    for col in colunas_citadas:
        u = col.upper()
        if u in mt_upper:
            map_mt[col] = mt_upper[u]
        if u in bt_upper:
            map_bt[col] = bt_upper[u]

    LOGGER.info("Mapeamento case-insensitive para UCMT_tab (%d colunas mapeadas): %s", len(map_mt), map_mt)
    LOGGER.info("Mapeamento case-insensitive para UCBT_tab (%d colunas mapeadas): %s", len(map_bt), map_bt)

    # Teste de conversao de DAT_CON
    df_dat_mt = pyogrio.read_dataframe(
        gdb, layer="UCMT_tab", columns=["DAT_CON"], read_geometry=False
    )
    dt_mt_test = pd.to_datetime(df_dat_mt["DAT_CON"], errors="coerce", dayfirst=True)
    nat_mt = int(dt_mt_test.isna().sum())
    valid_mt = len(df_dat_mt) - nat_mt
    LOGGER.info(
        "Teste conversao DAT_CON em UCMT_tab: %d valores validos, %d valores nao convertem (NaT/nulo) em %d linhas",
        valid_mt, nat_mt, len(df_dat_mt)
    )

    df_dat_bt = pyogrio.read_dataframe(
        gdb, layer="UCBT_tab", columns=["DAT_CON"], read_geometry=False, max_features=100000
    )
    dt_bt_test = pd.to_datetime(df_dat_bt["DAT_CON"], errors="coerce", dayfirst=True)
    nat_bt = int(dt_bt_test.isna().sum())
    valid_bt = len(df_dat_bt) - nat_bt
    LOGGER.info(
        "Teste conversao DAT_CON em UCBT_tab (lote 100k): %d validos, %d nao convertem (NaT/nulo) em %d linhas",
        valid_bt, nat_bt, len(df_dat_bt)
    )

    return info_mt, info_bt, map_mt, map_bt


def passo_2_amostra_ucmt(
    gdb: Path, cols_mt: list[str]
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    """Passo 2: Carrega UCMT_tab, sorteia 5 COD_ID repetidos e imprime lado a lado."""
    LOGGER.info("=== PASSO 2: Amostra de Linhas Completas em UCMT_tab ===")
    df_mt = pyogrio.read_dataframe(gdb, layer="UCMT_tab", read_geometry=False).astype(str)

    vc_mt = df_mt["COD_ID"].value_counts()
    rep_ids_mt = sorted(vc_mt[vc_mt > 1].index.tolist())
    LOGGER.info("UCMT_tab: total de COD_ID repetidos/divergentes: %d", len(rep_ids_mt))

    rng = random.Random(SEED)
    amostra_5_mt = sorted(rng.sample(rep_ids_mt, 5))
    LOGGER.info("UCMT_tab: 5 COD_ID sorteados para inspecao detalhada: %s", amostra_5_mt)

    # Identificar colunas que variam para cada COD_ID repetido de UCMT
    df_mt_rep = df_mt[df_mt["COD_ID"].isin(rep_ids_mt)].copy()
    registros_amostra_csv: list[dict[str, Any]] = []

    print("\n" + "#" * 105)
    print("IMPRESSAO PASSO 2: 5 GRUPOS COMPLETOS DE COD_ID REPETIDOS EM UCMT_tab (COLUNAS LADO A LADO)")
    print("#" * 105)

    grupos_mt_dict: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in df_mt_rep.to_dict("records"):
        grupos_mt_dict[str(row["COD_ID"])].append(row)

    for cid in rep_ids_mt:
        linhas = grupos_mt_dict[cid]
        sub_df = pd.DataFrame(linhas)
        cols_var = [c for c in cols_mt if sub_df[c].nunique(dropna=False) > 1]
        str_cols_var = ", ".join(cols_var)

        if cid in amostra_5_mt:
            txt_bloco = formatar_tabela_lado_a_lado("UCMT_tab", cid, sub_df, cols_mt, cols_var)
            print(txt_bloco)

        for _, r in sub_df.iterrows():
            item = {
                "tabela_origem": "UCMT_tab",
                "COD_ID": cid,
                "colunas_que_variam": str_cols_var,
            }
            for c in cols_mt:
                item[c] = r[c]
            registros_amostra_csv.append(item)

    return df_mt_rep, registros_amostra_csv, amostra_5_mt


def passo_3_amostra_ucbt_por_balde(
    gdb: Path, total_features_bt: int, cols_bt: list[str]
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Passo 3: Amostra de linhas completas em UCBT_tab por 20 baldes via crc32."""
    LOGGER.info("=== PASSO 3: Amostra de Linhas Completas em UCBT_tab por Balde ===")
    LOGGER.info("Configuracao: N_BALDES=%d, LOTE=%d, AMOSTRA_BALDE=%d, SEED=%d",
                N_BALDES, LOTE, AMOSTRA_BALDE, SEED)

    linhas_controle: list[dict[str, Any]] = []
    amostras_por_balde: dict[int, list[str]] = {}
    todos_ids_amostrados: list[str] = []

    # Processamento balde a balde
    for k in range(N_BALDES):
        t0 = time.time()
        counter_k: Counter[str] = Counter()
        linhas_lidas_k = 0

        for n in range(0, total_features_bt, LOTE):
            chunk = pyogrio.read_dataframe(
                gdb,
                layer="UCBT_tab",
                columns=["COD_ID"],
                read_geometry=False,
                skip_features=n,
                max_features=LOTE,
            )
            linhas_lidas_k += len(chunk)
            vals = chunk["COD_ID"].dropna().astype(str).tolist()
            for c_str in vals:
                c_str = c_str.strip()
                if c_str and (zlib.crc32(c_str.encode("utf-8")) % N_BALDES) == k:
                    counter_k[c_str] += 1

        repetidos_k = sorted([cid for cid, count in counter_k.items() if count > 1])
        n_sortear = min(AMOSTRA_BALDE, len(repetidos_k))
        sorteados_k = sorted(random.Random(SEED).sample(repetidos_k, n_sortear))

        t_balde = round(time.time() - t0, 2)
        amostras_por_balde[k] = sorteados_k
        todos_ids_amostrados.extend(sorteados_k)

        linhas_controle.append({
            "balde": k,
            "linhas_lidas": linhas_lidas_k,
            "COD_ID_repetidos_no_balde": len(repetidos_k),
            "COD_ID_amostrados": len(sorteados_k),
            "tempo_s": t_balde,
        })

        LOGGER.info(
            "Balde %02d/%02d concluido: %d repetidos, %d amostrados, tempo=%.2fs",
            k, N_BALDES - 1, len(repetidos_k), len(sorteados_k), t_balde
        )

        # Descarte das estruturas do balde antes do proximo
        counter_k.clear()
        repetidos_k.clear()
        del counter_k
        del repetidos_k

    # Validacao de soma da amostra
    total_sorteados = len(todos_ids_amostrados)
    set_sorteados = set(todos_ids_amostrados)
    LOGGER.info("Verificacao da soma: total amostrados = %d, distintos = %d", total_sorteados, len(set_sorteados))
    if total_sorteados != 10000 or len(set_sorteados) != 10000:
        raise RuntimeError(
            f"Erro na soma da amostra de UCBT: esperado 10000 IDs disjuntos, obtido {total_sorteados} (distintos: {len(set_sorteados)})"
        )

    # Releitura da tabela completa em lotes para os 10.000 IDs sorteados
    LOGGER.info("Releitura da tabela UCBT_tab completa em lotes para extrair linhas dos 10.000 IDs...")
    t_releitura = time.time()
    chunks_amostra: list[pd.DataFrame] = []

    for n in range(0, total_features_bt, LOTE):
        chunk_full = pyogrio.read_dataframe(
            gdb,
            layer="UCBT_tab",
            read_geometry=False,
            skip_features=n,
            max_features=LOTE,
        )
        mask = chunk_full["COD_ID"].astype(str).isin(set_sorteados)
        if mask.any():
            chunks_amostra.append(chunk_full.loc[mask].astype(str))

    df_bt_sample = pd.concat(chunks_amostra, ignore_index=True)
    t_total_releitura = round(time.time() - t_releitura, 2)
    LOGGER.info("Releitura concluida em %.2fs: %d linhas carregadas para os 10.000 COD_ID",
                t_total_releitura, len(df_bt_sample))

    # Sorteio de 5 grupos para impressao como no Passo 2
    amostra_5_bt = sorted(random.Random(SEED).sample(sorted(set_sorteados), 5))
    LOGGER.info("UCBT_tab: 5 COD_ID sorteados para impressao detalhada: %s", amostra_5_bt)

    print("\n" + "#" * 105)
    print("IMPRESSAO PASSO 3: 5 GRUPOS COMPLETOS DE COD_ID REPETIDOS EM UCBT_tab (COLUNAS LADO A LADO)")
    print("#" * 105)

    grupos_bt_dict: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in df_bt_sample.to_dict("records"):
        grupos_bt_dict[str(row["COD_ID"])].append(row)

    registros_amostra_bt_csv: list[dict[str, Any]] = []

    for cid, linhas in grupos_bt_dict.items():
        sub_df = pd.DataFrame(linhas)
        cols_var = [c for c in cols_bt if sub_df[c].nunique(dropna=False) > 1]
        str_cols_var = ", ".join(cols_var)

        if cid in amostra_5_bt:
            txt_bloco = formatar_tabela_lado_a_lado("UCBT_tab", cid, sub_df, cols_bt, cols_var)
            print(txt_bloco)

        for _, r in sub_df.iterrows():
            item = {
                "tabela_origem": "UCBT_tab",
                "COD_ID": cid,
                "colunas_que_variam": str_cols_var,
            }
            for c in cols_bt:
                item[c] = r[c]
            registros_amostra_bt_csv.append(item)

    return df_bt_sample, registros_amostra_bt_csv, linhas_controle, amostra_5_bt


def passo_4_combinacoes_valores(
    df_mt_rep: pd.DataFrame,
    df_bt_rep: pd.DataFrame,
    cols_mt: list[str],
    cols_bt: list[str],
) -> list[dict[str, Any]]:
    """Passo 4: Contagens de combinacoes (SIT_ATIV, DAT_CON, CLAS_SUB) e variacao por coluna."""
    LOGGER.info("=== PASSO 4: Contagem de Combinacoes de Valores e Variacao por Coluna ===")
    registros_comb: list[dict[str, Any]] = []

    # 4.1 UCMT_tab (645 COD_ID divergentes)
    grupos_mt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_mt_rep.to_dict("records"):
        grupos_mt[str(r["COD_ID"])].append(r)
    n_mt_cids = len(grupos_mt)

    sit_vals_mt = Counter(df_mt_rep["SIT_ATIV"].tolist())
    for sit_v, cnt in sorted(sit_vals_mt.items(), key=lambda x: -x[1]):
        pct = round(100.0 * cnt / len(df_mt_rep), 2)
        registros_comb.append({
            "tabela": "UCMT_tab",
            "tipo_analise": "contagem_linhas_sit_ativ",
            "chave": sit_v,
            "contagem": cnt,
            "total_referencia": len(df_mt_rep),
            "proporcao_pct": pct,
        })

    # Combinacoes de SIT_ATIV, DAT_CON, CLAS_SUB em UCMT
    comb_mt_counter: Counter[str] = Counter()
    for cid, linhas in grupos_mt.items():
        sits = tuple(sorted(str(r.get("SIT_ATIV", "<NA>")) for r in linhas))
        dats = tuple(sorted(str(r.get("DAT_CON", "<NA>")) for r in linhas))
        clas = tuple(sorted(str(r.get("CLAS_SUB", "<NA>")) for r in linhas))
        dat_var = "DAT_VARIA" if len(set(dats)) > 1 else "DAT_IGUAL"
        clas_var = "CLAS_VARIA" if len(set(clas)) > 1 else "CLAS_IGUAL"
        chave = f"SIT={sits} | {dat_var} | {clas_var}"
        comb_mt_counter[chave] += 1

    for chave, cnt in comb_mt_counter.most_common():
        pct = round(100.0 * cnt / n_mt_cids, 2)
        registros_comb.append({
            "tabela": "UCMT_tab",
            "tipo_analise": "combinacao_sit_dat_clas",
            "chave": chave,
            "contagem": cnt,
            "total_referencia": n_mt_cids,
            "proporcao_pct": pct,
        })

    # Proporcao de COD_ID em que cada coluna varia em UCMT
    for c in cols_mt:
        cnt_var = sum(1 for cid, linhas in grupos_mt.items() if len(set(r.get(c, "<NA>") for r in linhas)) > 1)
        pct = round(100.0 * cnt_var / n_mt_cids, 2)
        registros_comb.append({
            "tabela": "UCMT_tab",
            "tipo_analise": "proporcao_cod_id_coluna_varia",
            "chave": c,
            "contagem": cnt_var,
            "total_referencia": n_mt_cids,
            "proporcao_pct": pct,
        })

    # 4.2 UCBT_tab (amostra de 10.000 COD_ID)
    grupos_bt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_bt_rep.to_dict("records"):
        grupos_bt[str(r["COD_ID"])].append(r)
    n_bt_cids = len(grupos_bt)

    sit_vals_bt = Counter(df_bt_rep["SIT_ATIV"].tolist())
    for sit_v, cnt in sorted(sit_vals_bt.items(), key=lambda x: -x[1]):
        pct = round(100.0 * cnt / len(df_bt_rep), 2)
        registros_comb.append({
            "tabela": "UCBT_tab",
            "tipo_analise": "contagem_linhas_sit_ativ",
            "chave": sit_v,
            "contagem": cnt,
            "total_referencia": len(df_bt_rep),
            "proporcao_pct": pct,
        })

    comb_bt_counter: Counter[str] = Counter()
    for cid, linhas in grupos_bt.items():
        sits = tuple(sorted(str(r.get("SIT_ATIV", "<NA>")) for r in linhas))
        dats = tuple(sorted(str(r.get("DAT_CON", "<NA>")) for r in linhas))
        dat_var = "DAT_VARIA" if len(set(dats)) > 1 else "DAT_IGUAL"
        chave = f"SIT={sits} | {dat_var}"
        comb_bt_counter[chave] += 1

    for chave, cnt in comb_bt_counter.most_common():
        pct = round(100.0 * cnt / n_bt_cids, 2)
        registros_comb.append({
            "tabela": "UCBT_tab",
            "tipo_analise": "combinacao_sit_dat",
            "chave": chave,
            "contagem": cnt,
            "total_referencia": n_bt_cids,
            "proporcao_pct": pct,
        })

    for c in cols_bt:
        cnt_var = sum(1 for cid, linhas in grupos_bt.items() if len(set(r.get(c, "<NA>") for r in linhas)) > 1)
        pct = round(100.0 * cnt_var / n_bt_cids, 2)
        registros_comb.append({
            "tabela": "UCBT_tab",
            "tipo_analise": "proporcao_cod_id_coluna_varia",
            "chave": c,
            "contagem": cnt_var,
            "total_referencia": n_bt_cids,
            "proporcao_pct": pct,
        })

    return registros_comb


def avaliar_regras_candidatas(
    tabela: str, grupos_dict: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Passo 5: Avalia resolucao por regra candidata (resolvidos, ambiguos, perdidos)."""
    n_total = len(grupos_dict)
    # Identificar valores distintos observados de SIT_ATIV
    todos_sit = sorted(
        {
            str(r.get("SIT_ATIV", "")).strip()
            for linhas in grupos_dict.values()
            for r in linhas
            if str(r.get("SIT_ATIV", "")).strip() not in ("", "<NA>", "None", "nan")
        }
    )

    # Dicionario de acumuladores por regra
    # regras: R1 para cada valor distinto, R2, R3 (ordens aplicaveis), R4
    resultados: dict[str, dict[str, int]] = defaultdict(lambda: {"resolvidos": 0, "ambiguos": 0, "perdidos": 0})

    for cid, linhas in grupos_dict.items():
        # R1: para cada valor distinto observado de SIT_ATIV
        for v in todos_sit:
            regra_nome = f"R1_SIT_ATIV_{v}"
            filtradas = [r for r in linhas if str(r.get("SIT_ATIV")) == v]
            if len(filtradas) == 1:
                resultados[regra_nome]["resolvidos"] += 1
            elif len(filtradas) > 1:
                resultados[regra_nome]["ambiguos"] += 1
            else:
                resultados[regra_nome]["perdidos"] += 1

        # R2: manter a linha com DAT_CON maxima (apos conversao)
        datas = [(parse_data_br(r.get("DAT_CON")), r) for r in linhas]
        datas_validas = [(d, r) for d, r in datas if d is not None]
        if not datas_validas:
            resultados["R2_DAT_CON_MAX"]["perdidos"] += 1
        else:
            max_d = max(d for d, _ in datas_validas)
            linhas_max_d = [r for d, r in datas_validas if d == max_d]
            if len(linhas_max_d) == 1:
                resultados["R2_DAT_CON_MAX"]["resolvidos"] += 1
            elif len(linhas_max_d) > 1:
                resultados["R2_DAT_CON_MAX"]["ambiguos"] += 1
            else:
                resultados["R2_DAT_CON_MAX"]["perdidos"] += 1

        # R3 (Ordem A): R1(AT) entao R2(DAT_CON MAX)
        ats = [r for r in linhas if str(r.get("SIT_ATIV")) == "AT"]
        if len(ats) == 0:
            resultados["R3_SIT_ATIV_AT_entao_DAT_CON_MAX"]["perdidos"] += 1
        elif len(ats) == 1:
            resultados["R3_SIT_ATIV_AT_entao_DAT_CON_MAX"]["resolvidos"] += 1
        else:
            at_datas = [(parse_data_br(r.get("DAT_CON")), r) for r in ats if parse_data_br(r.get("DAT_CON")) is not None]
            if not at_datas:
                resultados["R3_SIT_ATIV_AT_entao_DAT_CON_MAX"]["ambiguos"] += 1
            else:
                max_d = max(d for d, _ in at_datas)
                linhas_at_max = [r for d, r in at_datas if d == max_d]
                if len(linhas_at_max) == 1:
                    resultados["R3_SIT_ATIV_AT_entao_DAT_CON_MAX"]["resolvidos"] += 1
                else:
                    resultados["R3_SIT_ATIV_AT_entao_DAT_CON_MAX"]["ambiguos"] += 1

        # R3 (Ordem B): R2(DAT_CON MAX) entao R1(AT)
        if not datas_validas:
            resultados["R3_DAT_CON_MAX_entao_SIT_ATIV_AT"]["perdidos"] += 1
        else:
            max_d = max(d for d, _ in datas_validas)
            linhas_max_d = [r for d, r in datas_validas if d == max_d]
            if len(linhas_max_d) == 1:
                resultados["R3_DAT_CON_MAX_entao_SIT_ATIV_AT"]["resolvidos"] += 1
            else:
                ats_no_empate = [r for r in linhas_max_d if str(r.get("SIT_ATIV")) == "AT"]
                if len(ats_no_empate) == 1:
                    resultados["R3_DAT_CON_MAX_entao_SIT_ATIV_AT"]["resolvidos"] += 1
                elif len(ats_no_empate) > 1:
                    resultados["R3_DAT_CON_MAX_entao_SIT_ATIV_AT"]["ambiguos"] += 1
                else:
                    resultados["R3_DAT_CON_MAX_entao_SIT_ATIV_AT"]["perdidos"] += 1

        # R3 (Cascata sem perda): prioriza AT; se ausente usa todas; desempata por DAT_CON MAX
        cand = ats if ats else linhas
        cand_datas = [(parse_data_br(r.get("DAT_CON")), r) for r in cand if parse_data_br(r.get("DAT_CON")) is not None]
        if not cand_datas:
            resultados["R3_cascata_AT_e_DAT_CON_MAX"]["ambiguos"] += 1
        else:
            max_d = max(d for d, _ in cand_datas)
            cand_max = [r for d, r in cand_datas if d == max_d]
            if len(cand_max) == 1:
                resultados["R3_cascata_AT_e_DAT_CON_MAX"]["resolvidos"] += 1
            else:
                resultados["R3_cascata_AT_e_DAT_CON_MAX"]["ambiguos"] += 1

        # R4: Manter a linha com maior valor de CAR_INST
        cargas: list[tuple[float, dict[str, Any]]] = []
        for r in linhas:
            val_c = str(r.get("CAR_INST", "")).strip().replace(",", ".")
            if val_c and val_c not in ("<NA>", "None", "nan"):
                try:
                    cargas.append((float(val_c), r))
                except (ValueError, TypeError):
                    LOGGER.debug("Valor invalido de CAR_INST em %s para COD_ID=%s: %s", tabela, cid, val_c)

        if not cargas:
            resultados["R4_CAR_INST_MAX"]["perdidos"] += 1
        else:
            max_c = max(c for c, _ in cargas)
            linhas_max_c = [r for c, r in cargas if c == max_c]
            if len(linhas_max_c) == 1:
                resultados["R4_CAR_INST_MAX"]["resolvidos"] += 1
            else:
                resultados["R4_CAR_INST_MAX"]["ambiguos"] += 1

    # Formatacao para impressao e para CSV (uma linha por tabela, regra e resultado)
    print("\n" + "-" * 95)
    print(f"TABELA DE RESOLUCAO POR REGRA CANDIDATA: {tabela} (N = {n_total} COD_ID)")
    print("-" * 95)
    print(f"{'REGRA CANDIDATA':<38} | {'RESOLVIDOS':<10} | {'AMBIGUOS':<10} | {'PERDIDOS':<10} | {'% RESOLVIDOS':<12}")
    print("-" * 95)

    registros_regras_csv: list[dict[str, Any]] = []

    for regra_nome, contagens in sorted(resultados.items()):
        res = contagens["resolvidos"]
        amb = contagens["ambiguos"]
        per = contagens["perdidos"]
        pct_res = round(100.0 * res / n_total, 2)
        pct_amb = round(100.0 * amb / n_total, 2)
        pct_per = round(100.0 * per / n_total, 2)

        print(f"{regra_nome:<38} | {res:>10} | {amb:>10} | {per:>10} | {pct_res:>11.2f}%")

        # Uma linha por tabela, regra e resultado (resolvidos, ambiguos, perdidos)
        for tipo_res, valor_cnt, valor_pct in [
            ("resolvidos", res, pct_res),
            ("ambiguos", amb, pct_amb),
            ("perdidos", per, pct_per),
        ]:
            registros_regras_csv.append({
                "tabela": tabela,
                "regra": regra_nome,
                "resultado": tipo_res,
                "contagem": valor_cnt,
                "total_cod_id": n_total,
                "percentual": valor_pct,
            })

    print("-" * 95)
    return registros_regras_csv


def main() -> None:
    """Fluxo principal do script 03h."""
    # Verificacao de saidas preexistentes antes de criar qualquer arquivo
    for p in (CSV_AMOSTRA, CSV_COMBINACOES, CSV_REGRAS, CSV_CONTROLE, LOG_PATH):
        if p.exists():
            raise FileExistsError(f"Arquivo de saida ja existente com RUN_TAG={RUN_TAG}: {p}")

    setup_logging()
    LOGGER.info("Iniciando execucao de 03h_amostra_grupos_duplicados | RUN_TAG=%s", RUN_TAG)

    gdb = obter_gdb()
    LOGGER.info("GDB de entrada localizado: %s", gdb.name)

    # Passo 1: Metadados
    info_mt, info_bt, map_mt, map_bt = passo_1_leitura_metadados(gdb)
    cols_mt = list(info_mt["fields"])
    cols_bt = list(info_bt["fields"])
    total_bt = int(info_bt["features"])

    # Passo 2: Amostra UCMT
    df_mt_rep, registros_amostra_mt, amostra_5_mt = passo_2_amostra_ucmt(gdb, cols_mt)

    # Passo 3: Amostra UCBT por balde
    df_bt_rep, registros_amostra_bt, linhas_controle, amostra_5_bt = passo_3_amostra_ucbt_por_balde(
        gdb, total_bt, cols_bt
    )

    # Consolidacao do CSV de amostra de grupos duplicados
    LOGGER.info("Consolidando amostra_grupos_duplicados (UCMT: %d linhas, UCBT: %d linhas)...",
                len(registros_amostra_mt), len(registros_amostra_bt))
    df_amostra_completa = pd.concat(
        [pd.DataFrame(registros_amostra_mt), pd.DataFrame(registros_amostra_bt)],
        ignore_index=True
    )
    cols_pref = ["tabela_origem", "COD_ID", "colunas_que_variam"]
    outras_cols = [c for c in df_amostra_completa.columns if c not in cols_pref]
    df_amostra_completa = df_amostra_completa[cols_pref + outras_cols]

    # Passo 4: Combinacoes de valores
    registros_comb = passo_4_combinacoes_valores(df_mt_rep, df_bt_rep, cols_mt, cols_bt)

    # Passo 5: Avaliacao de regras candidatas
    grupos_mt_dict: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_mt_rep.to_dict("records"):
        grupos_mt_dict[str(r["COD_ID"])].append(r)

    grupos_bt_dict: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in df_bt_rep.to_dict("records"):
        grupos_bt_dict[str(r["COD_ID"])].append(r)

    registros_regras_mt = avaliar_regras_candidatas("UCMT_tab", grupos_mt_dict)
    registros_regras_bt = avaliar_regras_candidatas("UCBT_tab", grupos_bt_dict)
    registros_regras_todos = registros_regras_mt + registros_regras_bt

    # Gravacao dos 4 arquivos CSV de saida com encoding utf-8-sig
    LOGGER.info("Gravando %s...", CSV_AMOSTRA.name)
    salvar_csv_sem_sobrescrever(df_amostra_completa, CSV_AMOSTRA)

    LOGGER.info("Gravando %s...", CSV_COMBINACOES.name)
    salvar_csv_sem_sobrescrever(pd.DataFrame(registros_comb), CSV_COMBINACOES)

    LOGGER.info("Gravando %s...", CSV_REGRAS.name)
    salvar_csv_sem_sobrescrever(pd.DataFrame(registros_regras_todos), CSV_REGRAS)

    LOGGER.info("Gravando %s...", CSV_CONTROLE.name)
    salvar_csv_sem_sobrescrever(pd.DataFrame(linhas_controle), CSV_CONTROLE)

    LOGGER.info("Execucao finalizada com exito absoluto | RUN_TAG=%s", RUN_TAG)


if __name__ == "__main__":
    main()
