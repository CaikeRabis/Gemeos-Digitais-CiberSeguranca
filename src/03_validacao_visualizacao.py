"""Validação e visualização da sub-rede produzida por 02_filtro_espacial.py.

Script somente-leitura para BDGD, CSV de hospitais e GeoPackage de entrada.
Cria apenas: mapa e relatório em data/processed/ e log em logs/.

A validação é geométrica/espacial (proximidade). Ela NÃO prova atendimento,
conectividade ou alimentação elétrica de nenhum hospital.
"""

import hashlib
import logging
import math
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyogrio  # noqa: E402
import shapely  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from pyproj import CRS  # noqa: E402
from shapely.geometry import Point  # noqa: E402
from shapely.geometry.base import BaseGeometry  # noqa: E402

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"

GPKG_PATH: Path = PROCESSED_DIR / "subrede_hospitais.gpkg"
CSV_PATH: Path = RAW_DIR / "hospitais_df.csv"
MAPA_PATH: Path = PROCESSED_DIR / "validacao_visual_subrede_hrc.png"
RELATORIO_PATH: Path = PROCESSED_DIR / "relatorio_validacao_subrede_hrc.txt"
PROTEGIDOS: tuple[Path, ...] = (
    GPKG_PATH, CSV_PATH, PROCESSED_DIR / "mapa_topologia.png",
)

CRS_ORIGEM: int = 4674
CRS_TRABALHO: int = 31983
RAIO_M: float = 3_000.0

TOL_LINHA_M: float = 0.01          # tolerância de contenção no buffer (m)
TOL_PONTO_M: float = 1.0           # tolerância hospital CSV x GeoPackage (m)
TOL_AREA_REL: float = 0.01         # área do buffer vs. círculo ideal (1 %)
TOL_RAIO_REL: float = 0.005        # raio mín./máx. da borda vs. 3.000 m
TOL_COMPRIMENTO_M: float = 0.5     # comprimento recortado esperado x gravado

REF_NOME: str = "Hospital Regional de Ceilândia (HRC)"
REF_LAT: float = -15.81506
REF_LON: float = -48.09605
REF_TOL_M: float = 500.0           # conferência informativa apenas

CAMADAS_LINHAS: tuple[str, ...] = ("SSDMT", "SSDAT", "SSDBT")
CAMADAS_TRAFOS: tuple[str, ...] = ("UNTRMT", "UNTRAT")
CAMADAS_ATIVOS: tuple[str, ...] = CAMADAS_LINHAS + CAMADAS_TRAFOS
CHAVE_ID: str = "COD_ID"

CONTAGENS_REFERENCIA: dict[str, int] = {
    "SSDMT": 6_932, "SSDAT": 36, "SSDBT": 17_532, "UNTRMT": 1_023, "UNTRAT": 6,
}

ALIASES_NOME: tuple[str, ...] = ("nome", "name", "hospital", "nome_hospital")
ALIASES_LAT: tuple[str, ...] = ("latitude", "lat", "y")
ALIASES_LON: tuple[str, ...] = ("longitude", "lon", "lng", "long", "x")

NIVEL_OK, NIVEL_AVISO, NIVEL_FALHA = "OK", "AVISO", "FALHA"

logger = logging.getLogger("validacao")


# --------------------------------------------------------------------------- #
# Estruturas
# --------------------------------------------------------------------------- #
@dataclass
class InfoCamada:
    """Resumo de inspeção de uma camada."""

    nome: str
    crs: str
    tipos: dict[str, int]
    n: int
    nulas: int
    vazias: int
    invalidas: int
    campos: list[str]
    hospital_ids: dict[str, list[str]]


@dataclass
class Resultado:
    """Acumula achados de validação e define a conclusão."""

    achados: list[tuple[str, str]] = field(default_factory=list)
    extras: dict[str, object] = field(default_factory=dict)

    def add(self, nivel: str, msg: str) -> None:
        """Registra achado e o envia ao log."""
        self.achados.append((nivel, msg))
        log = {NIVEL_OK: logger.info, NIVEL_AVISO: logger.warning, NIVEL_FALHA: logger.error}
        log[nivel]("[%s] %s", nivel, msg)

    def conclusao(self) -> tuple[str, str]:
        """Retorna categoria final e motivo objetivo."""
        falhas = [m for n, m in self.achados if n == NIVEL_FALHA]
        avisos = [m for n, m in self.achados if n == NIVEL_AVISO]
        if falhas:
            return "REPROVADA", f"{len(falhas)} falha(s): " + " | ".join(falhas[:5])
        if avisos:
            return "APROVADA COM RESSALVAS", f"{len(avisos)} ressalva(s): " + " | ".join(avisos[:5])
        return "VALIDAÇÃO APROVADA", "Todas as verificações executadas passaram sem ressalvas."


