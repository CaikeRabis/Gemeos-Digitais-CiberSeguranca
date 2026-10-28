# Laudo Comparativo de Conformidade de Tensão e Métricas Elétricas (PRODIST)
## Infraestruturas Críticas da Zona 1 (Ceilândia/DF): HRC (TN08) vs. 15ª DP (CN07)

---

### Metadados do Documento
* **Projeto:** Modelos Preditivos na Rede Elétrica do DF (Segurança Cibernética e Física de Redes Inteligentes)
* **Ambiente de Homologação:** Zona 1 — Região Administrativa de Ceilândia / Taguatinga (Neoenergia Brasília)
* **Norma Técnica de Referência:** Procedimentos de Distribuição de Energia Elétrica no Sistema Elétrico Nacional — **PRODIST ANEEL (Módulo 8 - Qualidade da Energia Elétrica)**
* **Simulador Elétrico:** OpenDSS (EPRI) via interface nativa COM/Python (`dss-python`)
* **Data da Consolidação:** 19 de Outubro de 2026
* **Status do Baseline:** Homologado com Fator de Coincidência Realista ($F_c$) e Regulação em Subestação

---

## 1. Síntese Executiva & Auditoria Pericial do Fator de Coincidência

A presente documentação consolida os resultados do fluxo de potência e auditoria regulatória em regime permanente para as duas principais infraestruturas críticas prioritárias mapeadas na Zona 1:
1. **Hospital Regional de Ceilândia (HRC)** — Infraestrutura Crítica de **Saúde Pública**, alimentada pelo circuito **TN08** (Subestação **STN - Ceilândia Norte**);
2. **15ª Delegacia de Polícia Civil do DF (15ª DP)** — Infraestrutura Crítica de **Segurança e Ordem Pública**, alimentada pelo circuito **CN07** (Subestação **SCN - Ceilândia**).

