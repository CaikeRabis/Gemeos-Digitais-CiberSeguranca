# Laudo Pericial de Topologia Segregada e Calibração Elétrica — Zona 2 (Asa Sul / Plano Piloto)
## Desmistificação do SPOF, Georreferenciamento e Modelagem Definitiva do HBDF na Subestação SBG

---

### 1. Resumo Executivo e Contexto Histórico da Análise

Este laudo consolida a auditoria geográfica e elétrica definitiva da **Zona 2 (Asa Sul / Plano Piloto)** no âmbito do projeto de modelagem de resiliência e cibersegurança das infraestruturas críticas do Distrito Federal.

Inicialmente, com base no cruzamento cadastral preliminar da BDGD (Banco de Dados Geográfico da Distribuidora / Neoenergia Brasília), havia sido levantada a hipótese de um **Ponto Único de Falha (SPOF - Single Point of Failure)** compartilhado na **Subestação Subterrânea Hípica (SE SHP)**, na qual o Hospital de Base do Distrito Federal (HBDF) supostamente compartilharia a mesma subestação que o Complexo da Polícia Civil do Distrito Federal (1ª DP / DPE no Setor Policial Sul).

Contudo, uma investigação espacial aprofundada (varredura com buffer métrico de 500 metros em EPSG:31983) e a auditoria de demanda revelaram que a associação prévia se tratava de um **falso positivo cadastral**:
1. A UC cadastrada na SE SHP possuía apenas **90 kW** de demanda contratada e estava localizada a **4,41 km** de distância física do hospital, tratando-se provavelmente de um posto administrativo periférico ou erro de chaveamento histórico.
2. O **verdadeiro centro de carga do HBDF** está conectado ao PAC primário **`S02_0201_PT_TF_913`**, pertencente ao alimentador **`02_BGC1`** da **Subestação Brasília Geral (SE SBG / Furnas)**.
3. A **1ª Delegacia de Polícia (Complexo PCDF SPS)** permanece suprida pela **Subestação SHP** através do alimentador **`HP04`** no PAC **`SHP_HP04_9025_BSB27A`**.

**Conclusão Topológica Principal:** Assim como observado na **Zona 1 (Ceilândia)** — onde o HRC é suprido pela SE STN e a 15ª DP pela SE SCN —, a **Zona 2 (Asa Sul / Plano Piloto) possui segregação física e elétrica absoluta entre as redes de Saúde e Segurança Pública (SE SBG ≠ SE SHP)**. Essa configuração confere alta imunidade contra blecautes conjuntos originados por contingências N-1 em subestações.

---

### 2. Linha do Tempo e Correção do Erro Geográfico (Ground Truth GIS)

| Etapa da Investigação | Coordenadas Atribuídas | Erro de Posicionamento | Carga Registrada | Subestação Cadastrada | Diagnóstico Técnico |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **1. BDGD Preliminar** | Lat `-15.8411`, Lon `-47.9432` | **+4.405,8 m (4,41 km)** | `90.00 kW` | SE SHP (`HP03`) | Falso positivo (ponto na Hípica/ParkShopping) |
| **2. Correção Buscoords (Script 17)** | Lat `-15.7983`, Lon `-47.8921` | `0,0 m` (Ground Truth) | `90.00 kW` | SE SHP (`HP03`) | Correção geográfica mantendo rede elétrica anterior |
| **3. Rastreamento Espacial (Script 19)**| Buffer 500m no SMHS | `0,0 m` (Varredura UTM) | **`1.700,68 kW`** | **SE SBG (`02_BGC1`)** | Descoberta do verdadeiro PAC (`S02_0201_PT_TF_913`) |
| **4. Modelo Definitivo (Script 20)**| Lat `-15.7948`, Lon `-47.8922` | **383,0 m** (Baricentro) | **`1.700,68 kW`** | **SE SBG (`02_BGC1`)** | Malha primária 34.5/13.8 kV conectada e resolvida |

---

### 3. Especificações Técnicas do Verdadeiro Complexo Hospitalar (HBDF)

O complexo do Hospital de Base do Distrito Federal (SMHS - Setor Médico Hospitalar Sul) é uma infraestrutura de saúde terciária de alta complexidade. Na BDGD consolidada, o PAC oficial **`S02_0201_PT_TF_913`** agrega 12 Unidades Consumidoras de Média Tensão com as seguintes características:

