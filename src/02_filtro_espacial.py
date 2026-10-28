"""Filtro espacial da BDGD: recorta a rede em raio de influência de hospitais-alvo.

Entradas:
    - data/raw/<BDGD>.gdb (camadas SSDMT, SSDAT, UNTRMT, UNTRAT e, se linear, SSDBT)
    - data/raw/hospitais_df.csv (colunas: nome, latitude, longitude)

Saída:
    - data/processed/subrede_hospitais.gpkg
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"

CRS_ORIGEM_ESPERADO: int = 4674
CRS_TRABALHO: int = 31983
RAIO_METROS: float = 3_000.0

LAYERS_LINHAS: tuple[str, ...] = ("SSDMT", "SSDAT")
LAYERS_TRAFOS: tuple[str, ...] = ("UNTRMT", "UNTRAT")
LAYER_BT: str = "SSDBT"

HOSPITAIS_CSV: Path = RAW_DIR / "hospitais_df.csv"
SAIDA_GPKG: Path = PROCESSED_DIR / "subrede_hospitais.gpkg"

logger = logging.getLogger("filtro_espacial")


def configurar_logging() -> None:
    """Configura logging (INFO) com timestamp no terminal."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def localizar_bdgd(raw_dir: Path = RAW_DIR) -> Path:
    """Localiza a geodatabase (.gdb ou .gpkg) em data/raw/."""
    if not raw_dir.exists():
        raise FileNotFoundError(f"Diretório inexistente: {raw_dir}")
    candidatos = sorted(
        p for p in raw_dir.iterdir() if p.suffix.lower() in {".gdb", ".gpkg"}
    )
    if not candidatos:
        raise FileNotFoundError(f"Nenhuma geodatabase (.gdb/.gpkg) em {raw_dir}")
    logger.info("BDGD: %s", candidatos[0].name)
    return candidatos[0]


def carregar_hospitais(csv: Path) -> gpd.GeoDataFrame:
    """Lê hospitais (nome, latitude, longitude) como pontos em EPSG:4674."""
    if not csv.exists():
        raise FileNotFoundError(
            f"Arquivo de hospitais ausente: {csv} (colunas: nome,latitude,longitude)"
        )
    df = pd.read_csv(csv)
    faltantes = {"nome", "latitude", "longitude"} - set(df.columns)
    if faltantes:
        raise ValueError(f"Colunas ausentes em {csv.name}: {sorted(faltantes)}")
    df = df.dropna(subset=["latitude", "longitude"])
    if df.empty:
        raise ValueError(f"{csv.name} não contém hospitais com coordenadas.")
    if not df["latitude"].between(-90, 90).all() or not df["longitude"].between(-180, 180).all():
        raise ValueError("Coordenadas fora do intervalo válido (lat/lon em graus).")
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=f"EPSG:{CRS_ORIGEM_ESPERADO}",
    )
    logger.info("Hospitais carregados: %d", len(gdf))
    return gdf


def criar_buffers(hospitais: gpd.GeoDataFrame, raio: float) -> gpd.GeoDataFrame:
    """Cria buffers circulares (metros) no CRS projetado de trabalho."""
    proj = hospitais.to_crs(epsg=CRS_TRABALHO)
    proj["geometry"] = proj.geometry.buffer(raio)
    return proj


def validar_camada(caminho: Path, camada: str) -> tuple[CRS, str]:
    """Valida existência, CRS e tipo geométrico (linear/ponto) sem carregar feições."""
    info = pyogrio.read_info(caminho, layer=camada)
    geom_tipo = info.get("geometry_type")
    if not geom_tipo:
        raise ValueError(f"Camada {camada} não possui geometria.")
    if not info.get("crs"):
        raise ValueError(f"Camada {camada} sem CRS definido; não será atribuído por suposição.")
    crs = CRS.from_user_input(info["crs"])
    if crs.to_epsg() != CRS_ORIGEM_ESPERADO:
        logger.warning("Camada %s com CRS %s (esperado EPSG:%d).", camada, crs.to_string(), CRS_ORIGEM_ESPERADO)
    logger.info(
        "Camada %s validada | tipo=%s | CRS=%s | feições=%s",
        camada, geom_tipo, crs.to_string(), info.get("features"),
    )
    return crs, geom_tipo