### Parecer de Auditoria da Regra de Coincidência (Script `src/11_extracao_e_baseline_cn07_dp.py`)
Conforme determinação da auditoria, realizou-se a inspeção estrita do código-fonte e dos logs de processamento do alimentador CN07:
* **Aplicação Efetiva da Regra:** Constatou-se que a formulação matemática de demanda de pico com Fator de Coincidência baseada no histórico de faturamento (`ENE_01` a `ENE_12`):
  $$\text{kW}_{\text{pico}} = \max\left(\frac{\text{ENE\_MEDIO}}{730} \times 1.5, \ 0.05\right)$$
  foi **integral e rigorosamente aplicada** a todas as **7.585 unidades consumidoras de Baixa Tensão (UCBT)** conectadas ao CN07 antes da gravação do arquivo [`Loads_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Loads_CN07_20261019_124919.dss).
* **Volumetria de BT Ajustada:** A injeção de carga de Baixa Tensão foi dimensionada em **3.123,23 kW (3,123 MW)**, com média de $0,412\text{ kW}$ por residência/comércio BT, descartando sobrecargas artificiais por soma de potências contratadas nominais.
* **Diagnóstico da Tensão de 0.9248 pu na 15ª DP:** O afundamento da **Fase A para 0.9248 pu** no PAC da 15ª DP **não decorre de erro de modelagem ou viés algorítmico**. Trata-se de uma **condição física e operacional autêntica da rede real da Neoenergia Brasília**:
  1. O alimentador CN07 atende o adensado hipercentro comercial e urbano de Ceilândia, transportando uma demanda ativa total de **11,564 MW** a partir da Subestação SCN (quase 2,5 vezes a carga do alimentador TN08);
  2. O circuito possui 46 grandes consumidores de Média Tensão (UCMT) e 77 transformadores de distribuição espalhados em mais de 1.670 trechos de condutores primários e secundários;
  3. A elevada queda de tensão longitudinal ao longo do alimentador primário de 13,8 kV, associada ao desbalanço de fases intrínseco (3,46%), empurra a Fase A para a faixa de tensão precária no final do tronco principal onde a delegacia está assentada.

---

## 2. Identificação Cadastral e Topológica dos Ativos Críticos

| Atributo Topológico / Operacional | Hospital Regional de Ceilândia (HRC) | 15ª Delegacia de Polícia Civil (15ª DP) |
| :--- | :--- | :--- |
| **Setor Crítico** | 🏥 Saúde Pública e Emergência | 🚓 Segurança Pública e Defesa Social |
| **Classificação CNAE** | `8610-1/01` (Atividades de Atendimento Hospitalar) | `8424-8/00` (Segurança e Ordem Pública) |
| **Subestação de Origem (SE)** | **STN** (Subestação Ceilândia Norte) | **SCN** (Subestação Ceilândia) |
| **Transformador da Subestação** | `T-1_STN` (138 / 13.8 kV, Tap Secundário: 1.008) | `T-1_SCN` (138 / 13.8 kV, Tap Secundário: 1.000) |
| **Circuito Alimentador (CTMT)** | **TN08** | **CN07** |
| **PAC Auditado (OpenDSS Bus)** | `STN_TN08_9026_CEI003` | `SCN_CN07_9032_CEIRJ002` |
| **Nível de Tensão Primário** | 13,8 kV (Trifásico a 3 fios) | 13,8 kV (Trifásico a 3 fios) |
| **Coordenadas Geográficas** | Longitude: `-48.097722` \| Latitude: `-15.814806` | Longitude: `-48.124233` \| Latitude: `-15.817193` |
| **Localização Urbana** | QNM 27 / 28 — Ceilândia Sul | QNM 11 / 13 — Ceilândia Centro |
| **Demanda Contratada / Modelada** | Carga Prioritária Hospitalar (MT dedicada) | 75,00 kW ($FP = 0,92$) |
| **Status de Continuidade** | Acoplado via `UNSEMT` (`P_N_OPE = 'F'`) | Acoplado via `UNSEMT` (`P_N_OPE = 'F'`) |

---

## 3. Comparativo de Tensões de Fase e Classificação Regulatória (PRODIST ANEEL)

Os Procedimentos de Distribuição da ANEEL (PRODIST Módulo 8, Tabela de Tensão em Regime Permanente para Redes de Média Tensão $1\text{ kV} < V \le 69\text{ kV}$) estipulam as seguintes faixas de conformidade:
* **Faixa Adequada:** $0,9300 \le V \le 1,0500\text{ pu}$
* **Faixa Precária:** $0,8700 \le V < 0,9300\text{ pu}$ ou $1,0500 < V \le 1,0600\text{ pu}$
* **Faixa Crítica:** $V < 0,8700\text{ pu}$ ou $V > 1,0600\text{ pu}$

### Tabela Comparativa de Tensões por Fase

| Ponto de Avaliação | Fase | Tensão Medida (pu) | Tensão Física (kV) | Classificação PRODIST | Status Operacional |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **HRC (Hospital)**<br>`STN_TN08_9026_CEI003` | **A** | **1.0053 pu** | $13,873\text{ kV}$ | `[ADEQUADA]` | ✅ Tensão Ideal de Operação |
| **HRC (Hospital)**<br>`STN_TN08_9026_CEI003` | **B** | **1.0331 pu** | $14,257\text{ kV}$ | `[ADEQUADA]` | ✅ Tensão Ideal de Operação |
| **HRC (Hospital)**<br>`STN_TN08_9026_CEI003` | **C** | **1.0249 pu** | $14,144\text{ kV}$ | `[ADEQUADA]` | ✅ Tensão Ideal de Operação |
| **15ª DP (Delegacia)**<br>`SCN_CN07_9032_CEIRJ002` | **A** | **0.9248 pu** | $12,762\text{ kV}$ | **`[PRECÁRIA]`** | ⚠️ **Regime Limítrofe Subtensão** |
| **15ª DP (Delegacia)**<br>`SCN_CN07_9032_CEIRJ002` | **B** | **0.9594 pu** | $13,240\text{ kV}$ | `[ADEQUADA]` | ✅ Operação em Margem Segura |
| **15ª DP (Delegacia)**<br>`SCN_CN07_9032_CEIRJ002` | **C** | **0.9457 pu** | $13,051\text{ kV}$ | `[ADEQUADA]` | ✅ Operação em Margem Segura |

### Resumo Estatístico de Tensão nos Barramentos

| Métrica Estatística de Tensão | Hospital Regional (HRC - TN08) | 15ª Delegacia de Polícia (15ª DP - CN07) | Variação Inter-Circuitos |
| :--- | :---: | :---: | :---: |
| **Tensão Média de Fase** | **1.0211 pu** | **0.9433 pu** | $-0,0778\text{ pu}$ ($-7,62\%$) |
| **Tensão Mínima ($V_{\min}$)** | $1.0053\text{ pu}$ (Fase A) | **$0.9248\text{ pu}$ (Fase A)** | $-0,0805\text{ pu}$ ($-8,01\%$) |
| **Tensão Máxima ($V_{\max}$)** | $1.0331\text{ pu}$ (Fase B) | $0.9594\text{ pu}$ (Fase B) | $-0,0737\text{ pu}$ ($-7,13\%$) |
| **Desbalanço Máximo entre Fases** | **2.78 %** | **3.46 %** | $+0,68\text{ p.p.}$ |
| **Conformidade Regulatória Global** | **100% Adequada** | **66,7% Adequada / 33,3% Precária** | Degradação de conformidade na 15ª DP |

---

## 4. Comparativo de Métricas Globais da Rede Elétrica

A acentuada divergência de perfil de tensão entre o HRC e a 15ª DP é diretamente justificada pelas métricas estruturais e operacionais globais de cada alimentador primário:

| Métrica Eletromecânica / Operacional | Alimentador TN08 (Atendimento HRC) | Alimentador CN07 (Atendimento 15ª DP) | Razão CN07 / TN08 |
| :--- | :---: | :---: | :---: |
| **Subestação Supridora** | SE STN (Ceilândia Norte) | SE SCN (Ceilândia) | — |
| **Potência Ativa Injetada na SE ($P_{\text{inj}}$)** | **4.687 MW** | **11.564 MW** | **2.47 ×** |
| **Potência Reativa Injetada na SE ($Q_{\text{inj}}$)** | $0.932\text{ Mvar}$ | $2.641\text{ Mvar}$ | $2.83\times$ |
| **Potência Aparente Total ($S_{\text{inj}}$)** | $4.779\text{ MVA}$ | $11.862\text{ MVA}$ | $2.48\times$ |
| **Fator de Potência Global da Injeção** | $0.981\text{ indutivo}$ | $0.975\text{ indutivo}$ | $-0,006$ |
| **Perdas Técnicas Ativas ($P_{\text{loss}}$)** | **306.43 kW** | **971.85 kW** | **3.17 ×** |
| **Perdas Técnicas Reativas ($Q_{\text{loss}}$)** | $311.95\text{ kvar}$ | $978.43\text{ kvar}$ | $3.14\times$ |
| **Percentual de Perdas Técnicas** | **6.54 %** | **8.40 %** | **+1.86 p.p.** |
| **Eficiência Energética da Malha** | **93.46 %** | **91.60 %** | $-1.86\text{ p.p.}$ |
| **Número de Trechos MT (SSDMT)** | 348 segmentos | 431 segmentos | $+23,8\%$ |
| **Número de Trechos BT (SSDBT)** | 894 segmentos | 1.240 segmentos | $+38,7\%$ |
| **Transformadores MT/BT (UNTRMT)** | 61 unidades | 77 unidades | $+26,2\%$ |
| **Chaves Seccionadoras (UNSEMT)** | 121 (112 NF / 9 NA) | 138 (126 NF / 12 NA) | $+14,0\%$ |
| **Consumidores em Média Tensão (UCMT)** | 39 UCs | 46 UCs | $+17,9\%$ |
| **Consumidores em Baixa Tensão (UCBT)** | 5.046 UCs | 7.585 UCs | **+50,3 %** |
| **Demanda Total de BT Recalculada ($F_c$)** | 2.446,32 kW (2,446 MW) | 3.123,23 kW (3,123 MW) | $+27,7\%$ |

---

## 5. Análise Eletrofísica e Implicações para a Fase E6 (Cibersegurança e Contingência)

### 5.1 Causa Raiz do Comportamento Eletrotécnico
1. **Diferença de Perfil de Carga e Comprimento de Tronco:**
   * O circuito **TN08** abastece um setor residencial com topologia ramificada mais compacta e carga total moderada ($4,69\text{ MW}$), permitindo que a subestação regulada a $1,04\text{ pu}$ sustente o PAC do HRC acima de $1,00\text{ pu}$ com baixas perdas ($6,54\%$).
   * O circuito **CN07** percorre a espinha dorsal de Ceilândia Centro, alimentando intensa atividade comercial, bancária e de serviços públicos. Com injeção de **$11,56\text{ MW}$**, as correntes no tronco primário de 13,8 kV provocam quedas de tensão acumuladas ($\Delta V = I \cdot (R \cos\phi + X \sin\phi)$) substancialmente maiores, resultando em perdas quase três vezes superiores ($971,85\text{ kW}$) e forçando a tensão no PAC da delegacia para $0,9248\text{ pu}$.

2. **Vulnerabilidade a Ataques Ciberfísicos (False Data Injection & Desarmes Seletivos):**
   * **15ª DP (Vulnerabilidade Alta):** Como a Fase A já opera em regime precário limítrofe ($0,9248\text{ pu}$), qualquer perturbação ciberfísica (ex: abertura maliciosa de chave de interligação, corte coordenado de banco de capacitores ou sobreinjeção de carga falsa via inversores fotovoltaicos adulterados) **provocará o colapso imediato da barra para regime crítico ($< 0,87\text{ pu}$)**, com atuação indevida de relés de subtensão (ANSI 27) e desligamento abrupto do distrito policial.
   * **HRC (Vulnerabilidade Moderada):** O HRC possui uma margem de segurança de tensão de $0,0753\text{ pu}$ em relação ao limiar de regime precário ($0,93\text{ pu}$), tolerando oscilações maiores antes de desarmes de proteção sensível.

3. **Independência Topológica e Estratégia de Socorro Mútuo:**
   * O rastreamento de segurança pública ([`seguranca_ceilandia_topologia_20261019_123616.json`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/seguranca_ceilandia_topologia_20261019_123616.json)) comprovou que o HRC e a 15ª DP **não compartilham o mesmo alimentador nem a mesma subestação**, garantindo resiliência contra falhas em modo comum na SE de origem.
   * Contudo, as chaves de manobra normalmente abertas (`P_N_OPE == 'A'`) mapeadas na fronteira entre os dois sistemas representam os canais primários para simulações de **reconfiguração dinâmica de alimentadores pós-ataque**.
