# Dialectical Argumentation Protocol Sequence Diagrams

## Figure 0: Computational Dialectics (Original — No Round Limit)

```mermaid
%%{init: {"sequence": {"width": 250, "actorMargin": 150, "noteMargin": 20}}}%%
sequenceDiagram
    participant AG1
    participant AG2

    loop Until no new argument can be constructed

        rect rgb(200,220,255)
            Note over AG1,AG2: Argumentation Phase

            AG1->>AG2: Main Argument A
            Note over AG1,AG2: Argumentation Model  Determine status of A
            alt A justified
                Note over AG1,AG2: Dialogue ends  A is the conclusion
            end

            AG2->>AG1: Main Argument A2
            Note over AG1,AG2: Argumentation Model  Determine status of A2
            alt A2 justified
                Note over AG1,AG2: Dialogue ends  A2 is the conclusion
            end
        end

        rect rgb(180,240,200)
            Note over AG1,AG2: Integration Phase
            Note over AG1,AG2: Specialization  Identify conditions each argument depends on
            Note over AG1,AG2: Generalization  Lift conditions into an abstract integrated rule
            AG1->>AG2: Share integrated rule
            AG2->>AG1: Share integrated rule
        end

    end
```

## Figure 1: Protocol Overview

```mermaid
%%{init: {"sequence": {"width": 250, "actorMargin": 150, "noteMargin": 20}}}%%
sequenceDiagram
    participant AG1
    participant AG2

    rect rgb(200,220,255)
        Note over AG1,AG2: Argumentation Phase

        loop Repeat up to max_turns rounds

            AG1->>AG2: Main Argument A
            Note over AG1,AG2: Argumentation Model  Determine status of A
            alt A justified
                Note over AG1,AG2: Dialogue ends  Adopt AG1 main argument as final answer
            end

            AG2->>AG1: Main Argument A2
            Note over AG1,AG2: Argumentation Model  Determine status of A2
            alt A2 justified
                Note over AG1,AG2: Dialogue ends  Adopt AG2 main argument as final answer
            end

        end
    end

    Note over AG1,AG2: Round limit reached

    rect rgb(180,240,200)
        Note over AG1,AG2: Integration Phase
        Note over AG1,AG2: Generalization  Abstract each warrant into a judgment criterion
        Note over AG1,AG2: Integration  Combine criteria into an integrated rule
        AG1->>AG2: Share integrated rule
        AG2->>AG1: Share integrated rule
    end

    Note over AG1,AG2: Back to AG1 Main Argument  next round starts

    Note over AG1,AG2: Generate provisional answer when overall limit reached
```

## Figure 2: Argumentation Model

### Figure 2a: Prior Work (Prakken & Sartor) — 既存研究

```mermaid
%%{init: {"sequence": {"width": 250, "actorMargin": 150, "noteMargin": 20}}}%%
sequenceDiagram
    participant Proponent
    participant Opponent

    Proponent->>Opponent: Main Argument A

    loop Until Opponent has no new defeating argument

        Opponent->>Proponent: Defeating Argument B  rebut or undercut A
        Proponent->>Opponent: Counter Argument C  rebut or undercut B
        Note over Proponent,Opponent: Verify B defeats A / C defeats B / B defeats C

    end

    Note over Proponent,Opponent: Determine status of A  justified / overruled / defensible
```

### Figure 2b: Proposed Method (this implementation) — 提案手法

```mermaid
%%{init: {"sequence": {"width": 250, "actorMargin": 150, "noteMargin": 20}}}%%
sequenceDiagram
    participant Proponent
    participant Opponent

    Proponent->>Opponent: Main Argument A

    loop Up to max_attack_attempts, or until Opponent has no new defeating argument

        Note over Proponent,Opponent: Check attempt count first  if exhausted, stop early as A defensible
        Note over Proponent,Opponent: If Opponent has no new B at all (regardless of count)  stop as A justified
        Opponent->>Proponent: Defeating Argument B  rebut or undercut A
        Proponent->>Opponent: Counter Argument C  rebut or undercut B
        Note over Proponent,Opponent: Verify B defeats A / C defeats B / B defeats C

    end

    Note over Proponent,Opponent: Otherwise, determine status of A  overruled / defensible
```

## Figure 3: MAD (Multi-Agent Debate)

```mermaid
%%{init: {"sequence": {"width": 250, "actorMargin": 150, "noteMargin": 20}}}%%
sequenceDiagram
    participant AG1
    participant AG2
    participant Judge

    AG1->>AG2: Initial Argument

    loop Repeat up to max_turns rounds
        AG2->>AG1: Argue against AG1
        AG1->>AG2: Argue against AG2
    end

    AG1->>Judge: Dialogue history
    AG2->>Judge: Dialogue history
    Note over Judge: Generate final answer from full dialogue
```

## Figure 4: Free Debate

```mermaid
%%{init: {"sequence": {"width": 250, "actorMargin": 150, "noteMargin": 20}}}%%
sequenceDiagram
    participant AG1
    participant AG2

    AG1->>AG2: Initial Argument

    loop Repeat up to max_turns rounds
        AG2->>AG1: Updated Argument  no direct counter
        AG1->>AG2: Updated Argument  no direct counter
    end

    Note over AG1,AG2: Round limit reached
    Note over AG1,AG2: Generate final answer from dialogue history
```
