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

- NPU 侧的 **PE Array / Buffer / WorkloadDriver / DmaEngine 的核心 timing 逻辑保留**，
  但需要补齐真实 DMA payload、真实地址生成，并把独立 `sc_main()` 拆成 gem5 可实例化的
  NPU SimObject / SystemC 模块。
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

---

## 7. 基于当前 npu-perf-model 的架构审查结论

结论：**总体方向可行，但 P1/P2 不能只理解成“换一行 bind”**。当前
`npu-perf-model` 是 timing-only 的独立 SystemC 程序，接入 gem5 真实内存系统前，
需要把几个简化假设补成显式架构设计。

### 7.1 必须改：DMA payload 不能再用 1 字节 dummy

当前 `DmaEngine::submitTransfer()` 里使用：

```cpp
static unsigned char dummy[1] = {0};
gp.set_data_ptr(dummy);
gp.set_data_length(bytes);
```

这个在自带 `Memory` 模型里能跑，是因为 `Memory` 只看 `data_length` 做时序，
不真正读写 `data_ptr`。

但 gem5 的 `TlmToGem5Bridge` 会把 TLM payload 转成 gem5 `Packet`，并使用
`trans.get_data_ptr()` 作为 packet 数据指针：

```cpp
pkt->dataStatic(trans.get_data_ptr());
```

所以接 gem5 真实内存后，`data_ptr` 必须至少有 `bytes` 长度，否则读写大块 tile
时会有功能错误甚至内存越界风险。

建议：

- `Transfer` 内部持有 `std::vector<unsigned char> data;`
- `submitTransfer()` 按 `bytes` 分配 data buffer
- `gp.set_data_ptr(transfer->data.data())`
- timing-only 模式可以不关心内容，但 buffer 生命周期必须覆盖到 `END_RESP`

### 7.2 必须改：地址模型不能都打到 0

当前 `WorkloadDriver` 的访存地址都是 0：

```cpp
dma_->read(/*addr=*/0, bytes, kind, tid);
dma_->write(/*addr=*/0, bytes, TileExtension::OUTPUT, tid);
```

异步接口 `issue_read()` / `issue_write()` 也没有地址参数，内部固定传 `addr=0`。

这对独立 HBM timing 模型没问题，因为它只统计 bytes 和 latency；但对 gem5 内存系统，
地址会影响：

- memory range 是否合法
- cache line 映射
- bank/channel 映射
- Ruby directory 映射
- 多 NPU 是否访问同一片地址
- CPU/NPU 共享内存一致性

建议新增显式地址布局：

```text
A_base / B_base / C_base
tile_addr(kind, i, j, k)
```

并修改 DMA API：

```cpp
TransferPtr issue_read(uint64_t addr, uint32_t bytes, Kind kind, uint32_t tile_id);
TransferPtr issue_write(uint64_t addr, uint32_t bytes, Kind kind, uint32_t tile_id);
```

P2 的 NPU-only 可以先用简单线性地址；P3 的 CPU+NPU 必须和 CPU 侧分配/传参一致。

### 7.3 必须改：独立 sc_main 要拆成可被 gem5 实例化的模块

当前顶层在 `src/main.cpp` 中：

```cpp
Memory         mem("mem", cfg);
OnchipBuffer   buf("buf", cfg);
DmaEngine      dma("dma", cfg);
PeArray        pe("pe", cfg);
WorkloadDriver drv("drv", cfg, task, &dma, &buf, &pe);
dma.isock.bind(mem.tsock);
sc_start();
```

接入 gem5 后，`sc_start()` 应由 gem5 的 `SystemC_Kernel` 驱动，NPU 不应再作为独立
可执行程序的 `sc_main()` 自己启动仿真。

建议拆成：

```text
NpuTop : sc_module
  - OnchipBuffer
  - DmaEngine
  - PeArray
  - WorkloadDriver
  - 对外暴露 dma.isock
```

独立 repo 仍保留 `main.cpp` 做 standalone 测试；gem5 侧使用 `NpuTop` 或 gem5
SimObject wrapper 来实例化。

### 7.4 P2 建议先走 classic memory，不要一开始上 Ruby coherent

如果目标只是先跑通：

```text
NPU DMA -> TlmToGem5Bridge64 -> membus -> MemCtrl -> DRAM
```

