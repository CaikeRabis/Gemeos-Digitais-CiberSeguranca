"""Auditoria de duplicidade de UCs nas saídas dos scripts 03b, 03c e 03d.

Lê apenas artefatos CSV já existentes (não abre o .gdb) e corrige as contagens
usando COD_ID distintos. NÃO identifica a UC do HRC, NÃO constrói grafo e NÃO
conclui atendimento elétrico.
"""

import hashlib
import logging
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"
SRC_DIR: Path = BASE_DIR / "src"

ENTRADAS: dict[str, Path] = {
    "perfil_ucs_entorno_hrc": PROCESSED_DIR / "perfil_ucs_entorno_hrc.csv",
    "triagem_publicas": PROCESSED_DIR / "triagem_ucs_mt_publicas_hrc.csv",
    "triagem_cnae": PROCESSED_DIR / "triagem_ucs_mt_cnae_saude_seguranca_hrc.csv",
    "triagem_interseccao": PROCESSED_DIR / "triagem_candidatas_hrc_interseccao.csv",
    "hipoteses_h1_h4": PROCESSED_DIR / "hipoteses_h1_h4_ucs_candidatas_hrc.csv",
}
SCRIPTS_ANALISADOS: tuple[str, ...] = (
    "03b_inventario_schema_bdgd.py", "03c_triagem_ucs_hrc.py", "03d_hipoteses_alimentador_hrc.py",
)

OUT_CONTAGEM: Path = PROCESSED_DIR / "auditoria_contagem_ucs_hrc.csv"
OUT_DUP_COLUNAS: Path = PROCESSED_DIR / "auditoria_duplicidade_colunas_hrc.csv"
OUT_RECONTAGEM: Path = PROCESSED_DIR / "recontagem_ucs_hrc_distintas.csv"
OUT_CNAE500: Path = PROCESSED_DIR / "ucs_cnae_saude_500m_hrc.csv"
OUT_RELATORIO: Path = PROCESSED_DIR / "relatorio_auditoria_duplicidade_hrc.txt"
SAIDAS: tuple[Path, ...] = (OUT_CONTAGEM, OUT_DUP_COLUNAS, OUT_RECONTAGEM, OUT_CNAE500, OUT_RELATORIO)

ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("cod_id", "identificador", "id"),
    "origem": ("tabela_origem", "origem"),
    "clas_sub": ("clas_sub",), "cnae": ("cnae",), "ctmt": ("ctmt",), "sub": ("sub",),
    "car_inst": ("car_inst",), "dem_cont": ("dem_cont",),
    "pn_con": ("pn_con",), "uni_tr_mt": ("uni_tr_mt",),
    "dist": ("distancia_hrc_m", "dist_hrc_m", "distancia_m"),
    "hip": ("hipotese",), "cat": ("categoria_cruzamento",), "criterio": ("criterio_atendido",),
}
COLS_VINCULO: tuple[str, ...] = ("pn_con", "uni_tr_mt", "metodo_vinculo")
COLS_CADASTRAIS: tuple[str, ...] = ("clas_sub", "cnae", "ctmt", "sub", "car_inst", "dem_cont")
CATEGORIAS: tuple[str, ...] = ("coincide_ctmt_e_sub", "coincide_apenas_sub",
                               "coincide_apenas_ctmt", "sem_coincidencia")
NA_TOKEN: str = "<NA>"
LIMIAR_NAO_DISCRIMINANTE_PCT: float = 30.0
RAIO_CNAE_M: float = 500.0
PREFIXOS_PUBLICA: tuple[str, ...] = ("PP", "SP")
PREFIXOS_CNAE: tuple[str, ...] = ("86", "84")

logger = logging.getLogger("auditoria_duplicidade_hrc")


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