* **Demanda Contratada Agregada:** **`1.700,68 kW` (1,70 MW)**
* **Carga Instalada Agregada Cadastrada:** **`117.863,81 kW` (~117,9 MW)**
* **Tensão Primária de Fornecimento:** **`13.8 kV` (Trifásico)**
* **CNAE Predominante:** `8610-1/01` (Atividades de Atendimento Hospitalar)
* **Fator de Potência Operacional:** `0.92` (Indutivo)
* **Distância ao Baricentro Histórico:** `383,0 metros`

---

### 4. Topologia Físico-Elétrica da Subestação SBG (Brasília Geral)

A modelagem eletromecânica no OpenDSS do circuito `02_BGC1` revelou uma arquitetura robusta de distribuição subterrânea em dois níveis:

1. **Subtransmissão em 34.5 kV:**
   * A Subestação Central SBG (Furnas) opera com transformador de força de **60 MVA (138 / 34.5 kV)** regulado a **1.04 pu** na barra `SBG34S1`.
   * O alimentador primário `02_BGC1` transporta a energia até as subestações intermediárias de rebaixamento urbano.

2. **Rebaixamento para Média Tensão (13.8 kV):**
   * Três transformadores de subestação (`T1_S02`, `T2_S02`, `T3_S02`), cada um de **20 MVA** (totalizando **60 MVA**), realizam o rebaixamento de 34.5 kV para 13.8 kV nas barras `02_BA1138KV`, `02_BA2138KV` e `02_BA3138KV`.

3. **Distribuição Primária e Atendimento ao SMHS:**
   * A malha de média tensão subterrânea de 13.8 kV conecta diretamente o barramento do HBDF (`S02_0201_PT_TF_913`), garantindo suporte de potência e baixíssima impedância.

---

### 5. Resultados do Fluxo de Potência e Auditoria Regulatória PRODIST

O modelo foi resolvido em regime permanente pelo método de Newton-Raphson com carregamento total (UCMT + 15.095 UCBT recalculadas pelo Fator de Coincidência: `kW = max((ENE_MEDIO / 730) * 1.5, 0.05)`).

#### 5.1 Perfil de Tensões Nodais no PAC do HBDF (`S02_0201_PT_TF_913`)

| Fase | Tensão Nodal (pu) | Tensão Física Linha-Linha (kV) | Limite Mínimo PRODIST | Limite Máximo PRODIST | Classificação Regulatória |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Fase A** | **`0.9514 pu`** | `13.129 kV` | `0.9300 pu` | `1.0500 pu` | **`[ADEQUADA]`** |
| **Fase B** | **`0.9922 pu`** | `13.692 kV` | `0.9300 pu` | `1.0500 pu` | **`[ADEQUADA]`** |
| **Fase C** | **`0.9857 pu`** | `13.603 kV` | `0.9300 pu` | `1.0500 pu` | **`[ADEQUADA]`** |

* **Tensão Média Nodal:** `0.9764 pu`
* **Desbalanço de Tensão Nodal:** `4.08%`
* **Margem de Segurança Regulatória:** Todas as fases operam com folga mínima de **`+2.14%`** acima do limite crítico inferior (0.9300 pu).

#### 5.2 Perfil de Tensões Nodais no PAC da 1ª DP / PCDF SPS (`SHP_HP04_9025_BSB27A`)

| Fase | Tensão Nodal (pu) | Tensão Física Linha-Linha (kV) | Limite Mínimo PRODIST | Limite Máximo PRODIST | Classificação Regulatória |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Fase A** | **`1.0138 pu`** | `13.991 kV` | `0.9300 pu` | `1.0500 pu` | **`[ADEQUADA]`** |
| **Fase B** | **`1.0158 pu`** | `14.018 kV` | `0.9300 pu` | `1.0500 pu` | **`[ADEQUADA]`** |
| **Fase C** | **`1.0157 pu`** | `14.017 kV` | `0.9300 pu` | `1.0500 pu` | **`[ADEQUADA]`** |

* **Desbalanço de Tensão Nodal:** `0.20%` (Excelente simetria de fases).
* **Diagnóstico Regulatório:** Conforme **`[ADEQUADA]`** em 100% das fases.