可以先用 classic memory system，避开 CPU cache coherence。

如果 P3 要做：

```text
CPU cache + NPU DMA 共享内存
```

就必须明确一致性策略：

- 非一致性 DMA：CPU 通过 cache flush/invalidate 或 uncached memory region 配合
- Ruby DMA controller：把 NPU DMA 请求接进 Ruby 协议路径
- coherent IO：让 NPU 请求参与系统一致性

否则 CPU cache 可能持有旧数据，NPU 写 DRAM 后 CPU 读不到最新结果。

### 7.5 `hbm_bw` 旋钮要决定由谁负责

当前 NPU 模型里 `Memory` 用 `hbm_bw_GBps` 和 `hbm_lat_cyc` 建模 HBM 时序。
如果 P2 扔掉自带 `Memory`，改走 gem5 `MemCtrl`，那么内存带宽/延迟应该主要由
gem5 内存配置决定。

建议拆分语义：

| 参数 | 归属 | 作用 |
|------|------|------|
| `buf_bw_Bpc` | NPU 模型 | 片上 SRAM/NoC 到 PE 的内部带宽 |
| `dma_outstanding` | NPU 模型 | DMA 发起端并发窗口 |
| `hbm_bw_GBps` | standalone 模式 | 自带 Memory 桩的带宽 |
| gem5 MemCtrl 参数 | gem5 模式 | 真实 DRAM 带宽和延迟 |

这样避免 standalone 模型和 gem5 memory 同时限制带宽，导致重复建模。

### 7.6 P1/P2 推荐调整后的最小闭环

新的推荐顺序：

1. **P1a：保留 standalone npu_sim**，继续用自带 `Memory` 做 sanity baseline。
2. **P1b：抽出 `NpuTop`**，去掉对 `sc_main()` 的强依赖。
3. **P1c：修 DMA payload buffer**，保证 `data_ptr` 长度等于 `data_length`。
4. **P1d：加入 tile 地址生成**，不再所有访问都使用地址 0。
5. **P2a：gem5 内实例化 `SystemC_Kernel` + `NpuTop` + `TlmToGem5Bridge64`。**
6. **P2b：NPU-only 连接 classic membus/DRAM**，先看 gem5 `stats.txt` 中的内存请求。
7. **P2c：对齐 standalone Memory 与 gem5 MemCtrl 的 latency/bandwidth，做误差检查。**
8. **P3：再加入 CPU offload 和一致性策略。**

### 7.7 修改后的架构图

P2 推荐目标：

```text
             gem5 Python config
                    │
             SystemC_Kernel
                    │
          ┌─────────▼─────────┐
          │      NpuTop       │
          │  WorkloadDriver   │
          │  PeArray          │
          │  OnchipBuffer     │
          │  DmaEngine        │
          └─────────┬─────────┘
                    │ TLM initiator socket
                    ▼
          TlmToGem5Bridge64.tlm
                    │ gem5 RequestPort
                    ▼
              membus / xbar
                    │
                  MemCtrl
                    │
                   DRAM
```

P3 加 CPU 后：

```text
CPU ── cache hierarchy ─┐
                        ├── shared memory system ── DRAM
NPU ── TLM bridge ──────┘

关键问题：CPU cache 与 NPU DMA 是否一致？
```

### 7.8 最终判断

原方案的方向是对的：**NPU 保留 PE/Buffer/DMA/Driver，末端通过 gem5 TLM bridge 接入
gem5 内存系统**。

但架构需要补上四个硬要求：

1. DMA payload 必须有真实 `bytes` 长度的 data buffer。
2. WorkloadDriver 必须生成真实 tile 地址。
3. 独立 `sc_main()` 必须拆成 gem5 可实例化的 NPU top/module。
4. CPU+NPU 阶段必须明确 DMA 与 CPU cache 的一致性策略。

---

## 8. 方案 A：gem5 SimObject wrapper + SystemC NpuTop

### 8.1 方案 A 的核心思想

方案 A 不再把 NPU 当成一个独立 `sc_main()` 程序跑，而是把它做成 gem5 正规组件：

```text
Python config
    |
    | 创建 gem5 SimObject
    v
NpuDevice : gem5 SimObject
    |
    | C++ 内部持有
    v
NpuTop : sc_module
    |
    | TLM initiator socket
    v
TlmToGem5Bridge64 : gem5 自带桥
    |
    | RequestPort
    v
membus -> MemCtrl -> DRAM
```

