"""Teste de hipóteses sobre o alimentador do HRC (somente leitura, sem conclusão).

Gera ranking/evidências separadas para as hipóteses H1-H5. Nenhuma hipótese é
confirmada por este script: ele NÃO identifica a UC do HRC, NÃO constrói grafo
topológico e NÃO conclui conectividade ou atendimento elétrico.
"""

import hashlib
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"

GPKG_PATH: Path = PROCESSED_DIR / "subrede_hospitais.gpkg"
CSV_HOSPITAIS: Path = RAW_DIR / "hospitais_df.csv"
PERFIL_CSV: Path = PROCESSED_DIR / "perfil_ucs_entorno_hrc.csv"

OUT_H1H4: Path = PROCESSED_DIR / "hipoteses_h1_h4_ucs_candidatas_hrc.csv"
OUT_H5: Path = PROCESSED_DIR / "hipoteses_h5_subestacao_e_circuitos_hrc.csv"
OUT_DIST: Path = PROCESSED_DIR / "distribuicao_clas_sub_entorno_hrc.csv"
OUT_REL: Path = PROCESSED_DIR / "relatorio_hipoteses_alimentador_hrc.txt"
SAIDAS: tuple[Path, ...] = (OUT_H1H4, OUT_H5, OUT_DIST, OUT_REL)

CRS_TRABALHO: int = 31983
CRS_ORIGEM: int = 4674
N_SEGMENTOS: int = 20
RAIOS_BUSCA_M: tuple[float, ...] = (500.0, 1_000.0, 2_000.0, 4_000.0, 8_000.0)
MARGEM_PONNOT_M: float = 1_500.0
PREFIXOS_PUBLICA: tuple[str, ...] = ("PP", "SP")
PREFIXO_SAUDE: str = "86"
PREFIXO_ADM_PUBLICA: str = "84"

# Camada -> nomes aceitos (minúsculas)
CAMADAS: dict[str, tuple[str, ...]] = {
    "SUB": ("sub",), "SSDMT": ("ssdmt",), "SSDBT": ("ssdbt",), "UNTRMT": ("untrmt",),
    "UCMT": ("ucmt_tab", "ucmt"), "UCBT": ("ucbt_tab", "ucbt"),
    "PONNOT": ("ponnot",), "CTMT": ("ctmt",), "UCAT": ("ucat_tab", "ucat"),
}
CAMADAS_OBRIGATORIAS: tuple[str, ...] = ("SUB", "SSDMT", "PONNOT")

ALIASES_PERFIL: dict[str, tuple[str, ...]] = {
    "id": ("cod_id", "id"), "origem": ("tabela_origem", "origem"),
    "clas_sub": ("clas_sub",), "cnae": ("cnae",), "ctmt": ("ctmt",), "sub": ("sub",),
    "car_inst": ("car_inst",), "dem_cont": ("dem_cont",),
    "pn_con": ("pn_con",), "uni_tr_mt": ("uni_tr_mt",),
}
ALIASES_UCAT: dict[str, tuple[str, ...]] = {
    "id": ("cod_id", "id"), "clas_sub": ("clas_sub",), "cnae": ("cnae",),
    "ctat": ("ctat",), "sub": ("sub",), "car_inst": ("car_inst",),
    "dem_cont": ("dem_cont",), "pn_con": ("pn_con",),
}
ALIASES_SSDMT: dict[str, tuple[str, ...]] = {
    "id": ("cod_id", "id"), "ctmt": ("ctmt",), "sub": ("sub",),
}
ALIASES_SUB: dict[str, tuple[str, ...]] = {"id": ("cod_id", "id"), "nome": ("nome",)}
ALIASES_CTMT: dict[str, tuple[str, ...]] = {
    "id": ("cod_id", "id"), "nome": ("nome",), "sub": ("sub",),
}
ALIASES_PONNOT: dict[str, tuple[str, ...]] = {"id": ("cod_id", "id")}

logger = logging.getLogger("hipoteses_alimentador_hrc")


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


def sha256_arquivo(caminho: Path) -> str:
    """SHA-256 de um arquivo."""
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def sha256_entrada(caminho: Path) -> str:
    """SHA-256 de arquivo ou composto determinístico dos arquivos de um diretório (.gdb)."""
    if not caminho.is_dir():
        return sha256_arquivo(caminho)
    h = hashlib.sha256()
    for arq in sorted(p for p in caminho.iterdir() if p.is_file()):
        h.update(arq.name.encode())
        h.update(str(arq.stat().st_size).encode())
        h.update(sha256_arquivo(arq).encode())
    return h.hexdigest()


def coletar_hashes(gdb: Path) -> dict[str, str]:
    """Hash de entradas principais e de todos os arquivos já existentes em data/processed."""
    hashes = {f"gdb:{gdb.name}": sha256_entrada(gdb), f"raw:{CSV_HOSPITAIS.name}": sha256_arquivo(CSV_HOSPITAIS)}
    for p in sorted(PROCESSED_DIR.iterdir()):
        if p.is_file() and p not in SAIDAS:
            hashes[f"processed:{p.name}"] = sha256_arquivo(p)
    return hashes


