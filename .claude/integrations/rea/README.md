# REA 与本仓库的集成

REA（Reverse Engineer Anything）用于分析交付二进制、软件包和应用行为，不是绘图引擎。本目录把其官方分析 Skill 融入现有 .claude 工作流，没有把整套 TypeScript 工程复制进 gem5，也没有修改 gem5 构建。

## 已整合与尚未启用

| 项目 | 状态 |
|---|---|
| 官方 reverse-engineer-anything Skill 及六份按需参考 | 已纳入 .claude/skills |
| gem5 场景分流与证据记录约定 | 已提供，见下方 |
| 环境检查脚本 | 已提供；检查不会下载软件或执行目标 |
| Node/npm、REA CLI、原生分析引擎 | 未由本次整合安装 |
| MCP 运行时连接 | 未注册；Skill 文件存在不代表工具已连接 |

截至本次核对，当前 shell PATH 中未发现 node、npm 或 claude，不能声称 REA 已可运行。其他终端可能使用不同 PATH，应重新检查。

## 适用场景：什么时候用 REA

| 任务 | 优先方案 |
|---|---|
| 阅读 gem5 C++、Python、SLICC，解释状态机 | rg、源码及现有技术文档流程；不启动 REA |
| 分析无源码的 guest ELF、交付库，比较二进制版本 | REA 的二进制工作流；按任务需要配置 Ghidra/Hopper/IDA 等引擎 |
| 分析 JS/Electron 交付包 | REA 的 JavaScript 工作流，不要求原生反编译引擎 |
| 绘制架构图、状态图 | technical-diagrams；REA 只提供分析证据，不负责绘图 |
| 跟踪 gem5 仿真时间与协议行为 | gem5 debug flag、ProtocolTrace、stats；REA 不能替代仿真器 |

`tests/test-progs/...` 下的 guest 程序可能是 x86/ARM 等目标架构，不等于宿主机可直接运行。先做静态分析；执行目标、调试附加和外部服务访问应限于用户明确的任务范围。

## 使用流程

1. 读取 [官方 Skill](../../skills/reverse-engineer-anything/SKILL.md)，按目标类型选择相关参考，不一次性加载全部参考。
2. 普通源码问题直接读源码。只有问题需要二进制或运行时证据，才选 REA。
3. 若已连接，按当前工具列表和 schema 调用，不凭 Skill 文本假设某工具必然存在。
4. 记录目标绝对路径、SHA-256、架构、REA 版本和分析引擎，区分观察、推断、未解决问题。保存结论时引用源码位置或 Evidence ID。
5. 将确认后的组件/事务关系交给 technical-diagrams 制图；静态推断不能标成“实际运行已观测”。

调用示例：

> 使用 .claude/skills/reverse-engineer-anything/SKILL.md，静态分析这个 guest ELF 的函数与依赖，给出证据和限制；不要运行它。

## 本地检查：不改变环境

在仓库根目录执行：

```bash
python3 .claude/integrations/rea/check_environment.py
```

输出为 JSON。退出码 0 表示检查脚本完成，不表示 REA/MCP 就绪；看 runtime_prerequisites_found、node_version_supported 和各项结果。只检查 PATH、版本及 ps 兼容性，不下载 npm 包，不检查全盘客户端配置，不运行目标。

## 可选的项目范围 MCP 接入

以下命令是接入说明，**本次未执行**。先具备 Node 和 npm，以及 Claude Code；核对上游固定版本 package.json 的 engines。同步时上游版本为 6.7.0，要求 Node ^22.19.0、^24.11.0 或 >=26.0.0，不能只看 Node 主版本。

在希望启用的 gem5 仓库目录运行上游文档提供的 local-scope 注册命令：

```bash
claude mcp add --scope local rea -- npx -y rea-agents@6.7.0 mcp
claude mcp list
```

该命令会下载 npm 包并修改当前用户的 Claude 项目本地注册；只在用户要求实际启用工具时执行。它不需要将 MCP 凭据或 .mcp.json 提交到仓库，也不会自动安装 Ghidra。Windows 原生终端需要按上游说明使用 cmd.exe 包装，WSL 使用 Linux 命令。

重启/重连对应项目会话后，以会话实际出现的工具为准。doctor 对用户级注册的报告不代表 local-scope 注册已可用；上游注明其 doctor/uninstall 不管理此项目本地注册。

撤销此本地注册（需用户要求）应在同一项目目录使用：

```bash
claude mcp remove --scope local rea
```

不要为项目接入直接运行会改用户级配置的全客户端 setup。需要 REA CLI 诊断或某个分析引擎时，按官方 Skill 的按需恢复指南处理，避免对普通源码问题无条件运行 setup/doctor。

## 来源、许可证与更新

- 上游：https://github.com/morluto/rea
- 固定源码提交：a5f982de8dbe4b092cc20ab89d492b7e7028b758
- 上游 package.json：6.7.0；Skill metadata.version：44
- 同步日期：2026-10-21
- 复制范围：`.agents/skills/reverse-engineer-anything/`，本地副本保持原文；另有独立项目说明和检查脚本。
- 上游 MIT 许可证保留于 [LICENSE](LICENSE)。各参考中的工具名和使用约束以该提交为准，不能假定 npm 发布包与 main 完全相同。

上游依据：[固定版本安装指南](https://github.com/morluto/rea/blob/a5f982de8dbe4b092cc20ab89d492b7e7028b758/docs/installation.md)、[版本与运行时要求](https://github.com/morluto/rea/blob/a5f982de8dbe4b092cc20ab89d492b7e7028b758/package.json)。

更新时在临时目录获取指定提交，仅比较并同步该 Skill 子树，保留本地集成说明；重新核对许可证、工具要求和参考链接，再更新来源信息。不要自动覆盖既有客户端配置或安装无关上游开发技能。上游的 CI、changelog、tool-design 等技能专为开发 REA 本身，本次未引入。
