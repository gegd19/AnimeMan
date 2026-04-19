# 🎌 AnimeMan · 番剧智能管家

<div align="center">

![AnimeMan Banner](https://via.placeholder.com/1200x300/2c7be5/ffffff?text=AnimeMan+·+让每一部番，终归此匣)

**🤖 AI 驱动的动漫媒体库全自动整理神器 · 专为 NAS 用户与二次元收藏家设计**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://hub.docker.com/)

[✨ 为什么选择 AnimeMan](#-为什么选择-animeman) • [🚀 快速开始](#-快速开始) • [📸 界面预览](#-界面预览) • [📖 完整文档](#-配置说明)

</div>

---

## 🤔 你是否也经历过这些崩溃瞬间？

- 辛辛苦苦从网络上下载了 100多集的番剧BDRip**，文件名全是 `[压制组] Prince of Tennis [01][Ma10p_1080p].mkv`，手动改名改到怀疑人生？
- Emby / Jellyfin 刮削总是识别成奇怪的罗马音，海报牛头不对马嘴，媒体库乱七八糟？
- 特典、OVA、SP、NCED 散落各处，被 Emby 统统塞进 `S00E00`，找都找不到？
- 想保种又想让媒体库整洁美观，复制一份浪费空间，不复制 Emby 又扫不到？

**别慌，AnimeMan 就是来终结这一切的。**

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

## 🚀 快速开始（NAS 用户看这里）

### 方式一：Docker Compose（推荐）

```bash
# 下载项目
git clone https://github.com/gegd19/AnimeMan.git
cd AnimeMan

# 修改 docker-compose.yml 中的挂载路径（将 /path/to/... 替换为你 NAS 上的实际路径）
vim docker-compose.yml

# 准备配置文件
cp auto_config.json.example auto_config.json
# 编辑 auto_config.json，至少填写 tmdb_api.api_key 和路径

# 启动！
docker compose up -d
```

浏览器访问 `http://你的NAS_IP:8000`，开始配置。

### 方式二：源码运行（含虚拟环境教程）

#### 1. 克隆项目并创建虚拟环境
```bash
git clone https://github.com/gegd19/AnimeMan.git
cd AnimeMan

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境 (Linux/macOS)
source venv/bin/activate

# 激活虚拟环境 (Windows PowerShell)
.\venv\Scripts\Activate.ps1
```

#### 2. 安装依赖
```bash
pip install -r requirements.txt
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
访问 `http://127.0.0.1:8000`。

---

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

## 🙋 常见问题

**Q：我下载的文件在多个硬盘上，能用硬链接吗？**  
A：硬链接仅限同一分区。跨盘会自动尝试符号链接，并在 Web 界面提示。建议将下载盘与媒体库盘设置在同一分区。

**Q：AI 解析会花很多钱吗？**  
A：DeepSeek 等大模型新用户通常有免费额度，文件夹批量解析模式能大幅节省 Token。单文件解析成本极低（约 0.001 元/次）。

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
