# Part 2 · 第 3 章：自己写一个缓存（SimpleCache）

> 对应源码：`src/learning_gem5/part2/simple_cache.{hh,cc}` + `SimpleCache.py`
> 配置脚本：`configs/learning_gem5/part2/simple_cache.py`

## 本章目标

在 SimpleMemobj 的基础上写一个**真正的（但极简的）缓存**，重点引入：
**向量端口(VectorPort)**、**参数(Param)**、**时钟对象(ClockedObject)**、**统计(stats)**。

## SimpleCache 的特性（对照真实 Cache 做了简化）

- 全相联（fully-associative）
- 随机替换（random replacement）
- 写回（writeback）
- 完全阻塞（同一时刻只处理一个请求）

## 关键新概念 1：向量端口 VectorPort

```python
# SimpleCache.py
cpu_side = VectorResponsePort("CPU side port, receives requests")
mem_side = RequestPort("Memory side port, sends requests")
```

`cpu_side` 是一个**向量端口**：CPU 的取指口和数据口都连到它，gem5 会自动把它
拆成两个独立的端口实例（每个都对应一套 C++ 侧的 `CPUSidePort` 类）。

```python
# simple_cache.py —— 连两次，向量端口自动扩展
system.cpu.icache_port = system.cache.cpu_side
system.cpu.dcache_port = system.cache.cpu_side
```

## 关键新概念 2：Param 参数

```python
latency = Param.Cycles(1, "Cycles taken on a hit or to resolve a miss")
size    = Param.MemorySize("16KiB", "The size of the cache")
system  = Param.System(Parent.any, "The system this cache is part of")
```

- `Param.Cycles` / `Param.MemorySize`：带单位的类型（cycle / 字节），脚本里可写成 `size="1KiB"`。
- `Parent.any`：一个**代理(proxy)**，自动指向父节点所在的 `System`，免去手动连线。

## 关键新概念 3：ClockedObject 与统计

- SimpleCache 继承 `gem5::ClockedObject`（**有自己时钟**的 SimObject），
  用 `clockEdge()` 来模拟命中/缺失的 `latency` 个周期延迟。
- 通过 `statistics.hh` 里的 `statistics::Scalar` / `Histogram` 暴露统计量，
  模拟结束会写进 `m5out/stats.txt`（如命中数、缺失数、缺失率）。

## 配置拓扑

```python
system.cache = SimpleCache(size="1KiB")          # 只 1KiB，方便观察命中/缺失
system.cpu.icache_port = system.cache.cpu_side
system.cpu.dcache_port = system.cache.cpu_side
system.cache.mem_side  = system.membus.cpu_side_ports
```

```
CPU ──icache/dcache──► SimpleCache ──mem_side──► membus ──► DDR3
```

## 运行

```bash
cd /home/guangxinxiang.linux/github/gem5
build/X86/gem5.opt configs/learning_gem5/part2/simple_cache.py
```

## 实际输出

```
Hello world!
Exiting @ tick 53367000 because exiting with last active thread context
```

**要点**：结束时刻 `53367000` 比 pass-through 的 `507962000` 快了约 **9.5 倍**，
这就是缓存命中带来的加速。想看内部统计，去看 `m5out/stats.txt` 里
`system.cache.overallMisses` / `overallHits` 等字段。