@dataclass
class Entradas:
    """Caminhos de entrada resolvidos."""

    gpkg: Path
    csv: Path
    gdb: Optional[Path]


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
    for handler in (logging.StreamHandler(sys.stdout),
                    logging.FileHandler(log_path, encoding="utf-8")):
        handler.setFormatter(fmt)
        logger.addHandler(handler)


def sha256(caminho: Path) -> str:
    """Hash SHA-256 de um arquivo."""
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def normalizar_texto(txt: str) -> str:
    """Remove acentos/caixa para comparação de nomes."""
    base = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in base if not unicodedata.combining(c)).casefold().strip()


def localizar_entradas() -> Entradas:
    """Resolve e valida existência das entradas."""
    for caminho in (GPKG_PATH, CSV_PATH):
        if not caminho.exists():
            raise FileNotFoundError(
                f"Entrada ausente: {caminho}. Execute src/02_filtro_espacial.py antes."
            )
    gdbs = sorted(p for p in RAW_DIR.glob("*.gdb") if p.is_dir())
    gdb = gdbs[0] if gdbs else None
    logger.info("GeoPackage: %s", GPKG_PATH)
    logger.info("CSV: %s", CSV_PATH)
    logger.info("BDGD: %s", gdb if gdb else "NÃO ENCONTRADA")
    return Entradas(GPKG_PATH, CSV_PATH, gdb)


# --------------------------------------------------------------------------- #
# 1. Integridade do GeoPackage
# --------------------------------------------------------------------------- #
def resolver_camadas(reais: dict[str, Optional[str]], res: Resultado) -> dict[str, str]:
    """Mapeia nomes esperados para nomes reais do GeoPackage."""
    por_lower = {n.lower(): n for n in reais}
    mapa: dict[str, str] = {}
    esperado: dict[str, Optional[str]] = {
        "hospitais": por_lower.get("hospitais") or next(
            (n for l, n in por_lower.items() if l.startswith("hospital")), None),
        "buffer": por_lower.get("buffer_3000m") or next(
            (n for l, n in por_lower.items() if l.startswith("buffer")), None),
    }
    for c in CAMADAS_ATIVOS:
        esperado[c] = por_lower.get(c.lower())
    for chave, real in esperado.items():
        if real is None:
            res.add(NIVEL_FALHA, f"Camada esperada ausente no GeoPackage: {chave}")
        else:
            mapa[chave] = real
            if real != chave and chave not in ("hospitais", "buffer"):
                res.add(NIVEL_AVISO, f"Camada '{chave}' encontrada como '{real}'.")
    logger.info("Correspondência de camadas: %s", mapa)
    return mapa


def inspecionar(gdf: gpd.GeoDataFrame, nome: str) -> InfoCamada:
    """Calcula estatísticas de integridade geométrica."""
    geom = gdf.geometry
    nulas = int(geom.isna().sum())
    nao_nulas = geom[geom.notna()]
    vazias = int(nao_nulas.is_empty.sum())
    validas_base = nao_nulas[~nao_nulas.is_empty]
    invalidas = int((~validas_base.is_valid).sum())
    ids: dict[str, list[str]] = {}
    for col in ("hospital_id", "hospital_name", "nome"):
        if col in gdf.columns:
            ids[col] = [str(v) for v in gdf[col].dropna().unique()[:10]]
    return InfoCamada(
        nome=nome,
        crs=gdf.crs.to_string() if gdf.crs else "SEM CRS",
        tipos={str(k): int(v) for k, v in gdf.geom_type.value_counts().items()},
        n=len(gdf), nulas=nulas, vazias=vazias, invalidas=invalidas,
        campos=[c for c in gdf.columns if c != "geometry"], hospital_ids=ids,
    )