def coletar_hashes() -> dict[str, str]:
    """Hash das entradas e de todo arquivo já existente em data/processed e hospitais_df.csv."""
    caminhos: dict[str, Path] = {f"entrada:{k}": p for k, p in ENTRADAS.items()}
    for p in sorted(PROCESSED_DIR.iterdir()):
        if p.is_file() and p not in SAIDAS:
            caminhos.setdefault(f"processed:{p.name}", p)
    hosp = RAW_DIR / "hospitais_df.csv"
    if hosp.exists():
        caminhos["raw:hospitais_df.csv"] = hosp
    return {k: sha256(p) for k, p in caminhos.items()}, caminhos  # type: ignore[return-value]


def verificar_saidas() -> None:
    """Aborta se algum artefato de saída já existir."""
    existentes = [p.name for p in SAIDAS if p.exists()]
    if existentes:
        raise FileExistsError(f"Artefatos já existem e não serão sobrescritos: {existentes}.")


def mapear(cols: list[str]) -> dict[str, str]:
    """Mapeia papéis para colunas reais (sem diferenciar caixa)."""
    low = {c.strip().lower(): c for c in cols}
    return {papel: next(low[a] for a in aliases if a in low)
            for papel, aliases in ALIASES.items() if any(a in low for a in aliases)}


