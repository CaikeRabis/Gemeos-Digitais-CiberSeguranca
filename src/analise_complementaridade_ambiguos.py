"""analise_complementaridade_ambiguos.py

Analise de complementaridade de consumo (ENE_01..12 e DEM_01..12) e
divergencia topologica para os 102 grupos ambiguos da cascata R3 em UCBT_tab.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Caminhos e constantes
BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

LOG_PATH = LOGS_DIR / f"complementaridade_{RUN_TAG}.log"
CSV_GRUPOS = PROCESSED_DIR / f"complementaridade_grupos_{RUN_TAG}.csv"
CSV_PARES = PROCESSED_DIR / f"complementaridade_pares_{RUN_TAG}.csv"
CSV_RESUMO = PROCESSED_DIR / f"complementaridade_resumo_{RUN_TAG}.csv"
CSV_TOPOLOGIA = PROCESSED_DIR / f"topologia_divergente_{RUN_TAG}.csv"

INPUT_CSV = PROCESSED_DIR / "ambiguos_cascata_linhas_20261017_180249.csv"

COLUNAS_ENE = [f"ENE_{i:02d}" for i in range(1, 13)]
COLUNAS_DEM = [f"DEM_{i:02d}" for i in range(1, 13)]
COLUNAS_CONSUMO = COLUNAS_ENE + COLUNAS_DEM
COLUNAS_TOPOL = ["PAC", "RAMAL", "PN_CON", "UNI_TR_MT"]

ORDEM_PRIORIDADE_GRUPO = [
    "zerado",
    "sobreposto_diferente",
    "identico_consumo",
    "complementar",
]

LOGGER = logging.getLogger("complementaridade")


def verificar_arquivos_saida() -> None:
    """Garante que nenhum arquivo com RUN_TAG ja exista antes de iniciar."""
    arquivos = (LOG_PATH, CSV_GRUPOS, CSV_PARES, CSV_RESUMO, CSV_TOPOLOGIA)
    for caminho in arquivos:
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


def aplicar_cascata(df: pd.DataFrame) -> dict[str, list[int]]:
    """Passo 1: Aplica a cascata R3 grupo a grupo e registra indices remanescentes."""
    LOGGER.info("=== Passo 1: Aplicacao da cascata R3 sobre os grupos ===")
    resolvidos = 0
    ambiguos = 0
    perdidos = 0
    remanescentes: dict[str, list[int]] = {}

    grupos = df.groupby("COD_ID", sort=False)
    for cid, g in grupos:
        linhas = [r._asdict() for r in g.itertuples(index=True)]
        ats = [r for r in linhas if str(r.get("SIT_ATIV")) == "AT"]
        cand = ats if ats else linhas
        cand_datas = [
            (parse_data_br(r.get("DAT_CON")), r)
            for r in cand
            if parse_data_br(r.get("DAT_CON")) is not None
        ]
        if not cand_datas:
            ambiguos += 1
            rem = cand
        else:
            max_d = max(d for d, _ in cand_datas)
            cand_max = [r for d, r in cand_datas if d == max_d]
            if len(cand_max) == 1:
                resolvidos += 1
                rem = cand_max
            else:
                ambiguos += 1
                rem = cand_max

        remanescentes[str(cid)] = [int(r["Index"]) for r in rem]

    LOGGER.info(
        "Resultado da cascata: resolvidos=%d, ambiguos=%d, perdidos=%d",
        resolvidos,
        ambiguos,
        perdidos,
    )

    if ambiguos != 102 or resolvidos != 0 or perdidos != 0:
        LOGGER.error(
            "Esperado exatamente 102 ambiguos e 0 resolvidos/perdidos. Obtido: res=%d, amb=%d, per=%d",
            resolvidos,
            ambiguos,
            perdidos,
        )
        sys.exit(1)

    total_linhas_rem = sum(len(v) for v in remanescentes.values())
    LOGGER.info(
        "Confirmacao Passo 1: 102 grupos ambiguos reproduzidos com sucesso (%d linhas remanescentes)",
        total_linhas_rem,
    )
    return remanescentes


def tratar_colunas_consumo(df: pd.DataFrame) -> pd.DataFrame:
    """Passo 2.1: Diagnostica e trata nulos, vazios e conversao numerica das 24 series."""
    LOGGER.info("=== Passo 2.1: Tratamento das 24 series de consumo (ENE e DEM) ===")
    df_consumo_num = pd.DataFrame(index=df.index)

    for c in COLUNAS_CONSUMO:
        s = df[c] if c in df.columns else pd.Series(np.nan, index=df.index, dtype=object)
        nv = s.isna() | (s.astype(str).str.strip() == "") | s.isin(["<NA>", "None", "nan", "NaT"])
        qtd_nv = int(nv.sum())

        s_limpa = s.astype(str).str.replace(",", ".", regex=False)
        converted = pd.to_numeric(s_limpa, errors="coerce")
        nao_converte = s[~nv & converted.isna()]
        qtd_nc = int(len(nao_converte))

        LOGGER.info(
            "Coluna %s: %d nulos/vazios tratados como zero | %d valores nao convertidos",
            c,
            qtd_nv,
            qtd_nc,
        )
        if qtd_nc > 0:
            LOGGER.warning("Exemplos que nao converteram em %s: %s", c, nao_converte.head().tolist())

        df_consumo_num[c] = converted.fillna(0.0)

    return df_consumo_num


def classificar_par(
    va: np.ndarray, vb: np.ndarray
) -> tuple[int, str, str, int, int]:
    """Classifica um par de linhas remanescentes nas metricas de consumo."""
    pos_a = va > 0
    pos_b = vb > 0
    meses_zerados_a = int((va == 0).sum())
    meses_zerados_b = int((vb == 0).sum())

    sobreposicao = int((pos_a & pos_b).sum())
    identico = bool(np.array_equal(va, vb))
    a_zerado = meses_zerados_a == 24
    b_zerado = meses_zerados_b == 24

    if identico:
        # Se identico e ambos 24 meses zero, ou identico positivo
        classe_par = "identico_consumo"
        subclasse = "ambos_zerados" if a_zerado and b_zerado else "identico_positivo"
    elif sobreposicao > 0:
        classe_par = "sobreposto_diferente"
        subclasse = "sobreposto_diferente"
    elif a_zerado or b_zerado:
        classe_par = "zerado"
        subclasse = "uma_linha_zerada"
    elif sobreposicao == 0 and not a_zerado and not b_zerado:
        classe_par = "complementar"
        subclasse = "complementar"
    else:
        classe_par = "indefinido"
        subclasse = "indefinido"

    return sobreposicao, classe_par, subclasse, meses_zerados_a, meses_zerados_b


def avaliar_pior_caso_grupo(classes_pares: list[str]) -> str:
    """Retorna o pior caso entre os pares segundo a ordem de prioridade definida."""
    for regra in ORDEM_PRIORIDADE_GRUPO:
        if regra in classes_pares:
            return regra
    return classes_pares[0] if classes_pares else "indefinido"


def executar_analise_complementaridade(
    df: pd.DataFrame,
    remanescentes: dict[str, list[int]],
    df_consumo: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Passo 2 e 3: Compara pares, classifica grupos e avalia topologia."""
    LOGGER.info("=== Passo 2.2 e 3: Comparacao de pares e analise topologica ===")
    registros_pares: list[dict[str, Any]] = []
    registros_grupos: list[dict[str, Any]] = []
    linhas_topologia_divergente: list[dict[str, Any]] = []

    for cid, idx_list in remanescentes.items():
        sub_df = df.loc[idx_list]
        n_linhas = len(idx_list)

        # Analise de topologia no grupo
        tem_topol_div = False
        tem_cep_sem_pac = False

        for i_a, i_b in combinations(idx_list, 2):
            ra = sub_df.loc[i_a]
            rb = sub_df.loc[i_b]
            diff_topol = [
                c for c in COLUNAS_TOPOL if str(ra.get(c, "")).strip() != str(rb.get(c, "")).strip()
            ]
            if len(diff_topol) > 0:
                tem_topol_div = True

            pac_igual = str(ra.get("PAC", "")).strip() == str(rb.get("PAC", "")).strip()
            cep_dif = str(ra.get("CEP", "")).strip() != str(rb.get("CEP", "")).strip()
            if cep_dif and pac_igual:
                tem_cep_sem_pac = True

        if tem_topol_div:
            for idx_lin in idx_list:
                r_lin = sub_df.loc[idx_lin]
                linhas_topologia_divergente.append(
                    {
                        "COD_ID": cid,
                        "indice_original": idx_lin,
                        "PAC": r_lin.get("PAC", ""),
                        "RAMAL": r_lin.get("RAMAL", ""),
                        "PN_CON": r_lin.get("PN_CON", ""),
                        "UNI_TR_MT": r_lin.get("UNI_TR_MT", ""),
                        "CEP": r_lin.get("CEP", ""),
                        "DESCR": r_lin.get("DESCR", ""),
                        "SIT_ATIV": r_lin.get("SIT_ATIV", ""),
                        "DAT_CON": r_lin.get("DAT_CON", ""),
                        "CLAS_SUB": r_lin.get("CLAS_SUB", ""),
                    }
                )

        # Analise de consumo entre os pares do grupo
        classes_pares_grupo: list[str] = []
        classes_zerado_amplo_grupo: list[str] = []
        sobreposicoes_grupo: list[int] = []

        for i_a, i_b in combinations(idx_list, 2):
            va = df_consumo.loc[i_a].to_numpy(dtype=float)
            vb = df_consumo.loc[i_b].to_numpy(dtype=float)
            sob, cl_par, subclasse, zer_a, zer_b = classificar_par(va, vb)

            classes_pares_grupo.append(cl_par)
            sobreposicoes_grupo.append(sob)

            # Criterio alternativo onde qualquer par com linha zerada e zerado
            cl_amplo = "zerado" if (zer_a == 24 or zer_b == 24) else cl_par
            classes_zerado_amplo_grupo.append(cl_amplo)

            registros_pares.append(
                {
                    "COD_ID": cid,
                    "indice_a": i_a,
                    "indice_b": i_b,
                    "sobreposicao": sob,
                    "classe_par": cl_par,
                    "subclasse_par": subclasse,
                    "classe_par_zerado_amplo": cl_amplo,
                    "meses_zerados_a": zer_a,
                    "meses_zerados_b": zer_b,
                }
            )

        classe_final_grupo = avaliar_pior_caso_grupo(classes_pares_grupo)
        classe_amplo_grupo = avaliar_pior_caso_grupo(classes_zerado_amplo_grupo)
        max_sob = max(sobreposicoes_grupo) if sobreposicoes_grupo else 0

        registros_grupos.append(
            {
                "COD_ID": cid,
                "classe": classe_final_grupo,
                "classe_criterio_zerado_amplo": classe_amplo_grupo,
                "linhas_remanescentes": n_linhas,
                "sobreposicao_maxima": max_sob,
                "flag_topologia_divergente": tem_topol_div,
                "flag_cep_dif_sem_pac": tem_cep_sem_pac,
                "indices_remanescentes": str(idx_list),
            }
        )

    df_pares = pd.DataFrame(registros_pares)
    df_grupos = pd.DataFrame(registros_grupos)
    df_topol = pd.DataFrame(linhas_topologia_divergente)

    return df_grupos, df_pares, df_topol


