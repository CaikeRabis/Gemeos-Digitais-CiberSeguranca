"""Triagem de UCs candidatas no entorno do HRC (somente cadastro estático).

Lê data/processed/perfil_ucs_entorno_hrc.csv (gerado por 03b) e aplica filtros
separados (classe pública, CNAE de saúde/segurança, interseção) sobre as UCs MT.

Esta etapa NÃO identifica a UC do HRC, NÃO monta grafo e NÃO conclui conectividade
elétrica. A lista produzida é apenas de candidatas para confirmação posterior.
"""

import hashlib
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
BASE_DIR: Path = Path(__file__).resolve().parent.parent
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"

ENTRADA_CSV: Path = PROCESSED_DIR / "perfil_ucs_entorno_hrc.csv"
OUT_PUBLICAS: Path = PROCESSED_DIR / "triagem_ucs_mt_publicas_hrc.csv"
OUT_CNAE: Path = PROCESSED_DIR / "triagem_ucs_mt_cnae_saude_seguranca_hrc.csv"
OUT_INTERSECAO: Path = PROCESSED_DIR / "triagem_candidatas_hrc_interseccao.csv"
OUT_AGREGADA: Path = PROCESSED_DIR / "triagem_agregada_ctmt_sub_hrc.csv"
OUT_RELATORIO: Path = PROCESSED_DIR / "relatorio_triagem_ucs_hrc.txt"
SAIDAS: tuple[Path, ...] = (OUT_PUBLICAS, OUT_CNAE, OUT_INTERSECAO, OUT_AGREGADA, OUT_RELATORIO)

PREFIXOS_CLASSE: tuple[str, ...] = ("PP", "SP")
PREFIXOS_CNAE: tuple[str, ...] = ("86", "84")
COL_FILTROS: str = "filtros_atendidos"

# Papel -> aliases aceitos (comparação sem diferenciar maiúsculas/minúsculas)
ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("cod_id", "id", "id_uc", "uc_id"),
    "origem": ("tabela_origem", "tabela", "origem"),
    "clas_sub": ("clas_sub", "classe_subclasse", "classe_sub"),
    "cnae": ("cnae",),
    "ctmt": ("ctmt", "circuito", "cod_ctmt"),
    "sub": ("sub", "subestacao", "cod_sub"),
    "car_inst": ("car_inst", "carga_instalada", "carga_inst"),
    "dem_cont": ("dem_cont", "demanda_contratada", "dem_contratada"),
    "metodo": ("metodo_vinculo", "metodo", "vinculo"),
}

# Contagens esperadas (relatório 03b e inspeção prévia); informativas, não obrigatórias
ESPERADO: dict[str, int] = {
    "universo_mt": 236, "f1_publicas": 27, "f2_cnae": 27,
}

logger = logging.getLogger("triagem_ucs_hrc")