def carregar_camadas(
    gpkg: Path, res: Resultado
) -> tuple[dict[str, InfoCamada], dict[str, gpd.GeoDataFrame]]:
    """Lista, lê e inspeciona camadas; devolve cópias projetadas em EPSG:31983."""
    reais = {str(n): g for n, g in pyogrio.list_layers(gpkg)}
    logger.info("Camadas no GeoPackage: %s", reais)
    mapa = resolver_camadas(reais, res)
    infos: dict[str, InfoCamada] = {}
    dados: dict[str, gpd.GeoDataFrame] = {}
    for chave, real in mapa.items():
        try:
            gdf = gpd.read_file(gpkg, layer=real, engine="pyogrio")
        except Exception:
            logger.exception("Falha ao ler camada %s", real)
            res.add(NIVEL_FALHA, f"Camada {real} não pôde ser lida.")
            continue
        info = inspecionar(gdf, real)
        infos[chave] = info
        logger.info(
            "%s | CRS=%s | tipos=%s | n=%d | nulas=%d vazias=%d inválidas=%d | campos=%d | ids=%s",
            real, info.crs, info.tipos, info.n, info.nulas, info.vazias,
            info.invalidas, len(info.campos), info.hospital_ids,
        )
        if gdf.crs is None:
            res.add(NIVEL_FALHA, f"Camada {real} sem CRS; não será atribuído por suposição.")
            continue
        if gdf.crs.to_epsg() != CRS_TRABALHO:
            res.add(NIVEL_AVISO, f"Camada {real} em {info.crs} (esperado EPSG:{CRS_TRABALHO}); reprojetada em memória.")
            gdf = gdf.to_crs(epsg=CRS_TRABALHO)
        else:
            res.add(NIVEL_OK, f"Camada {real} em EPSG:{CRS_TRABALHO}.")
        if info.nulas or info.vazias:
            res.add(NIVEL_AVISO, f"Camada {real}: {info.nulas} nulas e {info.vazias} vazias.")
        if info.invalidas:
            res.add(NIVEL_AVISO, f"Camada {real}: {info.invalidas} geometrias inválidas.")
        dados[chave] = gdf
    return infos, dados


def comparar_contagens(infos: dict[str, InfoCamada], res: Resultado) -> dict[str, tuple[int, int, int]]:
    """Compara contagens gravadas com as do log (informativo)."""
    tabela: dict[str, tuple[int, int, int]] = {}
    for chave, ref in CONTAGENS_REFERENCIA.items():
        if chave not in infos:
            continue
        n = infos[chave].n
        tabela[chave] = (ref, n, n - ref)
        if n != ref:
            res.add(NIVEL_AVISO, f"{chave}: gravadas={n} vs. referência do log={ref} (Δ={n - ref:+d}); os dados podem ter mudado.")
        else:
            res.add(NIVEL_OK, f"{chave}: contagem igual à referência ({n}).")
    return tabela


# --------------------------------------------------------------------------- #
# 2. Hospital e buffer
# --------------------------------------------------------------------------- #
def ler_csv(csv: Path) -> tuple[pd.DataFrame, str, str]:
    """Lê o CSV testando codificações e detectando separador; não altera o arquivo."""
    erros: list[str] = []
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(csv, sep=None, engine="python", encoding=enc)
            return df, enc, "auto-detectado"
        except UnicodeDecodeError as exc:
            erros.append(f"{enc}: {exc}")
    raise ValueError("CSV ilegível nas codificações testadas: " + "; ".join(erros))


def achar_coluna(df: pd.DataFrame, aliases: tuple[str, ...]) -> Optional[str]:
    """Encontra coluna equivalente por alias."""
    mapa = {str(c).strip().lower(): c for c in df.columns}
    return next((mapa[a] for a in aliases if a in mapa), None)


def validar_csv(csv: Path, res: Resultado) -> Optional[gpd.GeoDataFrame]:
    """Valida CSV e devolve hospitais (EPSG:31983) com coluna 'nome_csv'."""
    df, enc, sep = ler_csv(csv)
    logger.info("CSV lido | codificação=%s | separador=%s | linhas=%d | colunas=%s",
                enc, sep, len(df), list(df.columns))
    res.extras["csv_enc"] = enc
    c_nome, c_lat, c_lon = (achar_coluna(df, a) for a in (ALIASES_NOME, ALIASES_LAT, ALIASES_LON))
    if not (c_nome and c_lat and c_lon):
        res.add(NIVEL_FALHA, f"CSV sem campos de nome/latitude/longitude (colunas: {list(df.columns)}).")
        return None
    lat = pd.to_numeric(df[c_lat], errors="coerce")
    lon = pd.to_numeric(df[c_lon], errors="coerce")
    ok_num = np.isfinite(lat) & np.isfinite(lon)
    if not ok_num.all() or df.empty:
        res.add(NIVEL_FALHA, "CSV com coordenadas ausentes/não numéricas/não finitas ou vazio.")
        return None
    if not (lat.between(-90, 90).all() and lon.between(-180, 180).all()):
        res.add(NIVEL_FALHA, "Coordenadas do CSV fora do intervalo geográfico.")
        return None
    if not (lat.between(-16.1, -15.4).all() and lon.between(-48.4, -47.2).all()):
        res.add(NIVEL_AVISO, "Coordenadas fora da janela plausível do Distrito Federal.")
    else:
        res.add(NIVEL_OK, "Coordenadas do CSV numéricas, finitas e plausíveis para o DF.")
    gdf = gpd.GeoDataFrame(
        {"nome_csv": df[c_nome].astype(str).values, "lat": lat.values, "lon": lon.values},
        geometry=gpd.points_from_xy(lon, lat), crs=f"EPSG:{CRS_ORIGEM}",
    ).to_crs(epsg=CRS_TRABALHO)
    comparar_com_referencia(gdf, res)
    return gdf