def processar_camada(
    caminho: Path,
    camada: str,
    zona: BaseGeometry,
    crs_zona: CRS,
    tipo_esperado: str,
) -> gpd.GeoDataFrame:
    """Pré-seleciona por bbox na leitura e recorta exatamente pela zona de buffer.

    A bbox serve apenas para reduzir candidatos; o recorte final usa a geometria
    circular exata (união dos buffers) em EPSG:31983.
    """
    crs_camada, geom_tipo = validar_camada(caminho, camada)
    if tipo_esperado not in geom_tipo:
        raise ValueError(f"Camada {camada}: tipo {geom_tipo} incompatível com '{tipo_esperado}'.")

    total = pyogrio.read_info(caminho, layer=camada).get("features")
    zona_origem = gpd.GeoSeries([zona], crs=crs_zona).to_crs(crs_camada)
    bbox = tuple(float(v) for v in zona_origem.total_bounds)

    candidatos = gpd.read_file(caminho, layer=camada, bbox=bbox, engine="pyogrio")
    if candidatos.crs is None or CRS.from_user_input(candidatos.crs) != crs_camada:
        raise ValueError(f"Camada {camada}: CRS lido diverge do CRS declarado.")
    n_pre = len(candidatos)
    if n_pre == 0:
        logger.info("%s | lidas(total)=%s pré-selecionadas=0 recortadas=0", camada, total)
        return candidatos.to_crs(epsg=CRS_TRABALHO)

    candidatos = candidatos.to_crs(epsg=CRS_TRABALHO)
    candidatos = candidatos[candidatos.geometry.notna() & ~candidatos.geometry.is_empty]
    alvo = gpd.GeoSeries([zona], crs=CRS_TRABALHO)
    candidatos = candidatos[candidatos.intersects(alvo.iloc[0])]
    recortado = gpd.clip(candidatos, alvo.iloc[0])
    recortado = recortado[~recortado.geometry.is_empty].reset_index(drop=True)
    logger.info(
        "%s | total=%s pré-selecionadas(bbox)=%d recortadas=%d",
        camada, total, n_pre, len(recortado),
    )
    return recortado


def camada_bt_processavel(caminho: Path) -> bool:
    """Verifica a SSDBT na geodatabase e registra a decisão no log."""
    nomes = [n for n, _ in pyogrio.list_layers(caminho)]
    if LAYER_BT not in nomes:
        logger.info("%s verificada: não existe nesta geodatabase; não processada.", LAYER_BT)
        return False
    info = pyogrio.read_info(caminho, layer=LAYER_BT)
    geom_tipo = info.get("geometry_type") or "sem geometria"
    if "LineString" not in geom_tipo:
        logger.info("%s verificada: tipo '%s' não é linear; não processada.", LAYER_BT, geom_tipo)
        return False
    logger.info("%s verificada: tipo %s, %s feições; será processada.", LAYER_BT, geom_tipo, info.get("features"))
    return True


def gravar_camada(gdf: gpd.GeoDataFrame, saida: Path, camada: str) -> None:
    """Grava uma camada no GeoPackage (CRS EPSG:31983)."""
    if gdf.empty:
        logger.warning("Camada %s vazia após o recorte; não gravada.", camada)
        return
    gdf.to_file(saida, layer=camada, driver="GPKG", engine="pyogrio")
    logger.info("Gravada %s: %d feições", camada, len(gdf))


def executar(hospitais_csv: Path, saida: Path, raio: float) -> None:
    """Orquestra o filtro espacial."""
    caminho = localizar_bdgd()
    hospitais = carregar_hospitais(hospitais_csv)
    buffers = criar_buffers(hospitais, raio)
    zona = buffers.geometry.union_all()
    crs_zona = CRS.from_epsg(CRS_TRABALHO)

    camadas: list[tuple[str, str]] = [(c, "LineString") for c in LAYERS_LINHAS]
    if camada_bt_processavel(caminho):
        camadas.append((LAYER_BT, "LineString"))
    camadas += [(c, "Point") for c in LAYERS_TRAFOS]

    saida.parent.mkdir(parents=True, exist_ok=True)
    if saida.exists():
        saida.unlink()

    gravar_camada(hospitais.to_crs(epsg=CRS_TRABALHO), saida, "hospitais")
    gravar_camada(buffers, saida, f"buffer_{int(raio)}m")
    for nome, tipo in camadas:
        gdf = processar_camada(caminho, nome, zona, crs_zona, tipo)
        gravar_camada(gdf, saida, nome)
    logger.info("GeoPackage salvo em %s", saida)


def main(argv: Optional[list[str]] = None) -> int:
    """Ponto de entrada."""
    configurar_logging()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hospitais", type=Path, default=HOSPITAIS_CSV)
    parser.add_argument("--saida", type=Path, default=SAIDA_GPKG)
    parser.add_argument("--raio", type=float, default=RAIO_METROS, help="metros")
    args = parser.parse_args(argv)
    try:
        executar(args.hospitais, args.saida, args.raio)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erro inesperado no filtro espacial.")
        return 1
    logger.info("Filtro espacial concluído com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
