# Prakken & Sartor (1997) 定義集 和訳

出典: Henry Prakken & Giovanni Sartor, "Argument-based extended logic programming with defeasible priorities", Journal of Applied Non-Classical Logics 7(1-2), 25-75.

## この文書の範囲

- 本文中の番号付き **Definition 30個すべて**を、全文和訳した。各定義には英語原文を併記した。
- 各定義の直前・直後にある地の文のうち、その定義の理解に必要なものも、要約せず全文和訳して付けた。
- **含めていないもの**: 例(Example)、命題(Proposition)、系(Corollary)、補題(Lemma)、証明。ただし、定義の説明がそれらに依存している箇所は、該当箇所に省略した旨を書いた。
- 「【訳注】」は和訳者(Claude)による注で、原文にはない。
- PDF のテキスト抽出で上線(補完リテラル L̄)が欠落している箇所は、定義2.8などの文脈から補い、その旨を訳注に書いた。

## 用語

| 英語 | 訳語 |
|---|---|
| argument | argument(訳さない) |
| rule / antecedent / consequent | rule / 前件 / 後件 |
| strong literal / weak literal | strong literal / weak literal |
| strict rule / defeasible rule | strict rule / defeasible rule |
| conclusion / assumption | 結論 / assumption |
| attack / rebut / undercut | attack / rebut / undercut |
| defeat / strictly defeat | defeat / strictly defeat |
| justified / overruled / defensible | justified / overruled / defensible |
| proponent (P) / opponent (O) | proponent(P) / opponent(O) |

## 目次(全30個)

| 節 | 定義 | 内容 | 原論文のページ |
|---|---|---|---|
| 2 | 2.1 | rule | 29 |
| | 2.2 | argument | 30-31 |
| | 2.3 | strict / defeasible、subargument、結論、assumption | 31 |
| | 2.7 | A + T | 33 |
| | 2.8 | attack | 33-34 |
| | 2.11 | coherent | 34 |
| | 2.12 | conflict-free | 34 |
| | 2.13 | R_L(結論 L に関係する defeasible rule の集合) | 35-36 |
| | 2.14 | rule 集合の順序 | 36 |
| | 2.15 | rebut / undercut | 36 |
| | 2.16 | defeat / strictly defeat | 37 |
| 3 | 3.1 | acceptable | 39 |
| | 3.2 | 特性関数 F_Γ | 39 |
| | 3.4 | justified / overruled / defensible | 40 |
| | 3.5 | finitary | 40 |
| 4 | 4.5 | dialogue | 48 |
| | 4.6 | dialogue tree | 48 |
| | 4.7 | 勝敗 | 48 |
| | 4.8 | provably justified | 48 |
| 5 | 5.1 | <_Args、Args-defeat | 50 |
| | 5.3 | acceptable(再定義) | 51 |
| | 5.4 | 特性関数 G_Γ | 51 |
| | 5.6 | justified(再定義) | 51 |
| | 5.10 | complete extension | 52 |
| 6 | 6.1 | priority dialogue | 54-55 |
| | 6.2 | priority dialogue tree | 55 |
| 7 | 7.1 | stable extension | 58 |
| | 7.5 | defensible extension | 59 |
| 9 | 9.2 | d-acceptable | 61 |
| | 9.4 | d-well-founded conclusions | 62 |

---

# 第2節 形式システム I:固定された優先順位

## 2.1 言語(定義2.1の前提)

> システムのオブジェクト言語は、おなじみの論理プログラミング風のものである。リテラルから rule を作る、2項・一方向の結合子をもち、リテラルは2種類の否定、すなわち weak negation と strong negation を含みうる(weak negation はしばしば「失敗による否定(negation as failure)」とも呼ばれ、strong negation は「古典的」または「明示的」否定とも呼ばれる)。**strong literal** とは、原子一階論理式、またはそのような式の前に strong negation ¬ を付けたものである。任意の原子 A について、A と ¬A は互いの補完(complement)であるという。メタ言語では、リテラル L の補完を L̄ と書く。**weak literal** とは、∼L の形のリテラルである。ただし L は strong literal である。非形式的には、∼L は「L であるという証拠がない」と読み、¬L は「L は決して成り立たない」と言う。

### 定義2.1

**原文:** A rule is an expression of the form r : L0 ∧ … ∧ Lj ∧ ∼Lk ∧ … ∧ ∼Lm ⇒ Ln, where r, a first-order term, is the name of the rule and each Li (0 ≤ i ≤ n) is a strong literal. The conjunction at the left of the arrow is the antecedent and the literal at the right of the arrow is the consequent of the rule. As usual, a rule with variables is a scheme standing for all its ground instances.

**和訳:** **rule** とは、次の形の式である。

　r : L0 ∧ … ∧ Lj ∧ ∼Lk ∧ … ∧ ∼Lm ⇒ Ln

ここで r は一階の項で、その rule の名前であり、各 Li(0 ≤ i ≤ n)は strong literal である。矢印の左側の連言を**前件(antecedent)**、矢印の右側のリテラルをその rule の**後件(consequent)**という。通常どおり、変数を含む rule は、そのすべての基底例(ground instance)を表すスキームである。

### 直後の説明

> rule は、前件にリテラルを1つも含まなくてもよいことに注意されたい。そのような rule は、無条件の言明を表すのに使える。
>
> 変数は本論文では x, y, z の文字で表し、定数はそれ以外の文字または単語で表す。例の読みやすさのため、リテラルをくだけた書き方で書くことが多い。例えば「x は y より前である」は、より標準的な論理記法 Earlier(x, y) の、我々なりの書き方である。

## 順序理論(定義2.2の前提)

> 次に、システムの入力情報を定義する。これを**順序理論(ordered theory)**と呼ぶ。入力が rule を含むのは明らかである。ただし、入力の rule は2つのカテゴリに分かれると仮定する。すなわち、**defeasible rule** の集合 D と **strict rule** の集合 S である。S のどの要素も weak literal を含まないと仮定する。非形式的には、defeasible rule は、システムの利用者が議論の対象となりうると意図する情報を表し、strict rule は、議論の余地がないと意図する情報を表す。defeasible rule は2通りの意味で defeasible でありうることに注意されたい。すなわち、矛盾する後件をもつより強い rule によって覆されうること、そして、保証されていない assumption を含みうることである。strict rule は、「独身者は結婚していない」のような意味公準や、「より年上である」の推移性、「父である」の非対称性のような関係の性質を表すのに使える。技術的には、strict rule の役割は、例えば default logic の default 理論の一階部分とほぼ同じである。
>
> 構文的には、strict rule と defeasible rule は、ただ1点でのみ異なる。assumption を含みうるのは defeasible rule だけである。それ以外については、strict rule と defeasible rule の区別を、構文のレベルではなく語用論のレベルで行うことにした。すなわち、条件演算子を支配する論理は、どちらの種類の rule でも同じであり、両者は認識論的な身分だけが異なる。それでも、表記の便宜上、rule を書き下すときは、strict rule には → を、defeasible rule には ⇒ を使う。ただし形式的には、記号 → はオブジェクト言語の一部ではなく、その rule が strict rule の集合に属することを示す略記にすぎない。
>
> 序論で論じたように、法的推論では、defeasible rule 間の衝突は、どの rule が優先するかについての言明の助けを借りて解決されることが多い。したがって、入力情報には、D 上の順序 < も含まれるものとし、これを strict partial order、すなわち推移的(x < y かつ y < z ならば x < z)かつ非対称(x < y ならば y ≮ x)であるとする。「x < y」は、y が x より優先されることを意味する。strict rule は議論の余地がないということを捉えるため、S 上には順序を定義する必要はない。
>
> 要するに、我々のシステムは、順序理論 (S, D, <) の形の入力情報を仮定する。ここで S と D はそれぞれ strict rule と defeasible rule の集合で、< は D 上の strict partial order である。

## 2.2 argument

