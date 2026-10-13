# gem5 学习路线：从最小系统到 NPU/SoC 性能分析

> 本路线面向已有 C++ / Python 基础、希望从事 ESL 建模与 SoC/NPU 架构分析的学习者。
> 配套入口：[learning_gem5 导航](learning_gem5/README.md)。命令以仓库根目录为工作目录。
> 适用范围：当前仓库的教学源码与配置；构建能力以实际 build 配置为准。路线中的新增设备、实验与 NPU 集成均为待完成任务，不代表仓库已有实现。

## 1. 目标与边界

最终交付一个可复现的 CPU + NPU + 共享内存性能实验平台：CPU 能提交任务，NPU 能搬运数据并完成计算，结果可校验，性能变化有统计与模型解释。

先建立可信的最小闭环，再增加模型细节。默认从 X86、SE、TimingSimpleCPU、Classic 内存系统开始；已有 ARM/RISC-V 软件栈时可以换 ISA，但必须同步替换程序与配置。

- SE 适合用户态程序和微基准。真实驱动、操作系统中断及完整软件栈验证通常需要 FS。
- SE 下访问设备不能假定普通用户态指针自动对应 MMIO 物理地址，需要显式处理映射或使用仿真侧测试驱动。
- Classic 可以构建一致性多核系统。Ruby/Garnet 在研究具体协议或详细片上网络时加入，不是接入 NPU 的必经前提。
- gem5 并不自动提供目标芯片的精确性能或能耗；精度取决于模型、参数、负载及校验。

## 2. 路径与依赖

```text
A 最小系统与配置
  → B 内存实验与测量方法
  → C SimObject / Event / Port 开发
  → D MMIO 与 DMA 设备
  → E SystemC 最小事务闭环
  → F NPU 接入、校验与 DSE

B → CPU 深入分支：Minor / O3
C → 一致性分支：MSI / Ruby → Garnet / NoC
```

事件学习应早于异步端口开发；设备测试应早于完整 NPU 接入；模型校验应早于大规模参数扫描。

## 3. 阶段 A：最小系统与配置（1～2 周）

**前置**：会基本 Linux 命令、Python 和 C++ 编译；理解地址、缓存和时钟的基本含义。

**阅读**：[最小系统](learning_gem5/part1/minimal_system.md)、[添加缓存](learning_gem5/part1/cache.md)。

**任务**：

1. 记录仓库 commit、构建配置、ISA 与编译器；运行 `simple.py` 和 `two_level.py`。
2. 画出 CPU、端口、交叉开关、Cache、MemCtrl、DRAM 的连接；区分 SimObject 的 Python 配置层和 C++ 实现层。
3. 在 `config.ini` / `config.json` 中找到实际生效的时钟、容量、地址范围；在 `stats.txt` 中找到仿真时间与指令计数。
4. 区分 functional、atomic、timing 访问：功能性访问、原子式延迟估计、异步时序交互不能当成同一精度的实验。

**交付与验收**：保存两次运行的命令、退出原因、配置和统计；能解释增加缓存为什么可能改变性能。hello 只验证系统通路，不用于评价缓存收益。

## 4. 阶段 B：内存实验与可信测量（2～3 周）

**前置**：完成 A，能独立定位配置对象。

**阅读**：[实验与统计方法](learning_gem5/experiments/README.md)、[benchmark 与指标笔记](gem5_benchmark_and_stats.md)。

**任务**：

- 使用顺序流、随机指针追逐、不同工作集大小三类微基准，分别观察吞吐、依赖访问延迟和容量边界。
- 固定负载与 CPU，分别改变 Cache 容量、相联度、MSHR 数量，分析 miss、排队及访存并行度。
- 区分 SimpleMemory 的抽象延迟/带宽参数与 DRAM 控制器的通道、时序、队列、地址映射；不能把所有内存模型当成同一个“带宽旋钮”。
- 明确测量区间（ROI）、预热、统计重置与转储；建立单变量基线，再做联合扫描。

**交付与验收**：至少三组对照曲线、原始统计和一份瓶颈解释。能区分“请求量”“实际传输字节”“有效数据量”，并用理论上限检查带宽结果。

### CPU 深入分支（按研究问题选修，2～4 周）

TimingSimpleCPU 是使用 timing 内存访问的简单顺序模型，不用于详细流水线研究。MinorCPU 用于研究顺序流水线；O3CPU 用于研究乱序执行及其与内存并行性的相互作用。

阅读 O3 时沿 Fetch → Decode → Rename → IEW（Issue/Execute/Writeback）→ Commit 理解流程，重点识别 ROB、IQ、LSQ、分支预测及错误路径恢复。用计算密集与内存密集负载比较 CPU 模型；改变模型前确认 ISA、配置与工作负载兼容。

**验收**：能解释 CPU 模型改变后，内存带宽需求和 IPC 为什么变化，而不是仅比较速度。

## 5. 阶段 C：真正修改模型（2～3 周）

**阅读顺序**：

