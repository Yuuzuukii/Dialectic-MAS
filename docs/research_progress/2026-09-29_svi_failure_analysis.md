# SVI結果の原因分析と次の研究PDCA（2026-09-29）

## 1. 現時点の結論

今回の結果は、単純に「Schemaが失敗した」と読むより、次の二段階で整理するのが妥当である。

1. **論点保持（Coverage）は改善している。**
   - Atomic Coverage: Schema 0.8221 / No Schema 0.7806 / Free Debate 0.7642 / MAD 0.5061（各 n=30）。
   - したがって、Schemaを含むDialectic系プロトコルは、最終回答に双方の論点を残す点では機能している。
2. **しかし、双方がその結論を受容すること（bilateral acceptability）は保証できていない。**
   - 補正後SVI InstrumentalをAG1/AG2別に見ると、Schemaはトピックによって大きな非対称が生じる。
   - 特に election_day, animal_dissection, artificial_intelligence で片側のInstrumentalが低い。

この結果から、現在の研究課題は「論点を統合できるか」から一段進み、**論点を保持した統合結果を、双方が受容可能な結論に変換できるか**に移っている。

---

## 2. 定量結果の読み方

6トピック×5試行の補正後Instrumentalについて、各トピック内で5試行を平均し、AG1/AG2を別々に確認した。

Schemaの例:

- abortion: AG1 4.25 / AG2 3.45
- alternative_energy: AG1 3.20 / AG2 4.35
- american_socialism: AG1 4.90 / AG2 3.60
- animal_dissection: AG1 2.95 / AG2 4.90
- artificial_intelligence: AG1 3.15 / AG2 4.65
- election_day: AG1 2.75 / AG2 5.30

重要なのは、Schemaが常に両者とも低いわけではなく、**片側は高いがもう片側が低いケースが多い**ことである。したがって、全エージェントを単純平均したSVIだけでは問題の性質を捉えにくい。

今後の主要集計値として以下を併記する。

- bilateral mean: (AG1 + AG2) / 2
- bilateral min: min(AG1, AG2) — 最も不満な当事者の受容度
- bilateral gap: |AG1 - AG2| — 当事者間の非対称性

---

## 3. 代表ログ分析

### 3.1 election_day / Schema / trial 1

形式状態:

- AG1 main: defensible, closed_by_budget
- AG2 main: defensible, closed_by_budget
- consensus_reached = false
- justification_status = fallback_no_consensus

両側の主張が残ったままformal consensusには至っていない。それにもかかわらず、final_answerは明確に **"Election Day should not be a national holiday"** とAG2側を採用している。

final answer自体はAG1側の利点（schedule conflict、civic framing、cross-party support、international precedent）も記述しておりCoverageは高い。しかし最終的な政策判断はAG2側に決めているため、AG1にとってInstrumental satisfactionが低くなる構造である。

**示唆:** CoverageとAgreementは独立した性質である。論点を含めただけでは、双方が結論を受け入れるとは限らない。

### 3.2 animal_dissection / Schema / trial 1

形式状態:

- total_dialogue_turns = 5
- main_argument_count = 1
- AG1 main: defensible, closed_by_budget
- consensus_reached = false
- justification_status = fallback_no_consensus
- integrated_rules = []

final_answerは **students should generally not dissect animals** とAG2側の結論を採用した。

ここでは特に、AG2独自のmain argumentが形式的に完成する前にbudgetで終了しているにもかかわらず、fallback finalizationがAG2側の結論を選択している。このケースは、現在の終了条件とfallback処理が「弁証法的な合意形成」より「最終ジャッジ」に近い挙動を生んでいる可能性を示す。

**示唆:** 対話budgetは単なる計算量制約ではなく、各側の議論機会の対称性に影響している可能性がある。

### 3.3 abortion / Schema / trial 4（比較的受容度が高いケース）

この試行も consensus_reached = false / fallback_no_consensus であるが、SVI Instrumentalは AG1 5.25 / AG2 4.25 と比較的高い。

final answerはlegalizationを選ぶ一方で、anti-legalization側の道徳的前提を明示し、「prohibition側の条件が満たされる場合」のdecision ruleをintegrated_rulesとして保持している。

**示唆:** formal consensusが成立していなくても、最終回答が相手側の価値を単なる反論対象ではなく「条件付きで有効な判断基準」として保持できると、主観的受容度が上がる可能性がある。

---

## 4. 原因仮説

### H1. Fallback finalizationが「統合」ではなく「勝敗判定」になっている

formal consensusに到達しなかった場合でも、最終生成器がbest-supported conclusionを1つ選ぶ。そのため、Coverageは高くても片側のInstrumental valueが下がる。

### H2. 合意案に対する当事者のRatificationが存在しない

現在はfinal answer生成後にAG1/AG2へ「この結論を受け入れられるか」を確認しない。したがって、生成器が統合したつもりでも当事者の一方が拒否する結論をそのまま終了状態にできる。