> システムの基本概念は argument である。一般に、ある命題の argument とは、基礎となる言語の論理におけるその命題の証明である。我々のシステムでは、単純な言語から単純な argument の概念が得られる。すなわち、連鎖させることができ、かつ事実に「根拠づけられた」rule の列である。これは [Dung 93b] の「defeasible proof」の概念の、わずかな変種で捉えられる。

### 定義2.2

**原文:** An argument is a finite sequence A = [r0, …, rn] of ground instances of rules such that
1. for every i (0 ≤ i ≤ n), for every strong literal Lj in the antecedent of ri there is a k < i such that Lj is the consequent of rk;
2. No two distinct rules in the sequence have the same consequent.
An argument A is based on the ordered theory (S, D, <) iff all rules of A are in S ∪ D.

**和訳:** **argument** とは、rule の基底例の有限列 A = [r0, …, rn] であって、次を満たすものである。

1. すべての i(0 ≤ i ≤ n)について、ri の前件に含まれるすべての strong literal Lj に対し、k < i であって、Lj が rk の後件であるような k が存在する。
2. 列の中の異なる2つの rule が、同じ後件をもつことはない。

argument A が順序理論 (S, D, <) に**基づく(based on)**とは、A のすべての rule が S ∪ D に属するときかつそのときに限る。(脚注2: 混乱のおそれがない場合、「(S, D, <) に基づく」という句は省略する。)

### 直後の説明

> 条件(1)は、argument が rule を連鎖させて作られることを述べている。細かい点として、その際、weak literal は無視されうる。実際、この条件は、2つの暗黙の推論規則を仮定している。strong literal を連言にする規則と、次の形の「defeasible modus ponens」の規則である。
>
> 　r : L0 ∧ … ∧ Lj ∧ ∼Lk ∧ … ∧ ∼Lm ⇒ Ln、　L0 ∧ … ∧ Lj
> 　―――――――――――――――――――――――――――――
> 　　　　　　　　　　　　Ln
>
> 条件(2)が、argument が rule の循環した連鎖を含むことを防いでいることに注意されたい。
>
> 任意の順序理論 Γ について、Γ に基づくすべての argument の集合を Args_Γ と書く。同様に、任意の rule の集合 R について、Args_R は、R の rule だけからなるすべての argument の集合を表す。

## 定義2.3(前置き)

> 次の概念も使う。

### 定義2.3

**原文:** For any argument A:
1. A is strict iff it does not contain any defeasible rule; it is defeasible otherwise.
2. An argument A′ is a (proper) subargument of A iff A′ is a (proper) subsequence of A.
3. A literal L is a conclusion of A iff L is the consequent of some rule in A.
4. A literal L is an assumption of A iff ∼L̄ occurs in some rule in A.

**和訳:** 任意の argument A について:

1. A が **strict** であるとは、defeasible rule を1つも含まないときかつそのときに限る。そうでなければ **defeasible** である。
2. argument A′ が A の(真の)**subargument** であるとは、A′ が A の(真の)部分列であるときかつそのときに限る。
3. リテラル L が A の**結論(conclusion)**であるとは、L が A のある rule の後件であるときかつそのときに限る。
4. リテラル L が A の **assumption** であるとは、∼L̄ が A のある rule に現れるときかつそのときに限る。

【訳注】4の上線(L̄)は PDF のテキスト抽出で欠落していた。直後の例(assumption が {b, ¬d})と整合するよう補った。

### 直後の説明

> 条件(3)は、連鎖の中のどの rule の後件も、その argument の結論になることを述べている。最後の rule の後件だけを結論と見なす、という代替案のほうが、哲学的にはおそらく通常だが、我々の選択のほうが、他のいくつかの定義を簡単にする。
>
> これらの概念を説明するため、(defeasible な)argument
>
> 　A = [r1: → a、 r2: a ∧ ∼¬b ⇒ c、 r3: c ∧ ∼d ⇒ e]
>
> について、A の結論は {a, c, e} であり、その subargument は {[ ], [r1], [r1, r2], [r1, r2, r3]} で、このうち strict なのは [ ] と [r1] だけであり、A の assumption は {b, ¬d} である。

(例2.4〜2.6は省略)

## 2.3 argument 間の衝突

> ここまでの概念は、かなり標準的なものだった。ここからは、システムの敵対的な側面を示す。まず、argument が他の argument をどのように attack できるか、すなわち反論(counterargument)になれるかを定義する。この定義にはまだ、どちらの argument がより良いかを確かめる方法は含まれない。どの argument が衝突しているかを教えるだけである。2種類の否定が、argument を attack する2通りの方法を生む。まず非形式的に説明しよう。argument A が結論 L をもつとする。すると第1の attack の方法は、結論を否定することである。すなわち A は、結論 L̄ をもつ任意の argument B を attack する。明らかに、そのような head-to-head の衝突は対称である。A が B を head-to-head で attack するなら、B も A を head-to-head で attack する。第2の attack の方法は、weak negation を使い、assumption を否定することである。すなわち A は、assumption L̄ をもつ任意の argument B を attack する。明らかに、この attack の方法は対称ではない。これは [POL 87] の「undercutting defeater」の特別な場合と見なせる。第9節を参照。
>
> ただし、strict rule があると事情が複雑になる。それを見るため、次の例を考える。(例2.5と2.6は省略。strict rule による含意関係のため、結論が互いに補完的な rule どうしが、実際の衝突の当事者ではない場合がある、という例。)
>
> これらの例が、[Nute 88, Nute 94] から離れる理由である。彼の体系は、我々のものと同様に2種類の一方向の rule をもつが、weak negation はない。Nute は、結論が補完的な rule だけを衝突していると見なすので、例2.5と2.6では、2つの argument [s1, r1] と [s2, r2] が衝突していないと見なす。このため、ある人が独身である(または結婚している)ことと、そうでないことを主張する2つの argument の衝突を決めるときに、r1 と r2 の間の優先順位関係が考慮されない。
>
> argument 間の衝突を、次のように定義することを提案する。argument A が結論または assumption L をもつなら、A は、**strict rule だけを使って**、結論 L̄ をもつ argument に拡張できるすべての argument によって attack されていると見なすべきである。(以降の説明は例2.5に依存するため省略。)
>
> より一般には、第1の attack の方法では、両方の argument を strict rule だけで拡張し、最終的に補完的な結論をもつかどうかを見る必要がある。これは次の定義で捉えられる。すべての定義と同様に、これらも暗黙に順序理論 (S, D, <) に相対的であると仮定する。まず、argument の拡張の概念を定義する必要がある。

【訳注】結論 L̄ と assumption L̄ の上線は、PDF のテキスト抽出で欠落していたため、補った。(初版では assumption 側の上線を誤って落としていたので修正した。)

### 定義2.7

**原文:** Let A be an argument and T a sequence of rules. Then A + T is the concatenation of A and T.

**和訳:** A を argument、T を rule の列とする。このとき A + T は、A と T の連接(concatenation)である。

(脚注4: rule の順序は、rule の前件が前の rule から来なければならないという点を除いて重要ではないので、A + T が一意に定まらないことは無視する。)

> これで、attack / 衝突 / 反論の概念を次のように定義できる。(脚注5: 用語の混乱を避けるため、[Dung 93b] と [BTK 93] は「attack」という語を異なる意味で使っており、後で定義する我々の「defeat」の概念に近いことに注意されたい。彼らには、我々が「attack」と呼ぶものの明示的な概念はない。)

### 定義2.8

**原文:** Let A1 and A2 be two arguments. Then A1 attacks A2 iff there are sequences S1, S2 of strict rules such that A1 + S1 is an argument with conclusion L and
1. A2 + S2 is an argument with a conclusion L̄; or
2. A2 is an argument with an assumption L̄.

**和訳:** A1 と A2 を2つの argument とする。A1 が A2 を **attack** するとは、strict rule の列 S1, S2 が存在して、A1 + S1 が結論 L をもつ argument であり、かつ次のいずれかが成り立つときかつそのときに限る。

1. A2 + S2 が、結論 L̄ をもつ argument である。または
2. A2 が、assumption L̄ をもつ argument である。

