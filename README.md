# MangaTrans · 漫画汉化工作台

> English version: [jump to English](#english)

> 本地漫画文本翻译工具：解压 → 阅读 → 框选 → OCR / 翻译 → 改字 → 导出。
> 无需登录注册，支持本地模型与 10 家云端 API。

![Python](https://img.shields.io/badge/Python-3.12-blue)
![PySide6](https://img.shields.io/badge/PySide6-6.11-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

<img src="assets/icon_256.png" width="96" alt="MangaTrans icon">

---

## 目录

- [功能亮点](#功能亮点)
- [三个版本对比](#三个版本对比)
- [快速开始](#快速开始)
- [翻译模型](#翻译模型)
- [日文 OCR](#日文-ocr)
- [使用流程](#使用流程)
- [开源声明](#开源声明)
- [联系作者](#联系作者)

---

## 功能亮点

| 能力 | 说明 |
|---|---|
| **自动解压** | 拖入 `.zip` / `.cbz` 自动解压，按文件名自然排序（`page2 < page10`、`第2话 < 第10话`），GBK/Shift-JIS 老压缩包的中文名也能正确解出 |
| **阅读** | 左右翻页 / 上下翻页一键切换，滚轮缩放、拖拽平移、页码框直达 |
| **框选** | 左键长按 0.3 秒后拖动框选，可连续框多个，右击确认进入翻译面板 |
| **OCR** | 日文用 manga-ocr（自动把竖排气泡切成单列再逐列识别），中文/英文用系统 OCR |
| **翻译** | 本地 LM Studio / Ollama / llama.cpp 等，或 OpenAI / Claude / DeepSeek / Kimi / 通义千问 / 智谱 / MiniMax / Gemini / 硅基流动 |
| **实时指标** | 生成中显示供应商 › 模型 › 速度 › 首字延迟 |
| **排版** | 5 种填充形状（方形/圆角/椭圆/自定义描边/不填充）、字间距、行距、列间距、竖排、旋转、涂鸦补线 |
| **断点记忆** | 项目库自动记录页码与全部译文，每 10 分钟自动保存 |
| **导出** | 单页 / 整个文件夹 / 单个 ZIP |

### 界面语言

界面提供 **简体中文 / English** 两种语言，在 `设置 → 界面语言` 切换（重启后完全生效）。

- 按钮、菜单、面板标签等**界面部件**已双语化
- 帮助 / 关于 / 开源声明等**长文本**在弹窗内保持中英并列，避免维护两份长文案
- 翻译模型的**目标语言固定为简体中文**（这是产品设定，不是界面语言）

> 实现方式：`mangatrans/i18n.py` 内置 109 条词条的字典 + `tr()` 查表，
> 不依赖 Qt 的 .ts/.qm 工具链，改文案直接改 Python 字典即可。
> 未收录的字符串自动回退为中文原文，不会出现空白或 key 名。

---

## 三个版本对比

仓库提供三种打包形式，**功能完全相同**，区别只在体积与依赖方式。

### 1. 精简版 `MangaTrans.exe` —— ⭐ 推荐日常使用

| 项 | 值 |
|---|---|
| 体积 | **约 174 MB** |
| 日文 OCR | 通过外部 Python 调用（需本机装有 `pip install manga-ocr`） |
| 依赖 | 需要 Python + manga-ocr 才能识别日文；中/英可用系统 OCR |

**优点**

- 体积小、启动快
- 改 OCR 逻辑不用重新打包（`tools/ocr_worker.py` 是独立脚本）
- OCR 崩溃不会拖垮主程序（独立进程）

**缺点**

- 首次使用日文 OCR 需自己装 Python 包
- 换电脑要重新配置环境

**适合**：自己长期使用、会一点 Python 的用户。

---

### 2. 便携版 `MangaTrans-Portable.exe` —— ⭐ 推荐分发

| 项 | 值 |
|---|---|
| 体积 | **约 208 MB** |
| 日文 OCR | 同精简版（外部 Python） |
| 数据位置 | **全部在程序目录的 `data\` 内**，不写 `%APPDATA%` |

```
MangaTrans-Portable\
├─ MangaTrans-Portable.exe
├─ _internal\          运行库（Python + Qt，无需安装）
├─ portable.txt        便携标记
├─ 使用说明.txt
└─ data\              设置 / 进度 / 缓存（首次运行自动创建）
```

**优点**

- **免安装、免依赖**：目标机器不用装 Python 或任何运行库
- **数据自包含**：整个文件夹拷到 U 盘或另一台电脑就能继续用，进度不丢
- 不污染系统（不写注册表、不写 `%APPDATA%`）

**缺点**

- 体积比精简版大（多了运行库）
- 日文 OCR 仍需外部 Python（模型 400 MB 不内置）

**适合**：发给别人、在多台电脑间来回用。

---

### 3. 全内置 OCR 版 `MangaTrans-OCR.exe` —— 完全离线

| 项 | 值 |
|---|---|
| 体积 | **约 2.4 GB** |
| 日文 OCR | **完全内置**（PyTorch + manga-ocr + 词典） |
| 依赖 | **无**，只需模型权重（首次运行提示下载约 400 MB） |

**优点**

- **真正的开箱即用**：不需要 Python、不需要装任何包
- 日文 OCR 引擎随包发布，版本可控
- 配合本地翻译模型时**可全程离线**

**缺点**

- **体积巨大**（2.4 GB），不便分发
- 每次重新打包需 5–10 分钟
- 改一行 OCR 代码也要重打整包

**适合**：完全不懂技术的接收方、需要离线环境、或经常发给多人。

---

### 版本速查

| | 精简版 | 便携版 | 全内置 OCR 版 |
|---|---|---|---|
| 体积 | 174 MB | 208 MB | 2.4 GB |
| 免安装 | ❌ 需 Python | ✅ | ✅ |
| 日文 OCR 开箱可用 | ❌ | ❌ | ✅ |
| 数据自包含 | ❌ | ✅ | ❌ |
| 修改 OCR 无需重打包 | ✅ | ✅ | ❌ |
| **推荐场景** | 自己用 | 分发给人 | 完全离线/零基础用户 |

> **一句话建议**：自己用选**精简版**，发给别人选**便携版**；
> 只有对方完全不会装环境、或必须离线时，才用**全内置 OCR 版**。

---

## 快速开始

### 用源码运行

```bash
pip install PySide6 pillow requests zhconv
python main.py
```

日文 OCR 另需：`pip install manga-ocr`

> **关于三个 `.bat` 的编码**：批处理文件保存为 **GBK**，因为 `cmd.exe` 按原始
> 字节解析脚本，UTF-8 会让中文字节被截断、后半截当成命令名（实测会报
> `'到' is not recognized as an internal or external command`）。
> 代价是 **GitHub 网页预览会显示乱码**，这不影响功能 —— 下载到本机双击即可正常运行。
> 也可以直接用上面的 `python main.py` 启动，完全不经过 `.bat`。
>
> 另外这几个文件必须保持 **CRLF 换行**（仓库里由 `.gitattributes` 的 `*.bat -text`
> 锁定）。LF-only 的批处理在 `cmd.exe` 下会直接报错，实测 `'MangaTrans' 不是内部或
> 外部命令`。所以请**下载仓库 ZIP 或 `git clone`**，不要从网页复制粘贴脚本内容。

### 用 exe

双击 `MangaTrans.exe`（或便携版 / 全内置版）。日文 OCR 模型首次运行时会
提示下载（约 400 MB），可跳过并改用手打原文。

---

## 翻译模型

`设置 → 翻译模型 → 供应商`，共 16 个选项：

**本地运行时**（数据不出本机）

| 供应商 | 默认地址 |
|---|---|
| LM Studio | `127.0.0.1:1234/v1` |
| Ollama | `127.0.0.1:11434/v1` |
| llama.cpp server | `127.0.0.1:8080/v1` |
| KoboldCpp | `127.0.0.1:5001/v1` |
| MLX (Apple) | `127.0.0.1:8081/v1` |
| vLLM | `127.0.0.1:8000/v1` |

**云端 API**（需填 API Key）

OpenAI · Anthropic Claude · DeepSeek · Kimi · 通义千问 · 智谱 GLM ·
MiniMax · Google Gemini · 硅基流动 · 自定义（任意 OpenAI 兼容）

> 每个供应商的地址 / Key / 模型 / 温度**各自独立保存**，切换不会互相覆盖。
> API Key 只存在本机配置文件里，不会上传到任何地方。
>
> 本地运行时会自动探测相邻端口（LM Studio 端口被占时会换到 1235/1236）；
> 云端失败不会误连 localhost。

---

## 日文 OCR

| 引擎 | 语言 | 说明 |
|---|---|---|
| **manga-ocr** | 日文 | 漫画专用，竖排/手写体效果好；自动分栏 |
| Windows OCR | 中文简 / 英文 | 系统自带，无需安装 |
| 手动输入 | 任意 | 始终可用 |

**竖排分栏**：日文气泡常有多列竖排，整块丢给 manga-ocr 会**静默漏掉部分文字**
（实测三列只读出一列）。程序会先按墨迹投影切分单列，再按右→左顺序识别。

**模型下载**：权重不在包内，首次运行会提示下载（优先 `hf-mirror.com` 镜像）。
连不上时也可先设镜像再启动：

```bat
set HF_ENDPOINT=https://hf-mirror.com
MangaTrans.exe
```

---

## 使用流程

| 步骤 | 操作 |
|---|---|
| 打开 | 拖入 `.zip` / `.cbz`，或 `Ctrl+O` |
| 翻页 | `←` `→` / `PageUp` `PageDown` / 底部滑块 / 页码框 |
| 缩放 | 滚轮、`+` `−`、`Ctrl+9` 适应窗口、`Ctrl+0` 适应宽度 |
| 框选 | **左键长按 0.3 秒**后拖动；可连续框多处 |
| 确认 | **右击** → 翻译面板 |
| 批量 | 面板内「全部识别 / 全部翻译」，或概览列表逐个精修 |
| 撤销 | `Ctrl+Z` 翻译上一步 / `Alt+←` 视图上一步 |
| 导出 | `Ctrl+E` 当前页 / `Ctrl+Shift+E` 文件夹 / `Ctrl+Shift+Z` ZIP |
| 取消 | `Esc` 取消框选 / `Shift+Backspace` 撤销最后一个选区 |

---

## 开发

```bash
python tools/build_all.py          # 构建三个版本 + 自动校验
python tools/build_all.py --check  # 只校验已有构建
python tools/package_release.py    # 生成干净的发包目录 + 泄露审计
python tools/selftest.py           # 冒烟测试
```

`tools/` 下还有 17 个专项测试（翻页一致性、断点记忆、排版、供应商、
旋转、ZIP 导出、静音通知等），全部为无依赖的纯 Python 脚本。

---

## 开源声明

**MangaTrans 是开源免费工具**

- **无需登录 / 注册**，没有账号体系
- **不收集任何个人信息**，不含统计、埋点或自动更新上传
- 唯一需要配置的是翻译模型；用本地运行时数据不出本机
- 用云端 API 时，仅台词文本会发送到你选择的那家平台，Key 只存本机
- 配合本地 OCR + 本地模型时**可完全离线运行**

以 MIT 协议开源，详见 [LICENSE](LICENSE)。

---

## 联系作者

| | |
|---|---|
| 作者 | DeepSeek-V4.1-Flash-1017 |
| GitHub | [github.com/qqwq112112](https://github.com/qqwq112112) |
| 邮箱 | [qqwq112112@Outlook.com](mailto:qqwq112112@Outlook.com) |

欢迎提 Issue 反馈问题。报问题时请附上：

- 使用的供应商与模型名
- 错误日志（若有）：`%LOCALAPPDATA%\MangaTrans\cache\last_error.txt`
- 能复现问题的操作步骤

---
---

<a id="english"></a>

# MangaTrans · English

> A local manga text translation tool: extract -> read -> select -> OCR / translate
> -> re-letter -> export. No account required. Works with local models and 10 cloud APIs.

## Features

| Capability | Details |
|---|---|
| **Auto-extract** | Drop a `.zip` / `.cbz` and it unpacks automatically, sorted naturally (`page2 < page10`). GBK/Shift-JIS filename archives decode to correct CJK names |
| **Reading** | Toggle single-page / continuous scrolling, wheel zoom, drag pan, jump to page |
| **Selection** | Long-press 0.3 s then drag to draw a box; stack several; right-click to confirm |
| **OCR** | manga-ocr for Japanese (splits vertical columns automatically), Windows OCR for Chinese/English |
| **Translation** | Local LM Studio / Ollama / llama.cpp etc., or OpenAI / Claude / DeepSeek / Kimi / Qwen / GLM / MiniMax / Gemini / SiliconFlow |
| **Live metrics** | Shows provider / model / tokens-per-second / first-token latency while generating |
| **Typesetting** | 5 fill shapes (rect / rounded / ellipse / custom outline / none), letter spacing, line spacing, column gap, vertical writing, rotation, freehand strokes |
| **Resume** | Project library remembers page and every region; autosaves every 10 minutes |
| **Export** | Single page / folder / single ZIP |

### Interface language

The UI is available in **Simplified Chinese and English**, switched under
`Settings -> Language` (fully applied after a restart).

- Buttons, menus and panel labels are localised
- Long-form text (help / about / license) stays side-by-side bilingual inside the
  dialog, so there is only one copy to maintain
- The **translation target language is always Simplified Chinese** - that is a
  product decision, independent of the UI language

> Implemented with a 109-entry dict in `mangatrans/i18n.py` plus a `tr()` lookup,
> so no Qt .ts/.qm toolchain or build step is involved. Unmapped strings fall back
> to the Chinese source instead of showing blanks or raw keys.

---

## Three builds compared

All three builds have **identical features**; they differ only in size and how
they obtain their runtime.

### 1. Slim `MangaTrans.exe` — recommended for daily use

|  |  |
|---|---|
| Size | **~174 MB** |
| Japanese OCR | Delegated to an external Python (`pip install manga-ocr`) |
| Requirements | Python + manga-ocr for Japanese; system OCR covers Chinese/English |

**Pros**: small and quick to start; OCR logic can be changed without repackaging
(`tools/ocr_worker.py` is standalone); a crashing OCR process cannot take the UI down.

**Cons**: requires a Python install with manga-ocr; the environment must be set up
again on a new machine.

**Best for**: your own long-term use, if you are comfortable with Python.

### 2. Portable `MangaTrans-Portable.exe` — recommended for distribution

|  |  |
|---|---|
| Size | **~208 MB** |
| Japanese OCR | Same as slim (external Python) |
| Data location | **Everything under `data\` next to the exe**, never `%APPDATA%` |

**Pros**: **no install, no dependencies** (the target machine needs nothing
preinstalled); **self-contained data** (copy the folder to a USB stick or another PC
and keep going); leaves no trace in the system.

**Cons**: larger than the slim build; Japanese OCR still needs the external Python.

**Best for**: sending to others, or moving between several computers.

### 3. All-in-one OCR `MangaTrans-OCR.exe` — fully offline

|  |  |
|---|---|
| Size | **~2.4 GB** |
| Japanese OCR | **Fully bundled** (PyTorch + manga-ocr + dictionary) |
| Requirements | **None** — only the model weights (~400 MB, offered on first run) |

**Pros**: **truly zero-setup**; ships its own OCR engine so behaviour is
version-locked; runs **entirely offline** with a local translation model.

**Cons**: **huge** (2.4 GB); repackaging takes 5-10 minutes; even a one-line OCR
change requires a full rebuild.

**Best for**: non-technical recipients, offline environments, repeated distribution.

### Quick comparison

|  | Slim | Portable | All-in-one |
|---|---|---|---|
| Size | 174 MB | 208 MB | 2.4 GB |
| No install needed | No (needs Python) | Yes | Yes |
| Japanese OCR out of the box | No | No | Yes |
| Self-contained data | No | Yes | No |
| OCR editable without rebuilding | Yes | Yes | No |
| **Recommended for** | personal use | sharing | offline / zero-setup |

> **In one line**: use **Slim** for yourself, **Portable** to hand out, and
> **All-in-one** only when the recipient cannot install anything or must stay offline.

## Quick start

From source:

```bash
pip install PySide6 pillow requests zhconv
python main.py
```

For Japanese OCR: `pip install manga-ocr`

> **Note on the three `.bat` files**: they are stored as **GBK**, because `cmd.exe`
> parses batch scripts as raw bytes — UTF-8 turns the Chinese prompts into mojibake
> or outright errors (`is not recognized as an internal or external command`).
> The trade-off is that **GitHub's web preview shows them as garbled text**; the
> files still work fine once downloaded and double-clicked. You can also skip them
> entirely and launch with `python main.py` as shown above.
>
> These files must also keep **CRLF** line endings, enforced by `*.bat -text` in
> `.gitattributes`. LF-only batch files fail outright under `cmd.exe`
> (`'MangaTrans' is not recognized as an internal or external command`), so grab
> the repo **as a ZIP download or via `git clone`** rather than copy-pasting scripts
> from the web view.

From a build: run the exe. On first launch you are offered the ~400 MB Japanese OCR
model download; you can skip it and type source text by hand instead.

## Translation models

`Settings -> Translation model -> Provider`, 16 options.

**Local runtimes** (data never leaves the machine): LM Studio `127.0.0.1:1234/v1`,
Ollama `11434`, llama.cpp `8080`, KoboldCpp `5001`, MLX `8081`, vLLM `8000`.

**Cloud APIs** (key required): OpenAI, Anthropic Claude, DeepSeek, Kimi, Qwen,
Zhipu GLM, MiniMax, Google Gemini, SiliconFlow, Custom (any OpenAI-compatible).

> Base URL, key, model and temperature are stored **per provider**, so switching
> never overwrites another entry. Keys stay in the local config file and are never
> uploaded. Local runtimes probe neighbouring ports automatically (LM Studio moves
> to 1235/1236 when 1234 is taken); cloud providers never fall back to localhost.

## Japanese OCR

| Engine | Language | Notes |
|---|---|---|
| **manga-ocr** | Japanese | Best for manga; handles vertical text and handwriting |
| Windows OCR | Chinese (Simplified) / English | Built into Windows |
| Manual input | Any | Always available |

**Vertical columns**: Japanese bubbles often hold several vertical columns. Feeding a
whole bubble to manga-ocr **silently drops some of them** (measured: 3 columns, only 1
returned). The app splits columns by ink projection first, then reads them
right-to-left.

**Model download**: weights are not bundled; you are prompted on first run
(`hf-mirror.com` is tried first). Alternatively:

```bat
set HF_ENDPOINT=https://hf-mirror.com
MangaTrans.exe
```

## Workflow

| Step | Action |
|---|---|
| Open | Drop a `.zip` / `.cbz`, or press `Ctrl+O` |
| Navigate | `Left` `Right` / `PageUp` `PageDown` / slider / page box |
| Zoom | Wheel, `+` `-`, `Ctrl+9` fit window, `Ctrl+0` fit width |
| Select | **Long-press 0.3 s** then drag; stack multiple boxes |
| Confirm | **Right-click** to open the translation panel |
| Batch | "Translate all" in the panel, or per-region via the overview list |
| Undo | `Ctrl+Z` translation / `Alt+Left` view |
| Export | `Ctrl+E` page / `Ctrl+Shift+E` folder / `Ctrl+Shift+Z` ZIP |
| Cancel | `Esc` clear selection / `Shift+Backspace` undo last box |

## Development

```bash
python tools/build_all.py          # build all three + verify
python tools/build_all.py --check  # verify existing builds only
python tools/package_release.py    # clean release tree + leak audit
python tools/selftest.py           # smoke test
```

## Open source

**MangaTrans is free and open source**

- **No login / registration**, no accounts of any kind
- **No telemetry**: no analytics, no tracking, no auto-update uploads
- The only thing you configure is a translation model; local runtimes keep all data local
- With a cloud API, only the dialogue text goes to the provider you chose; the key
  stays in your local config
- Fully offline when paired with local OCR and a local model

Licensed under the MIT License, see [LICENSE](LICENSE).

## Contact

|  |  |
|---|---|
| Author | DeepSeek-V4.1-Flash-1017 |
| GitHub | [github.com/qqwq112112](https://github.com/qqwq112112) |
| Email | [qqwq112112@Outlook.com](mailto:qqwq112112@Outlook.com) |