这样做的好处：

- NPU 能像 CPU、DMA、MemCtrl 一样在 gem5 config 里配置。
- gem5 统一负责仿真启动、事件推进、stats dump。
- SystemC 内核仍用 gem5 自带 `SystemC_Kernel`。
- NPU 内部继续用 SystemC/TLM 写，不需要手写 gem5 `RequestPort` 协议。
- 以后多个 NPU、不同 array/buffer 配置、不同 workload 都能通过 Python 参数实例化。

### 8.2 最终拓扑

P2 阶段先做 NPU-only：

```text
Root
└── System
    ├── SystemC_Kernel
    ├── SrcClockDomain / VoltageDomain
    ├── membus : SystemXBar
    ├── mem_ctrl : MemCtrl
    │   └── dram
    ├── npu : NpuDevice
    │   └── top : NpuTop(sc_module)
    │       ├── WorkloadDriver
    │       ├── PeArray
    │       ├── OnchipBuffer
    │       └── DmaEngine.isock
    └── npu_bridge : TlmToGem5Bridge64
        ├── tlm  <- bind <- npu.top.dma.isock
        └── gem5 -> membus.cpu_side_ports
```

数据流：

```text
WorkloadDriver
    -> DmaEngine.issue_read/write()
    -> tlm_generic_payload
    -> TlmToGem5Bridge64
    -> gem5 Request/Packet
    -> membus
    -> MemCtrl
    -> DRAM
```

### 8.3 建议放置的源码目录

推荐先放在 gem5 源码树内，降低 build/link 复杂度：

```text
src/dev/npu/
  NpuDevice.py          # gem5 SimObject 参数定义
  npu_device.hh         # gem5 C++ SimObject wrapper
  npu_device.cc
  npu_top.hh            # SystemC sc_module 顶层
  npu_top.cc
  npu_config.hh         # 从原 common.h 拆出的配置/任务结构，可先直接移植
  dma_engine.hh/.cc
  onchip_buffer.hh/.cc
  pe_array.hh/.cc
  workload_driver.hh/.cc
  perf_monitor.hh/.cc
  SConscript
```

也可以放在：

```text
src/learning_gem5/npu/
```

如果目标是长期维护，`src/dev/npu/` 更像正式设备；如果目标是学习实验，
`src/learning_gem5/npu/` 更轻。

### 8.4 Python SimObject：NpuDevice.py

`NpuDevice.py` 负责暴露 gem5 配置参数。

示意：

```python
from m5.objects.SystemC import SystemC_ScModule
from m5.params import *

class NpuDevice(SystemC_ScModule):
    type = "NpuDevice"
    cxx_class = "gem5::NpuDevice"
    cxx_header = "dev/npu/npu_device.hh"

    array_n = Param.Unsigned(16, "Systolic array dimension")
    buffer_kb = Param.Unsigned(256, "On-chip buffer size in KiB")
    buf_bw_Bpc = Param.Float(64.0, "On-chip buffer bandwidth in bytes/cycle")
    dma_outstanding = Param.Unsigned(4, "Max outstanding DMA transactions")
    data_bytes = Param.Unsigned(1, "Bytes per matrix element")

    gemm_m = Param.Unsigned(512, "GEMM M dimension")
    gemm_k = Param.Unsigned(512, "GEMM K dimension")
    gemm_n = Param.Unsigned(512, "GEMM N dimension")
    double_buffer = Param.Bool(True, "Enable double buffering")

    a_base = Param.Addr(0x10000000, "Input matrix A base address")
    b_base = Param.Addr(0x20000000, "Input matrix B base address")
    c_base = Param.Addr(0x30000000, "Output matrix C base address")
```

注意：如果 `NpuDevice` 继承 `SystemC_ScModule`，它本身就是 gem5 管理的 SystemC 模块。
这比普通 `SimObject` 内部再手动 new 一个 `sc_module` 更贴近 gem5 的 SystemC 桥接方式。

### 8.5 C++ wrapper：NpuDevice

`NpuDevice` 的职责：

