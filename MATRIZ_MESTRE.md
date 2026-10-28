# MATRIZ MESTRE: Modelos Preditivos na Rede Elétrica do DF

- **Versão:** 18/10/2026 (Atualizada após conclusão das Etapas E1, E2, E3 e E4 no run `20261018_133430`)
- **Pasta de trabalho:** `C:\Users\adm\Documents\Modelos Preditivos na Rede Elétrica do DF`
- **Ambiente Python:** `& ".\venv\Scripts\python.exe"`
- **Base de dados de origem:** BDGD (Base de Dados Geográfica da Distribuidora - ANEEL / Neoenergia Distribuição Brasília) em `data/raw/*.gdb`.

---

## 1. OBJETIVO FINAL DO PROJETO

Finalizar a modelagem física, topológica e preditiva do sistema de distribuição de energia elétrica do Distrito Federal a partir da BDGD da ANEEL, com os seguintes entregáveis:

1. **Rastreamento Topológico Completo do HRC:** Identificar e mapear para o **Hospital Regional de Ceilândia (HRC)** toda a cadeia física que o atende a partir da média tensão:
   $$\text{UC} \longrightarrow \text{Ramal de Conexão} \longrightarrow \text{PAC} \longrightarrow \text{Transformador MT/BT } (\text{UNI\_TR\_MT}) \longrightarrow \text{Circuito MT } (\text{CTMT}) \longrightarrow \text{Subestação } (\text{SUB})$$
2. **Base de Unidades Consumidoras (UC) Consolidada e Desduplicada:** Construir uma base analítica unificada de UCs sem registros duplicados espúrios, com metodologia 100% reproduzível, auditável e fundamentada nos fatos medidos nos dados.
3. **Simulações Elétricas Avançadas:** Utilizar essa base consolidada para rodar simulações de fluxo de potência, carregamento de transformadores e circuitos, análise de contingências ($N-1$) e impacto de injeção de carga e geração distribuída.
4. **Generalização:** O HRC é o caso piloto (Ground Truth). Uma vez validada a cadeia de modelagem, o mesmo pipeline será aplicado a todos os outros hospitais e cargas críticas do DF.

---

## 2. ONDE ESTAMOS (FASE ATUAL: ETAPA E5)

- **Fase atual:** **Etapa E5 — Expansão e Simulação Elétrica do Circuito TN08 / HRC**.
- **Status das Etapas Anteriores:**
  - **E1 (Diagnóstico Populacional):** Concluído no script `03i` (`20261018_124845`).
  - **E2 (Regra de Deduplicação):** Formulada e validada (Cascata R3 + Partição H1/H3 por soma e H4 por pontos físicos).
  - **E3 (Consolidação da Base de UC):** Concluída no script `04` (`20261018_131447`). Geradas bases consolidadas de UCMT (5.609 UCs) e UCBT (1.183.916 UCs).
  - **E4 (Rastreamento Topológico do HRC):** Concluído no script `05` (`20261018_133430`). Identificada UC em MT alimentada pelo circuito **TN08** da subestação **STN**.

---

### 2.1 Fatos Medidos na População Total (Invariantes — Não Reabrir)

Medições realizadas diretamente no `.gdb` em modo somente leitura via `pyogrio`, particionadas em 20 baldes por dispersão de hash `CRC32(COD_ID)`:

| Tabela | Total de Linhas | `COD_ID` Distintos | `COD_ID` Repetidos | `COD_ID` Divergentes | Linhas Totalmente Idênticas na Origem |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`UCMT_tab`** (Média Tensão) | 6.275 | 5.609 | 666 (10,61%) | **645** | **0** |
| **`UCBT_tab`** (Baixa Tensão) | 1.310.713 | 1.183.787 | 126.926 (9,68%) | **124.224** | **0** |

#### Fatos Medidos Adicionais na População Total:
- **Ausência de clones puros:** Não há duplicatas com 100% das colunas idênticas no banco (`0` linhas idênticas). Cada linha duplicada apresenta variação em pelo menos um atributo.
- **Divergência topológica:** Em `UCBT_tab`, as colunas de conexão e rede (`PAC`, `RAMAL`, `PN_CON`, `UNI_TR_MT`, `CTMT`, `SUB`) variam entre 43.000 e 61.000 `COD_ID` repetidos.
- **Divergência de vigência e data:** `SIT_ATIV` varia em 66.816 `COD_ID` de BT e 641 de MT; `DAT_CON` varia em 60.912 de BT e 27 de MT.
- **Natureza de `CLAS_SUB`:** Subclasse tarifária (`CLAS_SUB`) é atributo comercial de consumo, não vínculo topológico de rede.

---

### 2.2 Histórico Consolidado de Execuções e Resultados