#### 5.3 Balanço Energético e Eficiência Global da Zona 2

| Métrica Eletromecânica | Subestação SBG (HBDF - Saúde) | Subestação SHP (1ª DP - Segurança) | Total Zona 2 Consolidada |
| :--- | :---: | :---: | :---: |
| **Alimentador Principal** | `02_BGC1` (com `BG_01C2`) | `HP04` (com `HP03`) | 4 Alimentadores MT |
| **Segmentos Primários (MT)** | `2.067` | `463` | `2.530` segmentos |
| **Transformadores de SE e MT**| `181` | `95` | `276` transformadores |
| **Potência Ativa Injetada** | **`19.969 MW`** | **`13.356 MW`** | **`33.325 MW`** |
| **Potência Reativa Injetada**| `8.888 Mvar` | `5.762 Mvar` | `14.650 Mvar` |
| **Potência Aparente Injetada**| `21.858 MVA` | `14.545 MVA` | `36.403 MVA` |
| **Perdas Técnicas Ativas** | **`1.119,13 kW`** | **`505,66 kW`** | **`1.624,79 kW`** |
| **Percentual de Perdas** | **`5.60%`** | **`3.79%`** | **`4.88%`** |
| **Eficiência da Malha** | **`94.40%`** | **`96.21%`** | **`95.12%`** |

---

### 6. Matriz Comparativa de Resiliência: Zona 1 (Ceilândia) vs Zona 2 (Asa Sul)

| Dimensão de Análise | Zona 1: Ceilândia (Periferia Urbana) | Zona 2: Asa Sul (Centro do Poder) | Diagnóstico Comparativo |
| :--- | :--- | :--- | :--- |
| **Topologia de Atendimento** | **Segregada** (`STN` para HRC ≠ `SCN` para 15ª DP) | **Segregada** (`SBG` para HBDF ≠ `SHP` para 1ª DP) | **Idêntica:** Ambas possuem isolamento físico de fontes. |
| **Ponto Único de Falha (SPOF)**| Inexistente | Descartado (Falso Positivo) | Resiliência contra colapso simultâneo garantida. |
| **Conformidade PRODIST Saúde** | **Adequada** (1.002 a 1.030 pu no HRC) | **Adequada** (0.951 a 0.992 pu no HBDF) | Tensão estável sob carregamento nominal de pico. |
| **Conformidade Segurança** | **Precária** (0.925 pu na Fase A da 15ª DP) | **Adequada** (1.014 a 1.016 pu na 1ª DP) | **Assimetria Estrutural:** Queda de tensão na Ceilândia. |
| **Topologia Física de Cabos** | Redes aéreas predominantes (longas distâncias)| Redes subterrâneas em anel e galerias técnicas | Asa Sul possui menores perdas (4,88% vs 7,76%). |
| **Potência Total Injetada** | `16.60 MW` | `33.33 MW` | Asa Sul concentra 2x a densidade de carga. |

---

### 7. Rastreabilidade de Artefatos Gerados

Os ativos definitivos referentes à modelagem da Zona 2 encontram-se versionados e disponíveis em:

1. **Modelos OpenDSS Subestação SBG (HBDF):**
   - [`Master_SBG.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Master_SBG.dss)
   - [`Loads_SBG_20261028_120647.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Loads_SBG_20261028_120647.dss)
   - [`geo_sbg.gpkg`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/geo_sbg.gpkg)
2. **Modelos OpenDSS Subestação SHP (1ª DP):**
   - [`Master_SHP_Calibrado.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Master_SHP_Calibrado.dss)
   - [`Buscoords_SHP_Calibrado.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Buscoords_SHP_Calibrado.dss)
   - [`geo_shp_20261028_101044.gpkg`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/geo_shp_20261028_101044.gpkg)
3. **Laudos de Auditoria em JSON:**
   - [`laudo_baseline_sbg_hbdf.json`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/laudo_baseline_sbg_hbdf.json)
   - [`laudo_correcao_geografica_asa_sul.json`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/laudo_correcao_geografica_asa_sul.json)
4. **Dashboard Frontend Integrado:**
   - [`Dashboard_Resiliencia_DF_Definitivo.html`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/Dashboard_Resiliencia_DF_Definitivo.html)
