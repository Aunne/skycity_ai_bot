# SkyCity Discord 顧問

Discord 只負責收發訊息；應用程式在本機保存每位玩家的對話、查詢結構化遊戲規則、搜尋攻略文件，再由 Ollama 產生回答。

## 架構

```text
Discord
  -> SkyCityAssistant
      -> SQLite (每位玩家記憶、結構化規則、語意索引)
      -> GameKnowledge (精確規則查詢 + 攻略語意檢索)
      -> OllamaClient (qwen3.5:4b)
```

## 設定

複製 `config.sample.yaml` 為 `config.yaml`，填入 Discord Bot Token。舊設定中的 `DIFY_API_KEY` 已不再使用。

將 Markdown 知識文件放進 `knowledge/documents`，或修改 `KNOWLEDGE_DOCUMENTS_PATH` 指向既有文件目錄。索引器同時相容舊的 `.txt`，新文件建議使用 `.md`。

## 本地模型

```cmd
ollama pull qwen3.5:4b
ollama pull nomic-embed-text-v2-moe
```

## 安裝與建立語意索引

```cmd
.\.venv\Scripts\pip3.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m skycity_bot.index_knowledge
```

文件內容異動後，重新執行索引命令。結構化寵物規則放在 `knowledge/structured.yaml`，不經向量搜尋。

## 執行

```cmd
.\.venv\Scripts\python.exe bot.py
```

Discord 文字指令：

- `顧問 <問題>`：回答並保存該使用者的對話記憶。
- `/test <問題>`：單次回答，不讀取或保存對話記憶。
- `/forget`：刪除發出指令者的所有對話記憶。
- `/inviteurl`：建立單次邀請連結。
- `/setPass @成員`：依既有權限規則授予身分組。

不啟動 Discord，直接測試本機問答：

```cmd
.\.venv\Scripts\python.exe -m skycity_bot.ask "道具店寵物 L5 的最高成長值是多少？"
```