def verificar_saidas() -> None:
    """Impede sobrescrita de artefatos."""
    existentes = [p.name for p in SAIDAS if p.exists()]
    if existentes:
        raise FileExistsError(f"Artefatos já existem: {existentes}. Mova/renomeie antes de reexecutar.")


def mapear(cols: list[str], aliases: dict[str, tuple[str, ...]]) -> tuple[dict[str, str], list[str]]:
    """Mapeia papéis para colunas reais (sem diferenciar caixa); devolve (mapa, ausentes)."""
    low = {c.strip().lower(): c for c in cols}
    mapa: dict[str, str] = {}
    ausentes: list[str] = []
    for papel, opcoes in aliases.items():
        real = next((low[o] for o in opcoes if o in low), None)
        if real:
            mapa[papel] = real
        else:
            ausentes.append(papel)
    return mapa, ausentes


def norm_cnae(s: pd.Series) -> pd.Series:
    """CNAE sem pontos, hífens, barras e espaços."""
    return s.fillna("").astype(str).str.replace(r"[\s.\-/]", "", regex=True)


def norm_classe(s: pd.Series) -> pd.Series:
    """Classe/subclasse em maiúsculas sem espaços."""
    return s.fillna("").astype(str).str.strip().str.upper()


# --------------------------------------------------------------------------- #
# Descoberta
# --------------------------------------------------------------------------- #
def localizar_gdb() -> Path:
    """Localiza a .gdb em data/raw."""
    gdbs = sorted(p for p in RAW_DIR.glob("*.gdb") if p.is_dir())
    if not gdbs:
        raise FileNotFoundError(f"Nenhuma .gdb em {RAW_DIR}")
    return gdbs[0]


def descobrir_camadas(gdb: Path) -> tuple[dict[str, Optional[str]], list[str]]:
    """Resolve camadas esperadas; devolve (mapa nome esperado -> nome real|None, ausentes)."""
    reais = {str(n).lower(): str(n) for n, _ in pyogrio.list_layers(gdb)}
    mapa: dict[str, Optional[str]] = {}
    for chave, opcoes in CAMADAS.items():
        mapa[chave] = next((reais[o] for o in opcoes if o in reais), None)
    ausentes = [k for k, v in mapa.items() if v is None]
    for k, v in mapa.items():
        logger.info("Camada %s -> %s", k, v if v else "AUSENTE")
    return mapa, ausentes


def ler_gdb(gdb: Path, camada: str, aliases: dict[str, tuple[str, ...]], **kwargs) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """Lê camada do gdb (com bbox/where opcionais) só com as colunas mapeadas."""
    campos = list(pyogrio.read_info(gdb, layer=camada)["fields"])
    mapa, ausentes = mapear(campos, aliases)
    df = pyogrio.read_dataframe(gdb, layer=camada, columns=list(mapa.values()), **kwargs)
    return df, mapa, ausentes


# --------------------------------------------------------------------------- #
# HRC
# --------------------------------------------------------------------------- #
def obter_hrc() -> tuple[Point, BaseGeometry, str]:
    """Ponto, buffer (EPSG:31983) e nome do hospital a partir do GeoPackage."""
    nomes = [str(n) for n, _ in pyogrio.list_layers(GPKG_PATH)]
    l_hosp = next(n for n in nomes if n.lower().startswith("hospita"))
    l_buf = next(n for n in nomes if n.lower().startswith("buffer"))
    hosp = gpd.read_file(GPKG_PATH, layer=l_hosp, engine="pyogrio")
    buf = gpd.read_file(GPKG_PATH, layer=l_buf, engine="pyogrio")
    if hosp.crs is None or buf.crs is None:
        raise ValueError("Camadas do GeoPackage sem CRS.")
    hosp, buf = hosp.to_crs(epsg=CRS_TRABALHO), buf.to_crs(epsg=CRS_TRABALHO)
    ponto = hosp.geometry.iloc[0]
    nome = str(hosp["nome"].iloc[0]) if "nome" in hosp.columns else "(sem nome)"
    return ponto, buf.geometry.union_all(), nome


def confirmar_nome_csv(nome_gpkg: str) -> bool:
    """Confirma que o nome do GeoPackage consta no CSV de hospitais."""
    df = pd.read_csv(CSV_HOSPITAIS, dtype=str)
    col = next((c for c in df.columns if c.strip().lower() in ("nome", "name", "hospital")), None)
    if col is None:
        logger.warning("CSV de hospitais sem coluna de nome.")
        return False
    ok = nome_gpkg.strip().casefold() in {v.strip().casefold() for v in df[col].dropna()}
    logger.info("Nome do hospital (%s) %s no CSV.", nome_gpkg, "confirmado" if ok else "NÃO encontrado")
    return ok


