# SkyCity 文檔問答顧問

把 Markdown (`.md`) 或純文字 (`.txt`) 文件放入 `knowledge/documents/`，即可透過本機 CLI 或現有 Discord 指令提問。一般事實只維護原始文件，不需要另寫寵物數值、匯率等領域專用 SQL 表或 YAML。SQLite 只保存對話記憶、文件版本與通用檢索區塊。

聊天模型維持呼叫設定的 Ollama API（可為 Ollama Cloud）；embedding 可留在本機 Ollama。文件內容會送到 **embedding API** 以建立索引，檢索到的原文片段會送到 **聊天 API** 產生一般問答。若使用遠端服務，請只將允許送往該服務的文件放入知識目錄。

## 設定

複製 `config.sample.yaml` 為 `config.yaml`，設定 API 端點、模型與 Discord Bot Token。API Key 建議放在 `OLLAMA_API_KEY` 環境變數。`KNOWLEDGE_DOCUMENTS_PATH` 可改成自己的文件目錄；相對路徑以專案根目錄為基準。

```yaml
OLLAMA_BASE_URL: "https://ollama.com"
OLLAMA_CHAT_MODEL: "gpt-oss:120b"
OLLAMA_EMBEDDING_BASE_URL: "http://127.0.0.1:11434"
OLLAMA_EMBEDDING_MODEL: "nomic-embed-text-v2-moe"
KNOWLEDGE_DOCUMENTS_PATH: "knowledge/documents"
KNOWLEDGE_TOP_K: 5
KNOWLEDGE_CONTEXT_CHARS: 6000
```

文件更新後執行索引命令，或直接使用 `ask.py`：它會先檢查文件雜湊，只重新索引新增或修改的文件，並移除已刪文件的索引。Bot 啟動時也會執行相同的增量檢查。更換 embedding 模型後會重建不相容的文件向量。索引失敗時保留該文件之前的有效版本，修正後重試即可。

```cmd
.\.venv\Scripts\pip3.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m skycity_bot.index_knowledge
.\.venv\Scripts\python.exe -m skycity_bot.ask "商寵 L5 最大成長值是多少？"
```

在 Windows cmd 若中文字顯示亂碼，先執行 `chcp 65001`，再加上 `-X utf8` 執行 Python。

## 文件寫法與回答

使用 Markdown 標題分章節，表格請用標準 Markdown 表格。索引保留章節、原文、行號與內容雜湊；長表格會分頁並重複欄名。檢索結合語意向量與字面線索，先找候選，再讀原文章節。精確識別字如 `L5` 必須在證據中出現。若答案缺少依據或來源互相衝突，顧問會說明，而不借用相近條目的數值。引用指向文件和行號；沒有可靠頁碼的文字文件不會顯示頁碼。

目前支援 UTF-8 Markdown 與文字。PDF、DOCX 與掃描文件尚未解析。一般問答仍受外部模型閱讀能力影響；程式會檢查引用是否存在、識別字及數字是否出現在引用原文，這不能取代語意正確性評估。

若要查看候選區塊、讀取範圍、版本、截斷狀態與問答耗時，執行 `skycity_bot.ask --debug "問題"`；Discord 執行時會寫入 `bot.log`。

## 測試與 Discord

```cmd
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe bot.py
```

本機問答只需 `skycity_bot.ask`，不必啟動 Discord。Discord 仍支援 `顧問 <問題>`、`/test <問題>`、`/forget`、`/inviteurl`、`/setPass @成員`。`/test` 不保存對話記憶。