### H3. Dialogue budgetによって議論機会が非対称になる

animal_dissection trial 1では5ターンでmain_argument_count=1のまま終了している。各側が同程度にmain/attack/counterを展開できたかを保証してからfinalizationする必要がある。

### H4. Binary QA形式そのものがAgreementと衝突している

質問が "Should X?" のYes/No形式であり、final answerも最終的にYes/Noを要求される場合、価値対立トピックでは一方のInstrumental outcomeが下がりやすい。弁証法的統合を評価するなら、単一勝者の選択ではなく、条件付き結論・policy bundle・合意可能範囲を最終成果物として明示する設計も検討する必要がある。

---

## 5. 次のPDCA

### Plan

Research Questionを次のように精緻化する。

> LLM Multi-Agent Debateにおいて、対立する論点を保持するだけでなく、双方が受容可能な統合案を形成できるか。

評価を三段階に分ける。

1. **Issue Preservation:** Atomic Coverage
2. **Bilateral Acceptability:** corrected SVI Instrumental（AG別、bilateral mean/min/gap）
3. **Formal Resolution:** consensus_reached / justification_status

### Do 1: 追加診断

`plot_svi_bilateral_diagnostics.py` を実行し、全120ログについて以下を集計する。

- formal consensus rate
- fallback rate
- bilateral mean Instrumental
- bilateral min Instrumental
- AG gap
- formal consensus vs fallbackでのSVI差

### Check 1

次の仮説を検証する。

- fallback_no_consensusのログほど bilateral min が低いか
- consensus_reached=TrueならAG gapが小さいか
- Coverageが高くてもbilateral minが低いケースが存在するか

これにより「CoverageだけではAgreementを説明できない」を実証的に示せる。

### Act 1: Protocol改善案

最有力案は **Ratification Loop** の追加。

1. Dialectical dialogue
2. Candidate synthesis生成
3. AG1 / AG2がcandidateを独立評価（accept / reject + unresolved reason）
4. 一方でもrejectなら、そのreasonを新たな論点として再統合
5. 両者accept、または上限到達で終了

この変更では、finalizerが一方的に「best side」を選ぶのではなく、**双方の受諾をprotocolの停止条件そのものにする**。

### Do 2: Ablation

比較候補:

- Current Schema
- Schema + Ratification
- No Schema + Ratification（必要なら）

主評価:

- Atomic Coverage
- bilateral min Instrumental
- bilateral gap
- consensus rate
- token/cost

---

## 6. 発表用の研究ストーリー

### Slide 1: 目的

既存MADは対立意見を戦わせることはできるが、双方の論点を保ちながら受容可能な結論を作ることは明示的に扱わない。

### Slide 2: 提案

Dialectical protocolにより、attack/counterを構造化し、最終的に両側の論点を統合した回答を生成する。

### Slide 3: まず「論点を保持できるか」を評価

Atomic Coverage:

- Schema 0.822
- No Schema 0.781
- Free Debate 0.764
- MAD 0.506

→ Schemaは論点保持では最も高い。

### Slide 4: しかしCoverage = Agreementではない

新たにSVIを用い、AG1/AG2それぞれの主観的な結果受容度を評価。

### Slide 5: SVI結果

トピック別AG1/AG2棒グラフを提示。

→ Schemaでは一部トピックで片側だけ低くなる非対称性が確認された。

### Slide 6: ログ分析

`election_day` を代表例とする。

- 両mainはdefensible
- formal consensus = false
- fallbackでAG2側のNoを採用
- AG1側の論点は回答内に残る

→ **論点保持には成功したが、合意形成には失敗した例**。

### Slide 7: 研究上の発見

> Dialectical structure improves issue preservation, but preserving both sides' arguments is not sufficient for bilateral agreement.

このnegative resultを失敗として隠すのではなく、CoverageとAgreementを分離する必要性を示す知見として位置づける。

### Slide 8: 次の改善

Candidate Synthesis → 双方Ratification → Reject理由を再議論するループを導入する。

目標は「LLMが良いと思う統合」から「両当事者が受け入れる統合」への変更。

---

## 7. 学会向けに現時点で安全に主張できる範囲

現段階で主張しやすい:

- SchemaはAtomic Coverageで比較手法より高い。
- Coverageとsubjective acceptabilityは一致しない。
- SVIのAG別分析により、片側への非対称な満足度が観察される。
- 代表ログではformal consensus未成立時のfallback finalizationが一方の結論を選ぶケースが確認できる。
- よって、合意形成システムには論点統合だけでなく当事者による受諾確認が必要という設計仮説が得られた。

まだ主張しない:

- Schemaが統計的に他手法よりAgreementを改善する。
- Ratificationを入れれば必ずAgreementが改善する。
- SVI単独で「合意成立」を直接測定できる。

これらは次の実験で検証する。