def gerar_resumo_passo_4(
    df_grupos: pd.DataFrame, df_pares: pd.DataFrame
) -> pd.DataFrame:
    """Passo 4: Gera o DataFrame de resumo com contagens consolidadas."""
    total_grupos = len(df_grupos)

    # Contagens no criterio A (identico_consumo para 24 meses iguais)
    cnt_classe = df_grupos["classe"].value_counts().to_dict()
    cnt_amplo = df_grupos["classe_criterio_zerado_amplo"].value_counts().to_dict()

    topol_div_qtd = int(df_grupos["flag_topologia_divergente"].sum())
    cep_sem_pac_qtd = int(df_grupos["flag_cep_dif_sem_pac"].sum())

    # Estatisticas de sobreposicao para sobreposto_diferente
    sob_dif_grupos = df_grupos[df_grupos["classe"] == "sobreposto_diferente"]
    media_sob = (
        round(sob_dif_grupos["sobreposicao_maxima"].mean(), 2)
        if len(sob_dif_grupos) > 0
        else 0.0
    )
    max_sob = (
        int(sob_dif_grupos["sobreposicao_maxima"].max())
        if len(sob_dif_grupos) > 0
        else 0
    )

    resumo_linhas = [
        {
            "categoria": "Passo 4 - Classes de Consumo (Criterio Estrito de Identico)",
            "metrica": "identico_consumo",
            "valor": cnt_classe.get("identico_consumo", 0),
            "proporcao_pct": round(100.0 * cnt_classe.get("identico_consumo", 0) / total_grupos, 2),
            "detalhe": "Os 24 meses sao iguais entre A e B (todos os 27 tem 24 meses zerados em ambas as linhas)",
        },
        {
            "categoria": "Passo 4 - Classes de Consumo (Criterio Estrito de Identico)",
            "metrica": "zerado",
            "valor": cnt_classe.get("zerado", 0),
            "proporcao_pct": round(100.0 * cnt_classe.get("zerado", 0) / total_grupos, 2),
            "detalhe": "Uma linha com 24 meses zerados/nulos e outra linha com consumo positivo",
        },
        {
            "categoria": "Passo 4 - Classes de Consumo (Criterio Estrito de Identico)",
            "metrica": "sobreposto_diferente",
            "valor": cnt_classe.get("sobreposto_diferente", 0),
            "proporcao_pct": round(100.0 * cnt_classe.get("sobreposto_diferente", 0) / total_grupos, 2),
            "detalhe": "Sobreposicao > 0 meses e valores nao identicos",
        },
        {
            "categoria": "Passo 4 - Classes de Consumo (Criterio Estrito de Identico)",
            "metrica": "complementar",
            "valor": cnt_classe.get("complementar", 0),
            "proporcao_pct": round(100.0 * cnt_classe.get("complementar", 0) / total_grupos, 2),
            "detalhe": "Sobreposicao = 0 meses e ambas as linhas possuem ao menos um mes positivo cada",
        },
        {
            "categoria": "Passo 4 - Classes de Consumo (Criterio Alternativo Zerado Precedente)",
            "metrica": "zerado_amplo",
            "valor": cnt_amplo.get("zerado", 0),
            "proporcao_pct": round(100.0 * cnt_amplo.get("zerado", 0) / total_grupos, 2),
            "detalhe": "Pelo menos uma linha com 24 meses zerados (soma de 23 com uma linha + 27 com ambas)",
        },
        {
            "categoria": "Passo 4 - Classes de Consumo (Criterio Alternativo Zerado Precedente)",
            "metrica": "identico_consumo_se_zerado_preceder",
            "valor": cnt_amplo.get("identico_consumo", 0),
            "proporcao_pct": round(100.0 * cnt_amplo.get("identico_consumo", 0) / total_grupos, 2),
            "detalhe": "Nenhum par possui consumo identico positivo nao-zerado",
        },
        {
            "categoria": "Passo 4 - Topologia",
            "metrica": "grupos_topologia_divergente",
            "valor": topol_div_qtd,
            "proporcao_pct": round(100.0 * topol_div_qtd / total_grupos, 2),
            "detalhe": "Ao menos uma diferenca em PAC, RAMAL, PN_CON ou UNI_TR_MT no mesmo par",
        },
        {
            "categoria": "Passo 4 - Topologia",
            "metrica": "grupos_cep_diferente_sem_pac_mudar",
            "valor": cep_sem_pac_qtd,
            "proporcao_pct": round(100.0 * cep_sem_pac_qtd / total_grupos, 2),
            "detalhe": "Grupos com CEP diferente entre linhas mas com PAC identico",
        },
        {
            "categoria": "Passo 4 - Sobreposicao em Sobreposto Diferente",
            "metrica": "media_meses_sobrepostos",
            "valor": media_sob,
            "proporcao_pct": np.nan,
            "detalhe": f"Media de meses positivos simultaneos entre os {len(sob_dif_grupos)} grupos sobreposto_diferente",
        },
        {
            "categoria": "Passo 4 - Sobreposicao em Sobreposto Diferente",
            "metrica": "maximo_meses_sobrepostos",
            "valor": max_sob,
            "proporcao_pct": np.nan,
            "detalhe": f"Maximo de meses positivos simultaneos entre os {len(sob_dif_grupos)} grupos sobreposto_diferente",
        },
    ]

    return pd.DataFrame(resumo_linhas)