【訳注】条件(2)の上線(L̄)は PDF のテキスト抽出で欠落していた。A1 が結論 L をもち、A2 が weak literal ∼L を含む(定義2.3(4)により、A2 の assumption は L̄ になる)ときに undercut が成り立つ、という意味で補った。Kido & Kurihara の定義3(L ∈ Conc(A1) かつ ¬L ∈ Ass(A2))とも一致する。

### 直後の説明

> この定義の特異な点のいくつかは、すでに論じた(strict rule が関わる場合)。付け加えると、2つの argument が、結論が衝突する defeasible rule を含んでいるなら、S1 と S2 が空であれば定義は満たされる。続いて、定義2.8のさらにいくつかの特徴を示す、この種の例をいくつか挙げる。

(例2.9と2.10は省略。attack が argument 自身だけでなく、その subargument に向けられて、間接的に argument 全体を attack しうること、を示す例。)

## 2.3 の続き(定義2.11・2.12の前置き)

> 「attack / 反論」の概念は、非常に重要である。なぜなら、防御可能な推論のどんな体系でも、最低限の要件は、互いに衝突する2つの argument を、両方とも justified として受け入れることができない、ということだからである。せいぜい、どちらか一方を選択的に受け入れることができるだけである。我々のシステムがこれに一致することを望む。すなわち、後で定義する「justified な argument」の集合が、一意で、conflict-free であることを望む。そのため、次の概念を定義する。

### 定義2.11

**原文:** An argument is coherent iff it does not attack itself.

**和訳:** argument が **coherent** であるとは、それ自身を attack しないときかつそのときに限る。

### 直後の説明

> incoherent な argument の2つの例は、[r1: ⇒ a, r2: a ⇒ ¬a] と [r1: ∼a ⇒ b, r2: b ⇒ a] である。

### 定義2.12

**原文:** A set Args of arguments is conflict-free iff no argument in Args attacks an argument in Args.

**和訳:** argument の集合 Args が **conflict-free** であるとは、Args のどの argument も、Args のどの argument も attack しないときかつそのときに限る。

## 2.4 argument 間の defeat

> どの argument どうしが衝突しているかが分かったので、次の段階は、衝突する argument を比較することである。そのため、2段階で、argument 間の2項関係 defeat を定義する。(脚注6: 以下で定義する argument の関係と性質は、暗黙に仮定された順序理論に相対的であることに注意されたい。)この比較は、どの argument で論争に勝てるかをまだ決めるものではない、と認識することが重要である。それは、2つの個別の argument(とその subargument)の間の関係について、何かを述べるだけである。
>
> 2種類の attack の異なる「力」を捉えるため、「defeat」を、argument を rebut する、undercut するという、2つの別の評価概念によって定義する。両者の違いは、attack する argument が、別の argument の結論を否定するのか、assumption を否定するのかに依存する。最初の場合にだけ、優先順位が使われる。この選択の擁護は、defeat の定義、すなわち rebut と undercut の概念を組み合わせて使う方法を述べる定義を示したあとに行う。
>
> まず、head-to-head の衝突に注目し、衝突する argument を比較するために優先順位がどう使えるかを見よう。最も単純な形、つまり2つの defeasible rule の間の head-to-head の衝突では、argument どうしを、これら2つの rule の間の優先順位関係に関して比較する(argument を「最弱の環(weakest link)」で比較する方法に対する擁護としては、[PRA 91, PRA 93] を参照されたい)。しかし、衝突に strict rule が関わる場合、各 argument は、優先順位が関係する rule を複数含みうる。それを見るため、A = [r1: ⇒ Rab, r2: ⇒ Rbc]、B = [r3: ⇒ Rca] とし、S に R の推移律と非対称律の公理が含まれると仮定する。すると A は、これらの公理を使って ¬Rca の argument に拡張できる。つまり A は B を attack し、その逆も成り立つ。ここで A を調べると、r1 と r2 の両方の優先順位が、衝突の決着に関係すると考えるのが自然に思える。つまり、r3 を、rule の集合 {r1, r2} と比較したい。一般に、衝突に関わる両方の argument が、衝突に直接関係する rule を複数もちうるので、一般には、2つの defeasible rule の**集合**を比較する必要がある。
>
> では、比較に関係する rule とは何か。単純な場合、つまり衝突が、補完的な後件をもつ2つの defeasible rule の間にあるときは、まさにその2つの defeasible rule である。より複雑な場合、つまり衝突が strict rule によって決まるときは、各 argument について、衝突を成立させるために(仮定的に)argument を拡張するのに使われる strict rule の前件を満たすのに使われる、すべての defeasible rule である。衝突がすべて strict rule によって生じる特殊な場合には、関係する defeasible rule の集合は空になる。形式的には次のようになる。

### 定義2.13

**原文:** For any argument A and set S of strict rules such that A + S is an argument with conclusion L we define the set R_L(A + S) of the defeasible rules relevant to L in the argument A + S as follows. R_L(A + S) =
1. {r_d} iff A includes a defeasible rule r_d with consequent L;
2. R_L1(A + S) ∪ … ∪ R_Ln(A + S) iff A is defeasible and S includes a strict rule r_s: L1 ∧ … ∧ Ln → L.

**和訳:** 任意の argument A と、A + S が結論 L をもつ argument であるような strict rule の集合 S について、argument A + S において L に**関係する defeasible rule の集合 R_L(A + S)** を次のように定義する。R_L(A + S) =

1. {r_d}。ただしそれは、A が、後件が L である defeasible rule r_d を含むときかつそのときに限る。
2. R_L1(A + S) ∪ … ∪ R_Ln(A + S)。ただしそれは、A が defeasible であり、かつ S が strict rule r_s: L1 ∧ … ∧ Ln → L を含むときかつそのときに限る。

### 直後の説明

> 定義により、どの argument も、同じ後件をもつ2つの rule を含まないので、集合 R_L(A + S) は常に一意であることに注意されたい。
>
> この定義を説明するため、例2.6と2.10で比較される rule は r1 と r2 である。次に、A = [r1: ⇒ Rab, r2: ⇒ Rbc, s1: Rab ∧ Rbc → Rac] を考える。すると R_Rac(A) = {r1, r2} である。ただし、s1 を defeasible rule にすると、R_Rac(A) = {s1} となる。
>
> 次に、rule の集合の順序を、その要素の順序に基づいて定義する。

### 定義2.14

**原文:** For any two sets R and R′ of defeasible rules, R < R′ iff for some r ∈ R and all r′ ∈ R′ it holds that r < r′.

**和訳:** defeasible rule の任意の2つの集合 R と R′ について、R < R′ であるとは、R のある r が存在して、R′ のすべての r′ に対して r < r′ が成り立つときかつそのときに限る。

### 直後の説明

> この定義の直観的な考え方は、R < R′ であるとき、R の中のある rule を R′ の任意の rule に置き換えることで R をより良くできるが、その逆はできない、というものである。
>
> これで、argument の rebut と undercut の定義を与えるための道具が揃った。実際、それは attack の定義とほとんど同じになる。唯一の違いは、attack の第1の場合、すなわち argument が補完的な結論をもつ場合に、それらを評価するために優先順位を使うことである。第2の場合には優先順位を使わないので、assumption に対する attack は常に成功する。

### 定義2.15

**原文:** Let A1 and A2 be two arguments. Then
• A1 rebuts A2 iff condition (1) of Definition 2.8 holds, provided that R_L(A1 + S1) ≮ R_L̄(A2 + S2).
• A1 undercuts A2 iff condition (2) of Definition 2.8 holds.

**和訳:** A1 と A2 を2つの argument とする。このとき:

- A1 が A2 を **rebut** するとは、定義2.8の条件(1)が成り立ち、かつ R_L(A1 + S1) ≮ R_L̄(A2 + S2) であるときかつそのときに限る。
- A1 が A2 を **undercut** するとは、定義2.8の条件(2)が成り立つときかつそのときに限る。

【訳注】R_L̄ の上線は PDF のテキスト抽出で欠落していたが、定義2.8(1)の「結論 L̄」との対応から補った。

### 直後の説明

