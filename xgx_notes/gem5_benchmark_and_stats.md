# gem5 跑 benchmark 与性能指标笔记

> 目标：说明 gem5 怎么跑 benchmark、输出文件怎么看、哪些性能指标最重要，
> 以及这些指标对应的物理意义。

## 1. gem5 跑 benchmark 的基本思路

gem5 运行 benchmark，本质上是：

```text
gem5 可执行文件 + 配置脚本 + benchmark 程序/镜像 + 参数
```

常见有两种模式：

| 模式 | 名称 | 适合场景 |
|------|------|----------|
| SE mode | Syscall Emulation | 跑单个用户态程序，启动快，适合微基准和算法程序 |
| FS mode | Full System | 跑完整 OS，适合真实系统软件、服务器程序、复杂 benchmark |

入门和调架构参数时，优先用 **SE mode**。需要 Linux 内核、磁盘镜像、真实用户环境时，再用
**FS mode**。

## 2. SE mode 跑一个普通 benchmark

最经典的入口脚本是：

```text
configs/example/se.py
```

假设你有一个 benchmark 可执行文件：

```text
/path/to/bench
```

可以这样跑：

```bash
build/X86/gem5.opt \
  --outdir=m5out/bench_se \
  configs/example/se.py \
  --cmd=/path/to/bench
```

如果 benchmark 需要参数：

```bash
build/X86/gem5.opt \
  --outdir=m5out/bench_se_args \
  configs/example/se.py \
  --cmd=/path/to/bench \
  --options="arg1 arg2 arg3"
```

常用参数：

```bash
--cpu-type=TimingSimpleCPU
--cpu-type=O3CPU
--num-cpus=1
--caches
--l2cache
--l1i_size=32kB
--l1d_size=32kB
--l2_size=256kB
--mem-size=2GB
```

例子：

```bash
build/X86/gem5.opt \
  --outdir=m5out/o3_test \
  configs/example/se.py \
  --cpu-type=O3CPU \
  --num-cpus=1 \
  --caches \
  --l2cache \
  --l1i_size=32kB \
  --l1d_size=32kB \
  --l2_size=256kB \
  --mem-size=2GB \
  --cmd=/path/to/bench \
  --options="input.txt"
```

## 3. 用 Ruby 跑 benchmark

如果要研究 Ruby cache coherence，需要加 Ruby 相关参数。

典型形式：

```bash
build/X86/gem5.opt \
  --outdir=m5out/ruby_mesi \
  configs/example/se.py \
  --ruby \
  --cpu-type=TimingSimpleCPU \
  --num-cpus=2 \
  --cmd=/path/to/bench
```

指定 Ruby 协议通常和编译时选择的协议有关。不同 gem5 版本、不同 build 配置会有差异。
先查看脚本支持哪些参数：

```bash
build/X86/gem5.opt configs/example/se.py --help
```

Ruby 调试时可以加：

```bash
--debug-flags=ProtocolTrace,RubySlicc,RubyQueue
--debug-file=ruby.log
```

完整例子：

```bash
build/X86/gem5.opt \
  --outdir=m5out/ruby_debug \
  --debug-flags=ProtocolTrace \
  --debug-file=protocol_trace.log \
  configs/example/se.py \
  --ruby \
  --cpu-type=TimingSimpleCPU \
  --num-cpus=2 \
  --cmd=/path/to/bench
```

## 4. FS mode 跑 benchmark

FS mode 会启动完整系统，通常需要：

- kernel
- disk image
- boot script 或 workload 描述
- CPU/cache/memory 配置

常见入口：

```text
configs/example/fs.py
configs/example/gem5_library/x86-ubuntu-run.py
configs/example/gem5_library/riscv-ubuntu-run.py
```

老式脚本大致是：

```bash
build/X86/gem5.opt \
  --outdir=m5out/fs_test \
  configs/example/fs.py \
  --kernel=/path/to/vmlinux \
  --disk-image=/path/to/disk.img \
  --cpu-type=TimingSimpleCPU \
  --num-cpus=2 \
  --caches \
  --l2cache
```

gem5-library 风格脚本一般会自动管理 resource，具体看对应脚本：

```bash
configs/example/gem5_library/x86-spec-cpu2017-benchmarks.py
configs/example/gem5_library/x86-npb-benchmarks.py
configs/example/gem5_library/x86-gapbs-benchmarks.py
```

FS mode 更真实，但调试成本也更高。建议先用 KVM 快速启动到 checkpoint，
再切换到 Timing/O3 CPU 做详细模拟。

## 5. benchmark 运行结果在哪里

gem5 默认输出目录是：

```text
m5out/
```

常见文件：

| 文件 | 作用 |
|------|------|
| `stats.txt` | 最重要，所有统计指标 |
| `config.ini` | 实际 SimObject 配置 |
| `config.json` | JSON 形式配置 |
| `simout.txt` | stdout 重定向后输出 |
| `simerr.txt` | stderr 重定向后输出 |
| `*.log` | 你用 `--debug-file` 指定的 debug 日志 |