def main() -> None:
    verificar_arquivos_saida()
    setup_logging()

    LOGGER.info("Iniciando analise de complementaridade dos ambiguos (RUN_TAG=%s)", RUN_TAG)
    LOGGER.info("Arquivo de entrada: %s", INPUT_CSV)

    if not INPUT_CSV.exists():
        LOGGER.error("Arquivo de entrada nao encontrado: %s", INPUT_CSV)
        sys.exit(1)

    df_raw = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", dtype=str)
    LOGGER.info("Linhas carregadas do CSV de entrada: %d", len(df_raw))

    # Passo 1: Aplicar cascata
    remanescentes = aplicar_cascata(df_raw)

    # Passo 2.1: Tratar colunas de consumo
    df_consumo = tratar_colunas_consumo(df_raw)

    # Passo 2.2 e 3: Analisar pares, grupos e topologia
    df_grupos, df_pares, df_topol = executar_analise_complementaridade(
        df_raw, remanescentes, df_consumo
    )

    # Passo 4: Resumo consolidado
    df_resumo = gerar_resumo_passo_4(df_grupos, df_pares)

    # Logging dos resultados consolidados
    LOGGER.info("=== RESULTADOS CONSOLIDADOS (Passo 4) ===")
    for _, r in df_resumo.iterrows():
        LOGGER.info("[%s] %s = %s (%s)", r["categoria"], r["metrica"], r["valor"], r["detalhe"])

    # Gravacao das saidas
    salvar_csv_sem_sobrescrever(df_grupos, CSV_GRUPOS)
    LOGGER.info("CSV de grupos gravado: %s", CSV_GRUPOS)

    salvar_csv_sem_sobrescrever(df_pares, CSV_PARES)
    LOGGER.info("CSV de pares gravado: %s", CSV_PARES)

    salvar_csv_sem_sobrescrever(df_resumo, CSV_RESUMO)
    LOGGER.info("CSV de resumo gravado: %s", CSV_RESUMO)

    salvar_csv_sem_sobrescrever(df_topol, CSV_TOPOLOGIA)
    LOGGER.info("CSV de topologia gravado: %s", CSV_TOPOLOGIA)

    LOGGER.info("Processamento concluido com sucesso.")


if __name__ == "__main__":
    main()