> この定義の性質を調べるため、まず、attack の定義から、rebut と undercut も「直接的」または「間接的」でありうることが引き継がれる、ということに注意する。次に、他のいくつかの性質を調べよう。まず、A が B を rebut または undercut するなら、A は B を attack する、ということに注意されたい。A が B を undercut するからといって、B が A を undercut するとは限らないのは明らかである。しかし、A が B を undercut するなら B は A を undercut しない、ということも成り立たない。反例は A = [r1: ∼b ⇒ a]、B = [r2: ∼a ⇒ b] である。また、A が B を rebut するなら B が A を rebut する、ということも成り立たない。A = [r3: ⇒ a]、B = [r4: ⇒ ¬a] とし、r3 < r4 と仮定すればよい。ただし、衝突する rule の間の < 関係を伴う rebut は、常に一方向とは限らない。それを見るため、例2.10で r1 < r4 かつ r3 < r2 と仮定する。すると [r1, r2] と [s1, r3, r4] は互いを rebut する。
>
> ついに defeat の定義を与えることができる。それは、argument を評価する際に、undercut と rebut という attack の概念をどう組み合わせるかを述べる。境界的な場合として、incoherent な argument は、空の argument によって defeat されると見なす。これとは別に、この定義は2つの考え方に基づいていて、その第1のものは暗黙であり、attack・rebut・undercut の定義から引き継がれる。すなわち、argument の defeat は、直接的にも間接的にも、その strict な subargument のひとつを defeat することによって起こりうる、というものである。もう一方の考え方は、assumption に対する attack は、常に成功するだけでなく、結論に対する attack よりも常に強い、というものである。すなわち、一方の argument が他方を undercut し、他方が前者を undercut せず rebut するだけなら、前者は後者を defeat するが、後者は前者を defeat しない。この選択は、後で例2.18を論じるときに擁護する。

### 定義2.16

**原文:** Let A1 and A2 be two arguments. Then A1 defeats A2 iff A1 is empty and A2 is incoherent, or else if
• A1 undercuts A2; or
• A1 rebuts A2 and A2 does not undercut A1.
We say that A1 strictly defeats A2 iff A1 defeats A2 and A2 does not defeat A1.

**和訳:** A1 と A2 を2つの argument とする。A1 が A2 を **defeat** するとは、A1 が空で A2 が incoherent であるか、そうでなければ次のいずれかが成り立つときかつそのときに限る。

- A1 が A2 を undercut する。または
- A1 が A2 を rebut し、かつ A2 が A1 を undercut しない。

A1 が A2 を **strictly defeat** するとは、A1 が A2 を defeat し、かつ A2 が A1 を defeat しないときかつそのときに限る。

### 直後の説明(系2.17は省略)

> 境界的な場合を確かめると、定義2.14から、空でないどの rule の集合 R についても R < ∅ である。これにより、strict な argument は、衝突する defeasible な argument を strictly defeat する。さらに ∅ ≮ ∅ なので、strict な argument が、衝突する別の strict な argument を strictly defeat することはない(strict rule は weak literal を含まないことを思い出されたい)。
>
> 本節の最後に、2つの主要な設計上の選択について論じる。第1に、なぜ undercut による defeat は優先順位に依存しないのか。これは、法(および同様の領域)における衝突解決規則は、rule 間の head-to-head の衝突を解決するためにだけ使われ、head-to-body の衝突を解決するためには使われないと思われるからである。ただし、別の領域ではこれが異なることもありうるだろう。その場合は、[BRE 96] の要素を我々の定義に取り込める。Brewka は、argument に基づかない、優先順位つきの拡張論理プログラムを提示している。彼は、defeasible であると意図されたすべての rule に、その後件 L を、前件の中で ∼L̄ として仮定させることにより、head-to-head の衝突を(相互の)head-to-body の衝突に還元する。こうすると、表現力が一部失われる。「A ならば B」と、「A ならば B、ただし反対が示されない限り」のような defeasible rule の違いを表現できなくなるからである。より重要な違いは、[BRE 96] では、すべての相互 head-to-body 衝突が優先順位で解決されるので、head-to-head の衝突ではない衝突にも、これが当てはまることである。次を考えよ。
>
> 　r1: ∼a ∧ ∼¬b ⇒ b
> 　r2: ∼b ∧ ∼¬a ⇒ a
> 　r2 < r1
>
> 我々は [r1] と [r2] の両方が互いを defeat すると見なす。一方 Brewka は、前者が後者を strictly defeat すると見なす。我々のシステムとの最後の違いは、第9節で論じる。
>
> 第2の設計上の選択は、undercut による attack を、rebut による attack より強いと見なすことだった。まず次の例を考える。
>
> 　r1: ∼¬OJ is innocent ⇒ OJ is innocent
> 　r2: ⇒ ¬OJ is innocent
>
> そして < = ∅ と仮定する。すると、[r1] は [r2] を rebut するが、[r1] は [r2] を defeat しない。[r2] が [r1] を undercut するからである。したがって [r2] は [r1] を strictly defeat する。
>
> この例で、undercut による attack を rebut による attack より強いと見なす理由を説明できる。両方の rule を受け入れる唯一の方法は、OJ は無実ではないと信じることだからである。その場合、r1 の条件は満たされない。対照的に、OJ が無実だと信じるなら、r2 は棄却されなければならない。つまり、その前件は信じられるが、後件は信じられない。実際、ここでは、法は可能な限り首尾一貫して解釈されるべきだという法原則の、論理的な対応物を用いている。
>
> 我々の defeat の概念の性質を調べると、それが**弱い**ものであることが分かる。argument を rebut するのに、関係する rule の集合の間に > 関係は要らず、≮ 関係だけが要るからである。つまり、defeat される argument より「本当に良い」必要はなく、defeat する argument は、劣っていなければよい。このように弱い defeat の概念をもつ理由は、次に定義する「justified な argument」の概念が、前提が与えられたとき、合理的な疑いや異議を超えている argument だけを justified と見なすからである。そして、argument への合理的な疑いは、それより劣っていない反論を提示するだけで投げかけられる。
>
> 同じ理由で、strict defeat の概念も必要である。これは非対称であり、「本当に〜より良い」という考えを捉える。次の節では、この概念を使って、ある反論が、それ自身が defeat から守られている少なくとも1つの反論より劣っているなら、疑いを投げかけられない、ということを保証する。

---

# 第3節 argument の status:不動点意味論

## 3.1 定義と性質(定義3.1の前置き)

> defeat する argument は、さらに別の argument に defeat されうるので、argument の組を比較するだけでは不十分である。argument の status の概念を、それらが相互作用するすべての仕方に基づいて定義する必要もある。特に、その定義は、defeat された argument が、その defeater 自身が別の argument に(strictly)defeat されている場合、復権(reinstatement)することを許すものでなければならない。さらに、argument は、そのすべての subargument が justified でない限り justified になれない、という「最弱の環」原理を尊重すべきである。
>
> この概念が、我々のシステムの中心要素である。その定義は、すべての可能な argument と、それらの相互の defeat 関係を入力とし、出力として argument を3つのクラスに分ける。すなわち、論争に「勝てる」argument、「負ける」argument、そして論争を未決のままにする argument である。上で述べたように、勝つ argument は、前提が与えられたとき、合理的な疑いを超える argument だけであるべきである。これらの argument に疑いを投げかける唯一の方法は、新しい前提を与え、新しい defeating な反論を生むことである。したがって、justified な argument の集合は、一意で、conflict-free で、これらおよび他のいくつかの妥当な条件に関して、できるだけ小さいことを望む。そのような集合を定義した後、負ける「overruled」な argument を、justified な argument に attack される argument として、未決の「defensible」な argument を、justified でも overruled でもないすべての argument として定義できる。
>
> justified な argument の概念を、意味論と証明論という2つの版で示す。ここで「意味論」とは、ある性質をもつ argument の集合の指定を意味し、「証明論」とは、個々の argument がこの集合のメンバーであるかどうかを決める手続きを意味する。他の研究者、例えば [LN 95] は、この区別を「宣言的」システムと「手続き的」システムという語で表した。我々の意味論の概念が、argument を構成する基礎となる論理がモデル論的意味論をもつ可能性を排除しないことに注意されたい。第10節を参照。
>
> 我々の意味論は、[Dung 93b] の、argument の集合に関する argument の受容可能性(acceptability)の概念の変種に基づく(Dung の仕事との詳細な比較は第9節で行う)。

