# gem5 + NPU 性能模型 集成方案

> NPU 模型仓库：https://github.com/xiangguangxin/npu-perf-model
> gem5 版本：stable (25.1.0.1)，已编译 X86（含 SystemC/TLM 支持）

---

## 1. 目标（研究问题）

把自研的 NPU 性能模型接入 gem5，实现一个 **CPU + NPU + DRAM** 的 SoC 级仿真，
做 NPU 的**设计空间探索（DSE）**。

### 系统拓扑

```
                 ┌───────────┐
                 │   CPU     │
                 │  ARM/RISC-V
                 └─────┬─────┘
                       │
                  System Bus
                       │
          ┌────────────┴────────────┐
          │                         │
       Memory                     NPU
          │                         │
       DRAM                  ┌──────┴──────┐
                             │   PE Array  │
                             │   SRAM      │
                             │   DMA       │
                             └─────────────┘
```

### 设计空间（旋钮）

| 旋钮 | 取值 |
|------|------|
| NPU 数量 | 1 / 2 / 4 / 8 |
| Memory Bandwidth | 50 / 100 / 200 GB/s |
| NPU 算力 | PE 阵列规模 × 频率 × dataflow → 算 TOPS |

### 最终指标

Latency / Throughput / **Utilization** / Energy

---

## 2. 现状

### 2.1 NPU 模型（npu-perf-model）

- **技术栈**：C++17 + SystemC 2.3.x + TLM2.0（Accellera 开源版，vendored）+ CMake
- **抽象层次**：cycle-approximate（近似周期级，非 RTL、非纯解析）
- **数据流**：weight-stationary 脉动阵列
- **模块**：
  - `PE Array`：fill / steady / drain 三阶段 timing
  - `Onchip Buffer`：容量 + 带宽双约束的片上 SRAM timing
  - `DMA Engine`：TLM AT initiator（四相协议 + PEQ）
  - `Interconnect`：仲裁器（**MVP-4，未实现**）
  - `Memory`：HBM 抽象，AT target（延迟 + 带宽）
  - `Workload Driver`：GEMM tiling + 调度 + double buffering
  - `Perf Monitor`：吞吐 / 利用率 / arithmetic intensity → CSV
- **配置**（`NpuConfig`）：`array_n=16`、`buffer_kb=256`、`buf_bw=64B/cyc`、
  `hbm_bw=256GB/s`、`hbm_lat=100cyc`、`dma_outstanding=4`、`data_bytes=1`
- **Workload**（`GemmTask`）：M / K / N
- **当前拓扑**：`DmaEngine.isock ──nb_transport(4-phase AT)──► Memory.tsock`

### 2.2 gem5 侧

- gem5 自带完整 **SystemC + TLM2.0** 支持，位于 `src/systemc/`。
- `USE_SYSTEMC` 默认开启（`Kconfig: default y`）；**当前 X86 build 已编译进去**
  （`build/X86/systemc/` 下含 95 个目标文件，含 `tlm_bridge/tlm_to_gem5.o`）。
- 关键桥接 SimObject（`src/systemc/tlm_bridge/TlmBridge.py`）：
  - `TlmToGem5Bridge64/32/128/256/512`：`tlm`（TLM target socket）+ `gem5`（RequestPort）
  - `Gem5ToTlmBridge*`：反方向（gem5 → TLM）

---

## 3. 对接方案（核心 seam）

**思路：扔掉 NPU 模型自带的 `Memory`（HBM 桩），让 DMA 直接读/写 gem5 的内存系统。**

```
【现在】
  DmaEngine.isock ──nb_transport(4-phase AT)──► Memory.tsock     ← 自带的 HBM 桩

【目标】
  DmaEngine.isock ──nb_transport(4-phase AT)──► TlmToGem5Bridge.tlm   ← gem5 TLM 桥
                                                       │
                                                gem5 的 RequestPort
                                                       │
                                                membus → MemCtrl → DRAM   ← gem5 真实内存
```

- NPU 侧的 **PE Array / Buffer / WorkloadDriver / DmaEngine 全部原样保留**，
  只有最后 `dma.isock.bind(...)` 一行，从 `mem.tsock` 换成 gem5 桥的 target socket。
- 附带好处：roadmap 里「Memory Bandwidth」这个旋钮，正好落到 gem5 的 `MemCtrl`/DDR
  配置上，不必再在 HBM 桩里手调。

---

## 4. 分阶段实施计划

| 阶段 | 内容 | 产出 | 工作量 |
|------|------|------|--------|
| **P0** | 独立 build 通 npu-perf-model + 跑通 sanity 测试；顺手验证 SystemC 兼容性 | 基线可运行 | 小 |
| **P1** | 把模型代码编译进 gem5（新建 SConscript，参照 `src/learning_gem5/part2`）；重构 `sc_main` 为 gem5 可调用的 SystemC 模块入口 | gem5 内可实例化 NPU | 中 |
| **P2** | config 里实例化 `TlmToGem5Bridge64`，`dma.isock` 绑到桥上，桥的 gem5 端口接 membus→DRAM；跑 **NPU-only** 的 GEMM | NPU↔gem5内存端到端 | 中 |
| **P3** | 加 CPU（X86/ARM/RISC-V），CPU offload GEMM 给 NPU，凑成完整 SoC | 完整 SoC DSE 平台 | 大 |

> 建议顺序：P0 → P1 → P2 先跑通「NPU 经 gem5 内存做 GEMM」的最小闭环，再上 P3。

---

## 5. 风险

1. **SystemC 内核差异（最大风险）**：模型 vendored 的是 Accellera SystemC 2.3.x，
   gem5 用的是自己改过的内核（`src/systemc/`）。模块（`simple_initiator_socket`、
   `peq_with_cb_and_phase` 等）大概率兼容，但需对着 gem5 头文件重编，可能有零星 API 差异。
2. **`sc_main` 重构**：`main.cpp` 里的 `sc_main()` 是独立程序入口，gem5 走的是
   `SystemC_Kernel` + `m5.systemc.sc_main()`，组装拓扑那部分要搬进去。
3. **时钟对齐**：模型 `CLK_FREQ_HZ = 1e9`、`cycles(n)` 换算 sc_time，要和 gem5 tick（1ps）对齐。
4. **桥的 AT 兼容性**：DMA 是严格四相 AT（BEGIN_REQ/END_REQ/BEGIN_RESP/END_RESP）+ PEQ，
   需实测 `TlmToGem5Bridge` 的 target 侧是否按此协议应答。
5. **Energy 建模**：gem5 本身不输出能耗，需补一层（活动计数 × 单操作能耗 / McPAT / SMAUG 能量模型）。

---

## 6. 待定决策

- [ ] **代码位置**：NPU 模型代码拷进 gem5 源码树（如 `src/learning_gem5/npu/`），
      还是保留独立 repo 只做接口对接？
- [ ] **范围**：先 NPU-only（P1→P2），还是一开始就上 CPU+NPU 完整 SoC（P3）？
- [ ] **Workload**：跑哪些 GEMM/网络层？（Utilization 对 layer shape 极敏感，需先定负载）
- [ ] **Baseline**：DSE 的参照系（CPU-only？1×NPU@50GB/s？）