def comparar_com_referencia(csv_gdf: gpd.GeoDataFrame, res: Resultado) -> None:
    """Conferência informativa contra o HRC aproximado (não altera o CSV)."""
    ref = gpd.GeoSeries([Point(REF_LON, REF_LAT)], crs=f"EPSG:{CRS_ORIGEM}").to_crs(epsg=CRS_TRABALHO).iloc[0]
    for _, row in csv_gdf.iterrows():
        d = row.geometry.distance(ref)
        nome_igual = normalizar_texto(row["nome_csv"]) == normalizar_texto(REF_NOME)
        if nome_igual and d <= REF_TOL_M:
            res.add(NIVEL_OK, f"CSV '{row['nome_csv']}' coincide com a referência HRC (distância {d:.1f} m; conferência informativa).")
        else:
            res.add(NIVEL_AVISO, f"CSV '{row['nome_csv']}' diverge da referência HRC (nome_igual={nome_igual}, distância={d:.1f} m). Não se presume que seja o HRC.")


def validar_hospital_buffer(
    csv_gdf: Optional[gpd.GeoDataFrame],
    dados: dict[str, gpd.GeoDataFrame],
    res: Resultado,
) -> Optional[BaseGeometry]:
    """Valida ponto, buffer e consistência com o CSV; devolve a zona (união dos buffers)."""
    if "hospitais" not in dados or "buffer" not in dados:
        res.add(NIVEL_FALHA, "Camadas de hospital/buffer indisponíveis para validação métrica.")
        return None
    hosp, buf = dados["hospitais"], dados["buffer"]
    pontos = hosp[hosp.geom_type == "Point"]
    if pontos.empty:
        res.add(NIVEL_FALHA, "Camada de hospitais sem geometria de ponto.")
        return None
    if csv_gdf is not None:
        if len(csv_gdf) != len(pontos):
            res.add(NIVEL_AVISO, f"CSV tem {len(csv_gdf)} hospital(is); GeoPackage tem {len(pontos)}.")
        dmax = max(min(g.distance(p) for p in pontos.geometry) for g in csv_gdf.geometry)
        nivel = NIVEL_OK if dmax <= TOL_PONTO_M else NIVEL_FALHA
        res.add(nivel, f"Ponto CSV x GeoPackage: desvio máximo {dmax:.4f} m (tolerância {TOL_PONTO_M} m).")
        res.extras["desvio_csv_m"] = dmax
        if "nome" in hosp.columns:
            nomes_csv = {normalizar_texto(n) for n in csv_gdf["nome_csv"]}
            nomes_gp = {normalizar_texto(str(n)) for n in hosp["nome"]}
            if nomes_csv != nomes_gp:
                res.add(NIVEL_AVISO, "Nome(s) do hospital no GeoPackage diferem do CSV.")
    zona = buf.geometry.union_all()
    for i, geom in enumerate(buf.geometry):
        if geom.geom_type != "Polygon":
            res.add(NIVEL_FALHA, f"Buffer {i} não é Polygon ({geom.geom_type}).")
            continue
        centro = min(pontos.geometry, key=lambda p: p.distance(geom.centroid))
        dist_centro = geom.centroid.distance(centro)
        area_ideal = math.pi * RAIO_M ** 2
        erro_area = abs(geom.area - area_ideal) / area_ideal
        dists = [Point(c).distance(centro) for c in geom.exterior.coords]
        rmin, rmax = min(dists), max(dists)
        dentro = geom.covers(centro)
        res.extras.update(buffer_area=geom.area, buffer_raio_equiv=math.sqrt(geom.area / math.pi),
                          buffer_erro_area=erro_area, buffer_dist_centro=dist_centro,
                          buffer_rmin=rmin, buffer_rmax=rmax)
        res.add(NIVEL_OK if dentro else NIVEL_FALHA, f"Hospital {'dentro' if dentro else 'FORA'} do buffer {i}.")
        res.add(NIVEL_OK if dist_centro <= TOL_PONTO_M else NIVEL_FALHA,
                f"Buffer {i}: centroide a {dist_centro:.4f} m do hospital (tol. {TOL_PONTO_M} m).")
        res.add(NIVEL_OK if erro_area <= TOL_AREA_REL else NIVEL_FALHA,
                f"Buffer {i}: área {geom.area:,.0f} m² (raio equivalente {math.sqrt(geom.area/math.pi):.1f} m; erro {erro_area:.3%}; tol. {TOL_AREA_REL:.0%}).")
        raio_ok = rmin >= RAIO_M * (1 - TOL_RAIO_REL) and rmax <= RAIO_M * (1 + TOL_RAIO_REL / 10)
        res.add(NIVEL_OK if raio_ok else NIVEL_FALHA,
                f"Buffer {i}: raio da borda entre {rmin:.2f} e {rmax:.2f} m (alvo {RAIO_M:.0f} m).")
    return zona