- 从 gem5 参数构造 `NpuConfig` 和 `GemmTask`
- 创建/持有 NPU 内部模块
- 暴露 TLM initiator socket，供 Python 侧绑定到 `TlmToGem5Bridge64.tlm`
- 在仿真结束时输出 NPU 统计，或接入 gem5 stats

示意：

```cpp
class NpuDevice : public sc_core::sc_module
{
  public:
    tlm_utils::simple_initiator_socket<NpuDevice, 64> dma_socket;

    NpuDevice(const NpuDeviceParams &p,
              const sc_core::sc_module_name &name);

  private:
    NpuConfig cfg;
    GemmTask task;

    std::unique_ptr<OnchipBuffer> buf;
    std::unique_ptr<DmaEngine> dma;
    std::unique_ptr<PeArray> pe;
    std::unique_ptr<WorkloadDriver> drv;
};
```

但更干净的做法是让 `NpuDevice` 持有一个 `NpuTop`：

```cpp
class NpuDevice : public sc_core::sc_module
{
  public:
    tlm_utils::simple_initiator_socket<NpuDevice, 64> dma_socket;

    NpuDevice(const NpuDeviceParams &p,
              const sc_core::sc_module_name &name)
      : sc_module(name),
        dma_socket("dma_socket"),
        top("top", cfg, task)
    {
        top.dmaSocket().bind(dma_socket);
    }

  private:
    NpuConfig cfg;
    GemmTask task;
    NpuTop top;
};
```

实际实现时要注意 socket 方向：`DmaEngine` 是 initiator，`TlmToGem5Bridge64.tlm`
是 target。`NpuDevice` 如果只是包装 `NpuTop`，可以直接暴露 `NpuTop` 里的 initiator socket，
不一定需要再包一层 socket。

### 8.6 SystemC 顶层：NpuTop

`NpuTop` 从原 `main.cpp` 中抽出来，删除 `Memory mem` 和 `sc_start()`：

```cpp
class NpuTop : public sc_core::sc_module
{
  public:
    SC_HAS_PROCESS(NpuTop);

    NpuTop(sc_core::sc_module_name name, NpuConfig cfg, GemmTask task)
      : sc_module(name),
        cfg(cfg),
        task(task),
        buf("buf", cfg),
        dma("dma", cfg),
        pe("pe", cfg),
        drv("drv", cfg, task, &dma, &buf, &pe)
    {
        // 不再 dma.isock.bind(mem.tsock)
        // 由 gem5 config 把 dma.isock 绑定到 TlmToGem5Bridge64.tlm
    }

    auto &dmaSocket() { return dma.isock; }

  private:
    NpuConfig cfg;
    GemmTask task;
    OnchipBuffer buf;
    DmaEngine dma;
    PeArray pe;
    WorkloadDriver drv;
};
```

独立 `npu_sim` 仍然可以保留，但它应该变成：

```text
standalone main.cpp
  NpuTop top
  Memory mem
  top.dmaSocket().bind(mem.tsock)
  sc_start()
```

gem5 模式则是：

```text
gem5 config
  NpuDevice/NpuTop
  TlmToGem5Bridge64
  npu.dma_socket <-> bridge.tlm
  bridge.gem5 -> membus
```

### 8.7 Python config 绑定方式

示意 config：

```python
import m5
from m5.objects import *

system = System()
system.clk_domain = SrcClockDomain(
    clock="1GHz", voltage_domain=VoltageDomain()
)
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("1GB")]

system.membus = SystemXBar()

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

system.systemc_kernel = SystemC_Kernel()

system.npu = NpuDevice(
    array_n=16,
    buffer_kb=256,
    gemm_m=512,
    gemm_k=512,
    gemm_n=512,
    a_base=0x10000000,
    b_base=0x20000000,
    c_base=0x30000000,
)

system.npu_bridge = TlmToGem5Bridge64()
system.npu_bridge.gem5 = system.membus.cpu_side_ports

# 需要通过 TLM socket 绑定把 npu 的 initiator socket 接到 bridge 的 target socket。
# 具体语法取决于 NpuDevice.py 暴露的 socket 参数名。
system.npu.dma = system.npu_bridge.tlm

root = Root(full_system=False, system=system)
m5.instantiate()
exit_event = m5.simulate()
```

这里的关键点：