| Script | RUN_TAG | Código de Saída | O que mediu / demonstrou |
| :--- | :--- | :--- | :--- |
| [`src/03g_colunas_dedup_matriz.py`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03g_colunas_dedup_matriz.py) / `03g2` | `20261017_152132` | `exit=0` | Identificou estouro de memória na leitura total. Estabeleceu a arquitetura obrigatória em **20 baldes via CRC32**. |
| [`src/03h_amostra_grupos_duplicados.py`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03h_amostra_grupos_duplicados.py) | `20261017_172116` | `exit=0` | Extraiu amostra balanceada de 10.000 `COD_ID` repetidos de BT (20 baldes x 500) e 645 de MT. Avaliou regras R1 a R4. |
| [`src/analise_ambiguos_cascata.py`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/analise_ambiguos_cascata.py) | `20261017_180249` | `exit=0` | Reproduziu e auditou os **102 ambíguos** da regra R3 na amostra. Mapeou 53 colunas divergentes. |
| [`src/analise_complementaridade_ambiguos.py`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/analise_complementaridade_ambiguos.py) | `20261018_112614` | `exit=0` | Testou complementaridade nos 24 meses (`ENE` e `DEM`) e consistência de rede nos 102 ambíguos. |

---

### 2.3 Status das Pendências Anteriores (Todas Sanadas)