# --------------------------------------------------------------------------- #
# 3. Ativos
# --------------------------------------------------------------------------- #
def validar_ativos(
    dados: dict[str, gpd.GeoDataFrame], zona: BaseGeometry, res: Resultado
) -> dict[str, float]:
    """Valida tipos e contenção no buffer; devolve comprimento por camada de linhas."""
    zona_tol = zona.buffer(TOL_LINHA_M)
    comprimentos: dict[str, float] = {}
    for chave in CAMADAS_LINHAS:
        if chave not in dados:
            continue
        gdf = dados[chave]
        ruins = gdf[~gdf.geom_type.isin(["LineString", "MultiLineString"])]
        res.add(NIVEL_OK if ruins.empty else NIVEL_FALHA,
                f"{chave}: {'todas lineares' if ruins.empty else str(len(ruins)) + ' geometrias não lineares'}.")
        fora = int((~gdf.geometry.within(zona_tol)).sum())
        res.add(NIVEL_OK if fora == 0 else NIVEL_FALHA,
                f"{chave}: {fora} linha(s) fora do buffer (tol. {TOL_LINHA_M} m).")
        comprimentos[chave] = float(gdf.length.sum())
        logger.info("%s: comprimento recortado total = %.1f m", chave, comprimentos[chave])
    for chave in CAMADAS_TRAFOS:
        if chave not in dados:
            continue
        gdf = dados[chave]
        ruins = gdf[gdf.geom_type != "Point"]
        res.add(NIVEL_OK if ruins.empty else NIVEL_FALHA,
                f"{chave}: {'todos pontos' if ruins.empty else str(len(ruins)) + ' não-pontos'}.")
        fora = int((~gdf.geometry.intersects(zona_tol)).sum())
        res.add(NIVEL_OK if fora == 0 else NIVEL_FALHA, f"{chave}: {fora} transformador(es) fora do buffer.")
    return comprimentos


# --------------------------------------------------------------------------- #
# Completude via BDGD
# --------------------------------------------------------------------------- #
def chaves_comparacao(gdf: gpd.GeoDataFrame, usar_id: bool) -> Counter:
    """Contador de chaves: COD_ID ou geometria normalizada."""
    if usar_id:
        return Counter(gdf[CHAVE_ID].astype(str))
    geoms = shapely.set_precision(gdf.geometry.values, 0.001)
    return Counter(shapely.to_wkb(shapely.normalize(geoms), hex=True))


def esperado_da_bdgd(gdb: Path, camada: str, zona: BaseGeometry) -> gpd.GeoDataFrame:
    """Reconstrói o recorte exato a partir da BDGD (bbox só pré-seleciona)."""
    info = pyogrio.read_info(gdb, layer=camada)
    if not info.get("crs"):
        raise ValueError(f"{camada}: BDGD sem CRS declarado.")
    crs = CRS.from_user_input(info["crs"])
    bbox = tuple(float(v) for v in gpd.GeoSeries([zona], crs=CRS_TRABALHO).to_crs(crs).total_bounds)
    cand = gpd.read_file(gdb, layer=camada, bbox=bbox, engine="pyogrio").to_crs(epsg=CRS_TRABALHO)
    cand = cand[cand.geometry.notna() & ~cand.geometry.is_empty]
    cand = cand[cand.intersects(zona)]
    clip = gpd.clip(cand, zona)
    return clip[~clip.geometry.is_empty].reset_index(drop=True)