1. [SimpleObject](learning_gem5/part2/simple_simobject.md)：Python 声明、C++ 类、生成参数、SConscript。
2. [事件与调试](learning_gem5/part2/stats_output.md)：Event、startup、tick、退出与 DPRINTF。
3. [SimpleMemobj](learning_gem5/part2/simple_memobj.md)：请求/响应、拒绝与 retry。
4. [SimpleCache](learning_gem5/part2/simple_cache.md)：ClockedObject、向量端口、缓存与统计。

**任务**：新增一个参数控制的延迟转发对象，支持 timing 请求、响应以及两侧背压；增加接受/完成计数、忙碌时间和延迟统计。先画状态机，再写实现。

**交付与验收**：代码变更、配置脚本和验证记录。零负载结束时接受数等于完成数；人为制造下游阻塞后没有丢包、重复响应或死锁；参数改变能产生预期的时序变化。需要 functional/atomic 时明确实现，不支持的模式应清晰报错。

## 6. 阶段 D：MMIO 与 DMA 设备（2～3 周）

**阅读**：[设备开发任务书](learning_gem5/part4/device_model.md)。

**任务**：先实现 SRC/DST/LEN/START/STATUS 寄存器与固定处理延迟，再实现内存到内存 DMA，最后加入分块与有限 outstanding。计算逻辑先用拷贝或确定性的简单运算。

**交付与验收**：地址映射、寄存器规范、设备状态机、测试配置和统计；能校验输出，处理忙时提交、无效参数及背压；证明所有 DMA 完成后才报告任务完成。

## 7. 阶段 E：SystemC 最小闭环（2～4 周）

**前置**：理解 D 的控制/数据路径；掌握 SystemC 进程、事件、时间及 TLM 基础。

**阅读**：[联合仿真接入指南](learning_gem5/part4/systemc_integration.md)。

**任务**：选择仿真内核归属，运行仓库内已有示例；分别验证 gem5 请求到 TLM target，以及 TLM initiator 到 gem5 内存。对照 Packet 与 payload 的地址、命令、长度、响应和生命周期。

**交付与验收**：一笔和多笔事务日志、延迟对照、读写结果；覆盖背压及错误响应，并确认时间单位转换。通过后再替换成 NPU 模块。

## 8. 阶段 F：NPU 接入与设计空间探索（3～5 周）

**阅读**：[NPU/DSE 实验任务书](learning_gem5/part4/npu_dse.md)、[现有集成方案](gem5_npu.md)。后者中的外部项目版本与完成状态需要在实际接入时重新核实。

**任务**：

1. 固定一个 GEMM，记录输入、输出与精度规则，建立独立模型参考结果。
2. 打通提交 → DMA 读入 → 计算 → DMA 写回 → 完成通知；明确共享内存与非一致性 DMA 的数据可见性策略。
3. 分别校验计算、SRAM、DMA 与内存模型，再验证端到端结果。
4. 扫描阵列规模、SRAM、DMA 并发度、内存配置；先单变量，再有限组合。
5. 在约束下比较时延、吞吐、利用率及 Pareto 候选；只有具备能耗参数与计算方法时才报告能耗。

**交付与验收**：可重复运行的最小平台、参数清单、正确性记录、原始数据、图表和瓶颈报告；至少解释一次瓶颈从计算转向内存或反向转移。

## 9. Ruby / Garnet 分支（4～6 周，可独立安排）

先回答研究问题：需要协议状态机、共享数据争用、通信网络拥塞中的哪一项？

- [MSI 基础](learning_gem5/part3/msi.md) → [Ruby/SLICC](learning_gem5/part3/ruby_slicc.md) → [Cache 控制器](learning_gem5/part3/cache_controller.md) → [目录控制器](learning_gem5/part3/directory_controller.md) → [构建运行](learning_gem5/part3/config_and_run.md)。
- Ruby 包含控制器、协议与网络；不要把它理解成 Classic L1 后面额外串接的一个部件。
- 先用共享读、交替写、false sharing 验证协议行为，再研究 NoC。
- Garnet 实验从合成流量入手，扫描注入率并找出饱和点；比较拓扑时控制节点数、链路宽度、频率、路由、VC 与缓冲深度，并说明资源预算差异。

**验收**：能追踪一次所有权转移；能解释网络负载、排队和吞吐随注入率的变化。合成流量结果不能直接代替实际 NPU 应用结论。

## 10. 时间与完成标准

以下按每周约 15～20 小时、已有 C++ 与基础体系结构知识估计，包含阅读与实验，不包含大型软件栈移植。

| 里程碑 | 累计工作量 | 可展示成果 |
|---|---|---|
| A～B | 3～5 周 | 最小系统、内存实验报告 |
| A～D | 7～11 周 | 可验证的自定义设备与 DMA |
| A～F | 12～20 周 | SystemC/NPU 闭环与初步 DSE |
| 加入 CPU/Ruby/NoC 深入研究 | 约 5～8 个月总周期 | 有明确研究问题的架构分析报告 |

三个月的合理目标是完成设备与最小接入闭环；完整 NPU 校验和深入架构探索视已有模型成熟度继续推进。阶段验收未通过时先缩小系统、定位问题，不靠增加组件弥补缺口。