```text
NpuDevice 侧暴露 TLM initiator socket
TlmToGem5Bridge64 侧暴露 TLM target socket
TlmToGem5Bridge64.gem5 接 membus.cpu_side_ports
```

### 8.8 SConscript 编译入口

`src/dev/npu/SConscript` 大致需要：

```python
Import("*")

SimObject("NpuDevice.py", sim_objects=["NpuDevice"])

Source("npu_device.cc")
Source("npu_top.cc")
Source("common.cc")
Source("dma_engine.cc")
Source("onchip_buffer.cc")
Source("pe_array.cc")
Source("workload_driver.cc")
Source("perf_monitor.cc")
```

如果使用 gem5 自带 SystemC/TLM 头文件，源码 include 应从：

```cpp
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
```

逐步改成 gem5 能找到的头文件路径。优先参考：

```text
src/systemc/tlm_bridge/
src/systemc/tests/tlm/
```

### 8.9 P2 需要先修的 NPU 代码

在接 bridge 之前，先改 NPU 模型本身：

1. `DmaEngine::Transfer` 增加 data buffer：

```cpp
std::vector<unsigned char> data;
```

2. `submitTransfer()` 中按 transaction 大小分配：

```cpp
transfer->data.resize(bytes);
gp.set_data_ptr(transfer->data.data());
```

3. 异步 DMA API 加地址参数：

```cpp
TransferPtr issue_read(uint64_t addr, uint32_t bytes, Kind kind, uint32_t tile_id);
TransferPtr issue_write(uint64_t addr, uint32_t bytes, Kind kind, uint32_t tile_id);
```

4. `WorkloadDriver` 增加地址计算：

```cpp
uint64_t weight_addr(uint32_t i, uint32_t j, uint32_t k);
uint64_t activation_addr(uint32_t i, uint32_t j, uint32_t k);
uint64_t output_addr(uint32_t i, uint32_t j);
```

5. standalone `Memory` 继续保留，但不再是 gem5 模式的内存后端。

### 8.10 分阶段落地 checklist

P1：NPU 代码可嵌入

- [ ] 从 `main.cpp` 抽出 `NpuTop`
- [ ] standalone `npu_sim` 改成实例化 `NpuTop + Memory`
- [ ] 修 DMA payload buffer
- [ ] 修 DMA API 地址参数
- [ ] `WorkloadDriver` 生成真实 tile 地址
- [ ] standalone sanity tests 仍通过

P2：gem5 内 NPU-only

- [ ] 新建 `src/dev/npu/`
- [ ] 新建 `NpuDevice.py`
- [ ] 新建 `npu_device.hh/.cc`
- [ ] 新建 `SConscript`
- [ ] 编译进 `build/X86/gem5.opt`
- [ ] Python config 创建 `SystemC_Kernel`
- [ ] Python config 创建 `NpuDevice`
- [ ] Python config 创建 `TlmToGem5Bridge64`
- [ ] 绑定 `NpuDevice.dma_socket -> TlmToGem5Bridge64.tlm`
- [ ] 绑定 `TlmToGem5Bridge64.gem5 -> membus.cpu_side_ports`
- [ ] 跑 NPU-only GEMM
- [ ] 从 `stats.txt` 确认 MemCtrl 收到读写请求

P3：CPU + NPU

- [ ] 加 CPU 和 workload
- [ ] 定义 CPU 通过 MMIO 或 shared memory 启动 NPU 的方式
- [ ] 明确 CPU/NPU 共享内存一致性策略
- [ ] 如果非一致性，划 uncached region 或加入 flush/invalidate
- [ ] 如果走 Ruby coherent，设计 Ruby DMA 接入路径
- [ ] 对比 CPU-only / NPU-only / CPU+NPU offload

### 8.11 这个方案的边界

方案 A 解决的是：

```text
怎么把 SystemC/TLM NPU 作为 gem5 设备接进 gem5 memory system
```

它暂时不解决：

- CPU 如何通过指令真正启动 NPU
- NPU 寄存器/MMIO programming model
- CPU cache 与 NPU DMA 的 coherent 语义
- 多 NPU 之间的仲裁/interconnect
- 能耗模型

这些应放到 P3/P4，不要压进 P2。P2 的目标很明确：**NPU 的 DMA 请求能真实进入
gem5 membus/DRAM，并能从 gem5 stats 里看到对应流量和延迟。**
