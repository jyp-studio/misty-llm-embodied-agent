# 12 — 保留 Episode 內脈絡並在 Episode 間遺忘

**What to build:** 讓同一個 Episode 的 working context 保留名字、utterances、Tool calls 與
Observations，但在 Episode 完成後丟棄個人脈絡；下一個人的 Episode 從新的 Trigger Evidence 開始。

同時落實「不保存」的既定意思：原始影音與可識別 transcript 可在當次記憶體處理，也可將 bounded
selected Evidence 傳給 hosted providers，但不得寫入持久儲存或進入跨 Episode memory。

**Blocked by:** 08

**Status:** resolved

- [x] 同一 Episode 後續 Turns 能使用使用者剛提供的名字和前文
- [x] Episode 完成會清除 model working context、active Skill instructions、target 與個人 transcript
- [x] A 結束後 B 的新 Episode 不包含 A 的名字、utterances 或模型摘要
- [x] Cue queue 與 suppression 只保存短期匿名 token 和必要 timing，不升格為 personal memory
- [x] 真實圖片、音訊與可識別 transcript 不寫入專案檔案、cache、持久 Journal 或測試 artifact
- [x] bounded selected Evidence 可以送往 configured hosted ASR/VLM/LLM，並與持久保存政策分開說明
- [x] synthetic／授權 scenario assets 與預先產生的匿名 replay fixtures 可以明確標示後保存
- [x] Demo 當次可顯示必要資訊，但刷新或 run cleanup 後不恢復真實 personal payload
- [x] A→B 內建案例顯示同 Episode 記得、跨 Episode 遺忘的差異
- [x] tests 檢查 context cleanup、磁碟副作用、UI payload 與 hosted-boundary redaction

## Answer

`run_episode` 現在只維持當次 Episode 的 working context，Episode 結束後不寫入或帶入下一位互動者的名字、utterances、Skill instructions 或 model summary。原本的跨 Episode `Memory` 與其設定已移除；可選的持久 Journal 在寫入時保留控制流結構，但將個人話語與開放文字欄位替換為明確的 redaction marker。Demo 回應使用 `no-store`，A→B 情境並以當次 runtime 的 Journal 呈現 Episode 內保留與 Episode 間清除。

拒絕後的短期 Cue Suppression 只能保留匿名 track token 與 timing，實際 suppression 行為由 Ticket 13 負責；這裡不將它建模成個人記憶。