强烈建议每次实验指定独立目录：

```bash
--outdir=m5out/experiment_name
```

否则新结果会覆盖旧的 `m5out`。

## 6. stats.txt 怎么看

先看总体：

```bash
grep -E "simSeconds|simTicks|finalTick|hostSeconds|hostTickRate|hostInstRate" m5out/stats.txt
```

看 CPU：

```bash
grep -E "numCycles|committedInsts|committedOps|ipc|cpi" m5out/stats.txt
```

看 cache：

```bash
grep -iE "missRate|misses|hits|demandMiss|overallMiss" m5out/stats.txt
```

看内存：

```bash
grep -iE "avgMemAccLat|bytesRead|bytesWritten|readReqs|writeReqs|bw|bandwidth" m5out/stats.txt
```

看 Ruby：

```bash
grep -iE "ruby|network|flit|packet|average_latency" m5out/stats.txt
```

看配置：

```bash
less m5out/config.ini
```

`stats.txt` 里的指标名字会随 CPU 模型、cache 模型、Ruby/classic 配置变化。
所以不要死记完整名字，要学会用 `grep` 搜关键词。

## 7. 最重要的总体指标

| 指标 | 物理意义 | 怎么理解 |
|------|----------|----------|
| `simSeconds` | 被模拟系统经过的时间 | benchmark 在目标机器上消耗的模拟时间 |
| `simTicks` / `finalTick` | gem5 内部 tick 数 | gem5 事件调度的时间尺度 |
| `hostSeconds` | 宿主机实际运行时间 | gem5 在真实电脑上跑了多久 |
| `hostTickRate` | 每秒模拟多少 tick | 衡量模拟速度，越高越快 |
| `hostInstRate` | 每秒模拟多少条 guest 指令 | 衡量模拟吞吐，越高越快 |

注意：

```text
simSeconds 是目标系统时间
hostSeconds 是你的电脑实际花的时间
```

二者不是一回事。

## 8. 最重要的 CPU 指标

| 指标 | 物理意义 | 怎么理解 |
|------|----------|----------|
| `numCycles` | CPU 周期数 | benchmark 总共经历了多少 CPU cycle |
| `committedInsts` | 提交指令数 | 程序真正完成了多少条指令 |
| `committedOps` | 提交 micro-op 数 | O3/x86 下可能比指令数更细 |
| `ipc` | Instructions Per Cycle | 每周期提交多少条指令，越高越好 |
| `cpi` | Cycles Per Instruction | 每条指令平均用多少周期，越低越好 |
| `idleCycles` | CPU 空闲周期 | 多见于等待内存、同步或无任务 |
| `quiesceCycles` | CPU 暂停/休眠周期 | 可能来自系统调用、等待事件等 |

核心关系：

```text
IPC = committedInsts / numCycles
CPI = numCycles / committedInsts
```

一般先看：

```text
committedInsts 是否差不多
numCycles 是否变多
IPC 是否下降
CPI 是否上升
```

如果两个实验的 `committedInsts` 差很多，说明它们可能没有跑同一段 workload，
这时直接比较 IPC 可能会误导。

## 9. O3 CPU 常见微架构指标

使用 `O3CPU` 时，可以进一步看 pipeline 行为。

| 指标关键词 | 物理意义 |
|------------|----------|
| `branchPred` | 分支预测行为 |
| `mispred` | 分支预测错误 |
| `iew` | issue/execute/writeback 阶段 |
| `iq` | instruction queue |
| `rob` | reorder buffer |
| `lsq` | load/store queue |
| `commit` | 指令提交阶段 |
| `squash` | 流水线冲刷，通常由分支错误或异常导致 |
| `stalls` | 流水线停顿 |

常用搜索：

```bash
grep -iE "branch|mispred|rob|iq|lsq|squash|stall" m5out/stats.txt
```

物理意义：

- 分支预测错误多：前端经常走错路，浪费取指和执行资源。
- ROB/IQ/LSQ 满：乱序窗口或访存队列成为瓶颈。
- squash 多：大量已经进入流水线的指令被取消。
- stall 多：CPU 某个阶段等资源、等数据或等内存。

## 10. 最重要的 cache 指标

| 指标 | 物理意义 | 怎么理解 |
|------|----------|----------|
| `hits` | cache 命中次数 | 数据在当前 cache 找到了 |
| `misses` | cache 未命中次数 | 需要访问下一级 cache 或 memory |
| `missRate` | miss 比例 | 越高说明 locality 越差或 cache 太小 |
| `overallMissRate` | 总体 miss rate | 包含读写等总体访问 |
| `demandMissRate` | demand access miss rate | CPU 正常 load/store 引起的 miss |
| `mshr_hits` | MSHR 命中 | 多个 miss 合并到同一个 outstanding miss |
| `writebacks` | 写回次数 | dirty block 被逐出或回写 |
| `replacements` | 替换次数 | cache 容量/组相联冲突导致驱逐 |

典型分析：