1. **Confirmação do exit code do run `172116`:** Auditado e confirmado (`exit=0`).
2. **Auditoria do fallback da cascata R3:** Auditado no código de [`03h`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03h_amostra_grupos_duplicados.py#L573-L584). Quando não há registro com `SIT_ATIV == 'AT'`, a regra faz fallback seguro considerando todas as linhas do grupo e desempata pela data de conexão máxima (`DAT_CON`), nunca gerando grupos perdidos.
3. **Teste de complementaridade e rede nos 102 ambíguos:** Executado com sucesso no run `20261018_112614`.

---

## 3. RESULTADOS CONSOLIDADOS E DESCOBERTAS ATÉ AGORA

### 3.1 Desempenho das Regras Candidatas na Amostra

#### A. Em `UCMT_tab` (População completa de 645 `COD_ID` divergentes):
- **R1 (`SIT_ATIV == 'AT'`):** 638 resolvidos, 7 ambíguos, 0 perdidos.
- **R2 (`DAT_CON` máxima):** 25 resolvidos, 620 ambíguos, 0 perdidos.
- **R3 Cascata (`SIT_ATIV == 'AT'` $\rightarrow$ `DAT_CON` máxima):** **645 resolvidos (100,00%)**, 0 ambíguos, 0 perdidos.
- **R4 (`CAR_INST` máxima):** 9 resolvidos, 636 ambíguos, 0 perdidos.

#### B. Em `UCBT_tab` (Amostra estratificada de 10.000 `COD_ID` divergentes):
- **R1 (`SIT_ATIV == 'AT'`):** 5.235 resolvidos, 4.685 ambíguos, 80 perdidos.
- **R2 (`DAT_CON` máxima):** 4.751 resolvidos, 5.249 ambíguos, 0 perdidos.
- **R3 Cascata A (`DAT_CON` máxima $\rightarrow$ `SIT_ATIV == 'AT'`):** 9.896 resolvidos, 25 ambíguos, 79 perdidos.
- **R3 Cascata B (`SIT_ATIV == 'AT'` $\rightarrow$ `DAT_CON` máxima):** 9.895 resolvidos, 25 ambíguos, 80 perdidos.
- **R3 Cascata sem perda (Prioriza AT; fallback para todas; desempata por `DAT_CON` máxima):**  
  **9.898 resolvidos (98,98%)**, **102 ambíguos (1,02%)**, **0 perdidos (0,00%)**.
- **R4 (`CAR_INST` máxima):** 1.453 resolvidos, 8.547 ambíguos, 0 perdidos.

---

### 3.2 Diagnóstico dos 102 Grupos Ambíguos (205 Linhas Remanescentes)

Medição exata nos 102 grupos de BT que empataram na cascata R3 (artefatos [`complementaridade_resumo_20261018_112614.csv`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/complementaridade_resumo_20261018_112614.csv) e [`topologia_divergente_20261018_112614.csv`](file:///C:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/topologia_divergente_20261018_112614.csv)):

1. **Uniformidade Temporal e de Vigência:**  
   Em **102 de 102 grupos (100%)**, `SIT_ATIV` e `DAT_CON` são estritamente iguais entre as linhas remanescentes do grupo (25 grupos com `AT` e mesma data; 77 grupos com `DS` e mesma data).
2. **Divergência Cadastral:**  
   - `CLAS_SUB` diverge em 102/102 grupos (100%), alternando sobretudo entre `RE1` (residencial pleno) e `RE2` (baixa renda).
   - `GRU_TAR` diverge em 93/102 grupos (91,18%), alternando entre `B1` e `B1BR`.
3. **Estrutura dos 24 Meses de Consumo (`ENE_01..12` e `DEM_01..12`):**
   - As colunas de demanda (`DEM_01` a `DEM_12`) são 100% nulas em `UCBT_tab` (tratadas como zero).
   - As colunas de energia (`ENE_01` a `ENE_12`) foram 100% convertidas para float sem perda ou erro.
   - **`complementar` (H1): 41 grupos (40,20%)**. Ambas as linhas têm consumo faturado positivo, mas em **meses rigorosamente disjuntos** (0 meses de sobreposição simultânea).
   - **`sobreposto_diferente` (H2): 11 grupos (10,78%)**. Ambas as linhas têm consumo positivo nos mesmos meses, com valores numéricos divergentes (**média de 11,82 meses sobrepostos**, máximo 12).
   - **Consumo zerado/nulo (H3): 50 grupos (49,02%)**. Sendo 27 grupos com todos os 24 meses zerados em ambas as linhas (`identico_consumo` nulo) e 23 grupos com uma linha ativa e uma linha cadastral sem medição (todos os 24 meses zerados).
4. **Divergência Topológica e Correlação Crítica (H4):**
   - **Exatamente 11 grupos (10,78%)** apresentam divergência física simultânea em `PAC`, `RAMAL`, `PN_CON` e `UNI_TR_MT`.
   - **Correlação Perfeita de 100%:** Os 11 grupos que divergem em topologia física de rede são **exatamente os mesmos 11 grupos com consumo sobreposto diferente**. Nenhum grupo complementar ou zerado diverge em topologia física.
   - **Divergência de CEP:** 1 grupo (0,98%) diverge em `CEP` mantendo o mesmo `PAC`.

---

### 3.3 Quadro Atualizado de Hipóteses

| Hipótese | Conceito Físico/Comercial | Resultado Medido nos 102 Ambíguos | Evidência nos Dados |
| :--- | :--- | :--- | :--- |
| **H1: Parcelas temporais de consumo (partição)** | A mesma UC teve mudança contratual/cadastral ao longo do ano sem sobreposição de faturamento. | **41 grupos (40,20%)** | 0 meses sobrepostos; consumo positivo em meses complementares; topologia de rede 100% idêntica. |
| **H2: Versões concorrentes / Duplicidade com conflito** | Registros concorrentes ativos com valores faturados distintos no mesmo mês. | **11 grupos (10,78%)** | Média de 11,82 meses sobrepostos simultaneamente. Coincidência total com múltiplos pontos de rede. |
| **H3: Linhas vazias / dormentes** | Registro cadastral sem consumo real associado no período (duplicata técnica dormente). | **50 grupos (49,02%)** | 27 grupos com 24 meses zerados em ambas as linhas; 23 grupos com uma linha ativa e outra zerada. |
| **H4: Múltiplos pontos físicos de rede** | O mesmo código cadastral foi associado a diferentes pontos físicos de conexão na rede de distribuição. | **11 grupos (10,78%)** | Divergem simultaneamente em `PAC`, `RAMAL`, `PN_CON`, `UNI_TR_MT` e `DESCR`. 100% correlacionados com H2. |

---

## 4. PRINCÍPIOS DE TRABALHO INEGOCIÁVEIS

1. **Separação Estrita entre Medido e Inferido:** Todo número citado deve ser classificado como *medido* (saída do terminal ou registro em arquivo gerado) ou *inferido* (dedução técnica formulada sobre os fatos medidos).
2. **Nada sem Saída Real:** Não se declara sucesso sem:
   - Saída completa do terminal;
   - Código de retorno do processo (`; "exit=$LASTEXITCODE"`);
   - Verificação com `Get-ChildItem` dos arquivos gerados.
3. **Não Reabrir o que está Verificado:** Os números da Seção 2.1 e 3.1 são a base consolidada do projeto.
4. **Não Escolher Regra Antes do Teste:** A regra de deduplicação definitiva só poderá ser selecionada após medição sobre a **população total** (124.224 IDs de BT e 645 de MT).
5. **Preservação de Scripts e Base:**
   - Não editar scripts `02` a `03h` nem scripts de análise já consolidados;
   - Não ler nem escrever no `.gdb` sem orientação explícita;
   - Não usar `pyarrow`; não instalar pacotes no ambiente virtual;
   - Não apagar, mover nem sobrescrever arquivos em `data/raw`, `data/processed` ou `logs`.
6. **Controle de Memória por Balde:** Nunca carregar a tabela inteira de `UCBT_tab` na memória RAM. Todas as operações sobre a população total devem processar em lotes de até 100.000 linhas por balde (20 partições via CRC32).
7. **Arquivos com `RUN_TAG` Único:** Todo script deve gerar arquivos com carimbo de data/hora (`%Y%m%d_%H%M%S`). Se o arquivo já existir, o script deve abortar imediatamente.
8. **Classificação Neutra de Colunas:** Colunas de cadastro versus consumo são classificadas estritamente pelo nome, sem pré-julgamento de seu significado.

---

## 5. ROTEIRO DAS ETAPAS DO PROJETO

$$\mathbf{E0} \longrightarrow \mathbf{E1} \longrightarrow \mathbf{E2} \longrightarrow \mathbf{E3} \longrightarrow \mathbf{E4} \longrightarrow \mathbf{E5}$$

| Etapa | Objetivo | Status | Dependência | Saída Esperada |
| :--- | :--- | :--- | :--- | :--- |
| **E0. Inventário da BDGD** | Mapear camadas, colunas, tipos de dados e chaves de relacionamento do GDB. | **Concluída** | Nenhuma | Dicionário de dados das tabelas de MT e BT. |
| **E1. Diagnóstico das Duplicatas** | Medir complementaridade de consumo e consistência topológica nos `COD_ID` duplicados. | **Concluída** (`03i`, `20261018_124845`) | E0 | Quantificação de H1, H2, H3 e H4 na população completa (124.224 BT e 645 MT). |
| **E2. Formulação da Regra de Deduplicação** | Definir regras formais de seleção, soma ou separação de registros com base nos dados medidos. | **Concluída** (Regra E2 validada) | E1 | Regra documentada: Cascata R3 + Partição H1/H3 por agregação e H4 por pontos físicos. |
| **E3. Base de UC Consolidada** | Gerar a tabela analítica final com 1 registro por UC física, reprodutível e livre de ambiguidades. | **Concluída** (`04`, `20261018_131447`) | E2 | Bases consolidadas: `UCMT_consolidada` (5.609 UCs) e `UCBT_consolidada` (1.183.916 UCs). |
| **E4. Rastreamento Topológico do HRC** | Subir a cadeia de conectividade elétrica a partir da UC do Hospital Regional de Ceilândia. | **Concluída** (`05`, `20261018_133430`) | E3 | UC primária identificada em MT (`01d6dfec...`), circuito **`TN08`**, subestação **`STN`**, poste `9026_CEI003`. |
| **E5. Expansão e Simulação Elétrica** | Modelar fluxo de potência, carregamento e contingências ($N-1$) no circuito do HRC e outros hospitais. | **EM ANDAMENTO** (Chaves UNSEMT acopladas via `08`, HRC 100% energizado) | E4 | Modelo OpenDSS nativo completo com 99 chaves (92 fechadas, 7 abertas), HRC energizado a 13,8 kV (`[0.87, 0.99, 0.94] pu`). |

---

## 6. PRÓXIMA AÇÃO IMEDIATA (PONTO EXATO DE CONTINUIDADE)

Com o alimentador **`TN08`** completamente conectado e o barramento do HRC energizado e validado (`08_acoplamento_chaves_unsemt.py`), as próximas ações técnicas são:

1. **Estudo de Contingência ($N-1$) no HRC:**
   - Simular o desligamento do alimentador primário `TN08` (abertura do disjuntor de saída da SE STN ou chave `FW9093`) e testar a transferência de carga para alimentadores adjacentes via as 7 chaves normalmente abertas (`P_N_OPE == 'A'`).
2. **Avaliação da Capacidade de Reserva e Margem de Carga:**
   - Quantificar os limites térmicos e de tensão ao absorver a carga hospitalar em regime de contingência de emergência.
3. **Injeção de Anomalias Cibernéticas e Detecção via Redes Neurais Gráficas (GNN):**
   - Injetar desvios estocásticos e avaliar a propagação de gradientes de tensão para treinamento e validação do modelo preditivo de QA.

---

## 7. DIRETRIZES DE RESPOSTA DO MODELO RECEPTOR

Qualquer agente ou modelo de linguagem que receber este documento deve seguir as seguintes diretrizes:

1. **Partida obrigatória pela Seção 2:** Confirmar explicitamente que compreendeu que o projeto está na **Etapa E1** antes de sugerir comandos ou códigos.
2. **Não violar as regras de bloqueio:** Não sugerir regra de deduplicação antes da medição populacional (E1) e não tentar identificar a UC do HRC antes da consolidação de E3.
3. **Rigor de evidência:** Separar estritamente o que foi medido do que foi inferido. Todo número deve ter seu script, `RUN_TAG` e arquivo de saída explicitados.
4. **Confirmação de ambiente:** Confirmar `Get-Location` na raiz antes de propor execuções; invocar Python exclusivamente com `& ".\venv\Scripts\python.exe"`.
5. **Estilo de comunicação:** Respostas técnicas, diretas, precisas e utilizando a terminologia oficial da BDGD/ANEEL e de engenharia de sistemas de distribuição.
