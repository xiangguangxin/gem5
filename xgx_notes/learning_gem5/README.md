# learning_gem5 学习导航

这里保存面向当前仓库的源码阅读笔记与工程练习。整体目标、时间和验收见[学习路线](../gem5-learning-roadmap.md)。已有 Part 1～3 以教学源码解析为主；新增实验与 Part 4 是待实现任务书。

## 推荐阅读顺序

| 顺序 | 主题 | 文档 | 仓库入口 |
|---|---|---|---|
| 1 | 最小配置 | [最小系统](part1/minimal_system.md) | `configs/learning_gem5/part1/simple.py` |
| 2 | 两级缓存 | [Cache](part1/cache.md) | `configs/learning_gem5/part1/two_level.py` |
| 3 | 测量方法 | [实验规范](experiments/README.md) | `src/mem/SimpleMemory.py`、`src/mem/MemCtrl.py` |
| 4 | 对象开发 | [SimpleObject](part2/simple_simobject.md) | `src/learning_gem5/part2/` |
| 5 | 异步事件 | [事件与调试](part2/stats_output.md) | `hello_object.cc`、`goodbye_object.cc` |
| 6 | 内存端口 | [SimpleMemobj](part2/simple_memobj.md) | `simple_memobj.cc` |
| 7 | 简化缓存 | [SimpleCache](part2/simple_cache.md) | `simple_cache.cc` |
| 8 | 设备练习 | [MMIO/DMA](part4/device_model.md) | `src/dev/io_device.hh`、`src/dev/dma_device.hh` |
| 9 | 事务桥接 | [SystemC](part4/systemc_integration.md) | `src/systemc/tlm_bridge/` |
| 10 | 最终项目 | [NPU/DSE](part4/npu_dse.md) | [现有方案](../gem5_npu.md) |

事件机制详解：[事件、调度器与 EventQueue](part2/event_mechanism.md)，整理回调包装、时间推进、链表结构及同组事件的 LIFO 顺序。

Part 2 文件名称保留兼容原链接；`stats_output.md` 主要讲事件和调试，应在端口开发前阅读。真正的统计练习结合 SimpleCache 与实验规范进行。

## 一致性研究分支

[MSI](part3/msi.md) → [Ruby/SLICC](part3/ruby_slicc.md) → [Cache 控制器](part3/cache_controller.md) → [目录控制器](part3/directory_controller.md) → [配置运行](part3/config_and_run.md)。

这些教学示例用于理解机制，不能直接作为高性能缓存或量产协议实现。源码行数、现有 build 能力及外部链接可能变化，阅读时以当前源码和构建配置为准。

## 如何记录学习成果

每个练习保留：研究问题、代码/配置变更、运行命令、退出原因、原始输出、分析和限制。使用[实验记录模板](experiments/report_template.md)，输出写入独立目录，避免覆盖默认 `m5out`。脚本跑完并不等于验收通过，先检查正确性再讨论性能。

## 实验编号与执行方式

每章末尾的“分步实验/练习”是操作入口；先读本章概念，再按编号执行。顺序如下：

| 顺序 | 实验 | 核心因果链 | 完成后能做什么 |
|---|---|---|---|
| 1 | A1 最小系统 | 配置 → 实例 → 运行输出 | 证明参数生效 |
| 2 | A2 Cache | 容量 → 命中/流量 → 时间 | 解释缓存收益 |
| 3 | [B 内存微基准](experiments/memory_lab.md) | 固定负载 → 单变量 → 统计校验 | 做可信对照实验 |
| 4 | C1 对象 | Python 声明 → 构建 → C++ 实例 | 修改并编译模型 |
| 5 | C2 事件 | 调度 → 回调 → 再调度/退出 | 表达未来动作 |
| 6 | C3 端口 | 接受/拒绝 → retry → 响应 | 处理异步事务 |
| 7 | C4 简化缓存 | hit/miss → 整块访问 → 统计 | 连接模型行为与指标 |
| 8 | D 设备 | PIO 提交 → DMA → 写回 → 完成 | 实现最小加速器接口 |
| 9 | E SystemC | 两个方向分别验证 → 接入模块 | 校验桥接语义与时间 |
| 10 | F NPU/DSE | 正确性 → 分层校验 → 参数扫描 | 形成架构结论 |
| 选修 | R1～R5 Ruby | 权限 → 状态机 → 跨控制器消息 → 测试 | 研究一致性 |

A/B 和 C1/C2/C4 的默认运行使用已有代码；C3 的延迟扩展、B4 ROI 与 D/E/F 的新增能力需要实现。R1～R4 以推演与源码追踪为主，R5 才运行完整协议。

所有相对路径命令从仓库根目录执行。练习脚本复制到原配置同目录，保证 import 与测试程序相对路径不变；后缀用 `_lab.py`，不要覆盖基线。Python 配置修改一般重新运行即可，C++/参数声明/SConscript 修改后需要重建。

每一步按“操作 → 预期 → 实际观察 → 解释”记笔记。预期不符合时先查正确性、实际配置和统计口径，再提出新的模型假设；不要连续调整多个参数直到数字看起来合理。