def comparar_com_bdgd(
    gdb: Optional[Path], dados: dict[str, gpd.GeoDataFrame], zona: BaseGeometry, res: Resultado
) -> dict[str, dict[str, object]]:
    """Compara conjuntos esperados (BDGD) com gravados (GeoPackage)."""
    stats: dict[str, dict[str, object]] = {}
    if gdb is None:
        res.add(NIVEL_AVISO, "BDGD não encontrada: verificação de completude NÃO executada.")
        return stats
    for chave in CAMADAS_ATIVOS:
        if chave not in dados:
            continue
        try:
            esperado = esperado_da_bdgd(gdb, chave, zona)
            gravado = dados[chave]
            usar_id = (CHAVE_ID in esperado.columns and CHAVE_ID in gravado.columns
                       and esperado[CHAVE_ID].notna().all() and gravado[CHAVE_ID].notna().all())
            ce, cg = chaves_comparacao(esperado, usar_id), chaves_comparacao(gravado, usar_id)
            faltam, sobram = ce - cg, cg - ce
            metodo = f"identificador {CHAVE_ID}" if usar_id else "geometria normalizada (sem ID estável; limitação: atributos não comparados)"
            s: dict[str, object] = {
                "esperado": len(esperado), "gravado": len(gravado), "faltam": sum(faltam.values()),
                "sobram": sum(sobram.values()), "metodo": metodo,
                "dup_esperado": sum(v - 1 for v in ce.values() if v > 1),
            }
            if chave in CAMADAS_LINHAS:
                le, lg = float(esperado.length.sum()), float(gravado.length.sum())
                s.update(comp_esperado=le, comp_gravado=lg)
                if abs(le - lg) > TOL_COMPRIMENTO_M:
                    res.add(NIVEL_FALHA, f"{chave}: comprimento esperado {le:.1f} m vs gravado {lg:.1f} m.")
            stats[chave] = s
            ok = not faltam and not sobram
            res.add(NIVEL_OK if ok else NIVEL_FALHA,
                    f"{chave}: esperado(BDGD)={len(esperado)} gravado={len(gravado)} faltam={s['faltam']} sobram={s['sobram']} [{metodo}].")
        except Exception:
            logger.exception("Falha na comparação de completude de %s", chave)
            res.add(NIVEL_AVISO, f"{chave}: verificação de completude NÃO executada (erro; ver log).")
    return stats


