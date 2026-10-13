# Part 1 · 第 3 章：给配置脚本添加缓存（Adding Caches）

> 对应源码：`configs/learning_gem5/part1/caches.py`、`two_level.py`
> 上一章对照：`simple.py`（CPU 直连内存，无缓存）

## 本章目标

在 `simple.py` 的基础上，在 CPU 和内存之间插入两级缓存（L1I/L1D + L2），
理解 gem5 里缓存是怎么作为 SimObject 创建、并通过「端口(port)」连接起来的。

```
simple.py:    CPU ──────────────► membus ──► DDR3
two_level.py: CPU ─► L1I/L1D ─► l2bus ─► L2 ─► membus ─► DDR3
```

## 核心概念

### 1. Cache 是一个 SimObject

`Cache` 定义在 `src/mem/cache/` 下（Python 侧是 `src/mem/cache/Cache.py`），
和 `System`、`CPU`、`MemCtrl` 一样都是 SimObject，在脚本里 `from m5.objects import Cache`
即可使用。本例通过继承 Python `Cache` 类设置参数和连接方法；改变缓存内部行为通常还需要修改或新增 C++ 实现。

### 2. 缓存寻址：tag / index / offset（Set 与 Way）

CPU 访问缓存时，地址被拆成三段：

```
地址 = tag | index | offset
```

- **index** 决定去哪个 **Set**（组）；
- **tag** 判断是不是目标数据——在 Set 内，所有 **Way** 的 tag **并行比较**，命中的那个 Way 就是目标 Cache Line；
- **offset** 定位 Cache Line 内的具体字节。

关键点：**Way 不是地址的一部分**，而是缓存内部为降低冲突而额外设置的多个存储槽位；
`assoc=2` 的意思就是一个 Set 里有 2 个 Cache Line（2 路组相联）。

一次缓存访问的流程：**index 找 Set → 并行比 tag → 读数据 → 返回 CPU**。

#### assoc：每组有多少个 Way

`L1Cache` 中的配置：

```python
assoc = 2
```

`assoc` 表示**相联度（associativity），即每个 Set 包含多少个 Way（槽位）**。
这里是两路组相联：每组最多存放两个有效 Cache Line。

以容量 **16KiB**、Cache Line 大小 **64B**、`assoc=2` 为例：

```text
总行数 = 缓存容量 / 每行大小 = 16 × 1024 / 64 = 256 行
组数   = 总行数 / 相联度    = 256 / 2 = 128 组

             Way 0       Way 1
Set 0       [缓存行]     [缓存行]
Set 1       [缓存行]     [缓存行]
...
Set 127     [缓存行]     [缓存行]
```

因此，三者的关系为：

```text
缓存数据容量 = Set 数量 × assoc × Cache Line 大小
```

这里的容量指数据容量，不包含 Tag 和状态位等元数据开销。
访问一个地址时，index 先选中一个 Set，再检查该组两个 Way 的 Tag 和有效状态；
匹配时命中，否则发生 miss。

#### 为什么增加 Way 可以减少冲突 miss

假设内存块 A、B 映射到同一个 Set，且交替访问 A、B：

| 相联度 | 每组槽位数 | 可能的行为 |
|---|---|---|
| `assoc=1`（直接映射） | 1 | A、B 无法同时保留，交替访问时可能反复替换 |
| `assoc=2`（两路组相联） | 2 | A、B 可以同时保留，首次装入后重复访问可能命中 |

在两路组相联中，如果再访问一个映射到该组的块 C，而两个槽位都已占用，
就需要按替换策略选择一个牺牲块。**相联度决定有多少个候选槽位，替换策略决定替换哪一个。**

**固定缓存容量和行大小时，增加 assoc 不会增加容量，而是减少 Set 数量。**
例如同样为 16KiB、64B 一行：`assoc=1` 时有 256 组，`assoc=2` 时有 128 组，
`assoc=4` 时有 64 组。组数改变后，地址到 Set 的映射也会改变。
相联度增大通常能减少冲突 miss，但不保证总性能一定提升；实际硬件还需要权衡查询延迟、面积与功耗。
在 gem5 中单独修改 `assoc`，不能假定这些硬件代价会自动反映到已配置的延迟参数中。

