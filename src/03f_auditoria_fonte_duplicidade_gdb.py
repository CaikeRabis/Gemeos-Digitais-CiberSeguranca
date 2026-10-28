"""Etapa 03f: auditoria somente-leitura da fonte de duplicidades de COD_ID.

Não identifica a UC do HRC, não constrói grafo e não conclui atendimento elétrico.
"""
from __future__ import annotations

import hashlib
import logging
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
GPKG_PATH = PROCESSED_DIR / "subrede_hospitais.gpkg"
SCRIPT_PATHS = tuple(BASE_DIR / "src" / name for name in (
    "03b_inventario_schema_bdgd.py", "03c_triagem_ucs_hrc.py", "03d_hipoteses_alimentador_hrc.py"))
UC_LAYERS = ("UCMT_tab", "UCBT_tab")
KEY_LAYERS = ("PONNOT", "UNTRMT", "UNTRAT", "SUB", "CTMT", "SSDMT", "SSDBT", "SSDAT")
PATTERNS = ("sjoin", "sjoin_nearest", "merge", "join", "explode", "drop_duplicates", "buffer", "intersects", "within", "nearest")
BATCH_SIZE = 25_000  # <= 100.000; reduzido para limitar memória da UCBT.
SUSPECT_AREA_M2 = 10_000.0
OUT_A = PROCESSED_DIR / f"auditoria_fonte_duplicidade_gdb_{RUN_TAG}.csv"
OUT_B = PROCESSED_DIR / f"auditoria_chaves_camadas_gdb_{RUN_TAG}.csv"
OUT_D = PROCESSED_DIR / f"auditoria_juncoes_scripts_{RUN_TAG}.csv"
OUT_E = PROCESSED_DIR / f"auditoria_sub_poligonos_hrc_{RUN_TAG}.csv"
OUT_REPORT = PROCESSED_DIR / f"relatorio_auditoria_fonte_gdb_hrc_{RUN_TAG}.txt"
LOG_PATH = LOGS_DIR / f"auditoria_fonte_gdb_hrc_{RUN_TAG}.log"
OUTPUTS = (OUT_A, OUT_B, OUT_D, OUT_E, OUT_REPORT)
PARTIAL_FILES = (
    "auditoria_fonte_duplicidade_gdb.csv", "auditoria_chaves_camadas_gdb.csv",
    "auditoria_juncoes_scripts.csv", "auditoria_sub_poligonos_hrc.csv")
LOGGER = logging.getLogger("auditoria_fonte_duplicidade_gdb")


def setup_logging() -> None:
    """Configura logging em terminal e arquivo sem handlers duplicados."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    LOGS_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def sha256_file(path: Path) -> str:
    """Calcula SHA-256 de um arquivo individual."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_hashes(gdb: Path) -> dict[str, Any]:
    """Calcula hash de cada arquivo da GDB e das demais entradas."""
    internal = {str(path.relative_to(gdb)): sha256_file(path) for path in sorted(gdb.rglob("*")) if path.is_file()}
    composite = hashlib.sha256()
    for name, digest in internal.items():
        composite.update(name.encode("utf-8"))
        composite.update(digest.encode("ascii"))
    return {"gdb_files": internal, "gdb_composite": composite.hexdigest(), "gpkg": sha256_file(GPKG_PATH),
            "scripts": {path.name: sha256_file(path) for path in SCRIPT_PATHS}}