# --------------------------------------------------------------------------- #
# 4. Mapa
# --------------------------------------------------------------------------- #
def desenhar_escala(ax: plt.Axes, comprimento_m: float = 1_000.0) -> None:
    """Escala gráfica em metros no canto inferior esquerdo."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    xi, yi = x0 + 0.04 * (x1 - x0), y0 + 0.04 * (y1 - y0)
    h = 0.006 * (y1 - y0)
    for k, cor in enumerate(("black", "white")):
        ax.add_patch(Rectangle((xi + k * comprimento_m / 2, yi), comprimento_m / 2, h,
                               facecolor=cor, edgecolor="black", zorder=10))
    for k, rot in enumerate(("0", "500 m", "1 km")):
        ax.text(xi + k * comprimento_m / 2, yi + 2 * h, rot, ha="center", fontsize=9, zorder=10)


def gerar_mapa(
    dados: dict[str, gpd.GeoDataFrame], zona: BaseGeometry, nome_hospital: str, saida: Path
) -> None:
    """Gera mapa estático (apenas proximidade espacial; sem base online)."""
    estilos: dict[str, dict[str, object]] = {
        "SSDBT": dict(color="#2a9d8f", linewidth=0.35, alpha=0.45, label="SSDBT (linhas)"),
        "SSDMT": dict(color="#e76f51", linewidth=0.6, alpha=0.7, label="SSDMT (linhas)"),
        "SSDAT": dict(color="#6a4c93", linewidth=1.4, alpha=0.95, label="SSDAT (linhas)"),
    }
    fig, ax = plt.subplots(figsize=(14, 14))
    if "buffer" in dados:
        dados["buffer"].plot(ax=ax, facecolor="#ffe8a3", edgecolor="#8d6e00", alpha=0.25,
                             linewidth=1.8, zorder=1)
    for chave in ("SSDBT", "SSDMT", "SSDAT"):
        if chave in dados and not dados[chave].empty:
            dados[chave].plot(ax=ax, zorder=3, **estilos[chave])
    if "UNTRMT" in dados and not dados["UNTRMT"].empty:
        dados["UNTRMT"].plot(ax=ax, marker="^", color="#1d3557", markersize=14, alpha=0.8,
                             edgecolor="white", linewidth=0.3, zorder=5, label="UNTRMT (transformadores)")
    if "UNTRAT" in dados and not dados["UNTRAT"].empty:
        dados["UNTRAT"].plot(ax=ax, marker="s", color="#d00000", markersize=60,
                             edgecolor="black", linewidth=0.8, zorder=6, label="UNTRAT (transformadores)")
    if "hospitais" in dados:
        dados["hospitais"].plot(ax=ax, marker="*", color="gold", markersize=420,
                                edgecolor="black", linewidth=1.2, zorder=9, label=f"Hospital: {nome_hospital}")
        for g in dados["hospitais"].geometry:
            ax.annotate(nome_hospital, (g.x, g.y), xytext=(10, 12), textcoords="offset points",
                        fontsize=10, fontweight="bold", zorder=11,
                        bbox=dict(boxstyle="round", fc="white", ec="black", alpha=0.85))
    minx, miny, maxx, maxy = zona.bounds
    m = 0.04 * max(maxx - minx, maxy - miny)
    ax.set_xlim(minx - m, maxx + m)
    ax.set_ylim(miny - m, maxy + m)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_xlabel(f"Leste (m) - EPSG:{CRS_TRABALHO} (SIRGAS 2000 / UTM 23S)")
    ax.set_ylabel(f"Norte (m) - EPSG:{CRS_TRABALHO}")
    ax.set_title("Validação visual - ativos da BDGD dentro do raio de 3 km\n"
                 "Representa apenas proximidade espacial (sem inferência de conectividade ou fluxo)",
                 fontsize=13)
    desenhar_escala(ax)
    leg = ax.legend(loc="upper right", framealpha=0.9, fontsize=10)
    leg.set_zorder(12)
    fig.text(0.5, 0.01,
             f"CRS do mapa: EPSG:{CRS_TRABALHO} | Raio aplicado: {RAIO_M:,.0f} m | Hospital: {nome_hospital} | "
             f"Gerado em {datetime.now():%Y-%m-%d %H:%M}", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    saida.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(saida, dpi=220)
    plt.close(fig)
    logger.info("Mapa salvo em %s", saida)


# --------------------------------------------------------------------------- #
# 5. Relatório
# --------------------------------------------------------------------------- #
def escrever_relatorio(
    saida: Path, entradas: Entradas, infos: dict[str, InfoCamada],
    tabela_contagens: dict[str, tuple[int, int, int]], comprimentos: dict[str, float],
    stats: dict[str, dict[str, object]], res: Resultado, hashes: dict[str, tuple[str, str]],
    duracao: float,
) -> None:
    """Escreve o relatório textual de validação."""
    cat, motivo = res.conclusao()
    L: list[str] = []
    L += ["=" * 78, "RELATÓRIO DE VALIDAÇÃO - SUB-REDE EM TORNO DO HOSPITAL (BDGD)", "=" * 78,
          f"Data/hora: {datetime.now():%Y-%m-%d %H:%M:%S} | Duração: {duracao:.1f} s", ""]
    L += ["1. ARQUIVOS INSPECIONADOS",
          f"  GeoPackage : {entradas.gpkg}", f"  CSV        : {entradas.csv} (codificação: {res.extras.get('csv_enc', '?')})",
          f"  BDGD       : {entradas.gdb}", f"  Mapa       : {MAPA_PATH} (existe: {MAPA_PATH.exists()})", ""]
    L += ["2. CAMADAS (contagem | CRS | tipo geométrico | nulas/vazias/inválidas)"]
    for chave, i in infos.items():
        L.append(f"  {i.nome:<14} n={i.n:<7} {i.crs:<12} {i.tipos}  N/V/I={i.nulas}/{i.vazias}/{i.invalidas}")
        if i.hospital_ids:
            L.append(f"      identificação: {i.hospital_ids}")
    L += ["", "3. CONTAGENS: REFERÊNCIA DO LOG x GEOPACKAGE (informativo)"]
    for k, (ref, n, d) in tabela_contagens.items():
        L.append(f"  {k:<7} referência={ref:<7} gravado={n:<7} diferença={d:+d}")
    L += ["", "4. COMPRIMENTO TOTAL DOS TRECHOS RECORTADOS (m)",
          "  (não representa a extensão total da rede que alimenta o hospital)"]
    for k, v in comprimentos.items():
        L.append(f"  {k:<7} {v:,.1f} m")
    L += ["", "5. COMPLETUDE (recálculo a partir da BDGD)"]
    if stats:
        for k, s in stats.items():
            L.append(f"  {k:<7} esperado={s['esperado']} gravado={s['gravado']} faltam={s['faltam']} sobram={s['sobram']} | {s['metodo']}")
    else:
        L.append("  NÃO EXECUTADA.")
    L += ["", "6. ACHADOS"]
    L += [f"  [{n}] {m}" for n, m in res.achados]
    L += ["", "7. INTEGRIDADE DAS ENTRADAS (SHA-256 antes/depois; somente leitura)"]
    for nome, (a, b) in hashes.items():
        L.append(f"  {nome}: {'inalterado' if a == b else 'ALTERADO!'} ({a[:16]}...)")
    L += ["", "8. LIMITAÇÕES",
          "  - A conferência de coordenadas não comprova a localização cadastral oficial nem o ponto de conexão elétrica do hospital.",
          "  - A seleção é por proximidade geométrica; provar atendimento ou conectividade exige análise topológica/elétrica adicional.",
          "  - Os ativos selecionados NÃO são declarados como alimentadores do hospital.",
          "  - Coordenadas do CSV assumidas em graus no datum compatível com EPSG:4674.",
          "  - Sem ID estável, a comparação com a BDGD seria apenas geométrica.", "",
          "9. CONCLUSÃO", f"  {cat}", f"  Motivo: {motivo}", "=" * 78]
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n".join(L) + "\n", encoding="utf-8")
    logger.info("Relatório salvo em %s", saida)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def nome_do_hospital(dados: dict[str, gpd.GeoDataFrame], csv_gdf: Optional[gpd.GeoDataFrame]) -> str:
    """Nome efetivo do hospital (GeoPackage, senão CSV)."""
    if "hospitais" in dados and "nome" in dados["hospitais"].columns and len(dados["hospitais"]):
        return str(dados["hospitais"]["nome"].iloc[0])
    if csv_gdf is not None and len(csv_gdf):
        return str(csv_gdf["nome_csv"].iloc[0])
    return "Hospital (nome indisponível)"


def main() -> int:
    """Executa a validação. 0=aprovada/ressalvas, 2=reprovada, 1=erro fatal."""
    inicio = time.perf_counter()
    configurar_logging(LOGS_DIR / f"validacao_{datetime.now():%Y%m%d_%H%M%S}.log")
    logger.info("Início da validação.")
    res = Resultado()
    try:
        entradas = localizar_entradas()
        assert MAPA_PATH not in PROTEGIDOS and RELATORIO_PATH not in PROTEGIDOS
        hashes_antes = {p.name: sha256(p) for p in (entradas.gpkg, entradas.csv)}
        infos, dados = carregar_camadas(entradas.gpkg, res)
        tabela = comparar_contagens(infos, res)
        csv_gdf = validar_csv(entradas.csv, res)
        zona = validar_hospital_buffer(csv_gdf, dados, res)
        if zona is None:
            raise RuntimeError("Sem buffer/hospital válidos: não é possível concluir a validação espacial.")
        comprimentos = validar_ativos(dados, zona, res)
        stats = comparar_com_bdgd(entradas.gdb, dados, zona, res)
        gerar_mapa(dados, zona, nome_do_hospital(dados, csv_gdf), MAPA_PATH)
        hashes = {n: (h, sha256(p)) for (n, h), p in zip(hashes_antes.items(), (entradas.gpkg, entradas.csv))}
        if any(a != b for a, b in hashes.values()):
            res.add(NIVEL_FALHA, "Uma entrada foi alterada durante a validação.")
        for sufixo in ("-wal", "-shm"):
            if Path(str(entradas.gpkg) + sufixo).exists():
                res.add(NIVEL_AVISO, f"Arquivo auxiliar {entradas.gpkg.name}{sufixo} presente.")
        escrever_relatorio(RELATORIO_PATH, entradas, infos, tabela, comprimentos, stats,
                           res, hashes, time.perf_counter() - inicio)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("Validação interrompida: %s", exc)
        return 1
    except Exception:
        logger.exception("Erro inesperado; validação inconclusiva.")
        return 1
    cat, motivo = res.conclusao()
    logger.info("CONCLUSÃO: %s | %s", cat, motivo)
    logger.info("Fim da validação em %.1f s.", time.perf_counter() - inicio)
    return 2 if cat == "REPROVADA" else 0


if __name__ == "__main__":
    sys.exit(main())