def bbox_4674(geom_31983: BaseGeometry) -> tuple[float, float, float, float]:
    """Bounding box em EPSG:4674 de uma geometria em EPSG:31983."""
    b = gpd.GeoSeries([geom_31983], crs=CRS_TRABALHO).to_crs(epsg=CRS_ORIGEM).total_bounds
    return tuple(float(v) for v in b)


def carregar_ponnot(gdb: Path, camada: str, buffer: BaseGeometry) -> tuple[dict[str, Point], int]:
    """Pontos de PONNOT na janela do buffer + margem (bbox); devolve (dict id->ponto, n lidos)."""
    janela = buffer.buffer(MARGEM_PONNOT_M)
    campos = list(pyogrio.read_info(gdb, layer=camada)["fields"])
    mapa, _ = mapear(campos, ALIASES_PONNOT)
    gdf = pyogrio.read_dataframe(gdb, layer=camada, columns=[mapa["id"]], bbox=bbox_4674(janela))
    gdf = gdf.to_crs(epsg=CRS_TRABALHO)
    pts = {str(i): g for i, g in zip(gdf[mapa["id"]], gdf.geometry)}
    logger.info("PONNOT na janela (buffer + %.0f m): %d", MARGEM_PONNOT_M, len(pts))
    return pts, len(gdf)


# --------------------------------------------------------------------------- #
# H5
# --------------------------------------------------------------------------- #
def testar_h5(
    gdb: Path, camadas: dict[str, Optional[str]], ponto: Point
) -> dict[str, object]:
    """Subestação que contém o HRC e 20 segmentos SSDMT mais próximos, agregados por CTMT."""
    res: dict[str, object] = {}
    sub_df, sub_map, _ = ler_gdb(gdb, camadas["SUB"], ALIASES_SUB)
    sub_df = sub_df.to_crs(epsg=CRS_TRABALHO)
    cont = sub_df[sub_df.geometry.contains(ponto)]
    res["sub_contem"] = cont
    res["sub_map"] = sub_map
    sub_df["dist_m"] = sub_df.geometry.distance(ponto)
    res["sub_proxima"] = sub_df.sort_values("dist_m").head(3)
    logger.info("Polígonos SUB que contêm o HRC: %d | SUB lidos: %d", len(cont), len(sub_df))

    seg, seg_map, aus = None, {}, []
    exato = False
    for raio in RAIOS_BUSCA_M:
        janela = box(ponto.x - raio, ponto.y - raio, ponto.x + raio, ponto.y + raio)
        seg, seg_map, aus = ler_gdb(gdb, camadas["SSDMT"], ALIASES_SSDMT, bbox=bbox_4674(janela))
        if len(seg) < N_SEGMENTOS:
            continue
        seg = seg.to_crs(epsg=CRS_TRABALHO)
        seg["dist_m"] = seg.geometry.distance(ponto)
        seg = seg.sort_values("dist_m").head(N_SEGMENTOS).reset_index(drop=True)
        if seg["dist_m"].iloc[-1] <= raio:
            exato = True
            res["raio_busca"] = raio
            break
    if seg is None or "dist_m" not in seg.columns:
        raise RuntimeError("Não foi possível obter 20 segmentos SSDMT próximos nos raios testados.")
    res["segmentos"], res["seg_map"], res["seg_ausentes"], res["exato"] = seg, seg_map, aus, exato
    ct = seg_map.get("ctmt")
    if ct:
        agg = seg.groupby(ct).agg(n_segmentos=("dist_m", "size"), dist_min_m=("dist_m", "min")).reset_index()
        res["circuitos"] = agg.sort_values(["dist_min_m", "n_segmentos"], ascending=[True, False]).reset_index(drop=True)
    else:
        res["circuitos"] = pd.DataFrame(columns=["ctmt", "n_segmentos", "dist_min_m"])
    return res