def ler_entrada(nome: str, caminho: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Lê CSV como texto e mapeia colunas; exige ao menos o identificador."""
    df = pd.read_csv(caminho, dtype=str)
    mapa = mapear(list(df.columns))
    logger.info("%s: %d linhas | colunas=%s | mapa=%s", nome, len(df), list(df.columns), mapa)
    if "id" not in mapa:
        raise KeyError(f"{nome}: coluna de identificador ausente. Cabeçalho: {list(df.columns)}")
    ausentes = [p for p in ALIASES if p not in mapa]
    if ausentes:
        logger.warning("%s: papéis sem coluna: %s", nome, ausentes)
    return df, mapa


def norm_cnae(s: pd.Series) -> pd.Series:
    """CNAE sem pontos, hífens, barras e espaços."""
    return s.fillna("").astype(str).str.replace(r"[\s.\-/]", "", regex=True)


def norm_classe(s: pd.Series) -> pd.Series:
    """Classe em maiúsculas sem espaços."""
    return s.fillna("").astype(str).str.strip().str.upper()


# --------------------------------------------------------------------------- #
# Objetivo 1: contagem e duplicidade por arquivo/tabela
# --------------------------------------------------------------------------- #
def auditar_grupo(
    arquivo: str, tabela: str, df: pd.DataFrame, mapa: dict[str, str]
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
    """Audita duplicidade de um arquivo/tabela; devolve (linha de contagem, divergências, extras)."""
    id_col = mapa["id"]
    f = df.fillna(NA_TOKEN)
    outras = [c for c in f.columns if c != id_col]
    redund = int(f.duplicated().sum())
    grupos_ident = int(f[f.duplicated(keep=False)].drop_duplicates().shape[0])
    cont = f.groupby(id_col).size()
    multi = cont[cont > 1].index
    div_rows: list[dict[str, object]] = []
    padroes: Counter = Counter()
    extras: dict[str, object] = {"ids_multilinha": int(len(multi))}
    if len(multi):
        sub = f[f[id_col].isin(multi)]
        nun = sub.groupby(id_col)[outras].nunique()
        divergentes = nun[(nun > 1).any(axis=1)]
        for cod, linha in divergentes.iterrows():
            variam = [c for c in outras if linha[c] > 1]
            padroes[tuple(variam)] += 1
            div_rows.append({
                "arquivo": arquivo, "tabela": tabela, "cod_id": cod,
                "n_linhas": int(cont[cod]),
                "n_variantes_de_linha": int(sub[sub[id_col] == cod].drop_duplicates().shape[0]),
                "colunas_variam": ";".join(variam),
                "valores_distintos_por_coluna": "; ".join(f"{c}={int(linha[c])}" for c in variam),
            })
        n_div = len(divergentes)
    else:
        n_div = 0
    extras["padroes"] = padroes
    extras.update(testes_d(df, mapa))
    linha_cont = {
        "arquivo": arquivo, "tabela": tabela, "linhas": len(df), "cod_id_distintos": int(cont.shape[0]),
        "linhas_identicas_redundantes": redund, "grupos_identicos": grupos_ident,
        "ids_com_mais_de_uma_linha": int(len(multi)), "ids_com_linhas_divergentes": n_div,
    }
    return linha_cont, div_rows, extras


def testes_d(df: pd.DataFrame, mapa: dict[str, str]) -> dict[str, object]:
    """Conta COD_ID com mais de um valor de UNI_TR_MT (D2), CTMT (D3) e PN_CON (proxy de D1)."""
    out: dict[str, object] = {}
    id_col = mapa["id"]
    for rotulo, papel in (("D2_uni_tr_mt", "uni_tr_mt"), ("D3_ctmt", "ctmt"), ("D1proxy_pn_con", "pn_con")):
        col = mapa.get(papel)
        if col is None:
            out[rotulo] = None
            continue
        nao_nulos = df.dropna(subset=[col]).groupby(id_col)[col].nunique()
        com_na = df.fillna({col: NA_TOKEN}).groupby(id_col)[col].nunique()
        out[rotulo] = (int((nao_nulos > 1).sum()), int((com_na > 1).sum()))
    return out


def auditar_todos(dados: dict[str, tuple[pd.DataFrame, dict[str, str]]]):
    """Executa a auditoria em todas as entradas, por tabela de origem."""
    contagem: list[dict[str, object]] = []
    divergencias: list[dict[str, object]] = []
    extras: dict[tuple[str, str], dict[str, object]] = {}
    for nome, (df, mapa) in dados.items():
        origem = mapa.get("origem")
        grupos = ([(t, df[df[origem] == t]) for t in sorted(df[origem].dropna().unique())]
                  if origem else [("(única)", df)])
        for tabela, sub in grupos:
            lc, dv, ex = auditar_grupo(nome, tabela, sub, mapa)
            contagem.append(lc)
            divergencias += dv
            extras[(nome, tabela)] = ex
            logger.info("%s/%s: linhas=%d ids=%d redundantes=%d ids_divergentes=%d", nome, tabela,
                        lc["linhas"], lc["cod_id_distintos"], lc["linhas_identicas_redundantes"],
                        lc["ids_com_linhas_divergentes"])
    return pd.DataFrame(contagem), pd.DataFrame(divergencias), extras


# --------------------------------------------------------------------------- #
# Objetivo 2: causa (leitura do código dos scripts)
# --------------------------------------------------------------------------- #
def varrer_scripts() -> dict[str, dict[str, int]]:
    """Conta usos de merge/sjoin nos scripts 03b-03d (leitura de texto, sem executar)."""
    resultado: dict[str, dict[str, int]] = {}
    for nome in SCRIPTS_ANALISADOS:
        caminho = SRC_DIR / nome
        if not caminho.exists():
            resultado[nome] = {"ausente": 1}
            continue
        txt = caminho.read_text(encoding="utf-8", errors="replace")
        resultado[nome] = {
            "merge": len(re.findall(r"\.merge\(|pd\.merge\(", txt)),
            "sjoin": len(re.findall(r"sjoin\(", txt)),
            "isin": len(re.findall(r"\.isin\(", txt)),
        }
    return resultado


# --------------------------------------------------------------------------- #
# Objetivo 3: recontagem
# --------------------------------------------------------------------------- #
def linha_recont(artefato: str, metrica: str, original, recalc, obs: str = "") -> dict[str, object]:
    """Linha de comparação original x recalculado."""
    dif = None if original is None or recalc is None else recalc - original
    pct = None if dif is None or not original else round(dif / original * 100, 2)
    return {"artefato": artefato, "metrica": metrica, "valor_original": original,
            "valor_recalculado": recalc, "diferenca_abs": dif, "diferenca_pct": pct, "observacao": obs}


def recontar_03c(perfil: pd.DataFrame, m: dict[str, str], arqs: dict[str, tuple[pd.DataFrame, dict[str, str]]]):
    """Recalcula universo MT, F1, F2 e F1+F2 com COD_ID distintos."""
    idc = m["id"]
    mt = perfil[perfil[m["origem"]].fillna("").str.upper().str.contains("UCMT")].copy()
    mt["_f1"] = norm_classe(mt[m["clas_sub"]]).str.startswith(PREFIXOS_PUBLICA).astype(int)
    mt["_f2"] = norm_cnae(mt[m["cnae"]]).str.startswith(PREFIXOS_CNAE).astype(int)
    mt["_f3"] = mt["_f1"] & mt["_f2"]
    g = mt.groupby(idc)[["_f1", "_f2", "_f3"]].agg(["min", "max"])
    linhas: list[dict[str, object]] = []
    conflitos: dict[str, int] = {}
    ctmt, sub = m["ctmt"], m["sub"]
    linhas.append(linha_recont("03c", "universo_mt", len(mt), mt[idc].nunique(), "linhas x COD_ID distintos"))
    originais = {
        "_f1": ("F1_PP_SP", len(arqs["triagem_publicas"][0])),
        "_f2": ("F2_CNAE_84_86", len(arqs["triagem_cnae"][0])),
        "_f3": ("F3_interseccao", len(arqs["triagem_interseccao"][0])),
    }
    arq_por_flag = {"_f1": "triagem_publicas", "_f2": "triagem_cnae", "_f3": "triagem_interseccao"}
    for flag, (rotulo, orig) in originais.items():
        verdadeiros = g.index[(g[(flag, "min")] == 1) & (g[(flag, "max")] == 1)]
        conf = int((g[(flag, "min")] != g[(flag, "max")]).sum())
        conflitos[rotulo] = conf
        linhas.append(linha_recont("03c", f"{rotulo}_ucs", orig, len(verdadeiros),
                                   f"IDs distintos consistentes; conflitos de filtro entre linhas do mesmo ID: {conf}"))
        d_arq = arqs[arq_por_flag[flag]][0]
        linhas.append(linha_recont("03c", f"{rotulo}_ids_distintos_no_arquivo", orig,
                                   int(d_arq[arqs[arq_por_flag[flag]][1]["id"]].nunique()), "COD_ID distintos no CSV da triagem"))
        sel = mt[mt[idc].isin(verdadeiros)]
        d_arq_m = arqs[arq_por_flag[flag]][1]
        for papel, col in (("ctmt", ctmt), ("sub", sub)):
            orig_n = int(d_arq[d_arq_m[papel]].nunique()) if papel in d_arq_m else None
            linhas.append(linha_recont("03c", f"{rotulo}_{papel}_distintos", orig_n, int(sel[col].nunique()),
                                       "união dos valores dos IDs selecionados"))
    ct_conf = mt.groupby(idc)[[ctmt, sub]].nunique()
    linhas.append(linha_recont("03c", "ids_com_conflito_ctmt_ou_sub", None, int((ct_conf > 1).any(axis=1).sum()),
                               "IDs MT com CTMT/SUB divergentes entre linhas"))
    return linhas, conflitos


def resolver_h1h4(df: pd.DataFrame, m: dict[str, str]) -> pd.DataFrame:
    """Uma linha por (hipótese, COD_ID): menor distância; conflito se CTMT/SUB/categoria divergirem."""
    d = df.copy()
    d["_dist"] = pd.to_numeric(d[m["dist"]], errors="coerce")
    for tag, papel in (("_ct", "ctmt"), ("_sb", "sub"), ("_cat", "cat")):
        d[tag] = d[m[papel]].fillna(NA_TOKEN)
    chave = [m["hip"], m["id"]]
    nun = d.groupby(chave)[["_ct", "_sb", "_cat"]].nunique()
    conflito = (nun > 1).any(axis=1)
    escolhido = (d.sort_values("_dist", na_position="last").drop_duplicates(chave, keep="first")
                 .set_index(chave))
    escolhido["conflito"] = conflito.reindex(escolhido.index).fillna(False)
    escolhido["categoria_final"] = escolhido[m["cat"]].where(~escolhido["conflito"], "conflito_ctmt_sub")
    return escolhido.reset_index()


def recontar_03d(df: pd.DataFrame, m: dict[str, str], resolvido: pd.DataFrame) -> list[dict[str, object]]:
    """Compara contagens originais (linhas) e recalculadas (IDs distintos) do 03d."""
    linhas: list[dict[str, object]] = []
    hip, idc, cat = m["hip"], m["id"], m["cat"]
    for h in sorted(df[hip].dropna().unique()):
        orig = df[df[hip] == h]
        rec = resolvido[resolvido[hip] == h]
        linhas.append(linha_recont("03d", f"{h}_total", len(orig), len(rec), "linhas x COD_ID distintos"))
        for c in CATEGORIAS:
            linhas.append(linha_recont("03d", f"{h}_{c}", int((orig[cat] == c).sum()),
                                       int((rec["categoria_final"] == c).sum())))
        linhas.append(linha_recont("03d", f"{h}_conflito_ctmt_sub", 0, int((rec["categoria_final"] == "conflito_ctmt_sub").sum()),
                                   "IDs com CTMT/SUB/categoria divergentes (não escolhidos por suposição)"))
    multi = resolvido.groupby(idc)[hip].nunique()
    linhas.append(linha_recont("03d", "ids_em_mais_de_uma_hipotese", None, int((multi > 1).sum())))
    return linhas


# --------------------------------------------------------------------------- #
# Objetivo 4: categorias não discriminantes
# --------------------------------------------------------------------------- #
def analisar_discriminacao(resolvido: pd.DataFrame, m: dict[str, str]) -> list[str]:
    """Distribuição de UCs distintas e CTMT por categoria; sinaliza apenas_sub não discriminante."""
    L: list[str] = []
    hip, sub, ct = m["hip"], m["sub"], m["ctmt"]
    for h in sorted(resolvido[hip].unique()):
        r = resolvido[(resolvido[hip] == h) & (~resolvido["conflito"])]
        total = len(r)
        L.append(f"  [{h}] UCs distintas sem conflito: {total}")
        for c in CATEGORIAS:
            s = r[r["categoria_final"] == c]
            L.append(f"    {c:<22} UCs={len(s):>5} CTMT distintos={s[ct].nunique():>3}")
        if total == 0:
            continue
        share = (r[sub].fillna(NA_TOKEN).value_counts() / total * 100).round(2)
        L.append("    participação de cada SUB no conjunto (%): " + ", ".join(f"{k}={v}" for k, v in share.items()))
        so = r[r["categoria_final"] == "coincide_apenas_sub"]
        subs_cat = set(so[sub].fillna(NA_TOKEN))
        dom = [(k, v) for k, v in share.items() if v > LIMIAR_NAO_DISCRIMINANTE_PCT and k in subs_cat]
        if len(so) == 0:
            L.append("    coincide_apenas_sub: sem UCs")
        elif dom:
            L.append(f"    coincide_apenas_sub: NÃO DISCRIMINANTE (SUB {dom} > {LIMIAR_NAO_DISCRIMINANTE_PCT:.0f}% das candidatas)")
        else:
            L.append(f"    coincide_apenas_sub: sem SUB acima de {LIMIAR_NAO_DISCRIMINANTE_PCT:.0f}% das candidatas")
    return L


# --------------------------------------------------------------------------- #
# Objetivo 5: CNAE 86 até 500 m
# --------------------------------------------------------------------------- #
def listar_cnae_saude(df: pd.DataFrame, m: dict[str, str]) -> pd.DataFrame:
    """UCs com CNAE 86 e distância <= 500 m (sem reclassificar), uma linha por COD_ID."""
    d = df.copy()
    d["_dist"] = pd.to_numeric(d[m["dist"]], errors="coerce")
    d = d[norm_cnae(d[m["cnae"]]).str.startswith("86") & (d["_dist"] <= RAIO_CNAE_M)]
    idc = m["id"]
    contagem = d.groupby(idc).size().rename("n_linhas_origem")
    hips = d.groupby(idc)[m["hip"]].agg(lambda s: ";".join(sorted(set(s)))).rename("hipoteses")
    nun = d.groupby(idc)[[m["ctmt"], m["sub"], m["clas_sub"]]].nunique().gt(1).any(axis=1).rename("conflito_entre_linhas")
    esc = d.sort_values("_dist").drop_duplicates(idc, keep="first").set_index(idc)
    out = esc.join([contagem, hips, nun]).reset_index()

    def fatos(r: pd.Series) -> str:
        itens = [f"CNAE iniciado em 86 ({r[m['cnae']]})", f"distância {r['_dist']:.1f} m <= {RAIO_CNAE_M:.0f} m",
                 f"CLAS_SUB={r[m['clas_sub']]}" + (" (PP/SP)" if str(r[m['clas_sub']]).upper().startswith(PREFIXOS_PUBLICA) else " (não PP/SP)"),
                 f"CTMT={r[m['ctmt']]}", f"SUB={r[m['sub']]}"]
        for papel in ("car_inst", "dem_cont"):
            v = r.get(m[papel]) if papel in m else None
            itens.append(f"{papel.upper()}=" + ("ausente" if pd.isna(v) else str(v)))
        if r["n_linhas_origem"] > 1:
            itens.append(f"{int(r['n_linhas_origem'])} linhas no arquivo")
        return "; ".join(itens)

    out["fatos_verificaveis"] = out.apply(fatos, axis=1)
    cols = [idc, m["origem"], m["clas_sub"], m["cnae"], m["ctmt"], m["sub"], m["car_inst"], m["dem_cont"],
            m["dist"], "hipoteses", "n_linhas_origem", "conflito_entre_linhas", "fatos_verificaveis"]
    return out[[c for c in cols if c in out.columns]].sort_values(m["dist"], key=lambda s: pd.to_numeric(s)).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Relatório
# --------------------------------------------------------------------------- #
def escrever_relatorio(ctx: dict[str, object]) -> None:
    """Escreve o relatório textual da auditoria."""
    c = ctx
    contagem: pd.DataFrame = c["contagem"]  # type: ignore[assignment]
    extras: dict = c["extras"]  # type: ignore[assignment]
    L: list[str] = ["=" * 80, "RELATÓRIO DE AUDITORIA DE DUPLICIDADE DE UCs (03b/03c/03d)", "=" * 80,
                    f"Data/hora: {datetime.now():%Y-%m-%d %H:%M:%S} | Duração: {c['duracao']:.1f} s", "",
                    "1. SHA-256 (antes -> depois)"]
    for k, a in c["hash_antes"].items():  # type: ignore[union-attr]
        d = c["hash_depois"][k]  # type: ignore[index]
        L.append(f"  {k}: {'INALTERADO' if a == d else 'ALTERADO!'} ({a})")
    L += ["  (o .gdb não foi aberto nem hasheado nesta etapa)", "",
          "2. CONTAGEM POR ARQUIVO E TABELA"]
    L.append(contagem.to_string(index=False))
    L += ["", "3. PADRÕES DE COLUNAS DIVERGENTES POR COD_ID (colunas que variam -> nº de IDs)"]
    for (arq, tab), ex in extras.items():
        pad: Counter = ex["padroes"]  # type: ignore[assignment]
        if not pad:
            continue
        L.append(f"  {arq}/{tab}:")
        for cols, n in pad.most_common():
            tipo = ("só vínculo" if all(x.lower() in COLS_VINCULO or x.lower() in ("pn_con", "uni_tr_mt") for x in cols)
                    else "envolve campos cadastrais/derivados")
            L.append(f"    {n:>6} IDs: {', '.join(cols)}  [{tipo}]")
    L += ["  Interpretação (INFERIDA): variação só em PN_CON/UNI_TR_MT sugere várias associações por UC;",
          "  variação em CLAS_SUB, CNAE, CTMT ou SUB indicaria conflito cadastral.", "",
          "4. HIPÓTESES DE CAUSA"]
    L.append("  D1 (PN_CON com mais de uma correspondência em PONNOT.COD_ID): NÃO TESTADA — exigiria abrir o .gdb (proibido nesta etapa).")
    L.append("     Proxy medido nos CSVs: COD_ID com mais de um PN_CON (nulos excluídos; incluindo nulos como valor):")
    for (arq, tab), ex in extras.items():
        L.append(f"       {arq}/{tab}: D1proxy={ex.get('D1proxy_pn_con')} D2(UNI_TR_MT)={ex.get('D2_uni_tr_mt')} D3(CTMT)={ex.get('D3_ctmt')}")
    L.append("  Formato das tuplas: (IDs sem contar nulos, IDs contando nulo como valor); None = coluna ausente no arquivo.")
    L.append("  Leitura do código (confirmado no texto dos scripts; contagens de merge/sjoin/isin):")
    for nome, v in c["scripts"].items():  # type: ignore[union-attr]
        L.append(f"    {nome}: {v}")
    L.append("  Os filtros por .isin() em conjuntos NÃO multiplicam linhas; sem merge/sjoin, a duplicação não nasce de join nesses scripts (INFERIDO).")
    L.append(f"  Causa: {c['causa']}")
    L += ["", "5. RECONTAGEM (original = linhas; recalculado = COD_ID distintos)"]
    L.append(c["recont"].to_string(index=False))  # type: ignore[union-attr]
    L += ["", "6. CATEGORIAS DE CRUZAMENTO: UCs distintas, CTMT e dominância de SUB"]
    L += c["discriminacao"]  # type: ignore[operator]
    L += ["  Os percentuais acima não alteram a classificação original.", "",
          "7. UCs COM CNAE 86 A ATÉ 500 m (fatos verificáveis; nenhuma conclusão sobre o HRC)"]
    cn: pd.DataFrame = c["cnae500"]  # type: ignore[assignment]
    L.append(f"  Total (COD_ID distintos): {len(cn)}")
    for _, r in cn.iterrows():
        L.append(f"  - {r.iloc[0]}\n      {r['fatos_verificaveis']}")
    L += ["", "8. LIMITAÇÕES",
          "  - D1 não testada (.gdb não aberto); causa raiz na tabela de origem não confirmada pelo .gdb.",
          "  - Distância existe apenas no CSV do 03d (UCs MT/BT de H1 a H4); UCAT não tem candidatas.",
          "  - Cadastro estático; CNAE pode estar desatualizado; proximidade não prova atendimento.",
          "  - Identificação da UC do HRC depende de fatura, código da conta contrato ou cadastro.",
          "  - Conflitos de CTMT/SUB entre linhas do mesmo COD_ID não foram resolvidos por suposição.", "=" * 80]
    OUT_RELATORIO.write_text("\n".join(L) + "\n", encoding="utf-8")
    logger.info("Relatório salvo em %s", OUT_RELATORIO)


def inferir_causa(extras: dict, contagem: pd.DataFrame) -> str:
    """Resume a causa observável sem presumir além dos dados."""
    partes: list[str] = []
    for (arq, tab), ex in extras.items():
        if arq != "perfil_ucs_entorno_hrc":
            continue
        pad: Counter = ex["padroes"]  # type: ignore[assignment]
        so_vinc = sum(n for cols, n in pad.items() if cols and all(x.lower() in COLS_VINCULO for x in cols))
        cad = sum(n for cols, n in pad.items() if any(x.lower() in COLS_CADASTRAIS for x in cols))
        red = int(contagem[(contagem.arquivo == arq) & (contagem.tabela == tab)]["linhas_identicas_redundantes"].iloc[0])
        partes.append(f"{tab}: IDs divergentes só em colunas de vínculo={so_vinc}; envolvendo campos cadastrais={cad}; "
                      f"linhas idênticas redundantes={red}")
    return ("; ".join(partes) + ". Linhas idênticas e variação de vínculo não foram atribuídas a D1 (não testada); "
            "se não houver D2/D3 nos contadores acima, a causa permanece não identificada.")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    """Executa a auditoria. 0=sucesso, 1=erro."""
    inicio = time.perf_counter()
    configurar_logging(LOGS_DIR / f"auditoria_duplicidade_hrc_{datetime.now():%Y%m%d_%H%M%S}.log")
    logger.info("Início da auditoria de duplicidade (somente leitura; .gdb não aberto).")
    try:
        for nome, p in ENTRADAS.items():
            if not p.exists():
                raise FileNotFoundError(f"Entrada ausente: {p}")
        verificar_saidas()
        hash_antes, caminhos = coletar_hashes()
        dados = {n: ler_entrada(n, p) for n, p in ENTRADAS.items()}

        contagem, divergencias, extras = auditar_todos(dados)
        scripts = varrer_scripts()
        causa = inferir_causa(extras, contagem)

        perfil, mp = dados["perfil_ucs_entorno_hrc"]
        lin03c, _ = recontar_03c(perfil, mp, dados)
        h, mh = dados["hipoteses_h1_h4"]
        for papel in ("hip", "cat", "dist", "ctmt", "sub"):
            if papel not in mh:
                raise KeyError(f"hipoteses_h1_h4 sem coluna '{papel}'.")
        resolvido = resolver_h1h4(h, mh)
        lin03d = recontar_03d(h, mh, resolvido)
        recont = pd.DataFrame(lin03c + lin03d)
        discr = analisar_discriminacao(resolvido, mh)
        cnae500 = listar_cnae_saude(h, mh)

        contagem.to_csv(OUT_CONTAGEM, index=False, encoding="utf-8", mode="x")
        divergencias.to_csv(OUT_DUP_COLUNAS, index=False, encoding="utf-8", mode="x")
        recont.to_csv(OUT_RECONTAGEM, index=False, encoding="utf-8", mode="x")
        cnae500.to_csv(OUT_CNAE500, index=False, encoding="utf-8", mode="x")
        logger.info("CSVs gravados (contagem=%d, divergências=%d, recontagem=%d, cnae500=%d linhas)",
                    len(contagem), len(divergencias), len(recont), len(cnae500))

        hash_depois = {k: sha256(p) for k, p in caminhos.items()}
        alterados = [k for k in hash_antes if hash_antes[k] != hash_depois[k]]
        if alterados:
            logger.error("Entradas alteradas: %s", alterados)
            return 1
        escrever_relatorio({
            "duracao": time.perf_counter() - inicio, "hash_antes": hash_antes, "hash_depois": hash_depois,
            "contagem": contagem, "extras": extras, "scripts": scripts, "causa": causa,
            "recont": recont, "discriminacao": discr, "cnae500": cnae500,
        })
    except (FileNotFoundError, FileExistsError, KeyError, ValueError) as exc:
        logger.error("Execução interrompida: %s", exc)
        return 1
    except Exception:
        logger.exception("Erro inesperado na auditoria.")
        return 1
    logger.info("Concluído em %.1f s.", time.perf_counter() - inicio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