### 定義3.1

**原文:** An argument A is acceptable with respect to a set Args of arguments iff each argument defeating A is strictly defeated by an argument in Args.

**和訳:** argument A が、argument の集合 Args に関して **acceptable(受容可能)**であるとは、A を defeat する各 argument が、Args に属するある argument によって strictly defeat されるときかつそのときに限る。

### 直後の説明

> justified な argument の集合は、作用素によって特徴づけられる。この作用素は、argument の各集合に対して、その集合に関して受容可能なすべての argument の集合を返す。この作用素は単調なので、justified な argument の集合を、その最小不動点として定義できる。この作用素は、[Dung 93b] の、拡張論理プログラムの grounded(懐疑的)意味論の中核でもあり、Dung はこれを順序理論の「特性関数(characteristic function)」と呼んでいる。

### 定義3.2

**原文:** Let Γ be an ordered theory and S any subset of Args_Γ. The characteristic function of Γ is:
• F_Γ : Pow(Args_Γ) → Pow(Args_Γ)
• F_Γ(S) = {A ∈ Args_Γ | A is acceptable with respect to S}

**和訳:** Γ を順序理論、S を Args_Γ の任意の部分集合とする。Γ の**特性関数(characteristic function)**は次のとおりである。

- F_Γ : Pow(Args_Γ) → Pow(Args_Γ)
- F_Γ(S) = {A ∈ Args_Γ | A は S に関して acceptable である}

(命題3.3「F_Γ は単調である」は省略。)

### 直後の説明

> この定義で、受容可能性の概念が復権(reinstatement)を捉えている。A が B に defeat されていても、B が、すでに justified と分かっている argument によって strictly defeat されているなら、そしてそのときに限り、A はなお justified でありうる。
>
> 単調な作用素は最小不動点をもつことが保証されているので、justified な argument の概念を、次のように定義できる。

### 定義3.4

**原文:** For any ordered theory Γ and argument A we say that on the basis of Γ:
1. A is justified iff A is in the least fixpoint of F_Γ (denoted by JustArgs_Γ);
2. A is overruled iff A is attacked by a justified argument.
3. A is defensible iff A is neither justified nor overruled.
And for any literal L, we say that on the basis of Γ L is a justified conclusion iff it is a conclusion of a justified argument, L is a defensible conclusion iff it is not justified and it is a conclusion of some defensible argument, and L is an overruled conclusion iff it is not justified or defensible, and a conclusion of an overruled argument.

**和訳:** 任意の順序理論 Γ と argument A について、Γ に基づいて次のように言う。

1. A が **justified** であるとは、A が F_Γ の最小不動点(JustArgs_Γ と書く)に属するときかつそのときに限る。
2. A が **overruled** であるとは、A が justified な argument に attack されるときかつそのときに限る。
3. A が **defensible** であるとは、A が justified でも overruled でもないときかつそのときに限る。

さらに、任意のリテラル L について、Γ に基づいて次のように言う。L が **justified な結論**であるとは、L が justified な argument の結論であるときかつそのときに限る。L が **defensible な結論**であるとは、L が justified ではなく、かつ L がある defensible な argument の結論であるときかつそのときに限る。L が **overruled な結論**であるとは、L が justified でも defensible でもなく、かつ overruled な argument の結論であるときかつそのときに限る。

【訳注】overruled の定義は、原文では「attacked by a justified argument(justified な argument に **attack** される)」で、「defeated(defeat される)」ではない。Kido & Kurihara(2009)の定義5は「defeated by the justified argument」と書いており、ここは原文と異なる。

### 直後の説明

> F_Γ の単調性は、それに構成的な性格を与える。その最小不動点は、空集合への反復適用によって近似でき、ある有限性の条件のもとでは、反復適用によって得ることもできる。

### 定義3.5

**原文:** [Dung 93b]. An ordered theory Γ is finitary iff each argument in Args_Γ is attacked by at most a finite number of arguments in Args_Γ.

**和訳:** [Dung 93b]。順序理論 Γ が **finitary** であるとは、Args_Γ の各 argument が、Args_Γ の高々有限個の argument にしか attack されないときかつそのときに限る。

(命題3.6は省略。F^1 = F_Γ(∅)、F^{i+1} = F^i ∪ F_Γ(F^i) として、その和集合が JustArgs_Γ に含まれる、finitary ならば等しい、という内容。)

---

# 第4節 優先順位が厳密な場合の証明論

## 4.1 一般的な考え方(定義4.5の前置き)

> ここまでは、システムの意味論、すなわち、justified であるという性質をもつ argument の集合の定義だけを与えた。本節では、この集合への、個々の argument の所属の検査、すなわち、我々の意味論のための証明論を定義する。命題3.6を利用する。それは、argument が justified であるのは(finitary な理論では「iff」)、F を空集合に有限回反復適用した結果に含まれるとき、というものである。基本的な考え方は、A が初めて現れる F^n までの列 F^1, …, F^n を、逆向きにたどることである。A から始めて、A を defeat するどの argument B についても、F^{n-1} の中から、B を strictly defeat し、それによって間接的に A を支える argument C を見つける。すると C を defeat するどの argument にも、F^{n-2} からの strict な defeater で応じる。以下同様である。列は有限なので、最後には、defeat されえない、A を間接的に支える argument に行き着く。
>
> [VRE 93b, Dung 94, BRE 94b, LN 95] に着想を得て、証明論を弁証法的なスタイルで示す。argument が justified であることの証明は、**対話の木(dialogue tree)**の形をとる。木の各枝は対話であり、木の根は、その式のための argument である。考え方は、対話のすべての手が、入力理論に基づく argument からなり、提示された各 argument が、プレイヤーの立証責任を満たす仕方で、相手の最後の手を attack する、というものである。手が完全な argument からなるということは、個々の argument の探索が、基礎となる論理の性質によって決まる「独白的(monological)」な仕方で行われることを意味する。反論を考慮する過程だけが、弁証法的にモデル化される。手に求められる力は、それを提示する者に依存する。proponent は結論が justified であることを望むので、proponent の argument は strictly defeating でなければならない。一方 opponent は、結論が justified になるのを妨げたいだけなので、opponent の手は、単に defeating であればよい。読者は、受容可能性の定義を思い出すだろう。
>
> 次の例に基づく対話で、これを説明しよう。

(例4.1と4.2は省略。)

> 弁証法的な証明システムでは、「ループ検査」を非常に自然な仕方で実装できる。すなわち、対話の同じ枝の中で、proponent の2つの手が同じ内容であってはならない、と定めることによってである。

(例4.3の対話は省略。)

> 非反復の規則は P を害さない、ということは容易に分かる。P が argument を最初に述べたときに O に打つ手があったなら、2回目に述べたときにも打つ手があるので、P の繰り返しによって、P が対話に勝てることはない。
>
> 一方、O には手を繰り返せる可能性がなければならない。次の例が示すとおりである。

(例4.4は省略。)

## 4.2 証明論

> ここで、弁証法的な証明論を形式的に定義する。

### 定義4.5

**原文:** A dialogue is a finite nonempty sequence of moves move_i = (Player_i, Arg_i) (i > 0), such that
1. Player_i = P iff i is odd; and Player_i = O iff i is even;
2. If Player_i = Player_j = P and i ≠ j, then Arg_i ≠ Arg_j;
3. If Player_i = P (i > 1), then Arg_i is a minimal (w.r.t. set inclusion) argument strictly defeating Arg_{i-1};
4. If Player_i = O, then Arg_i defeats Arg_{i-1}.

**和訳:** **対話(dialogue)**とは、手 move_i = (Player_i, Arg_i)(i > 0)の、有限で空でない列であって、次を満たすものである。

