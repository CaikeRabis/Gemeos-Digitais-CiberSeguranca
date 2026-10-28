"""Mineração e plotagem topológica da BDGD - Rede Elétrica do DF.

Na BDGD V11, SEGCON é tabela de catálogo sem geometria e UNTRD não existe;
usam-se as camadas espaciais SSDMT/SSDAT (linhas) e UNTRMT/UNTRAT (trafos).
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"

LAYERS_LINHAS: tuple[str, ...] = ("SSDMT", "SSDAT")
LAYERS_TRAFOS: tuple[str, ...] = ("UNTRMT", "UNTRAT")
LIMITE_AMOSTRAGEM: int = 50_000
FRACAO_AMOSTRA: float = 0.1

logger = logging.getLogger("mineracao_topologia")


def configurar_logging() -> None:
    """Configura logging (INFO) com timestamp no terminal."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def localizar_bdgd(raw_dir: Path = RAW_DIR) -> Path:
    """Localiza a base BDGD (.gdb, .gpkg ou .zip) em data/raw/."""
    if not raw_dir.exists():
        raise FileNotFoundError(f"Diretório inexistente: {raw_dir}")
    candidatos = sorted(
        p for p in raw_dir.iterdir() if p.suffix.lower() in {".gdb", ".gpkg", ".zip"}
    )
    if not candidatos:
        raise FileNotFoundError(f"Nenhuma BDGD encontrada em {raw_dir}")
    logger.info("BDGD encontrada: %s", candidatos[0].name)
    return candidatos[0]


def extrair_camada(caminho: Path, camada: str) -> gpd.GeoDataFrame:
    """Lê uma camada específica da BDGD usando o motor pyogrio."""
    logger.info("Lendo camada %s ...", camada)
    try:
        gdf = gpd.read_file(caminho, layer=camada, engine="pyogrio")
    except Exception as exc:  # pyogrio levanta DataSourceError/ValueError
        logger.error("Falha ao ler camada %s: %s", camada, exc)
        raise
    logger.info("Camada %s: %d feições | CRS=%s", camada, len(gdf), gdf.crs)
    return gdf


def extrair_conjunto(caminho: Path, camadas: tuple[str, ...]) -> gpd.GeoDataFrame:
    """Lê e concatena várias camadas da BDGD em um único GeoDataFrame."""
    partes = [extrair_camada(caminho, c) for c in camadas]
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=partes[0].crs)


def extrair_dados(caminho: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Extrai linhas (SSDMT/SSDAT) e transformadores (UNTRMT/UNTRAT)."""
    return (
        extrair_conjunto(caminho, LAYERS_LINHAS),
        extrair_conjunto(caminho, LAYERS_TRAFOS),
    )


def plotar_topologia(
    linhas: gpd.GeoDataFrame,
    trafos: gpd.GeoDataFrame,
    saida: Optional[Path] = None,
) -> None:
    """Plota o mapa espacial: linhas em azul (0.2) e transformadores em vermelho."""
    if len(trafos) > LIMITE_AMOSTRAGEM:
        logger.info(
            "UNTR* com %d feições; amostrando %.0f%% para plotagem.",
            len(trafos), FRACAO_AMOSTRA * 100,
        )
        trafos = trafos.sample(frac=FRACAO_AMOSTRA, random_state=42)

    fig, ax = plt.subplots(figsize=(12, 12))
    linhas.plot(ax=ax, color="blue", linewidth=0.2, label="Linhas (SSDMT/SSDAT)")
    trafos.plot(ax=ax, color="red", markersize=1, label="Transformadores (UNTRMT/UNTRAT)")

    ax.set_title("Topologia da Rede de Distribuição - Distrito Federal (BDGD)")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="upper right", markerscale=5)
    fig.tight_layout()

    if saida is not None:
        saida.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(saida, dpi=200)
        logger.info("Mapa salvo em %s", saida)
    plt.show()


def main() -> int:
    """Pipeline principal."""
    configurar_logging()
    try:
        caminho = localizar_bdgd()
        linhas, trafos = extrair_dados(caminho)
        plotar_topologia(linhas, trafos, PROCESSED_DIR / "mapa_topologia.png")
    except FileNotFoundError as exc:
        logger.error("Arquivo não encontrado: %s", exc)
        return 1
    except Exception:
        logger.exception("Erro inesperado no pipeline.")
        return 1
    logger.info("Pipeline concluído com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

