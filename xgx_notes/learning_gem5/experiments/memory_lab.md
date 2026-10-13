# 内存实验 B：把参数变化变成可解释的证据

**重点逻辑：先固定访问序列，再只改一个硬件参数；先证明结果正确与参数生效，再解释 miss 和时间。**

本实验提供 [memory_stream.c](memory_stream.c)，使用 volatile 数组保证读取不会被编译器整体消除。它是入门容量实验，不是优化过的峰值带宽测试，也不是随机访问测试。

## B1：准备三个工作集

在仓库根目录执行，需要宿主 GCC 能生成 X86 Linux 程序及静态链接依赖：

```bash
mkdir -p m5out/learning/bench
cc -O2 -std=c11 -static -DWORKSET_BYTES=4096 -DROUNDS=16 xgx_notes/learning_gem5/experiments/memory_stream.c -o m5out/learning/bench/stream4k
cc -O2 -std=c11 -static -DWORKSET_BYTES=65536 -DROUNDS=16 xgx_notes/learning_gem5/experiments/memory_stream.c -o m5out/learning/bench/stream64k
cc -O2 -std=c11 -static -DWORKSET_BYTES=524288 -DROUNDS=16 xgx_notes/learning_gem5/experiments/memory_stream.c -o m5out/learning/bench/stream512k
file m5out/learning/bench/stream4k
sha256sum m5out/learning/bench/stream4k m5out/learning/bench/stream64k m5out/learning/bench/stream512k
```

宿主为 X86 Linux 时可以先直接执行三个程序，确认 checksum 等于 expected。其他宿主需要交叉编译，不能直接复用这些命令。缺静态 libc 时先配置工具链；不要随意换成动态程序后忽略 SE 的加载依赖。

程序初始化每个元素为索引，再顺序读 16 轮。扫描的应用有效读字节为 `工作集大小 × 16`，但整程序还包含初始化写、启动、取指与打印。

## B2：固定工作集，只改 L1D 容量

```bash
build/X86/gem5.opt --outdir=m5out/learning/b2_16k configs/learning_gem5/part1/two_level.py --l1d_size=16KiB m5out/learning/bench/stream64k
build/X86/gem5.opt --outdir=m5out/learning/b2_64k configs/learning_gem5/part1/two_level.py --l1d_size=64KiB m5out/learning/bench/stream64k
build/X86/gem5.opt --outdir=m5out/learning/b2_128k configs/learning_gem5/part1/two_level.py --l1d_size=128KiB m5out/learning/bench/stream64k
```

每次执行后检查：checksum 与 expected 一致、正常退出、`config.ini` 的 L1D 容量符合要求。固定 L1I、L2、时钟、CPU、程序、编译选项与轮数。

先预测：16KiB 无法容纳 64KiB 数组；128KiB 更有余量保留数组；恰好 64KiB 不一定能保留所有行，因为还有其他数据及冲突。L2 可能吸收 L1 miss，因此 L1 miss 下降不一定对应 DRAM 流量同比下降。

```bash
rg -n 'simSeconds|dcache.*(Hits|Misses|Accesses|missRate)|l2cache.*(Hits|Misses|Accesses|missRate)' m5out/learning/b2_16k/stats.txt
```

实际对象命名或指标拼写可能变化，用 `rg -n 'dcache|l2cache'` 查找，并逐项核对统计描述与单位。

| L1D | 实际容量 | checksum | L1D miss/access | L2 miss/access | 整程序仿真时间 |
|---|---|---|---|---|---|
| 16KiB | 待填 | 待填 | 待填 | 待填 | 待填 |
| 64KiB | 待填 | 待填 | 待填 | 待填 | 待填 |
| 128KiB | 待填 | 待填 | 待填 | 待填 | 待填 |

这一轮报告整程序时间，**不能把扫描有效字节除以整程序时间后称作纯扫描带宽**。要报告 ROI 带宽，先完成 B4。

## B3：固定缓存，只改工作集

固定 `--l1d_size=64KiB`，分别运行三个二进制，输出目录取 `b3_4k/b3_64k/b3_512k`。比较 miss rate 或每个扫描元素的指标；三个程序的总访问数不同，不能仅比较总时间就判断哪组缓存行为更差。

预期小工作集重复命中较多，大工作集更容易超过缓存容量。分析时同时检查 L2，区分 L1 容量不足和整个缓存层次都不足。

**阶段验收**：两张实验表与一段分层解释。出现反常结果先核对实际容量、负载哈希、访问数量和统计口径。

## B4：增加 ROI，去掉初始化与打印

这是下一步实现练习，当前 C 文件没有 m5 标记。按以下顺序修改，不能只在报告里假定已经隔离 ROI：

1. 找 `include/gem5/m5ops.h` 与 `util/m5/`，按本地说明构建匹配 ISA 的 m5ops 库并链接程序。
2. 在初始化之后决定是否增加一轮预热，明确冷缓存或暖缓存测量目标。
3. 在正式扫描前 reset 统计，扫描后 dump，打印之前结束 ROI；具体 m5ops 参数与触发机制按当前头文件和所用配置核对。
4. 检查 `stats.txt` 是否出现预期转储段；结束时还可能自动转储，提取时只使用指定 ROI 段。
5. 用不同 ROUNDS 检查测量时间是否合理缩放，再报告 `WORKSET_BYTES × ROUNDS / ROI秒数`。

重置统计不会清空缓存。边界标记本身也可能有少量开销，短区间需报告此限制。

## B5：扩展为依赖访问与内存模型对照

容量实验通过后再做以下扩展，不同时改动所有变量：

- **指针追逐**：生成覆盖所有节点的单环置换，每次下一地址依赖上次 load 结果；保存生成算法与种子，校验环长度及终点。用大于缓存的工作集观察依赖延迟，不能把该负载当作峰值带宽测试。
- **固定延迟内存**：复制 `two_level.py` 到同目录练习脚本，把 MemCtrl/DRAM 初始化块整体替换为 `SimpleMemory(range=system.mem_ranges[0], latency="50ns", bandwidth="10GiB/s")`，保留其 `.port` 连接。先跑通，再只改 latency。
- **并发实验**：TimingSimpleCPU 的请求能力有限；需要更高并发时使用流量发生器或后续 DMA 设备，避免把 CPU 发不出请求误判为内存带宽不足。

**最终交付**：实验记录、编译命令与哈希、配置、原始统计、正确性结果、图表及模型限制。没有正确性结果的点不进入正常性能比较。