```text
L1 miss rate 高 -> 程序局部性差，或 L1 太小/相联度低
L2 miss rate 高 -> 更多请求打到内存，内存延迟更影响 IPC
writebacks 多 -> 写密集，dirty block 逐出多
replacements 多 -> 容量或冲突压力大
```

## 11. 最重要的内存控制器指标

| 指标 | 物理意义 | 怎么理解 |
|------|----------|----------|
| `avgMemAccLat` | 平均内存访问延迟 | cache miss 到 DRAM 的平均代价 |
| `bytesRead` | DRAM 读取字节数 | 从内存读了多少数据 |
| `bytesWritten` | DRAM 写入字节数 | 写回/写请求产生的内存写流量 |
| `readReqs` | 读请求数 | 到内存控制器的读事务数量 |
| `writeReqs` | 写请求数 | 到内存控制器的写事务数量 |
| `bwRead` / `bwWrite` | 读/写带宽 | 内存吞吐能力使用情况 |
| `busUtil` | 总线利用率 | 内存总线忙碌程度 |
| `queue` | 请求队列情况 | 队列长说明排队延迟可能较高 |

物理意义：

```text
内存访问延迟高 -> CPU 可能经常等数据
内存带宽高 -> workload 可能是 bandwidth-bound
队列排队严重 -> 多核或高并发访存造成拥塞
```

## 12. Ruby 相关重要指标

Ruby 关注的是一致性协议、消息和片上网络。

| 指标关键词 | 物理意义 |
|------------|----------|
| `Ruby` | Ruby 子系统总入口关键词 |
| `miss_latency` | Ruby cache miss 平均处理时间 |
| `network` | Ruby network 行为 |
| `flit` | Garnet 网络中的 flit 数量 |
| `packet` | 网络包数量 |
| `average_latency` | 平均网络/消息延迟 |
| `link_utilization` | 链路利用率 |
| `stall` | controller 或 network 停顿 |
| `retries` | 请求重试 |

常用搜索：

```bash
grep -iE "ruby|miss_latency|network|flit|packet|average_latency|link_utilization|stall" m5out/stats.txt
```

物理意义：

- Ruby miss latency 高：一致性协议处理或网络传输慢。
- packet/flit 多：协议消息开销大。
- network latency 高：NoC 拥塞或拓扑/路由/带宽限制。
- stall 多：controller 可能在等资源、等 ack、等 transient state 结束。

## 13. 多核 benchmark 还要看什么

多核时，单看总 IPC 不够。

重点看：

| 指标 | 物理意义 |
|------|----------|
| 每个 core 的 `ipc` | 负载是否均衡 |
| 每个 core 的 `committedInsts` | 每个核实际干了多少活 |
| L2/LLC miss rate | 多核共享 cache 压力 |
| memory bandwidth | 是否内存带宽瓶颈 |
| Ruby network latency | 是否一致性网络瓶颈 |
| coherence message 数量 | 是否有严重共享/伪共享 |

常见现象：

```text
某些 core IPC 很低 -> 可能负载不均衡、同步等待或远端访存多
总内存带宽很高但 IPC 不升 -> memory bandwidth-bound
coherence 消息很多 -> 共享数据竞争或 false sharing
```

## 14. 如何比较两个实验

比如比较 baseline 和 new_design：

```bash
grep -E "simSeconds|numCycles|committedInsts|ipc|cpi" m5out/baseline/stats.txt
grep -E "simSeconds|numCycles|committedInsts|ipc|cpi" m5out/new_design/stats.txt
```

比较时要先确认：

```text
benchmark 一样
输入一样
CPU 类型一样
warmup/simpoint 区间一样
committedInsts 接近
```

如果这些不一致，性能差异可能来自实验条件，而不是架构变化。

常用公式：

```text
speedup = baseline_simSeconds / new_simSeconds
cycle_reduction = (baseline_cycles - new_cycles) / baseline_cycles
IPC_improvement = (new_IPC - baseline_IPC) / baseline_IPC
```

## 15. benchmark 调试建议

跑 benchmark 前先做小规模验证：

1. 先用简单 hello world 验证配置能跑通。
2. 再跑小输入 benchmark。
3. 再打开 cache/Ruby。
4. 最后换 O3CPU 或 FS mode。

建议每次保留命令：

```bash
mkdir -p m5out/exp_name
```

并把运行命令记录到笔记或脚本中。真正做实验时，最好用 shell 脚本固定参数，
避免手输命令造成实验不可复现。

## 16. 一个实用分析路径

拿到 `stats.txt` 后，不要一上来搜几百个指标。建议按这个顺序：

```text
1. simSeconds / numCycles：整体是否变快
2. committedInsts：是否跑了同样多的程序
3. IPC / CPI：CPU 效率如何
4. L1/L2/LLC miss rate：cache 是否是瓶颈
5. memory latency / bandwidth：内存是否是瓶颈
6. Ruby/network latency：一致性和网络是否是瓶颈
7. O3 pipeline stall：CPU 内部哪里被卡住
```

一句话：

```text
先看整体，再看 CPU，再看 cache，再看 memory/Ruby，最后才钻到具体 pipeline。
```