def find_gdb() -> Path:
    """Localiza a única BDGD disponível."""
    gdbs = sorted(path for path in RAW_DIR.glob("*.gdb") if path.is_dir())
    if len(gdbs) != 1:
        raise RuntimeError(f"Esperada uma única .gdb; encontradas: {gdbs}")
    missing = [str(path) for path in (GPKG_PATH, *SCRIPT_PATHS) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Entradas ausentes: {missing}")
    return gdbs[0]


def ensure_outputs_absent() -> None:
    """Impede sobrescrita de qualquer artefato desta execução."""
    existing = [path.name for path in OUTPUTS if path.exists()]
    if existing:
        raise FileExistsError(f"Saídas para RUN_TAG={RUN_TAG} já existem: {existing}")


def layer_names(gdb: Path) -> dict[str, str]:
    """Mapeia camadas por nome case-insensitive."""
    return {str(name).lower(): str(name) for name, _ in pyogrio.list_layers(gdb)}


def cod_id_column(gdb: Path, layer: str) -> str:
    """Descobre o campo COD_ID preservando a capitalização original."""
    names = [str(name) for name in pyogrio.read_info(gdb, layer=layer)["fields"] if str(name).lower() == "cod_id"]
    if len(names) != 1:
        raise ValueError(f"COD_ID ausente ou ambíguo em {layer}: {names}")
    return names[0]


def text_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Converte atributos do lote para string; pyogrio não expõe dtype=str diretamente."""
    return frame.astype("string")


def read_batch(gdb: Path, layer: str, offset: int, columns: list[str] | None = None) -> pd.DataFrame:
    """Lê lote sem geometria via pyogrio.read_dataframe, sem pyarrow."""
    return text_frame(pyogrio.read_dataframe(gdb, layer=layer, columns=columns, read_geometry=False,
                                              skip_features=offset, max_features=BATCH_SIZE))


def string_value(value: Any) -> str:
    """Representação inequívoca de nulo para comparações cadastrais."""
    return "<NA>" if pd.isna(value) else str(value)


def audit_uc_table(gdb: Path, layer: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Teste A em duas passagens de baixa memória sobre a tabela de UC."""
    id_col = cod_id_column(gdb, layer)
    features = int(pyogrio.read_info(gdb, layer=layer)["features"])
    id_counts: Counter[str] = Counter()
    row_hash_counts: Counter[int] = Counter()
    timings: list[dict[str, Any]] = []
    columns: list[str] = []
    for offset in range(0, features, BATCH_SIZE):
        started = time.perf_counter()
        chunk = read_batch(gdb, layer, offset)
        columns = columns or list(chunk.columns)
        id_counts.update(chunk[id_col].map(string_value).tolist())
        row_hash_counts.update(int(value) for value in pd.util.hash_pandas_object(chunk, index=False).astype("uint64"))
        elapsed = time.perf_counter() - started
        timings.append({"tabela": layer, "passagem": 1, "lote": len(timings) + 1, "offset": offset,
                        "linhas": len(chunk), "segundos": round(elapsed, 3)})
        LOGGER.info("%s passagem 1 lote %s: %s linhas em %.3f s", layer, len(timings), len(chunk), elapsed)
    repeated_ids = {value for value, count in id_counts.items() if count > 1}
    repeated_hashes = {value for value, count in row_hash_counts.items() if count > 1}
    exact_rows: Counter[tuple[str, ...]] = Counter()
    first_values: dict[str, tuple[str, ...]] = {}
    divergent_values: dict[str, dict[str, set[str]]] = {}
    second_lot = 0
    for offset in range(0, features, BATCH_SIZE):
        started = time.perf_counter()
        chunk = read_batch(gdb, layer, offset)
        hashes = pd.util.hash_pandas_object(chunk, index=False).astype("uint64")
        for index in chunk.index[hashes.isin(repeated_hashes)]:
            exact_rows[tuple(string_value(value) for value in chunk.loc[index, columns])] += 1
        codes = chunk[id_col].map(string_value)
        repeated_chunk = chunk.loc[codes.isin(repeated_ids), columns]
        repeated_codes = codes.loc[repeated_chunk.index]
        for code, values in zip(repeated_codes.tolist(), repeated_chunk.itertuples(index=False, name=None)):
            normalized = tuple(string_value(value) for value in values)
            baseline = first_values.get(code)
            if baseline is None:
                first_values[code] = normalized
                continue
            per_id = divergent_values.setdefault(code, {})
            for position, (previous, current) in enumerate(zip(baseline, normalized)):
                if previous != current:
                    per_id.setdefault(columns[position], {previous}).add(current)
        elapsed = time.perf_counter() - started
        second_lot += 1
        timings.append({"tabela": layer, "passagem": 2, "lote": second_lot, "offset": offset,
                        "linhas": len(chunk), "segundos": round(elapsed, 3)})
        LOGGER.info("%s passagem 2 lote %s: %s linhas em %.3f s", layer, second_lot, len(chunk), elapsed)
    divergent = []
    for code, values in divergent_values.items():
        varying = {column: len(items) for column, items in values.items() if len(items) > 1}
        if varying:
            divergent.append((code, varying))
    columns_counter = Counter(column for _, varying in divergent for column in varying)
    details = "; ".join(f"{code}: " + ", ".join(f"{name}={amount}" for name, amount in varying.items())
                        for code, varying in divergent)
    summary = {"tabela": layer, "linhas": features, "cod_id_distintos": len(id_counts),
               "cod_id_repetidos": features - len(id_counts),
               "linhas_totalmente_identicas_redundantes": sum(count - 1 for count in exact_rows.values() if count > 1),
               "grupos_linhas_totalmente_identicas": sum(1 for count in exact_rows.values() if count > 1),
               "cod_id_com_linhas_divergentes": len(divergent),
               "colunas_que_variam": "; ".join(f"{name} ({count} COD_ID)" for name, count in sorted(columns_counter.items())),
               "detalhes_colunas_por_cod_id": details, "numero_lotes": len(timings) // 2,
               "tamanho_lote": BATCH_SIZE, "status": "OK"}
    return summary, timings


def count_key_layer(gdb: Path, requested: str, names: dict[str, str]) -> dict[str, Any]:
    """Teste B: conta COD_ID globalmente, em lotes, sem carregar geometrias."""
    layer = names.get(requested.lower())
    if layer is None:
        return {"camada": requested, "linhas": pd.NA, "cod_id_distintos": pd.NA, "cod_id_repetidos": pd.NA,
                "status": "AUSENTE", "erro": "camada não encontrada"}
    try:
        id_col = cod_id_column(gdb, layer)
        features = int(pyogrio.read_info(gdb, layer=layer)["features"])
        counts: Counter[str] = Counter()
        for offset in range(0, features, BATCH_SIZE):
            chunk = read_batch(gdb, layer, offset, [id_col])
            counts.update(chunk[id_col].map(string_value).tolist())
        return {"camada": layer, "linhas": features, "cod_id_distintos": len(counts),
                "cod_id_repetidos": features - len(counts), "status": "OK", "erro": ""}
    except (OSError, RuntimeError, ValueError) as error:
        LOGGER.exception("Falha no Teste B da camada %s", requested)
        return {"camada": requested, "linhas": pd.NA, "cod_id_distintos": pd.NA, "cod_id_repetidos": pd.NA,
                "status": "ERRO", "erro": str(error)}


def audit_script_patterns() -> pd.DataFrame:
    """Teste D: procura padrões literais sem executar os scripts de origem."""
    rows: list[dict[str, Any]] = []
    for path in SCRIPT_PATHS:
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            lowered = line.lower()
            for pattern in PATTERNS:
                if pattern in lowered:
                    rows.append({"script": path.name, "linha": line_number, "padrao": pattern, "trecho": line.strip()})
    return pd.DataFrame(rows, columns=["script", "linha", "padrao", "trecho"])


def hrc_point() -> Any:
    """Obtém o ponto do HRC do GeoPackage, sem coordenadas fixadas."""
    hospitals = gpd.read_file(GPKG_PATH, layer="hospitais")
    name_col = next((column for column in hospitals.columns if str(column).lower() == "nome"), None)
    if name_col is None:
        raise ValueError("Coluna nome ausente na camada hospitais")
    hrc = hospitals[hospitals[name_col].astype(str).str.contains("HRC|Hospital Regional de Ceil", case=False, regex=True, na=False)]
    if len(hrc) != 1:
        raise ValueError(f"Ponto HRC não é único: {len(hrc)} registros")
    return hrc.to_crs(31983).geometry.iloc[0] if str(hrc.crs) != "EPSG:31983" else hrc.geometry.iloc[0]


def audit_sub(gdb: Path, names: dict[str, str], point: Any) -> tuple[pd.DataFrame, bool, pd.DataFrame]:
    """Teste E: mede polígonos SUB sem corrigir geometrias."""
    layer = names.get("sub")
    if layer is None:
        raise ValueError("Camada SUB ausente")
    frame = pyogrio.read_dataframe(gdb, layer=layer)
    ident = cod_id_column(gdb, layer)
    sub = gpd.GeoDataFrame(frame, geometry="geometry", crs=pyogrio.read_info(gdb, layer=layer)["crs"]).to_crs(31983)
    rows = []
    for _, record in sub.iterrows():
        geometry = record.geometry
        rows.append({"cod_id": string_value(record[ident]), "area_m2": geometry.area if geometry is not None else pd.NA,
                     "geometria_valida": bool(geometry.is_valid) if geometry is not None else False,
                     "tipo_geometria": geometry.geom_type if geometry is not None else "AUSENTE",
                     "distancia_hrc_m": geometry.distance(point) if geometry is not None else pd.NA,
                     "suspeito_area_menor_10000m2": bool(geometry.area < SUSPECT_AREA_M2) if geometry is not None else True,
                     "contem_hrc": bool(geometry.contains(point)) if geometry is not None else False})
    result = pd.DataFrame(rows)
    return result, bool(result["contem_hrc"].any()), result.sort_values("distancia_hrc_m", na_position="last").head(3)


def classify(audits: list[dict[str, Any]]) -> tuple[str, str]:
    """Teste C: classificação limitada às evidências efetivamente medidas."""
    repeated = [row for row in audits if row["cod_id_repetidos"] > 0]
    if repeated:
        return "ORIGEM_BASE", "; ".join(f"{row['tabela']} tem {row['cod_id_repetidos']} linhas além dos COD_ID distintos diretamente na .gdb" for row in repeated)
    return "INDETERMINADO", "Tabelas de UC únicas na .gdb; CSVs anteriores não foram relidos nesta execução para provar PIPELINE."


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Cria uma saída nova sem permitir sobrescrita."""
    with path.open("x", encoding="utf-8", newline="") as target:
        frame.to_csv(target, index=False)


def write_report(text: str) -> None:
    """Cria relatório textual exclusivo desta execução."""
    with OUT_REPORT.open("x", encoding="utf-8", newline="") as target:
        target.write(text)


def hash_summary(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Compara hashes de todas as entradas e cada arquivo interno da GDB."""
    lines = []
    items = [("GDB composto", before["gdb_composite"], after["gdb_composite"]), ("GeoPackage", before["gpkg"], after["gpkg"])]
    items.extend((f"script:{name}", digest, after["scripts"].get(name, "AUSENTE")) for name, digest in before["scripts"].items())
    for name, old, new in items:
        lines.append(f"  {name}: {'INALTERADO' if old == new else 'ALTERADO'} ({old})")
    changed = [name for name, digest in before["gdb_files"].items() if after["gdb_files"].get(name) != digest]
    changed.extend(sorted(set(before["gdb_files"]) ^ set(after["gdb_files"])))
    lines.append(f"  Arquivos internos da GDB: {'INALTERADOS' if not changed else 'ALTERADOS'}; total={len(before['gdb_files'])}")
    return lines


def main() -> int:
    """Executa A-E, valida integridade e grava somente os novos artefatos versionados."""
    setup_logging()
    try:
        ensure_outputs_absent()
        gdb = find_gdb()
        LOGGER.info("RUN_TAG=%s; GDB=%s", RUN_TAG, gdb.name)
        before = collect_hashes(gdb)
        LOGGER.info("Hashes iniciais concluídos (%s arquivos internos na GDB)", len(before["gdb_files"]))
        names = layer_names(gdb)
        audits, batch_timings = [], []
        for requested in UC_LAYERS:
            layer = names.get(requested.lower())
            if layer is None:
                raise RuntimeError(f"Teste A impossível: camada ausente {requested}")
            summary, timings = audit_uc_table(gdb, layer)
            audits.append(summary)
            batch_timings.extend(timings)
        keys = [count_key_layer(gdb, requested, names) for requested in KEY_LAYERS]
        if any(row["status"] != "OK" for row in keys):
            raise RuntimeError("Teste B incompleto; conclusão não é válida")
        joins = audit_script_patterns()
        sub, contains_hrc, nearest = audit_sub(gdb, names, hrc_point())
        classification, evidence = classify(audits)
        after = collect_hashes(gdb)
        hashes = hash_summary(before, after)
        if before != after:
            raise RuntimeError("Falha de integridade: alguma entrada foi alterada")
        write_csv(pd.DataFrame(audits), OUT_A)
        write_csv(pd.DataFrame(keys), OUT_B)
        write_csv(joins, OUT_D)
        write_csv(sub, OUT_E)
        partial_lines = []
        for name in PARTIAL_FILES:
            path = PROCESSED_DIR / name
            stat = path.stat()
            partial_lines.append(f"  - {name}: {stat.st_size} bytes; mtime_utc={datetime.fromtimestamp(stat.st_mtime, tz=datetime.now().astimezone().tzinfo).isoformat()}")
        report = ["=" * 80, "RELATÓRIO DE AUDITORIA DA FONTE DE DUPLICIDADE (03f)", "=" * 80,
                  f"RUN_TAG: {RUN_TAG}", f"Data/hora: {datetime.now().isoformat(timespec='seconds')}", "", "1. HASHES ANTES -> DEPOIS", *hashes,
                  "", "2. TESTE A - UCMT_tab e UCBT_tab", pd.DataFrame(audits).to_string(index=False),
                  "", "Tempos por lote (s):", pd.DataFrame(batch_timings).to_string(index=False),
                  "", "3. TESTE B - CHAVES NAS CAMADAS-FONTE", pd.DataFrame(keys).to_string(index=False),
                  "", "4. TESTE C - ORIGEM", f"  Classificação: {classification}", f"  Evidência: {evidence}",
                  "", "5. TESTE D - OCORRÊNCIAS LITERAIS", joins.to_string(index=False) if not joins.empty else "  Nenhuma ocorrência.",
                  "", "6. TESTE E - POLÍGONOS SUB", f"  HRC contido em algum polígono SUB: {contains_hrc}", "  Três mais próximos:", nearest.to_string(index=False),
                  "", "7. EXECUÇÕES ANTERIORES", "  A execução interrompida anterior falhou porque pyarrow não está instalado.",
                  "  Os CSVs parciais abaixo não foram utilizados em nenhuma conclusão desta execução:", *partial_lines,
                  "", "8. LIMITAÇÕES", "  - Não foi usada pyarrow nem pyogrio.read_arrow; pyogrio não possui parâmetro dtype, portanto cada lote foi convertido para string imediatamente após a leitura.",
                  "  - Esta auditoria não identifica a UC do HRC, não prova atendimento elétrico e não monta grafo.",
                  "  - A classificação PIPELINE exigiria tabelas únicas na GDB e nova auditoria explícita dos CSVs; não foi necessária porque houve repetição na origem.", "=" * 80, ""]
        write_report("\n".join(report))
        LOGGER.info("Concluído: %s", classification)
        return 0
    except (FileExistsError, FileNotFoundError, OSError, RuntimeError, ValueError, MemoryError) as error:
        LOGGER.exception("Auditoria interrompida: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