# --------------------------------------------------------------------------- #
# Infraestrutura
# --------------------------------------------------------------------------- #
def configurar_logging(log_path: Path) -> None:
    """Configura logging (terminal + arquivo) sem handlers duplicados."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")):
        handler.setFormatter(fmt)
        logger.addHandler(handler)


def sha256(caminho: Path) -> str:
    """SHA-256 de um arquivo."""
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def verificar_saidas_inexistentes() -> None:
    """Impede sobrescrita de artefatos existentes."""
    existentes = [p.name for p in SAIDAS if p.exists()]
    if existentes:
        raise FileExistsError(
            f"Artefatos já existem e não serão sobrescritos: {existentes}. "
            "Mova ou renomeie-os antes de executar novamente."
        )


# --------------------------------------------------------------------------- #
# Leitura e mapeamento de colunas
# --------------------------------------------------------------------------- #
def ler_cabecalho(csv: Path) -> list[str]:
    """Lê apenas o cabeçalho do CSV."""
    return list(pd.read_csv(csv, nrows=0, dtype=str).columns)


def mapear_colunas(cabecalho: list[str]) -> tuple[dict[str, str], list[str]]:
    """Mapeia papéis para colunas reais; devolve (mapa, papéis ausentes)."""
    por_lower = {c.strip().lower(): c for c in cabecalho}
    mapa: dict[str, str] = {}
    ausentes: list[str] = []
    for papel, aliases in ALIASES.items():
        real = next((por_lower[a] for a in aliases if a in por_lower), None)
        if real is None:
            ausentes.append(papel)
        else:
            mapa[papel] = real
    return mapa, ausentes


def carregar_dados(csv: Path, mapa: dict[str, str]) -> pd.DataFrame:
    """Lê o CSV como texto e converte só carga/demanda para número."""
    df = pd.read_csv(csv, dtype=str)
    for papel in ("car_inst", "dem_cont"):
        col = mapa[papel]
        original = df[col]
        convertido = pd.to_numeric(original, errors="coerce")
        falhas = int((convertido.isna() & original.notna() & (original.str.strip() != "")).sum())
        if falhas:
            logger.warning("Coluna %s: %d valores não numéricos convertidos para nulo.", col, falhas)
        df[col] = convertido
    return df


# --------------------------------------------------------------------------- #
# Filtros
# --------------------------------------------------------------------------- #
def normalizar_cnae(serie: pd.Series) -> pd.Series:
    """Remove pontos, espaços, hífens e barras do CNAE (mantém zeros à esquerda)."""
    return serie.fillna("").astype(str).str.replace(r"[\s.\-/]", "", regex=True)


def selecionar_universo_mt(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """UCs MT: tabela de origem contendo 'UCMT' (justificativa: nome da tabela BDGD)."""
    origem = df[mapa["origem"]].fillna("").str.upper()
    return df[origem.str.contains("UCMT")].copy()


def marcar_filtros(mt: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """Adiciona máscaras F1/F2 e coluna descritiva de filtros atendidos."""
    out = mt.copy()
    classe = out[mapa["clas_sub"]].fillna("").str.strip().str.upper()
    out["_f1"] = classe.str.startswith(PREFIXOS_CLASSE)
    out["_cnae_norm"] = normalizar_cnae(out[mapa["cnae"]])
    out["_f2"] = out["_cnae_norm"].str.startswith(PREFIXOS_CNAE)

    def rotulo(f1: bool, f2: bool) -> str:
        return "+".join(n for n, ok in (("F1", f1), ("F2", f2)) if ok) or "nenhum"

    out[COL_FILTROS] = [rotulo(a, b) for a, b in zip(out["_f1"], out["_f2"])]
    return out


def separar_conjuntos(marcado: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Retorna conjuntos de cada filtro e universo."""
    return {
        "universo_mt": marcado,
        "f1_publicas": marcado[marcado["_f1"]],
        "f2_cnae": marcado[marcado["_f2"]],
        "f3_intersecao": marcado[marcado["_f1"] & marcado["_f2"]],
    }


# --------------------------------------------------------------------------- #
# Agregações
# --------------------------------------------------------------------------- #
def agregar_ctmt_sub(conjuntos: dict[str, pd.DataFrame], mapa: dict[str, str]) -> pd.DataFrame:
    """Agregação por (ctmt, sub) com contagens de cada filtro e do universo."""
    ct, sb = mapa["ctmt"], mapa["sub"]
    uni = conjuntos["universo_mt"].copy()
    uni[ct] = uni[ct].fillna("(nulo)")
    uni[sb] = uni[sb].fillna("(nulo)")
    uni["n_universo_mt"] = 1
    uni["n_f1_publicas"] = uni["_f1"].astype(int)
    uni["n_f2_cnae"] = uni["_f2"].astype(int)
    uni["n_f3_intersecao"] = (uni["_f1"] & uni["_f2"]).astype(int)
    agg = uni.groupby([ct, sb], as_index=False)[
        ["n_universo_mt", "n_f1_publicas", "n_f2_cnae", "n_f3_intersecao"]
    ].sum()
    agg["n_sub_distintas_no_ctmt"] = agg.groupby(ct)[sb].transform("nunique")
    agg["pct_universo_mt"] = (agg["n_universo_mt"] / agg["n_universo_mt"].sum() * 100).round(2)
    return agg.sort_values(
        ["n_f3_intersecao", "n_f1_publicas", "n_f2_cnae", "n_universo_mt"], ascending=False
    ).reset_index(drop=True)