def montar_csv_h5(h5: dict[str, object], ctmt_info: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """Unifica subestação, segmentos e circuitos agregados em uma tabela."""
    linhas: list[dict[str, object]] = []
    sub_map: dict[str, str] = h5["sub_map"]  # type: ignore[assignment]
    cont: gpd.GeoDataFrame = h5["sub_contem"]  # type: ignore[assignment]
    if cont.empty:
        linhas.append({"tipo_registro": "subestacao_contem_hrc", "observacao": "Nenhum polígono SUB contém o ponto do HRC"})
    for _, r in cont.iterrows():
        linhas.append({"tipo_registro": "subestacao_contem_hrc", "cod_id": r.get(sub_map.get("id")),
                       "nome": r.get(sub_map.get("nome")), "area_m2": r.geometry.area,
                       "geometria_tipo": r.geometry.geom_type})
    prox: gpd.GeoDataFrame = h5["sub_proxima"]  # type: ignore[assignment]
    for i, (_, r) in enumerate(prox.iterrows(), 1):
        linhas.append({"tipo_registro": "subestacao_mais_proxima_informativo", "rank": i,
                       "cod_id": r.get(sub_map.get("id")), "nome": r.get(sub_map.get("nome")),
                       "distancia_m": r["dist_m"], "area_m2": r.geometry.area,
                       "geometria_tipo": r.geometry.geom_type,
                       "observacao": "Informativo: proximidade ao polígono, não contenção"})
    seg: gpd.GeoDataFrame = h5["segmentos"]  # type: ignore[assignment]
    smap: dict[str, str] = h5["seg_map"]  # type: ignore[assignment]
    for i, r in seg.iterrows():
        linhas.append({"tipo_registro": "segmento_ssdmt", "rank": int(i) + 1,
                       "cod_id": r.get(smap.get("id")), "ctmt": r.get(smap.get("ctmt")),
                       "sub": r.get(smap.get("sub")), "distancia_m": r["dist_m"],
                       "geometria_tipo": r.geometry.geom_type})
    circ: pd.DataFrame = h5["circuitos"]  # type: ignore[assignment]
    ct = smap.get("ctmt")
    for i, r in circ.iterrows():
        cod = str(r[ct]) if ct else ""
        nome, sub_cad = ctmt_info.get(cod, ("", ""))
        linhas.append({"tipo_registro": "circuito_agregado", "rank": int(i) + 1, "ctmt": cod,
                       "n_segmentos": int(r["n_segmentos"]), "dist_min_m": r["dist_min_m"],
                       "nome": nome, "sub": sub_cad,
                       "observacao": "SUB/nome vindos da tabela CTMT (cadastro)"})
    cols = ["tipo_registro", "rank", "cod_id", "ctmt", "sub", "nome", "distancia_m", "dist_min_m",
            "n_segmentos", "area_m2", "geometria_tipo", "observacao"]
    return pd.DataFrame(linhas).reindex(columns=cols)


# --------------------------------------------------------------------------- #
# H1-H4
# --------------------------------------------------------------------------- #
def carregar_perfil() -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """Lê o perfil de UCs como texto e mapeia colunas."""
    df = pd.read_csv(PERFIL_CSV, dtype=str)
    mapa, aus = mapear(list(df.columns), ALIASES_PERFIL)
    faltam = [p for p in ("id", "origem", "clas_sub", "cnae", "ctmt", "sub", "pn_con") if p in aus]
    if faltam:
        raise KeyError(f"Colunas ausentes no perfil: {faltam}. Cabeçalho: {list(df.columns)}")
    for p in ("car_inst", "dem_cont"):
        if p in mapa:
            df[mapa[p]] = pd.to_numeric(df[mapa[p]], errors="coerce")
    return df, mapa, aus


def padronizar(df: pd.DataFrame, mapa: dict[str, str], tabela: str) -> pd.DataFrame:
    """Converte para esquema comum de candidatas."""
    g = lambda p: df[mapa[p]] if p in mapa else pd.Series([None] * len(df), index=df.index)  # noqa: E731
    return pd.DataFrame({
        "identificador": g("id"), "tabela_origem": tabela, "clas_sub": g("clas_sub"),
        "cnae": g("cnae"), "ctmt": g("ctmt") if "ctmt" in mapa else None, "sub": g("sub"),
        "pn_con": g("pn_con"), "car_inst": g("car_inst"), "dem_cont": g("dem_cont"),
    }, index=df.index)


def selecionar_h1_h2_h4(perfil: pd.DataFrame, mapa: dict[str, str]) -> dict[str, pd.DataFrame]:
    """Aplica critérios H1, H2 e H4 ao perfil do entorno."""
    origem = perfil[mapa["origem"]].fillna("").str.upper()
    cnae, classe = norm_cnae(perfil[mapa["cnae"]]), norm_classe(perfil[mapa["clas_sub"]])
    pub = classe.str.startswith(PREFIXOS_PUBLICA)
    saude, adm = cnae.str.startswith(PREFIXO_SAUDE), cnae.str.startswith(PREFIXO_ADM_PUBLICA)
    mt, bt = origem.str.contains("UCMT"), origem.str.contains("UCBT")
    h1 = padronizar(perfil[mt & saude & ~pub], mapa, "UCMT_tab").assign(hipotese="H1", criterio_atendido="cnae86_e_classe_fora_PP_SP")
    h2 = padronizar(perfil[mt & pub & adm], mapa, "UCMT_tab").assign(hipotese="H2", criterio_atendido="PP_SP_e_cnae84")
    sel4 = bt & (saude | pub)
    crit4 = pd.Series("", index=perfil.index)
    crit4[sel4 & saude & pub] = "cnae86+PP_SP"
    crit4[sel4 & saude & ~pub] = "cnae86"
    crit4[sel4 & ~saude & pub] = "PP_SP"
    h4 = padronizar(perfil[sel4], mapa, "UCBT_tab").assign(hipotese="H4", criterio_atendido=crit4[sel4])
    logger.info("H1=%d H2=%d H4=%d | MT com CNAE86 e PP/SP: %d", len(h1), len(h2), len(h4),
                int((mt & saude & pub).sum()))
    return {"H1": h1, "H2": h2, "H4": h4, "mt_saude_pub": pd.DataFrame({"n": [int((mt & saude & pub).sum())]})}


def testar_h3(gdb: Path, camada: Optional[str], buffer: BaseGeometry, pontos: dict[str, Point]) -> tuple[pd.DataFrame, dict[str, object]]:
    """UCAT no entorno (via PN_CON -> PONNOT) com CNAE 86 e classe PP/SP."""
    info: dict[str, object] = {"existe": camada is not None}
    if camada is None:
        return pd.DataFrame(), info
    df, mapa, aus = ler_gdb(gdb, camada, ALIASES_UCAT)
    info.update(total=len(df), mapa=mapa, ausentes=aus)
    if "pn_con" not in mapa:
        info["entorno"] = None
        return pd.DataFrame(), info
    pn = df[mapa["pn_con"]].astype(str)
    achou = pn.isin(pontos)
    dentro = pn.map(lambda k: bool(k in pontos and buffer.covers(pontos[k])))
    info.update(vinculadas_ponnot=int(achou.sum()), entorno=int(dentro.sum()))
    en = df[dentro]
    info["df_entorno"], info["mapa_df"] = en, mapa
    classe = norm_classe(en[mapa["clas_sub"]])
    sel = norm_cnae(en[mapa["cnae"]]).str.startswith(PREFIXO_SAUDE) & classe.str.startswith(PREFIXOS_PUBLICA)
    h3 = padronizar(en[sel], {**mapa, "ctmt": mapa.get("ctat", "")} if "ctat" in mapa else mapa, "UCAT_tab")
    if "ctat" not in mapa:
        h3["ctmt"] = None
    h3["hipotese"], h3["criterio_atendido"] = "H3", "cnae86_e_PP_SP"
    return h3, info


def adicionar_distancia(df: pd.DataFrame, pontos: dict[str, Point], ponto: Point) -> pd.DataFrame:
    """Distância UC->HRC via PN_CON -> PONNOT (NaN se o poste não estiver na janela lida)."""
    out = df.copy()
    out["distancia_hrc_m"] = out["pn_con"].map(lambda k: ponto.distance(pontos[str(k)]) if str(k) in pontos else float("nan"))
    return out


def categorizar(df: pd.DataFrame, circuitos: set[str], subs_ref: set[str]) -> pd.DataFrame:
    """Categoria de cruzamento (não é prova de atendimento)."""
    out = df.copy()
    ok_ct = out["ctmt"].astype(str).isin(circuitos) & out["ctmt"].notna()
    ok_sb = out["sub"].astype(str).isin(subs_ref) & out["sub"].notna()
    out["categoria_cruzamento"] = "sem_coincidencia"
    out.loc[ok_sb & ~ok_ct, "categoria_cruzamento"] = "coincide_apenas_sub"
    out.loc[ok_ct & ~ok_sb, "categoria_cruzamento"] = "coincide_apenas_ctmt"
    out.loc[ok_ct & ok_sb, "categoria_cruzamento"] = "coincide_ctmt_e_sub"
    return out


def distribuicao_clas_sub(perfil: pd.DataFrame, mapa: dict[str, str], h3_info: dict[str, object]) -> pd.DataFrame:
    """Contagem de CLAS_SUB no entorno por tabela (MT, BT e AT)."""
    linhas: list[pd.DataFrame] = []
    origem = perfil[mapa["origem"]].fillna("")
    for nome in sorted(origem.unique()):
        s = perfil.loc[origem == nome, mapa["clas_sub"]].fillna("(nulo)")
        c = s.value_counts().rename_axis("clas_sub").reset_index(name="n")
        c.insert(0, "tabela", nome)
        c["pct_tabela"] = (c["n"] / c["n"].sum() * 100).round(3)
        linhas.append(c)
    en = h3_info.get("df_entorno")
    if isinstance(en, pd.DataFrame) and not en.empty:
        mp: dict[str, str] = h3_info["mapa_df"]  # type: ignore[assignment]
        c = en[mp["clas_sub"]].fillna("(nulo)").value_counts().rename_axis("clas_sub").reset_index(name="n")
        c.insert(0, "tabela", "UCAT_tab")
        c["pct_tabela"] = (c["n"] / c["n"].sum() * 100).round(3)
        linhas.append(c)
    elif h3_info.get("existe"):
        linhas.append(pd.DataFrame([{"tabela": "UCAT_tab", "clas_sub": "(nenhuma UC no entorno)", "n": 0, "pct_tabela": 0.0}]))
    return pd.concat(linhas, ignore_index=True)


# --------------------------------------------------------------------------- #
# Relatório
# --------------------------------------------------------------------------- #
def escrever_relatorio(ctx: dict[str, object]) -> None:
    """Escreve o relatório textual (evidências separadas, sem conclusão de atendimento)."""
    c = ctx
    h5: dict[str, object] = c["h5"]  # type: ignore[assignment]
    cand: pd.DataFrame = c["cand"]  # type: ignore[assignment]
    L: list[str] = ["=" * 80, "RELATÓRIO DE HIPÓTESES SOBRE O ALIMENTADOR DO HRC (EVIDÊNCIAS, NÃO CONCLUSÕES)", "=" * 80,
                    f"Data/hora: {datetime.now():%Y-%m-%d %H:%M:%S} | Duração: {c['duracao']:.1f} s",
                    f"Hospital (GeoPackage): {c['nome']} | nome presente no CSV: {c['nome_ok']}", "",
                    "1. ENTRADAS E SHA-256 (antes -> depois)"]
    for k, a in c["hash_antes"].items():  # type: ignore[union-attr]
        d = c["hash_depois"].get(k, "")  # type: ignore[union-attr]
        L.append(f"  {k}: {'INALTERADO' if a == d else 'ALTERADO!'}\n      antes : {a}\n      depois: {d}")
    L += [f"  GeoPackage ({GPKG_PATH.name}): {c['gpkg_antes']} -> {c['gpkg_depois']}",
          f"  Perfil UCs ({PERFIL_CSV.name}): {c['perfil_antes']} -> {c['perfil_depois']}", "",
          "2. CAMADAS E COLUNAS"]
    for k, v in c["camadas"].items():  # type: ignore[union-attr]
        L.append(f"  {k:<7} -> {v if v else 'AUSENTE'}")
    L.append(f"  Mapeamento perfil UCs: {c['mapa_perfil']} (ausentes: {c['aus_perfil']})")
    L.append(f"  Mapeamento SSDMT: {h5['seg_map']} (ausentes: {h5['seg_ausentes']})")
    L.append(f"  Mapeamento SUB: {h5['sub_map']}")
    L.append("")
    L += ["3. RESULTADO POR HIPÓTESE (contagens)"]
    L.append(f"  H1 (MT, CNAE 86, classe fora PP/SP): {c['n']['H1']}")  # type: ignore[index]
    L.append(f"     MT com CNAE 86 e classe PP/SP (fora de H1 por definição): {c['n']['mt_saude_pub']}")  # type: ignore[index]
    L.append(f"  H2 (MT, PP/SP e CNAE 84): {c['n']['H2']}")  # type: ignore[index]
    i3 = c["h3_info"]  # type: ignore[assignment]
    if i3.get("existe"):  # type: ignore[union-attr]
        L.append(f"  H3 (UCAT): tabela existe, {i3.get('total')} registros; vinculadas a PONNOT na janela: "  # type: ignore[union-attr]
                 f"{i3.get('vinculadas_ponnot')}; no entorno: {i3.get('entorno')}; triadas (CNAE 86 e PP/SP): {c['n']['H3']}")  # type: ignore[index,union-attr]
        L.append(f"     Mapeamento UCAT: {i3.get('mapa')} (ausentes: {i3.get('ausentes')})")  # type: ignore[union-attr]
    else:
        L.append("  H3 (UCAT): tabela AUSENTE no .gdb")
    L.append(f"  H4 (UCBT, CNAE 86 ou PP/SP): {c['n']['H4']}")  # type: ignore[index]
    L.append("")
    L += ["4. H1: CNAE 86 NO ENTORNO MT (CLAS_SUB | CNAE | contagem)"]
    saude_mt = c["saude_mt"]  # type: ignore[assignment]
    L += [f"  {r['clas_sub']:<6} {r['cnae']:<10} {r['n']}" for _, r in saude_mt.iterrows()] or ["  (nenhuma)"]  # type: ignore[union-attr]
    L += ["", "5. H5: SUBESTAÇÃO E CIRCUITOS PRÓXIMOS"]
    cont: gpd.GeoDataFrame = h5["sub_contem"]  # type: ignore[assignment]
    sm: dict[str, str] = h5["sub_map"]  # type: ignore[assignment]
    if cont.empty:
        L.append("  Nenhum polígono SUB contém o ponto do HRC.")
    else:
        for _, r in cont.iterrows():
            L.append(f"  Polígono SUB que contém o HRC: {r.get(sm.get('id'))} ({r.get(sm.get('nome'))}) | área {r.geometry.area:,.1f} m²")
    for i, (_, r) in enumerate(h5["sub_proxima"].iterrows(), 1):  # type: ignore[union-attr]
        L.append(f"  [informativo] SUB próxima #{i}: {r.get(sm.get('id'))} ({r.get(sm.get('nome'))}) a {r['dist_m']:,.1f} m | área {r.geometry.area:,.1f} m²")
    L.append(f"  Base da SUB de referência usada no cruzamento: {c['base_sub']} -> {sorted(c['subs_ref'])}")  # type: ignore[arg-type]
    L.append(f"  Raio de busca dos segmentos: {h5.get('raio_busca')} m | 20 mais próximos exatos: {h5['exato']}")
    smap: dict[str, str] = h5["seg_map"]  # type: ignore[assignment]
    for i, r in h5["segmentos"].iterrows():  # type: ignore[union-attr]
        L.append(f"   #{int(i)+1:>2} {r.get(smap.get('id'))} | CTMT={r.get(smap.get('ctmt'))} | SUB={r.get(smap.get('sub'))} | {r['dist_m']:.1f} m | {r.geometry.geom_type}")
    L.append("  Circuitos agregados (CTMT | segmentos | dist. mín. m | nome | SUB cadastro):")
    for _, r in h5["circuitos"].iterrows():  # type: ignore[union-attr]
        cod = str(r[smap.get("ctmt")]) if smap.get("ctmt") else ""
        nome, sb = c["ctmt_info"].get(cod, ("", ""))  # type: ignore[union-attr]
        L.append(f"   {cod:<8} {int(r['n_segmentos']):>3}  {r['dist_min_m']:>8.1f}  {nome}  {sb}")
    L += ["", "6. CATEGORIA DE CRUZAMENTO POR CANDIDATA (hipótese | id | CLAS_SUB | CNAE | CTMT | SUB | dist. m | categoria)"]
    resumo = cand.groupby(["hipotese", "categoria_cruzamento"]).size()
    L += [f"  resumo {h} / {k}: {n}" for (h, k), n in resumo.items()]
    for h in ("H1", "H2", "H3"):
        sub = cand[cand["hipotese"] == h]
        for _, r in sub.iterrows():
            L.append(f"  {h} | {r['identificador']} | {r['clas_sub']} | {r['cnae']} | {r['ctmt']} | {r['sub']} | "
                     f"{r['distancia_hrc_m']:.1f} | {r['categoria_cruzamento']}")
    L.append("  H4: listado integralmente no CSV (muitas linhas); resumo acima.")
    L += ["", "7. NÃO TESTADO",
          "  - Conectividade elétrica / topologia (PAC, chaves, grafo): não construída.",
          "  - SSDBT, UNTRMT: presença confirmada, não usadas nas hipóteses.",
          "  - UCs sem PN_CON na janela de PONNOT têm distância indefinida (NaN).",
          "  - UCAT possui CTAT (sem CTMT): o cruzamento por CTMT não se aplica a H3.",
          "  - A UC do HRC não foi identificada.", "",
          "8. LIMITAÇÕES",
          "  - Cadastro estático; CNAE pode estar desatualizado.",
          "  - Proximidade e coincidência de CTMT/SUB não provam atendimento.",
          "  - A identificação do HRC depende de confirmação por fatura, código da conta contrato ou cadastro.",
          "  - Categorias de cruzamento são indícios, não provas.", "=" * 80]
    OUT_REL.write_text("\n".join(L) + "\n", encoding="utf-8")
    logger.info("Relatório salvo em %s", OUT_REL)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    """Executa o teste de hipóteses. 0=sucesso, 1=erro."""
    inicio = time.perf_counter()
    configurar_logging(LOGS_DIR / f"hipoteses_alimentador_hrc_{datetime.now():%Y%m%d_%H%M%S}.log")
    logger.info("Início do teste de hipóteses (somente leitura).")
    try:
        for p in (GPKG_PATH, CSV_HOSPITAIS, PERFIL_CSV):
            if not p.exists():
                raise FileNotFoundError(f"Entrada ausente: {p}")
        verificar_saidas()
        gdb = localizar_gdb()
        hash_antes = coletar_hashes(gdb)
        camadas, ausentes = descobrir_camadas(gdb)
        faltam = [k for k in CAMADAS_OBRIGATORIAS if k in ausentes]
        if faltam:
            raise KeyError(f"Camadas obrigatórias ausentes no .gdb: {faltam}")
        for k in ausentes:
            logger.warning("Camada %s AUSENTE (hipótese correspondente será limitada).", k)

        ponto, buffer, nome = obter_hrc()
        nome_ok = confirmar_nome_csv(nome)
        pontos, _ = carregar_ponnot(gdb, camadas["PONNOT"], buffer)  # type: ignore[arg-type]

        perfil, mapa_perfil, aus_perfil = carregar_perfil()
        hip = selecionar_h1_h2_h4(perfil, mapa_perfil)
        h3, h3_info = testar_h3(gdb, camadas["UCAT"], buffer, pontos)

        h5 = testar_h5(gdb, camadas, ponto)
        ctmt_info: dict[str, tuple[str, str]] = {}
        if camadas["CTMT"]:
            ct_df, ct_map, _ = ler_gdb(gdb, camadas["CTMT"], ALIASES_CTMT, read_geometry=False)
            ctmt_info = {str(r[ct_map["id"]]): (str(r.get(ct_map.get("nome"), "")), str(r.get(ct_map.get("sub"), "")))
                         for _, r in ct_df.iterrows()}
        smap: dict[str, str] = h5["seg_map"]  # type: ignore[assignment]
        circuitos = set(h5["circuitos"][smap["ctmt"]].astype(str)) if smap.get("ctmt") else set()  # type: ignore[index,union-attr]
        cont = h5["sub_contem"]
        sm: dict[str, str] = h5["sub_map"]  # type: ignore[assignment]
        if not cont.empty:  # type: ignore[union-attr]
            subs_ref = set(cont[sm["id"]].astype(str))  # type: ignore[index]
            base_sub = "polígono SUB que contém o HRC"
        else:
            subs_ref = set(h5["segmentos"][smap["sub"]].dropna().astype(str)) if smap.get("sub") else set()  # type: ignore[index,union-attr]
            base_sub = "SUB dos 20 segmentos SSDMT mais próximos (nenhum polígono SUB contém o HRC)"
        logger.info("Circuitos H5: %s | SUB de referência (%s): %s", sorted(circuitos), base_sub, sorted(subs_ref))

        cand = pd.concat([hip["H1"], hip["H2"], h3, hip["H4"]], ignore_index=True)
        cand = categorizar(adicionar_distancia(cand, pontos, ponto), circuitos, subs_ref)
        cols = ["identificador", "tabela_origem", "clas_sub", "cnae", "ctmt", "sub", "pn_con", "car_inst",
                "dem_cont", "distancia_hrc_m", "hipotese", "criterio_atendido", "categoria_cruzamento"]
        cand[cols].to_csv(OUT_H1H4, index=False, encoding="utf-8", mode="x")
        montar_csv_h5(h5, ctmt_info).to_csv(OUT_H5, index=False, encoding="utf-8", mode="x")
        distribuicao_clas_sub(perfil, mapa_perfil, h3_info).to_csv(OUT_DIST, index=False, encoding="utf-8", mode="x")
        logger.info("CSVs gravados: %s, %s, %s", OUT_H1H4.name, OUT_H5.name, OUT_DIST.name)

        hash_depois = {k: (sha256_entrada(gdb) if k.startswith("gdb:") else sha256_arquivo(
            RAW_DIR / k.split(":", 1)[1] if k.startswith("raw:") else PROCESSED_DIR / k.split(":", 1)[1]))
            for k in hash_antes}
        alterados = [k for k in hash_antes if hash_antes[k] != hash_depois[k]]
        if alterados:
            logger.error("Entradas alteradas durante a execução: %s", alterados)
            return 1

        mp = mapa_perfil
        mt_saude = perfil[perfil[mp["origem"]].fillna("").str.upper().str.contains("UCMT")
                          & norm_cnae(perfil[mp["cnae"]]).str.startswith(PREFIXO_SAUDE)]
        saude_mt = (mt_saude.assign(clas_sub=mt_saude[mp["clas_sub"]], cnae=mt_saude[mp["cnae"]])
                    .groupby(["clas_sub", "cnae"]).size().reset_index(name="n"))
        escrever_relatorio({
            "duracao": time.perf_counter() - inicio, "nome": nome, "nome_ok": nome_ok,
            "hash_antes": hash_antes, "hash_depois": hash_depois,
            "gpkg_antes": hash_antes.get(f"processed:{GPKG_PATH.name}", ""),
            "gpkg_depois": hash_depois.get(f"processed:{GPKG_PATH.name}", ""),
            "perfil_antes": hash_antes.get(f"processed:{PERFIL_CSV.name}", ""),
            "perfil_depois": hash_depois.get(f"processed:{PERFIL_CSV.name}", ""),
            "camadas": camadas, "mapa_perfil": mapa_perfil, "aus_perfil": aus_perfil,
            "n": {"H1": len(hip["H1"]), "H2": len(hip["H2"]), "H3": len(h3), "H4": len(hip["H4"]),
                  "mt_saude_pub": int(hip["mt_saude_pub"]["n"].iloc[0])},
            "h3_info": h3_info, "h5": h5, "cand": cand, "saude_mt": saude_mt,
            "ctmt_info": ctmt_info, "subs_ref": subs_ref, "base_sub": base_sub,
        })
    except (FileNotFoundError, FileExistsError, KeyError, ValueError, RuntimeError) as exc:
        logger.error("Execução interrompida: %s", exc)
        return 1
    except Exception:
        logger.exception("Erro inesperado no teste de hipóteses.")
        return 1
    logger.info("Concluído em %.1f s.", time.perf_counter() - inicio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
