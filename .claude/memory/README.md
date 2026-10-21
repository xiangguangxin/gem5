# 项目记忆：有证据地积累，不自动改写规则

## 存储与信任等级

| 文件 | 内容 | 是否用于后续任务 |
|---|---|---|
| records.json | 候选、已接受、冲突、拒绝和退役记录，以及操作历史 | 仅 accepted 且证据仍有效的相关条目 |
| evidence/*.json | 从宿主运行字段提取的精简收据、评审回执 | 作为来源，不作为操作指令 |
| current-task.json | 最近任务的状态、阶段、文件范围和需求哈希 | 短期交接，不能自动续跑 |
| .lock | POSIX 文件锁 | 运行辅助，不入 Git |

当前采用 Python 标准库、JSON、原子替换和 POSIX fcntl 锁，适合本项目 WSL/Linux。不是向量数据库，也没有后台监听器；多个进程写长期记录会串行化，短期检查点保留最后写入者，尚未实现多任务看板。

## 三类长期知识

- fact：具体项目事实，附观察或机器输出。
- decision：已发生的设计选择、约束和理由，不能将建议冒充已批准决定。
- lesson：从实际结果提炼的经验，写明适用边界，不假定一次成功能普遍推广。

每条记录有 id、key、scope、kind、statement、tags、evidence、status、created、updated、review。key/scope 用于精确冲突检测；语义近似的不同 key 仍需要评审发现，不宣称自动识别所有矛盾。

证据格式：

```json
{
  "path": ".claude/workflows/evidence/2026-10-21-codex/result.json",
  "sha256": "实际文件的 SHA-256",
  "pointer": "/earlier_attempts/0/outcome",
  "value": "JSON pointer 指向的实际内容"
}
```

来源必须在项目内，脚本检查路径、文件指纹和对应值。它不执行证据里的命令，不访问外部 URL。文件整体改变，即使只增加无关字段，也会使旧指纹失效；这是保守策略，需要重新核对而非自动刷新。

## 生命周期

```text
提取结论 → candidate → 语义评审
                       ├─ approve 且无同 key/scope 条目 → accepted
                       ├─ approve 但存在同 key/scope 条目 → conflict
                       └─ reject → rejected

accepted → 来源变化/缺失 → 检索排除，inspect 显示 evidence_valid=false
accepted → 明确退役 → retired
```

相同内容与证据的重复提议复用 id，不追加副本。冲突不会覆盖旧条目；核对并 retire 旧条目后，可再次 review 冲突项。所有操作保留审计记录。

review 命令记录调用方声明的 reviewer 和理由，**不验证评审者身份**。这不是权限系统；不能仅靠填一个“独立评审者”名字就证明独立性。本项目的首批经验另保留真实 Codex 评审结果。

## 命令

在仓库根目录运行：

```bash
python3 .claude/skills/project-memory/scripts/project_memory.py query 'harness verifier 证据'
python3 .claude/skills/project-memory/scripts/project_memory.py inspect
```

将受信任的已验证运行转换成有限运行事实：

```bash
python3 .claude/skills/project-memory/scripts/project_memory.py harvest \
  .claude/workflows/evidence/2026-10-21-codex/result.json
```

harvest 只接受 done=true、status=verified 且 final_checks 全部退出 0 的记录，生成“这份记录中验收通过”的事实；不把提交者提供的 JSON 当作不可伪造的运行证明。它保存精简字段，不复制完整日志和任务文本。重复采集同份运行不会重复入库。

经验提议以 JSON 传入 propose，字段为 key、kind、statement、tags、evidence，可选 scope。证据可通过 Python API 的 Memory.evidence(path,pointer) 从实际文件生成。review 接口：

```bash
python3 .claude/skills/project-memory/scripts/project_memory.py review RECORD_ID \
  --verdict approve --reviewer '实际评审者或会话标识' --reason '证据为什么支持这个限定结论'
```

没有语义核对时不要执行 approve。拒绝使用 --verdict reject。退役使用 `retire RECORD_ID --reason '具体原因'`。

## 与 Harness 的连接

`codex-team.py` 命令行默认启用项目记忆：

1. 运行开始按 requirement 做有界关键词检索，最多 5 条、约 5000 字符，并保存本次 memory_context。
2. 各角色接收这些条目及来源，明确它们不是更高优先级指令。
3. 每次状态写入同步短期检查点，不复制用户原始需求文本，仅存文件范围和需求哈希。
4. verified 后提取机器字段事实。记忆写入失败记为 memory_warning，不把已失败任务改判成功。

`--no-memory` 可关闭；作为 Python API 直接构造 Runner 默认关闭，避免单元测试污染真实项目。记忆目录若位于任务工作区内部，则自动跳过以保持任务文件范围契约。当前任务状态仍完整保存在其 output/state.json。

语义经验的提炼/评审由 project-memory Skill 在适合的任务后执行；本版没有每次运行都额外调用模型的后台反思，也没有自动改写技能和客户端配置。

## 已验证范围

首批内容来自已提交的 Codex fixture 验收：一条有限运行事实、两条关于评审阶段及验证证据交接的经验。经验须经过真实独立会话评审后才进入 accepted；结果见 evidence 中回执。自动化测试还覆盖候选隔离、指纹变化、冲突与退役、坏文件保护及 Harness 接入。

知识文件可以随项目分享，提交前仍需检查是否包含不应公开的内容。当前实现用于积累可审查经验，不修改模型参数，也不保证每次检索都提高效果。
