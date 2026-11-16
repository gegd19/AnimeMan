
# 🎌 AnimeMan · 番剧智能管家

<div align="center">

![AnimeMan Banner](https://via.placeholder.com/1200x300/2c7be5/ffffff?text=AnimeMan+·+让每一部番，终归此匣)

**🤖 AI 驱动的动漫媒体库全自动整理神器 · 专为 NAS 用户与二次元收藏家设计**

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1.3-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://hub.docker.com/)

[✨ 为什么选择 AnimeMan](#-为什么选择-animeman) • [🆚 对比同类项目](#-与同类项目的区别) • [🔧 失败处理对比](#-失败处理传统方法-vs-animeman) • [📦 实战案例](#-实战案例整理某科学的超电磁炮合集) • [🚀 快速开始](#-快速开始) • [📸 界面预览](#-界面预览)

</div>

---

## 🤔 你是否也经历过这些崩溃瞬间？

- 辛辛苦苦从网上拖了 **178 集《网球王子》BDRip**，文件名全是 `[压制组] Prince of Tennis [01][Ma10p_1080p].mkv`，手动改名改到怀疑人生？
- Emby / Jellyfin 刮削总是识别成奇怪的罗马音，海报牛头不对马嘴，媒体库乱七八糟？
- 特典、OVA、SP、NCED 散落各处，被 Emby 统统塞进 `S00E00`，找都找不到？
- 想保种又想让媒体库整洁美观，复制一份浪费空间，不复制 Emby 又扫不到？

**别慌，AnimeMan 就是来终结这一切的。**

---

## 🆚 与同类项目的区别

| 功能/特性 | AnimeMan | Sonarr/Radarr | FileBot | tinyMediaManager |
|-----------|:--------:|:-------------:|:-------:|:----------------:|
| **动漫文件名解析** | ⭐⭐⭐⭐⭐<br>内置 anitopy + 罗马数字转换 + 总集数换算 | ⭐⭐<br>对压制组命名支持较弱 | ⭐⭐⭐<br>需手动编写规则 | ⭐⭐⭐ |
| **AI 智能辅助** | ⭐⭐⭐⭐⭐<br>DeepSeek/OpenAI 驱动，自动修正解析失败的文件名 | ❌ | ❌ | ❌ |
| **硬链接保种** | ⭐⭐⭐⭐⭐<br>默认硬链接，跨盘自动降级符号链接 | ⭐⭐⭐⭐<br>支持硬链接但配置复杂 | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **特典/OVA 处理** | ⭐⭐⭐⭐⭐<br>可视化管理映射规则，一键归类 S00 | ⭐⭐⭐<br>需手动调整 | ⭐⭐⭐ | ⭐⭐⭐ |
| **移动端 Web 界面** | ⭐⭐⭐⭐⭐<br>专为手机优化，卡片化设计，躺沙发也能管理 | ⭐⭐⭐⭐<br>有移动端界面但体验一般 | ❌<br>无 Web 界面 | ⭐⭐⭐ |
| **字幕智能匹配** | ⭐⭐⭐⭐⭐<br>AI 分组匹配 + 自动调轴 | ⭐⭐⭐<br>需搭配 Bazarr | ❌ | ⭐⭐⭐ |
| **上手难度** | ⭐⭐⭐⭐⭐<br>Docker 一键部署，Web 界面配置，无需学习规则语法 | ⭐⭐⭐<br>配置项较多 | ⭐⭐⭐ | ⭐⭐⭐⭐ |

### 🎯 AnimeMan 更擅长的场景

- ✅ **你是 PT 玩家**：下载的动漫需要保种，又想让 Emby 完美刮削 → 硬链接模式两全其美
- ✅ **你收藏了大量动漫 BDRip**：文件名千奇百怪（`[VCB-Studio]`、`III`、`1072`）→ anitopy + AI 自动搞定
- ✅ **你经常在手机/平板上管理媒体库**：AnimeMan 的移动端界面专门优化，按钮大、卡片清晰
- ✅ **你不想学复杂的规则语法**：Web 界面点点按钮就能完成所有配置和修正
- ✅ **你有大量特典/OVA/SP 需要整理**：可视化映射规则，一键归类到 S00

### 🤝 更人性化的设计细节

- **失败缓存可视化**：处理失败的文件会集中展示，支持批量手动修正，而不是默默跳过
- **实时处理日志**：Web 界面实时滚动日志，出问题一目了然
- **引导式配置**：首次使用有教程横幅，一步步带你填写 TMDB Key、路径等必要信息
- **暂停日志功能**：日志滚动太快看不清？点击「暂停日志」慢慢查
- **双击停止任务**：Web 界面停止按钮支持双击强制重置，卡死也不怕

---

## ✨ 为什么选择 AnimeMan？

### 🧠 AI 大脑，看懂一切奇葩命名
- 纯数字 `1072.mkv`？方括号 `[11]`？罗马数字季号 `III`、`IV`？
- AnimeMan 调用 **DeepSeek / OpenAI** 大模型，像人类一样理解文件夹结构，自动换算总集数、识别正确的季和集。
- **动漫特化**：内置 anitopy 引擎，专为动漫文件名优化，压制组标签自动清洗。

### 🔗 NAS 党最爱的「硬链接」模式
- **不复制、不移动、不损坏做种**。通过硬链接在 Emby/Jellyfin 媒体库中生成文件入口，源文件继续保种上传。
- 跨盘自动降级为符号链接，并给出友好提示。Windows 开发者模式？没在怕，一键提示开启。

### 📺 Emby / Jellyfin / Plex 完美伴侣
- 自动生成 `movie.nfo`、`tvshow.nfo`、`episode.nfo`，刮削器直接读取，**100% 精准匹配**。
- 自动下载 TMDB 官方海报、背景图，你的媒体库从此颜值在线。

### 📝 字幕智能中心
- 自动扫描同目录及 `Subs/` 文件夹下的 `.ass`、`.srt` 字幕。
- **AI 分组匹配**：同一番剧的字幕文件，一次性批量关联到正确剧集，告别手动拖放。
- 支持 `ffsubsync` 自动调轴，日语字幕也能对得上嘴型。

### 📱 移动端友好，躺沙发上也能管理
- 响应式 Web 面板，手机、平板、电脑无缝切换。
- 失败缓存一键批量修正，**再也不用手动翻目录改文件名**。

### 🐳 为 NAS 量身打造的部署方式
- 提供 Docker Compose 一键部署，群晖、威联通、Unraid 通用。
- 源码运行支持 Python 虚拟环境，干净隔离不污染系统。

---

## 🔧 失败处理：传统方法 vs AnimeMan

即使是最智能的工具，也难免遇到无法自动处理的文件（例如 TMDB 无记录、文件名极度混乱）。这时候，如何处理失败项就成了区分工具好坏的关键。

### 😫 传统方法的痛苦

使用其他工具或手动整理时，你可能会经历以下流程：

1. 打开下载文件夹，找到那个处理失败的文件。
2. 手动分析文件名，猜测它应该是哪一季哪一集。
3. 打开 TMDB 网站，搜索剧集，找到正确的 TMDB ID。
4. 手动创建目标文件夹（如 `Season 03`）。
5. 手动复制/硬链接文件到正确位置，并重命名为 Emby 可识别的格式。
6. 如果有多个文件失败，重复以上步骤 N 次，每次都要切换窗口、复制粘贴。

**结果**：整理 10 个失败文件可能要花半小时，而且极易出错。

### 🚀 AnimeMan 的批量修正

AnimeMan 将这个过程简化为 **「所见即所得」的批量操作**：

1. **失败自动归类**：所有处理失败的文件会按文件夹聚合显示，一眼就知道哪些剧集出了问题。
2. **一键查看文件夹内全部文件**：点击「查看所有文件」，可以看到该文件夹下的所有视频文件（包括已成功和失败的），方便统一判断。
3. **智能排序与预览**：系统自动按文件名中的集号排序，并实时预览每个文件将被分配的集号（如 `1, 2, 3...`）。支持手动调整顺序（↑↓按钮）。
4. **内置 TMDB 搜索**：直接在弹窗内搜索 TMDB，选择正确条目后，系统自动获取该剧集的季集结构。
5. **绝对集数自动换算**：如果文件是总集数命名（如 `1072.mkv`），勾选「自动跨季换算」后，系统会自动计算正确的季号和季内集号。
6. **一键执行**：确认无误后，点击「开始批量修正」，系统会自动清理旧缓存、重新匹配、创建链接、生成 NFO，所有文件一次搞定。

### 📊 效率对比

| 场景 | 传统方法 | AnimeMan |
|------|---------|----------|
| 处理 10 个失败文件 | 约 30 分钟，需反复切换窗口 | **2 分钟**，在一个弹窗内完成 |
| 总集数换算（1072 → S21E08） | 手动计算或查表，易出错 | **一键自动换算** |
| 特典/OVA 归类 | 手动创建 S00 文件夹，逐个移动 | **映射规则自动归类** |
| 修改集数顺序 | 手动重命名文件 | **拖拽排序或点击上下移动** |

**这就是 AnimeMan 的核心理念：自动化能解决的问题绝不让你动手，实在需要你介入的，也尽量压缩到最少的点击次数。**

---

## 📦 实战案例：整理《某科学的超电磁炮》合集

假设你从 BT 站下载了《某科学的超电磁炮》全系列，目录结构如下：

```
/downloads/anime/[VCB-Studio] Toaru Kagaku no Railgun [Ma10p_1080p]/
├── [VCB-Studio] Toaru Kagaku no Railgun [01][Ma10p_1080p][x265_flac].mkv
├── [VCB-Studio] Toaru Kagaku no Railgun [02][Ma10p_1080p][x265_flac].mkv
├── ...
├── [VCB-Studio] Toaru Kagaku no Railgun S [01][Ma10p_1080p][x265_flac].mkv
├── [VCB-Studio] Toaru Kagaku no Railgun S [02][Ma10p_1080p][x265_flac].mkv
├── ...
├── [VCB-Studio] Toaru Kagaku no Railgun T [01][Ma10p_1080p][x265_flac].mkv
├── ...
├── [VCB-Studio] Toaru Kagaku no Railgun [OVA][Ma10p_1080p][x265_flac].mkv
└── [VCB-Studio] Toaru Kagaku no Railgun [NCED][Ma10p_1080p][x265_flac].mkv
```

### 1️⃣ 配置 AnimeMan

在 `auto_config.json` 中设置：

```json
{
  "source_folders": ["/downloads/anime"],
  "tv_target_folder": "/media/TV Shows",
  "movie_target_folder": "/media/Movies",
  "link_type": "hard",
  "tmdb_api": { "api_key": "你的TMDB密钥" },
  "ai_parser": { "enabled": true, "api_key": "你的AI密钥" },
  "ignore_patterns": ["NCED", "NCOP", "CM", "SPs"]
}
```

### 2️⃣ 添加特辑映射规则（可选）

为了正确处理 OVA 文件，在 Web 面板的「特辑/OVA 手动映射规则」中添加：

| 关键词 | TMDB ID | 类型 | 季号 | 集号 |
|--------|---------|------|------|------|
| `[OVA] 某科学的超电磁炮` | 4604 | tv | 0 | 1 |

### 3️⃣ 运行处理

点击「开始处理」，AnimeMan 将自动：
- 识别出《某科学的超电磁炮》第一季、第二季（S）、第三季（T）
- 将 OVA 归类到 S00E01
- 跳过 NCED 等特典文件
- 在 `/media/TV Shows/某科学的超电磁炮 (2009)/` 下创建标准目录结构

### 4️⃣ 最终输出

```
/media/TV Shows/
└── 某科学的超电磁炮 (2009)/
    ├── tvshow.nfo
    ├── poster.jpg
    ├── fanart.jpg
    ├── Season 01/
    │   ├── 某科学的超电磁炮 (2009) - S01E01 - 电击使.mkv
    │   ├── 某科学的超电磁炮 (2009) - S01E02 - 炎天下の撮影.mkv
    │   └── ...
    ├── Season 02/
    │   ├── 某科学的超电磁炮 (2009) - S02E01 - 超电磁炮.mkv
    │   └── ...
    ├── Season 03/
    │   └── ...
    └── Season 00/
        └── 某科学的超电磁炮 (2009) - S00E01 - OVA.mkv
```

此时刷新 Emby 媒体库，所有剧集已完美刮削，海报、简介、演员信息一应俱全。

---

## 🚀 快速开始（NAS 用户看这里）

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/gegd19/AnimeMan.git
cd AnimeMan
# 设置 UID/GID、媒体绝对路径和随机 SECRET_KEY，按 DEPLOYMENT.md 准备目录与认证
cp .env.example .env
vim .env
# 完成 DEPLOYMENT.md 的目录权限与配置步骤后启动
docker compose up -d --build
```

默认仅发布到 `http://127.0.0.1:8000`。远程使用前按 [部署说明](DEPLOYMENT.md) 启用认证并配置访问方式，填写 TMDB/AI Key 后保存。已有密钥不会回显，留空会保留；清除需使用对应复选框。

Compose 将配置、缓存、日志和字幕临时工作目录分别保存在 `./config`、`./cache`、`./logs`、`./work`，默认以 UID/GID 1000:1000 运行。示例中的 `SOURCE_FOLDERS`、`TV_TARGET_FOLDER`、`MOVIE_TARGET_FOLDER` 环境变量优先于配置文件，这三个路径会在界面中只读显示。若希望通过 Web 管理媒体路径，请移除这三项环境变量。

**升级已有容器前请先备份旧容器工作目录，勿直接删除旧容器。** 旧版本写在 `/app` 根目录的数据不会自动出现在挂载卷中。路径优先级、源目录数组格式、显式迁移和回滚步骤见 [运行数据与迁移说明](T04-NOTES.md)。健康检查使用不含业务数据的 `/healthz`。

### 方式二：源码运行（含虚拟环境教程）

#### 1. 克隆项目并创建虚拟环境
```bash
git clone https://github.com/gegd19/AnimeMan.git
cd AnimeMan

# 使用 Python 3.12 创建虚拟环境
python3.12 -m venv venv

# 激活虚拟环境 (Linux/macOS)
source venv/bin/activate

# 激活虚拟环境 (Windows PowerShell)
cmd
.\venv\Scripts\Activate.ps1

# 激活虚拟环境 (Windows CMD)
venv\Scripts\activate.bat
```

#### 2. 安装依赖
```bash
python -m pip install --require-hashes -r requirements.lock
```

#### 3. 配置文件
```bash
cp auto_config.json.example auto_config.json
vim auto_config.json  # 填写 TMDB API Key 和路径
```

#### 4. 启动！
```bash
python web_app.py
```
访问 `http://127.0.0.1:8000`。入口使用单进程 Waitress；不要使用多 worker。停机、目录权限、锁定依赖和回滚见 [DEPLOYMENT.md](DEPLOYMENT.md)。

---

## 🔍 命令行预览与全量处理

```bash
# 模拟：只读取和生成计划，不写配置、缓存、媒体、元数据或字幕
python main.py --config /绝对路径/auto_config.json --dry-run
# 强制重新处理所有扫描到的文件，保留未扫描项目历史并保存本次结果
python main.py --config /绝对路径/auto_config.json --force-full
# 模拟修复已有库缺失的元数据
python main.py --config /绝对路径/auto_config.json --dry-run --force-full --repair
```

CLI 覆盖值只影响本次运行，不改写配置文件。模拟仍可能查询 AI/TMDB 等外部 API，也会输出日志，因此不代表离线运行。目标冲突和不安全旧记录仍会被拒绝。Web 中开启模拟模式后，整理、纠错和字幕整理返回计划；配置保存、显式缓存管理及离线缓存扫描是独立操作。[完整契约与测试记录](T05-NOTES.md)。

## ⚙️ 配置核心项速览

| 配置项 | 必填 | 说明 |
|--------|:----:|------|
| `tmdb_api.api_key` | ✅ | 去 [TMDB](https://www.themoviedb.org/settings/api) 免费申请 |
| `source_folders` | ✅ | 你的下载目录，例如 `/downloads/anime` |
| `tv_target_folder` | ✅ | Emby 剧集库路径，例如 `/media/TV Shows` |
| `movie_target_folder` | ✅ | Emby 电影库路径，例如 `/media/Movies` |
| `ai_parser.enabled` | ❌ | 开启 AI 解析，强烈推荐！ |
| `ai_parser.api_key` | ❌ | DeepSeek 等 API Key（新用户有免费额度） |
| `link_type` | ❌ | 默认 `hard`，同盘保种最优解 |
| `ignore_patterns` | ❌ | 跳过包含这些关键词的文件/目录 |

---

## 📸 界面预览

### 桌面端

**主控制面板**

<img width="2542" height="1352" alt="桌面控制面板" src="https://github.com/user-attachments/assets/628e5794-50ff-40cd-85f7-f9b861f592db" />

**失败缓存管理**

<img width="1568" height="1151" alt="失败缓存管理" src="https://github.com/user-attachments/assets/e990039a-0d19-4c3f-b7ca-6dfb7f597569" />

**批量手动修正**

<img width="1937" height="1141" alt="批量手动修正" src="https://github.com/user-attachments/assets/68e1403c-26dd-4cb5-a5d8-461ded88690a" />

**媒体库管理界面**

<img width="2478" height="1295" alt="桌面媒体库管理界面" src="https://github.com/user-attachments/assets/4553413d-5797-4eb6-9671-b786b5a6b394" />

### 移动端

**手机控制面板**

<img width="1096" height="2560" alt="手机控制面板" src="https://github.com/user-attachments/assets/19cb163a-3494-4b75-941b-9aa61c2dcc95" />

**手机媒体库管理界面**

<img width="1096" height="2149" alt="手机媒体库管理界面" src="https://github.com/user-attachments/assets/fb3d93b9-29df-4e30-9301-36f5282dc4aa" />

---

## 🧩 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3, Flask, requests, anitopy |
| 前端 | 原生 JavaScript (模块化), CSS3 Grid/Flex |
| AI | DeepSeek / OpenAI / 智谱 / 通义千问 |
| 元数据 | TMDB API v3 |
| 字幕同步 | ffsubsync, pysubs2 |
| 部署 | Docker, Docker Compose |

---

## 任务运行与停止

同一服务进程一次接受一个写任务，覆盖整理、纠错、删除、字幕写入及离线扫描/解析。运行或停止过程中发起其他写任务会收到 HTTP 409；仍可读取状态和保存配置，保存的新配置用于下一任务。

点击停止后会显示“正在停止”，直到工作线程退出才可启动新任务。正在执行的网络请求或字幕子进程可能需要等待现有超时。界面保留最终成功/失败计数和日志；双击停止不再强制清空活任务状态。API 客户端可在 `/api/stop?task_id=...` 携带启动时返回的 ID，避免停止过期任务。`force=1` 仅能清理无活线程的残留状态。

该互斥只在单进程内有效；请由一个写进程管理同一媒体库。验证与回滚见 [T06-NOTES.md](T06-NOTES.md)。

---

## 缓存与失败重试

缓存采用同目录临时文件与原子替换，内部按记录更新。已有缓存损坏时保留原文件、创建 `.corrupt-*.bak` 并报错，不自动清空；旧失败项首次重新评估前创建 `.t07-*.bak` 完整备份。

默认增量运行对临时网络失败最多尝试 3 次，后续任务在 60/120 秒退避到期后重试。无匹配、无效输入和冲突在文件/相关配置不变时不自动重试。`--force-full` 可主动重新评估；`no_retry=true` 的人工保留项继续跳过。人工纠错显示“人工确认”，不再以 100% 代表未知算法评分。

新增字段、可选策略、测试与恢复步骤见 [T07-NOTES.md](T07-NOTES.md)。

---

## NFO 与元数据修复

单集 NFO 与实际视频同名，自动整理、人工纠错和 repair 共用路径规则。repair 可补齐电影、剧集、季和每一集的 NFO，以及图片；可先运行 `python main.py --config /path/to/auto_config.json --repair --dry-run` 查看计划，再执行实际修复。

NFO 和图片经过解析/解码验证并原子写入。显式修复替换无效旧文件前创建 `.t08-*.bak`；可解析的自定义 NFO 保持原样。普通整理发现同名无效元数据时会提示先修复。源路径、同 inode 冲突和缺少季/集信息会报告问题，不猜测或覆盖视频。

新增 Pillow 依赖，请重新安装 requirements.txt。完整测试、兼容与恢复说明见 [T08-NOTES.md](T08-NOTES.md)。

---

## 特典扫描与未知集号

`scan_policy.include_specials=true` 可开启默认特典扫描；启用的明确映射也可放行匹配文件。`scan_policy.exclude_patterns` 与文件名 `ignore_patterns` 优先，菜单/CD 等其他无关目录仍跳过。主扫描和离线扫描采用同一规则。未确定的集号保留 unknown，不默认整理为第一集。完整规则见 [T09-NOTES.md](T09-NOTES.md)。

---

## AI 解析与缓存

AI 返回值经过类型、季集号和输入文件标识校验；未知信息交给回退，不默认第一集。文件夹每批最多 30 个实际文件，未覆盖项单独列出，部分结果不计完整成功。同目录同配置请求共享结果，缓存随文件、解析配置及规则版本变化失效；旧解析缓存更新前创建 `.t10-*.bak`。

新长剧结果使用 `files/unparsed_files`，不再把少量样本宏观推断当作全目录解析完成。完整验证、迁移与回滚说明见 [T10-NOTES.md](T10-NOTES.md)。

---

## 字幕处理安全

调轴在独立临时目录中处理副本，保留源字幕和语言后缀；同步结果在临时目录清理前复制到媒体库。覆盖字幕会原子替换目标目录项，避免写穿旧硬链接或软链接。字幕发现按字面文件名前缀匹配，支持带 `[Group]` 的文件名。

批量改名先校验整批，限定配置的源目录及字幕扩展名；重复源/目标、已有目标、源符号链接、依赖及循环改名均拒绝，并返回逐项原因。跨文件系统改名失败时保留源文件。完整契约、测试和回滚说明见 [T11-NOTES.md](T11-NOTES.md)。

---

## 前端渲染与请求错误

文件路径、标题、失败原因和 AI 文本通过 DOM 文本/属性显示；动态操作使用事件监听器及闭包或 dataset 传递原值，避免引号、反斜杠和 HTML 实体改变路径。HTTP 401 提示重新认证，409 提示冲突，500 显示服务器错误，失败响应不会进入正常成功分支。

新增真实 Chromium 回归，页面 API 全部拦截为 mock，不连接真实媒体库。运行方式见 [TESTING.md](TESTING.md)，本卡范围、验证与回滚见 [T12-NOTES.md](T12-NOTES.md)。

---

## 输入与配置校验

接口先检查 JSON 对象、数组规模、路径字符串、数值范围及真正的布尔值，再进行业务处理；不把 `"false"` 当作布尔值。分页 `page` 从 1 开始，`per_page` 为 1–200，批量数组最多 1000 项，请求体上限 4 MiB。非法参数返回 JSON 400，超大请求 413，缺记录 404，任务或关键词冲突 409。

配置加载使用独立的深复制默认值。损坏 JSON、重复字段、错误配置类型或悬空配置链接会阻止业务访问，不自动回退为关闭认证的默认配置；可读取的损坏原件保留并生成私有 `.t13-invalid-*.bak`。配置与映射更新在同一锁内验证后原子写入，失败保留旧配置。完整范围、兼容变化和恢复方式见 [T13-NOTES.md](T13-NOTES.md)。

---

## 媒体身份与派生缓存

海报地址按媒体类型区分，例如 `/media_poster/movie/7` 与 `/media_poster/tv/7`。旧数字地址仅在当前处理记录中无类型歧义时兼容，否则返回 409。电影与 TV 不再因相同数字 ID 共用海报。

媒体库和海报索引以处理缓存为准，成功提交记录后标记过期；刷新完成后才原子发布完整新快照。旧派生缓存升级前生成 `.t14-*.bak`，预览不写派生文件。明确删除记录会移出索引；暂时缺失的目标仍保留离线信息并标记 `target_exists=false`。完整验证和回滚说明见 [T14-NOTES.md](T14-NOTES.md)。

---

## 🙋 常见问题

**Q：我下载的文件在多个硬盘上，能用硬链接吗？**
A：硬链接仅限同一分区。跨盘会自动尝试符号链接，并在 Web 界面提示。建议将下载盘与媒体库盘设置在同一分区。

**Q：AI 解析会花很多钱吗？**
A：DeepSeek 等大模型新用户通常有免费额度，文件夹批量解析模式能大幅节省 Token。单文件解析成本极低。

**Q：为什么有些特典还是被识别为 S01E01？**
A：你可以在「特辑/OVA 手动映射规则」中添加关键词规则，强制指定 TMDB ID 和季/集号。OVA、SP 等将自动归类到 S00 季。

**Q：支持 Windows NAS 吗？**
A：完全支持。源码运行或 Docker Desktop 均可。注意 Windows 下符号链接可能需要开启「开发者模式」。

---

## 🤝 贡献

欢迎提交 Issue 与 PR！如果你有更好的动漫文件名样本，也欢迎提交供 AI 训练参考。

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

<div align="center">
  <strong>🎌 AnimeMan · 让每一部番，终归此匣</strong>
  <br>
  <sub>Made with ❤️ for NAS & Anime Lovers</sub>
</div>