1. Player_i = P であるのは i が奇数のときかつそのときに限り、Player_i = O であるのは i が偶数のときかつそのときに限る。
2. Player_i = Player_j = P かつ i ≠ j ならば、Arg_i ≠ Arg_j である。
3. Player_i = P(i > 1)ならば、Arg_i は、Arg_{i-1} を strictly defeat する(集合の包含に関して)**極小の** argument である。
4. Player_i = O ならば、Arg_i は Arg_{i-1} を defeat する。

### 直後の説明

> 第1の条件は、P が最初に始め、それからプレイヤーが交互に打つことを述べている。第2の条件は、proponent が自分の攻撃を繰り返すことを防いでいる。残りの2つの条件が、この定義の核心である。これらは、P と O それぞれの立証責任を定めている。P の手に対する極小性の条件は、無関係な別の argument を組み合わせるだけで、自明に違うだけの argument を作ることを不可能にする。

### 定義4.6

**原文:** A dialogue tree is a finite tree of moves such that
1. Each branch is a dialogue;
2. If Player_i = P then the children of move_i are all defeaters of Arg_i.

**和訳:** **対話の木(dialogue tree)**とは、手の有限な木であって、次を満たすものである。

1. 各枝が対話である。
2. Player_i = P ならば、move_i の子は、Arg_i のすべての defeater である。

### 直後の説明

> この定義の第2の条件が、対話の木を証明の候補にする。それは、木が、O が P の argument を attack できるすべての可能な仕方を考慮しなければならない、と述べている。

### 定義4.7

**原文:** A player wins a dialogue if the other player cannot move. And a player wins a dialogue tree iff it wins all branches of the tree.

**和訳:** プレイヤーが**対話に勝つ**とは、相手のプレイヤーが手を打てないときである。そして、プレイヤーが**対話の木に勝つ**とは、その木のすべての枝に勝つときかつそのときに限る。

### 直後の説明

> この定義の考え方は、P の最後の argument が defeat されていなければ、その argument は、同じ枝の中の P のそれ以前のすべての argument、特に木の根を復権させる、というものである。

### 定義4.8

**原文:** An argument A is a provably justified argument iff there is a dialogue tree with A as its root, and won by the proponent. And a strong literal L is a provably justified conclusion iff it is a conclusion of a provably justified argument.

**和訳:** argument A が **provably justified な argument** であるとは、A を根とし、proponent が勝つ対話の木が存在するときかつそのときに限る。そして strong literal L が **provably justified な結論**であるとは、L が provably justified な argument の結論であるときかつそのときに限る。

(命題4.9「provably justified な argument はすべて justified である」、命題4.10「finitary な順序理論では、justified な argument はすべて provably justified である」は省略。)

---

# 第5節 形式システム II:defeasible な優先順位

## 5.1 新しい不動点意味論(定義5.1の前置き)

> ここまでは、rule の順序が固定されていて、議論の余地がないと単純に仮定してきた。しかし、序論で述べたように、この仮定は非現実的であることが多い。法的推論でも、実践的推論の他のいくつかの領域でも、衝突解決の基準自体が議論と不一致の対象になる。したがって、defeasible argumentation の完全な理論は、優先順位についての argument も形式化できるべきである。
>
> 当然ながら、これは、オブジェクト言語に優先順位の述語記号を加えるだけではできない。加えて、オブジェクトレベルで導かれた優先順位が、何らかの形でシステムのメタ理論、特に定義2.14に引き上げられる必要がある。したがって、オブジェクトとメタレベルの間の形式的な接続を定義しなければならない。
>
> 言語が、優先順位に関する情報をオブジェクト言語で表現できるようにする、特別な2項述語記号 ≺ をもつと仮定することから始める。これにより、順序理論の第3の構成要素は冗長になるので、これ以降、順序理論は単に対 (S, D) である。次に、こうして導かれた順序が、望ましい型であること、すなわち strict partial order であることを確かめなければならない。これは、半順序の公理を strict rule に加えることでできる。やや面倒なのは、strict rule は対偶を許さないので、推移律の対偶 rule も加える必要があることである(非対称律については、対偶は冗長である)。そこで、本論文の以降では、すべての入力理論について、strict rule の集合 S は、述語 ≺ を含む次の rule をすべて、かつそれだけを含むと仮定する。
>
> 　t1: x ≺ y ∧ y ≺ z → x ≺ z
> 　t2: x ≺ y ∧ ¬x ≺ z → ¬y ≺ z
> 　t3: y ≺ z ∧ ¬x ≺ z → ¬x ≺ y
> 　a: x ≺ y → ¬y ≺ x
>
> 次に、オブジェクトレベルで導ける優先順位の結論を、システムのメタレベルに結びつける必要がある。すなわち、(r, r′) ∈ < であるのは、r ≺ r′ の justified な argument が存在するときかつそのときに限る、ようにしたい。言い換えると、順序理論 Γ の順序の構成要素は、Γ に基づいて justified であるすべての優先順位 argument の集合によって決まるべきである。
>
> これを命題3.6の言葉で述べると、考え方は、justified な argument の集合とともに、順序も段階的に「構築」される、というものである(この考え方は [BRE 96] の以前の版に着想を得ている)。つまり、さまざまな概念の rule の順序への依存を明示する必要がある。この順序は、これまでに導かれた結論とともに変わるからである。そのため、まず、argument の集合が優先順位について何を「言って」いるかを捉える、次の記法を定義する。

### 定義5.1

**原文:** For any set Args of arguments <_Args = {r < r′ | r ≺ r′ is a conclusion of some A ∈ Args}. And we say for any set of arguments Args that A (strictly) Args-defeats B on the basis of Γ iff according to Definition 2.16 A (strictly) defeats B on the basis of (Γ, <_Args). Occasionally, we will also use the analogous notion Args-rebuts. And for any argument A we write {A}-defeats as A-defeats.

**和訳:** argument の任意の集合 Args について、

　<_Args = {r < r′ | r ≺ r′ は、ある A ∈ Args の結論である}

と定める。そして、argument の任意の集合 Args について、A が Γ に基づいて B を(strictly)**Args-defeat** するとは、定義2.16に従って、A が (Γ, <_Args) に基づいて B を(strictly)defeat するときかつそのときに限る、と言う。ときには、類似の概念 **Args-rebuts** も使う。また、任意の argument A について、{A}-defeats を A-defeats と書く。

(系5.2は省略。)

> 次に、新しい記法を受容可能性の定義に取り込む。

### 定義5.3

**原文:** An argument A is acceptable with respect to a set Args of arguments iff all arguments Args-defeating A are strictly Args-defeated by some argument in Args.

**和訳:** argument A が、argument の集合 Args に関して **acceptable** であるとは、A を Args-defeat するすべての argument が、Args に属するある argument によって strictly Args-defeat されるときかつそのときに限る。

### 直後の説明

> このように、argument の、集合 Args に関する受容可能性は、いまや Args の argument の優先順位に関する結論に依存する。
>
> 順序理論の特性関数を再定義するにあたって、上の定義3.4で定義された作用素は、一般には単調でないことを考慮しなければならない。単調性が証明できるのは、作用素の定義域を、conflict-free な argument の集合に制限した場合だけである。それ以外は、定義はそのままでよい。

【訳注】「定義3.4で定義された作用素」は原文のまま。文脈上は、特性関数を定義した定義3.2を指すと思われる。

### 定義5.4

**原文:** Let Γ = (S, D) be an ordered theory, S any subset of Args_Γ and Cargs_Γ the set of all conflict-free subsets of Args_Γ. Finally, let acceptability be defined as in Definition 5.3. Then the characteristic function of Γ is:
• G_Γ : Cargs_Γ → Pow(Args_Γ)
• G_Γ(S) = {A ∈ Args_Γ | A is acceptable with respect to S}

**和訳:** Γ = (S, D) を順序理論、S を Args_Γ の任意の部分集合、Cargs_Γ を Args_Γ のすべての conflict-free な部分集合の集合とする。最後に、受容可能性を定義5.3のように定義する。すると Γ の**特性関数**は次のとおりである。