def estatisticas_numericas(serie: pd.Series) -> dict[str, float]:
    """Soma, mediana, mínimo, máximo e nulos."""
    return {
        "n": int(len(serie)), "nulos": int(serie.isna().sum()),
        "soma": float(serie.sum(skipna=True)) if serie.notna().any() else float("nan"),
        "mediana": float(serie.median()) if serie.notna().any() else float("nan"),
        "min": float(serie.min()) if serie.notna().any() else float("nan"),
        "max": float(serie.max()) if serie.notna().any() else float("nan"),
    }


def nulos_vazios(df: pd.DataFrame, col: str) -> tuple[int, int]:
    """Conta nulos (NaN) e vazios (somente espaços) de uma coluna de texto."""
    s = df[col]
    nulos = int(s.isna().sum())
    vazios = int((s.dropna().astype(str).str.strip() == "").sum())
    return nulos, vazios


def ctmt_com_multiplas_sub(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """Quantidade de candidatas por (ctmt, sub) e flag de circuito com >1 sub."""
    ct, sb = mapa["ctmt"], mapa["sub"]
    if df.empty:
        return pd.DataFrame(columns=[ct, sb, "n", "n_sub_no_ctmt"])
    t = df.assign(**{ct: df[ct].fillna("(nulo)"), sb: df[sb].fillna("(nulo)")})
    g = t.groupby([ct, sb]).size().reset_index(name="n")
    g["n_sub_no_ctmt"] = g.groupby(ct)[sb].transform("nunique")
    return g


# --------------------------------------------------------------------------- #
# Saídas
# --------------------------------------------------------------------------- #
def colunas_saida(df_original_cols: list[str]) -> list[str]:
    """Colunas originais + coluna de filtros atendidos."""
    return df_original_cols + [COL_FILTROS]


def gravar_csvs(
    conjuntos: dict[str, pd.DataFrame], agregada: pd.DataFrame, cols_orig: list[str]
) -> None:
    """Grava as quatro tabelas CSV (sem sobrescrever)."""
    cols = colunas_saida(cols_orig)
    destinos = {"f1_publicas": OUT_PUBLICAS, "f2_cnae": OUT_CNAE, "f3_intersecao": OUT_INTERSECAO}
    for chave, destino in destinos.items():
        conjuntos[chave][cols].to_csv(destino, index=False, encoding="utf-8", mode="x")
        logger.info("Gravado %s (%d linhas)", destino.name, len(conjuntos[chave]))
    agregada.to_csv(OUT_AGREGADA, index=False, encoding="utf-8", mode="x")
    logger.info("Gravado %s (%d linhas)", OUT_AGREGADA.name, len(agregada))


def formatar_estatisticas(nome: str, st: dict[str, float]) -> str:
    """Linha textual de estatísticas numéricas."""
    return (f"    {nome:<9} n={st['n']} nulos={st['nulos']} soma={st['soma']:,.2f} "
            f"mediana={st['mediana']:,.2f} min={st['min']:,.2f} max={st['max']:,.2f}")


def escrever_relatorio(
    mapa: dict[str, str], ausentes: list[str], conjuntos: dict[str, pd.DataFrame],
    df_total: pd.DataFrame, hash_antes: str, hash_depois: str, duracao: float,
) -> None:
    """Escreve o relatório textual da triagem."""
    rotulos = {
        "universo_mt": "UNIVERSO: todas as UCs MT do entorno",
        "f1_publicas": "FILTRO 1: MT com CLAS_SUB iniciando em PP ou SP",
        "f2_cnae": "FILTRO 2: MT com CNAE iniciando em 86 ou 84 (normalizado)",
        "f3_intersecao": "FILTRO 3: interseção F1 e F2 (MT)",
    }
    L: list[str] = ["=" * 78, "RELATÓRIO DE TRIAGEM DE UCs CANDIDATAS - ENTORNO DO HRC (3 km)", "=" * 78,
                    f"Data/hora: {datetime.now():%Y-%m-%d %H:%M:%S} | Duração: {duracao:.1f} s", "",
                    "1. ENTRADA E INTEGRIDADE",
                    f"  Arquivo: {ENTRADA_CSV}", f"  SHA-256 antes : {hash_antes}",
                    f"  SHA-256 depois: {hash_depois}",
                    f"  Resultado     : {'INALTERADO' if hash_antes == hash_depois else 'ALTERADO!'}", "",
                    "2. COLUNAS MAPEADAS"]
    L += [f"  {papel:<9} -> {col}" for papel, col in mapa.items()]
    L += [f"  AUSENTES: {ausentes if ausentes else 'nenhuma'}", "",
          "3. CRITÉRIOS (todos aplicados apenas ao universo MT; origem contendo 'UCMT')",
          "  - F1: CLAS_SUB (maiúsculas, sem espaços) com prefixo PP ou SP.",
          "  - F2: CNAE sem pontos/hífens/barras/espaços, prefixo 86 (saúde) ou 84 (adm. pública/defesa/seguridade).",
          "  - F3: F1 e F2 simultâneos.",
          "  - Justificativa de escopo: nomes dos arquivos e universo de referência são MT; UCs BT não foram filtradas.",
          f"  - UCs BT presentes no CSV (fora da triagem): {len(df_total) - len(conjuntos['universo_mt'])}", ""]
    L += ["4. CONTAGENS"]
    uni_n = len(conjuntos["universo_mt"])
    for chave, rot in rotulos.items():
        n = len(conjuntos[chave])
        pct = n / uni_n * 100 if uni_n else 0
        L.append(f"  {rot}: {n} ({pct:.2f}% do universo MT)")
    L += ["", "5. DIVERGÊNCIA ENTRE PREVISTO E OBTIDO (informativo)"]
    for chave, previsto in ESPERADO.items():
        obtido = len(conjuntos[chave])
        L.append(f"  {chave}: previsto={previsto} obtido={obtido} "
                 f"{'(igual)' if previsto == obtido else '(DIVERGENTE: ' + format(obtido - previsto, '+d') + ')'}")
    L.append("")
    ct, sb = mapa["ctmt"], mapa["sub"]
    L += ["6. CTMT/SUB, CARGA E DEMANDA POR CONJUNTO"]
    for chave, rot in rotulos.items():
        df = conjuntos[chave]
        L += [f"  [{rot}]",
              f"    CTMT distintos: {df[ct].nunique(dropna=True)} | SUB distintas: {df[sb].nunique(dropna=True)}",
              formatar_estatisticas("CAR_INST", estatisticas_numericas(df[mapa['car_inst']])),
              formatar_estatisticas("DEM_CONT", estatisticas_numericas(df[mapa['dem_cont']]))]
        mult = ctmt_com_multiplas_sub(df, mapa)
        multi = mult[mult["n_sub_no_ctmt"] > 1]
        L.append(f"    CTMT ligados a mais de uma SUB: {multi[ct].nunique() if not multi.empty else 0}")
        for _, r in multi.iterrows():
            L.append(f"      {r[ct]} / {r[sb]}: {r['n']}")
        if chave != "universo_mt":
            L.append("    Candidatas por CTMT / SUB:")
            for _, r in mult.sort_values("n", ascending=False).iterrows():
                L.append(f"      {r[ct]:<10} {r[sb]:<8} {r['n']}")
        L.append("    Nulos/vazios (n, %):")
        for papel in ("clas_sub", "cnae", "ctmt", "sub"):
            nul, vaz = nulos_vazios(df, mapa[papel])
            tot = max(len(df), 1)
            L.append(f"      {mapa[papel]:<9} nulos={nul} ({nul/tot:.2%}) vazios={vaz} ({vaz/tot:.2%})")
        L.append("")
    L += ["7. CNAE ENCONTRADOS NO FILTRO 2 (código normalizado -> original -> contagem)"]
    f2 = conjuntos["f2_cnae"]
    cont = f2.groupby(["_cnae_norm", mapa["cnae"]]).size().reset_index(name="n").sort_values(["_cnae_norm"])
    L += [f"  {r['_cnae_norm']:<8} ({r[mapa['cnae']]}): {r['n']}" for _, r in cont.iterrows()]
    L += ["", "8. CANDIDATAS DA INTERSEÇÃO F1+F2 (identificador | CTMT | SUB | CLAS_SUB | CNAE)"]
    f3 = conjuntos["f3_intersecao"]
    for _, r in f3.iterrows():
        L.append(f"  {r[mapa['id']]} | {r[ct]} | {r[sb]} | {r[mapa['clas_sub']]} | {r[mapa['cnae']]}")
    if f3.empty:
        L.append("  (nenhuma)")
    L += ["", "9. LIMITAÇÕES",
          "  - Triagem baseada em cadastro estático da BDGD; não identifica a UC do HRC.",
          "  - O CNAE cadastrado pode estar desatualizado ou impreciso para a UC.",
          "  - Classe/CNAE são inferidos pelo prefixo; a semântica depende do PRODIST/CNAE, não confirmada aqui.",
          "  - A vinculação das UCs ao buffer foi feita por PN_CON -> PONNOT (proximidade), não por conectividade elétrica.",
          "  - A identificação do HRC depende de confirmação por fatura, código da conta contrato ou cadastro.",
          "  - Não foi construído grafo nem concluída conectividade elétrica.", "=" * 78]
    OUT_RELATORIO.write_text("\n".join(L) + "\n", encoding="utf-8")
    logger.info("Relatório salvo em %s", OUT_RELATORIO)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    """Executa a triagem. 0=sucesso, 1=erro."""
    inicio = time.perf_counter()
    configurar_logging(LOGS_DIR / f"triagem_ucs_hrc_{datetime.now():%Y%m%d_%H%M%S}.log")
    logger.info("Início da triagem de UCs.")
    try:
        if not ENTRADA_CSV.exists():
            raise FileNotFoundError(f"Entrada ausente: {ENTRADA_CSV}. Execute src/03b_inventario_schema_bdgd.py.")
        verificar_saidas_inexistentes()
        hash_antes = sha256(ENTRADA_CSV)
        logger.info("SHA-256 de entrada (antes): %s", hash_antes)

        cabecalho = ler_cabecalho(ENTRADA_CSV)
        logger.info("Cabeçalho: %s", cabecalho)
        mapa, ausentes = mapear_colunas(cabecalho)
        logger.info("Colunas mapeadas: %s", mapa)
        if ausentes:
            raise KeyError(
                f"Colunas ausentes no CSV: {ausentes}. Cabeçalho encontrado: {cabecalho}. "
                "Reexecute o 03b ou ajuste ALIASES."
            )

        df = carregar_dados(ENTRADA_CSV, mapa)
        logger.info("Linhas lidas: %d", len(df))
        mt = selecionar_universo_mt(df, mapa)
        logger.info("Universo MT: %d | BT (fora da triagem): %d", len(mt), len(df) - len(mt))
        if mt.empty:
            raise ValueError("Nenhuma UC MT encontrada na coluna de origem.")
        conjuntos = separar_conjuntos(marcar_filtros(mt, mapa))
        for chave, sub_df in conjuntos.items():
            logger.info("%s: %d | CTMT=%d | SUB=%d", chave, len(sub_df),
                        sub_df[mapa["ctmt"]].nunique(dropna=True), sub_df[mapa["sub"]].nunique(dropna=True))
        agregada = agregar_ctmt_sub(conjuntos, mapa)

        gravar_csvs(conjuntos, agregada, list(df.columns))
        hash_depois = sha256(ENTRADA_CSV)
        logger.info("SHA-256 de entrada (depois): %s", hash_depois)
        if hash_antes != hash_depois:
            logger.error("A entrada foi alterada durante a execução!")
            return 1
        escrever_relatorio(mapa, ausentes, conjuntos, df, hash_antes, hash_depois, time.perf_counter() - inicio)
    except (FileNotFoundError, FileExistsError, KeyError, ValueError) as exc:
        logger.error("Triagem interrompida: %s", exc)
        return 1
    except Exception:
        logger.exception("Erro inesperado na triagem.")
        return 1
    logger.info("Triagem concluída em %.1f s.", time.perf_counter() - inicio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