### 3. 端口（Port）的连接语义（本章最容易绕晕的点）

每个缓存有**两个端口**：

| 端口 | 方向 | 含义 |
|------|------|------|
| `cpu_side`  | 朝向 CPU | `ResponsePort`，接收上游请求并返回响应 |
| `mem_side`  | 朝向内存 | `RequestPort`，向下游发送请求并接收响应 |

总线（XBar）也有两组端口：`cpu_side_ports`（接请求方）和 `mem_side_ports`（接响应方）。

**连接规则**：`RequestPort` 连接 `ResponsePort`；本例中缓存的 `mem_side` 连接 XBar 的 `cpu_side_ports`，XBar 的 `mem_side_ports` 连接下一级缓存的 `cpu_side`。
即「上一级的出口」接「下一级的入口」：

```python
# L1 的出口(mem_side) 接 l2bus 的入口(cpu_side_ports)
self.mem_side = bus.cpu_side_ports          # L1Cache.connectBus

# L2 的入口(cpu_side) 接 l2bus 的出口(mem_side_ports)
self.cpu_side = bus.mem_side_ports          # L2Cache.connectCPUSideBus

# L2 的出口(mem_side) 接 membus 的入口(cpu_side_ports)
self.mem_side = bus.cpu_side_ports          # L2Cache.connectMemSideBus
```

### 4. 两级缓存的层次结构

`caches.py` 里的类继承关系：

```
Cache (gem5 内置)
 ├─ L1Cache          assoc=2, tag/data/response_latency=2, mshrs=4, tgts_per_mshr=20
 │    ├─ L1ICache    size="16KiB"   connectCPU → cpu.icache_port
 │    └─ L1DCache    size="64KiB"   connectCPU → cpu.dcache_port
 └─ L2Cache          size="256KiB", assoc=8, latency=20, mshrs=20, tgts_per_mshr=12
```

L1 采用**指令/数据分离**（Harvard 结构），各自独立；L2 是统一的（unified）。

### 5. two_level.py 的连接拓扑（完整链路）

| 组件 | 类型 | 连接 |
|------|------|------|
| CPU | `X86TimingSimpleCPU` | icache_port / dcache_port |
| L1I / L1D | `L1ICache` / `L1DCache` | cpu_side←CPU, mem_side→l2bus |
| l2bus | `L2XBar()` | 连接 L1 与 L2 |
| L2 | `L2Cache` | cpu_side←l2bus, mem_side→membus |
| membus | `SystemXBar()` | 连接 L2 与内存 |
| 内存 | `MemCtrl()` + `DDR3_1600_8x8()` | 范围 512MiB |

## 常用缓存参数（见 `src/mem/cache/Cache.py`）

| 参数 | 含义 | L1 默认 | L2 默认 |
|------|------|---------|---------|
| `size` | 缓存容量 | 16KiB(I) / 64KiB(D) | 256KiB |
| `assoc` | 组相联路数（associativity） | 2 | 8 |
| `tag_latency` | 读 tag 延迟（cycle） | 2 | 20 |
| `data_latency` | 读数据延迟（cycle） | 2 | 20 |
| `response_latency` | miss 返回路径延迟（cycle） | 2 | 20 |
| `mshrs` | Miss Status Holding Registers 数量（可同时处理多少未命中） | 4 | 20 |
| `tgts_per_mshr` | 每个 MSHR 最多合并多少个后续目标 | 20 | 12 |

这些参数不能统一理解为三个固定串行阶段。`tag_latency` 与 `data_latency` 的组合受 `sequential_access` 等配置影响；`response_latency` 在 Python 定义中表示 miss 的返回路径延迟。实际命中、未命中和转发的时间还需结合 `src/mem/cache/` 的 C++ 路径分析，不能直接把三项相加当作命中延迟。

- `mshrs`：**MSHR（Miss Status Holding Register，缺失状态保持寄存器）**的数量。
  一次访问 miss 时，会分配一个 MSHR 记录「这个 miss 正在等下一级缓存/内存返回」；
  `mshrs` 决定当前缓存能**同时处理多少个在途 miss**，MSHR 耗尽后新的 miss 只能停等。