- G_Γ : Cargs_Γ → Pow(Args_Γ)
- G_Γ(S) = {A ∈ Args_Γ | A は S に関して acceptable である}

【訳注】原文は S を、strict rule の集合と、argument の部分集合の両方に使っている。原文のまま訳した。

(命題5.5「G_Γ は単調である」は省略。)

### 定義5.6

**原文:** For any ordered theory Γ = (S, D) and argument A we say that A is justified on the basis of Γ iff A is in the least fixpoint of G_Γ (denoted by JustArgs_Γ). Overruled and defensible arguments are defined as above.

**和訳:** 任意の順序理論 Γ = (S, D) と argument A について、A が Γ に基づいて **justified** であるとは、A が G_Γ の最小不動点(JustArgs_Γ と書く)に属するときかつそのときに限る。overruled な argument と defensible な argument は、上と同様に定義する。

### 直後の説明(命題5.7、5.8、5.9は省略)

> ただし今回は、JustArgs の構築の各ステップが、rule の順序も暗黙に拡張することに注意されたい。G は受容可能性の概念を使い、それは Args-defeat の概念を使い、そして Args、したがって <_Args は、新しいステップごとに変わるからである。つまり、各新しいステップで、defeat 関係が、そこまでに構築された justified な argument の集合に基づいて、決め直される。

> (命題5.8の後)上で述べたように、G は、定義域を conflict-free な集合に制限しなければ単調でない。反例は次のとおりである。
>
> 　A1: [r1: ⇒ a]
> 　A2: [r2: ⇒ b, r3: b ⇒ ¬a]
> 　A3: [r4: ⇒ ¬b]
> 　A4: [r5: ⇒ r2 ≺ r4]
> 　A5: [r6: ⇒ r4 ≺ r2]
>
> 　G({A3, A4}) = {A1, A3}
> 　G({A3, A4, A5}) = {A3}
>
> これが有害かどうかを見るため、Dung の別の概念を使う。

### 定義5.10

**原文:** A set E of arguments is a complete extension iff it is a maximal (w.r.t. set inclusion) set such that A ∈ E iff A is acceptable with respect to E.

**和訳:** argument の集合 E が **complete extension** であるとは、E が、「A ∈ E であるのは、A が E に関して acceptable であるときかつそのときに限る」を満たす、(集合の包含に関して)極大の集合であるときかつそのときに限る。

### 直後の説明(命題5.11と系5.12は省略)

> Dung はこの概念を conflict-free な集合 E に対してだけ定義しているが、我々の目的には、この制限を外すほうが有益である。明らかに、G の最小不動点は complete extension である。さらに、次が成り立つ。(命題5.11: JustArgs の上位集合でない complete extension は、conflict-free ではない。系5.12: どの complete extension も JustArgs の部分集合ではない。)
>
> これらの結果は、G の定義域を conflict-free な集合に制限しても害がない、ということを意味する。JustArgs は極小の complete extension であり、他のすべての極小の complete extension は conflict-free ではないので、すべて合理的に justified として受け入れられる argument の集合を捉えていない。

---

# 第6節 優先順位が defeasible な場合の証明論

## 6.1 定義(定義6.1の前置き)

> 証明論を、defeasible な優先順位に適応させるときの主な問題は、どの優先順位に基づいて、手の defeating の力を決めるべきか、である。避けたいのは、手の defeating の力を決められるようになる前に、すべての優先順位 argument を生成しなければならないことである。うれしい驚きは、これを達成するのに、ごく単純な少数の条件で足りることである。O にとっては、その手が P の直前の手を ∅-defeat すれば十分である。これは、付録で示すように、定義2.16が、ある S について A が P の直前の手の S-defeater であるなら、それは、その手の ∅-defeater でもあることを含意するからである。したがって、O は優先順位を考慮する必要がない。次の例が示すとおりである。
>
> 　P1: [r1: ⇒ a]
>
> O の可能な手の1つは次のとおりである。
>
> 　O1: [r2: ⇒ b, r3: b ⇒ ¬a]
>
> 一方 P は、いくつかの優先順位を考慮すべきである。ただし、P の手が述べる優先順位だけを適用すれば足りる。定義2.16は、P の argument Arg_i が O の直前の手を strictly Args_i-defeat するなら、今後さらにどんな優先順位が導かれても、そうであることも含意するからである。したがって P は O1 に次のように応じられる。
>
> 　P2: [r4: ⇒ ¬b, r5: ⇒ r2 ≺ r4]
>
> しかし、これが proponent の取れる唯一の種類の手ではない。O が次のように応じて、
>
> 　O2: [r2: ⇒ b]
>
> これが P2 を ∅-defeat するなら、P は、優先順位 argument
>
> 　P3: [r5: ⇒ r2 ≺ r4]
>
> によって、O2 の defeating の力を「取り消す」可能性をもたなければならない。
>
> これらの考え方を、対話の定義に取り込む。すべての条件は上と同じだが、「defeat」への言及だけが異なる。

### 定義6.1

**原文:** A priority dialogue is a finite sequence of moves move_i = (Player_i, Arg_i) (i > 0), where
1. Player_i = P iff i is odd, and Player_i = O iff i is even;
2. If Player_i = Player_j = P and i ≠ j, then Arg_i ≠ Arg_j;
3. If Player_i = P (i > 1) then Arg_i is a minimal (w.r.t. set inclusion) argument such that
　• Arg_i strictly Arg_i-defeats Arg_{i-1}; or
　• Arg_{i-1} does not Arg_i-defeat A_{i-2};
4. If Player_i = O then Arg_i ∅-defeats Arg_{i-1}.

**和訳:** **priority dialogue** とは、手 move_i = (Player_i, Arg_i)(i > 0)の有限列であって、次を満たすものである。

1. Player_i = P であるのは i が奇数のときかつそのときに限り、Player_i = O であるのは i が偶数のときかつそのときに限る。
2. Player_i = Player_j = P かつ i ≠ j ならば、Arg_i ≠ Arg_j である。
3. Player_i = P(i > 1)ならば、Arg_i は、次のいずれかを満たす、(集合の包含に関して)極小の argument である。
　- Arg_i が Arg_{i-1} を strictly Arg_i-defeat する。または
　- Arg_{i-1} が A_{i-2} を Arg_i-defeat しない。
4. Player_i = O ならば、Arg_i は Arg_{i-1} を ∅-defeat する。

【訳注】原文は3の2つ目の条件で「A_{i-2}」と書いており、「Arg_{i-2}」の誤記と思われるが、原文のまま訳した。

### 直後の説明

> 対話の木の定義での唯一の変更は、O の手に対する defeat の条件が、空集合に相対的になることである。

### 定義6.2

**原文:** A priority dialogue tree is a finite tree of moves such that
1. Each branch is a dialogue;
2. If Player_i = P then the children of move_i are all ∅-defeaters of Arg_i.

**和訳:** **priority dialogue tree** とは、手の有限な木であって、次を満たすものである。

1. 各枝が(priority)対話である。
2. Player_i = P ならば、move_i の子は、Arg_i のすべての ∅-defeater である。

### 直後の説明

> その他の定義は変わらない。

(命題6.3、6.4、6.5と例6.6〜6.8は省略。)

---

# 第7節 代替の credulous 意味論

## 7.1 stable extension(定義7.1の前置き)

> 我々の意味論は、懐疑的(sceptical)である。つまり、受容可能な argument の一意の集合を定義し、2つの argument が解決不能な衝突にあれば、どちらもその集合に入らない。defensible な argument の概念は、いわば個別に定義されている。argument が defensible であるのは、justified ではなく、かつ justified な argument に attack されてもいないとき、かつそのときに限る。しかし、個々の argument が defensible であることを知るだけでなく、さらに知りたいこともある。どの defensible な argument の集合を一緒に擁護できるか、すなわち、どの集合が、同じ一貫した観点に基づいているか、である。例えば、
>
> 　r1: ⇒ a
> 　r2: ⇒ ¬a
> 　r3: ∼a ⇒ b
>
> があるとき、argument [r2] と [r3] は1つの観点に依存し、[r1] は別の、両立しない観点に依存する、と言いたい。
>
> そうした概念が、[Dung 93b] が定義した代替意味論、すなわち credulous な性格をもつ stable 意味論によって捉えられるかどうかを調べる。defeasible な優先順位をもつシステム向けに、これを定義する。

