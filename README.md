# Paper Daily

每天抓取 arXiv 最近论文，用 Codex 按个人兴趣进行语义筛选，并发布为 GitHub Pages 静态站点。

## 本地运行

```bash
cd submodule/paper-daily
python scripts/update.py                 # 使用已登录的 Codex CLI
python -m http.server 8000 -d site       # 打开 http://localhost:8000
```

无 Codex 或调试页面时可使用确定性的关键词降级模式：

```bash
python scripts/update.py --no-codex
```

兴趣、分类、阈值和每日入选数量都在 `config.json` 中配置。历史数据保存在
`site/data/papers.json`，同一 arXiv ID 不会重复。

## GitHub Pages 部署

1. 把本目录作为一个独立 GitHub 仓库推送（workflow 的相对路径按独立仓库设计）。
2. 在仓库 `Settings → Secrets and variables → Actions` 添加 `OPENAI_API_KEY`。
3. 在 `Settings → Pages → Build and deployment` 选择 **GitHub Actions**。
4. 手动运行一次 `Daily paper radar`，之后工作日北京时间 08:30 自动更新。

可选地添加 Actions variable `CODEX_MODEL` 指定模型；不设置则使用 Codex 默认模型。
如果 Codex 调用失败，流水线会记录原因并自动退化为关键词评分，站点仍会更新。

> arXiv API 请求使用明确 User-Agent、分类间隔 1 秒，并始终保留 arXiv ID 与原文链接。
