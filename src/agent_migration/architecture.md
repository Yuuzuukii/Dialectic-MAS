# 設計

# DialecticalProtocol

## エージェントが持つメソッド
- main_argument()
- attack()
- integrate()
- final_answer()


## ジャッジが持つメソッド
- can_undercut()

## 全体
- run()

if 上限/2に達したか == true:
    ⭐️4へ
else:
    // ag1の主張ターン
    ag1の主張A1 = main_argument(ag1) #⭐️0
    if ag1の主張A1 == "できない":
        ⭐️4へ # ag2の主張ターンへ

    // ag2の反論ターン
    ag2の反論B1 = attack(ag2, ag1の主張A1) #⭐️1

    if ag2の反論B1 == "rebut":
        A1はB1をundercutできるか = can_undercut(judge, ag1の主張A1, ag2の反論B1)
        if A1はB1をundercutできるか == true: #B1はA1をdefeatできない
            ⭐️1へ
    if ag2の反論B1 == "できない":
        ⭐️7へ #A1はjustified


    // ag1の反論ターン
    ag1の反論A2 = attack(ag1, ag2の反論B1) #⭐️2

    if ag1の反論A2 == "rebut":
        B1はA2をundercutできるか = can_undercut(judge, ag2の反論B1, ag1の反論A2)
        if B1はA2をundercutできるか == false: # A2はB1をdefeatできない
            ⭐️2へ
        if B1はA2をundercutできるか == true: # A2がB1をdefeat
            A2はB1をundercutできるか = can_undercut(judge, ag1の反論A2, ag2の反論B1) # B1は必ずA2をrebutするので、その判定は入れずに、defeat条件である、A2がB1をundercutできないかを見る
                
            if A2はB1をundercutできるか == false: # B1もA2をdefeat
                ⭐️2へ
                
    if ag2の反論A2 == "できない":
        if すでに1回以上B1に対し反論を作ったか == true:
            ⭐️4へ # A1はdefensible
        else:
            ⭐️4へ # A1はoverruled

    if ag1の反論A2 == "undercut": # A2がB1をdefeat
        B1はA2をundercutできるか = can_undercut(judge, ag2の反論B1, ag1の反論A2)
        if B1はA2をundercutできるか == true: # B1もA2をdefeat
            ⭐️2へ


    // ag2の反論ターン
    ag2の反論B2 = attack(ag1, ag1の反論A2) # ⭐️3
    if ag2の反論B2 == "rebut":
        A2はB2をundercutできるか = can_undercut(judge, ag1の反論A2, ag2の反論B2)
        if A2はB2をundercutできるか == true:
            ⭐️3へ
    if ag2の反論B2 == "できない": # A2はB1をstrictly defeat
        ⭐️1へ
    
    // ag1の反論ターン
    ag1の反論A3 = attack(ag1, ag2の反論B2)
    if 