### 定義7.1

**原文:** A conflict-free set S is a stable extension iff every argument that is not in S, is S-defeated by some argument in S.

**和訳:** conflict-free な集合 S が **stable extension** であるとは、S に属さないすべての argument が、S のある argument によって S-defeat されるときかつそのときに限る。

### 直後の説明(命題7.2、7.3、例7.4は省略)

> 明らかに、stable extension は conflict-free なので、ある意味で一貫した観点を反映している。さらにそれは、あらゆる可能な argument が、受け入れられるか棄却されるかのどちらかであるという意味で、極大の観点である。
>
> stable extension と、我々の defensible な argument の定義との関係はどうか。もしかすると、stable extension とは、JustArgs に、defensible な argument の任意の極大な conflict-free 集合を加えて得られる集合そのものだろうか。まず、次の結果を証明する。
>
> (命題7.2: すべての stable extension は JustArgs を含む。命題7.3: A が一部の stable extension には含まれ、すべてには含まれないなら、A は defensible である。例7.4: 逆の含意の反例。r1: ∼a ⇒ b、r2: ∼b ⇒ c、r3: ∼c ⇒ a のとき、[r1]、[r2]、[r3] はすべて defensible だが、どれも stable extension に含まれない。)
>
> それでも、集合 {[r1]} は、極大の一貫した観点を反映しているという意味がありそうである。それは次の概念で捉えられる。

### 定義7.5

**原文:** A defensible extension is any maximal (w.r.t. set inclusion) conflict-free subset of Args that includes JustArgs.

**和訳:** **defensible extension** とは、JustArgs を含む、Args の(集合の包含に関して)極大の conflict-free な部分集合のことである。

(系7.6「すべての stable extension は defensible extension だが、すべての defensible extension が stable とは限らない」と、例7.4・例5.16に基づく defensible extension の議論は省略。)

---

# 第9節 関連研究

## 9.1 Dung のアプローチとの関係(定義9.2・9.4の前置き)

> 関連研究として、まず [Dung 93b] の仕事との形式的な比較を行う。Dung は、[BTK 93] と [Dung 95] のより抽象的な研究に基づいて、明示的な否定をもつ拡張論理プログラムの、argument に基づくさまざまな意味論を発展させた。すでに述べたように、我々は [Dung 93b] の定義の1つ、特に、拡張論理プログラムの彼版の well-founded 意味論(例えば [BS 91] を参照)に基づいている。ただし、いくつかの違いがある。第1に、Dung は、優先順位を伴う推論、または優先順位についての推論を考慮しない。さらに、Dung は、論理プログラムのさまざまな意味論を再定式化することだけを意図しているので、well-founded 意味論の場合、彼の体系は、我々が魅力に乏しいと考える、その特徴のいくつかを引き継いでいる。したがって、我々の定義は、いくつかの点でこの意味論を修正している。
>
> 比較を、Dung の定式化と、我々の well-founded 意味論の修正との関係についての形式的な結果から始める。そのため、rule に優先順位が定義されていないと仮定する。まず、Dung の関連する定義を列挙する。ただし、彼の概念が我々のものと一致する場合は、我々の用語を使う。
>
> **d-argument**(d は「Dung」の d)とは、assumption の集合である。**defeasible proof** は、我々の argument の概念(定義2.2)と同様に定義されるが、条件(2)は課さない。defeasible proof が d-argument A に**基づく**とは、その assumption が A に含まれているときかつそのときに限る(我々の argument も、この意味で A に基づきうる)。L が A の**結論**であるとは、A に基づく L の defeasible proof が存在するときかつそのときに限る。
>
> argument A が **self-defeating** であるとは、A に基づく、2つの補完的なリテラルの defeasible proof が存在するときかつそのときに限る。argument が **sound** であるとは、self-defeating ではないときかつそのときに限る。
>
> A と B を、sound な2つの d-argument とする。このとき A が B を **raa-defeat** する(raa は「Reductio Ad Absurdum(背理法)」の略)(脚注8: ここでは Dung の用語を我々のものに合わせた。Dung は、我々が「defeat」と言うところを「attack」と言うことを思い出されたい。)とは、A ∪ B が self-defeating であるときである。A が B を **g-defeat** する(g は「ground(根拠)」の略)とは、ある L ∈ B について、A が結論 L̄ をもつときである。最後に、A が B を **d-defeat** するとは、A が B を raa-defeat または g-defeat するときである。
>
> (観察9.1は省略。)
>
> 最後に、Dung は受容可能性を次のように定義している。

### 定義9.2

**原文:** A d-argument A is d-acceptable with respect to a set S of d-arguments iff any d-argument that d-defeats A is g-defeated by a member of S.

**和訳:** d-argument A が、d-argument の集合 S に関して **d-acceptable** であるとは、A を d-defeat する任意の d-argument が、S のある要素によって g-defeat されるときかつそのときに限る。

### 直後の説明(観察9.3は省略)

> Dung は「g-defeated」と言うが、我々は定義3.1で「strictly defeated」と言うことに注意されたい。優先順位がなければ、これは違いを生まない。次の観察が述べるとおりである。実は、違いが出るのは defeasible な優先順位の場合だけである。その場合、補題10.1(2)は我々の定義についてのみ成り立つ。(以下の F^d_Γ は、定義3.2と同様に定義されるが、定義域が Args_Γ ではなく Dargs_Γ である。同様に、F^{ps}_Γ は、定義域が Args_Γ の F_Γ である。)
>
> Dung の grounded 意味論を我々のものと比較する前に、self-defeating な d-argument の場合に何が起きるかについて、コメントしなければならない。プログラム Γ = {⇒ a, ⇒ ¬a} を考える。このプログラムには、argument がただ1つしかなく、それは ∅ で、self-defeating である。Dung は d-defeat を sound な argument に対してだけ定義するので、この argument は、argument の空集合に関して acceptable であり、したがって {∅} が F_Γ の最小不動点となり、これは a と ¬a の defeasible proof を支持する。Dung はこの可能性についてコメントしていない。我々は、well-founded 意味論の以前の版に合わせて、そのようなプログラムの well-founded な結論の集合を、空と定義する(例えば [BRE 96, pp. 22/3] の議論を参照)。
>
> 次の定義では、任意の rule の集合 Γ について、Dargs_Γ は、Γ に基づくすべての d-argument の集合を表す。

### 定義9.4

**原文:** The set of d-well-founded conclusions of a set Γ of rules is empty if Dargs_Γ contains a self-defeating argument; otherwise it is the least fixpoint of F^d_Γ.

**和訳:** rule の集合 Γ の **d-well-founded な結論**の集合は、Dargs_Γ が self-defeating な argument を含むなら空であり、そうでなければ F^d_Γ の最小不動点である。

### 直後の説明(命題9.5は省略)

> この節の主な結果は、プログラムの justified な結論の集合が、そのプログラムの d-well-founded な結論を含む、というものである。

(命題9.5と、例9.6、命題9.7は省略。)

---

# 付記:このファイルに含めていないもの

次は、定義ではないため省略した。必要なら追加できる。

- **例(Example):** 2.4〜2.6、2.9、2.10、2.18の一部、3.10〜3.17、4.1〜4.4、4.12、4.13、5.13〜5.16、6.6〜6.8、7.4、9.6
- **命題・系・補題:** 3.3、3.6〜3.9、4.9〜4.11、5.2、5.5、5.7〜5.9、5.11〜5.12、6.3〜6.5、7.2、7.3、7.6、9.5、9.7、10.1〜10.5、系2.17
- **第8節(実装についての注)、第10節(未解決問題)、付録の証明**