- `tgts_per_mshr`：**一个 miss 最多能合并多少个后续请求**——多个请求访问同一块时，
  后到的请求不会各自开新 MSHR，而是「挂」在已有的那个 miss 上，等数据回来一起唤醒。

## 运行方式

```bash
# 在仓库根目录执行

# 默认跑 hello 程序
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py

# 通过命令行覆盖缓存大小（caches.py 用 SimpleOpts 暴露了这些参数）
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py \
    --l1i_size=32KiB --l1d_size=32KiB --l2_size=512KiB

# 指定要执行的二进制
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py binary=/path/to/prog
```

## 实验对比（有缓存 vs 无缓存）

同一段 hello 程序：

| 脚本 | 缓存 | 模拟结束时刻 (tick) |
|------|------|---------------------|
| `simple.py`  | 无缓存（直连内存） | ~507,962,000 |
| `two_level.py` | 两级缓存 | ~58,125,000 |

加了缓存后程序**约快 9 倍**完成（tick 越小越早结束）。
原因：CPU 大部分访存命中了 L1，避免了每次都要走 DRAM 的几百个 cycle 延迟。
可以进一步用统计输出（`m5out/stats.txt` 里的 `system.cpu.dcache.overallMissRate`
等）量化验证缓存命中率与加速。

## 分步实验 A2：从连接关系到缓存收益

**重点逻辑：缓存通过保留数据减少下游访问，但每次访问也引入查询延迟。容量、命中率和总性能之间不是无条件单调关系。**

### 步骤 1：完成默认系统基线

```bash
build/X86/gem5.opt --outdir=m5out/learning/a2_default configs/learning_gem5/part1/two_level.py
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py --help
```

`--outdir` 属于 gem5，放在配置脚本前；`--l1d_size` 等选项属于本配置脚本，放在脚本后。查 `caches.py` 的 `connectCPU/connectBus/connectCPUSideBus/connectMemSideBus`，分别给图上每条边找到对应连接语句。

### 步骤 2：只改 L1D 容量

```bash
build/X86/gem5.opt --outdir=m5out/learning/a2_l1d16 configs/learning_gem5/part1/two_level.py --l1d_size=16KiB
build/X86/gem5.opt --outdir=m5out/learning/a2_l1d64 configs/learning_gem5/part1/two_level.py --l1d_size=64KiB
rg -n '^\[system.cpu.dcache\]|^size=|^assoc=|^mshrs=' m5out/learning/a2_l1d16/config.ini
rg -n 'dcache.*(Hits|Misses|Accesses|missRate)|simSeconds' m5out/learning/a2_l1d16/stats.txt
```

检查对应 section 的容量，不能看到任何一行 `size` 就认为是 L1D。相同方式检查第二次输出。先用 hello 确认参数通路，再使用[内存微基准](../experiments/memory_lab.md)做容量实验。

### 步骤 3：建立解释表

| 配置 | 实际 L1D 容量 | 访问数 | miss 数/比例 | 仿真时间 | 结论 |
|---|---|---|---|---|---|
| 16KiB | 从配置填 | 从统计填 | 同一口径 | 从统计填 | 待解释 |
| 64KiB | 从配置填 | 从统计填 | 同一口径 | 从统计填 | 待解释 |

如果工作集本来就能放进较小缓存，增容不一定改善；如果程序主要等待其他组件，降低 miss 也不一定大幅提速。先解释结果，再考虑调整相联度或 MSHR。

### 步骤 4：追踪一次 miss

沿 CPU → L1D → L2 → MemCtrl 和返回路径画图，在图上标注“命中可在哪一层停止向下访问”。说明 cache line 大小与应用一次 load 字节数可能不同，为什么内存流量不能直接等同于源码读取字节数。

**验收**：连接表、参数生效证据、两组统计和一段因果解释。此时不要求阅读完整 Cache C++；优先掌握“参数 → 行为 → 指标”的对应关系。
