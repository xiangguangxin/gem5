# Part 3 · 第 2 章：L1 缓存控制器状态机（MSI-cache.sm）

> 对应源码：`src/learning_gem5/part3/MSI-cache.sm`（851 行）

## 本章目标

看懂 MSI 协议的 **cache 侧**（L1）状态机是怎么用 SLICC 写出来的。

## machine 声明与参数

```slicc
machine(MachineType:L1Cache, "MSI cache")
    : Sequencer *sequencer;        // CPU 请求从这里进来
      CacheMemory *cacheMemory;    // 存数据和 cache 状态
      bool send_evictions;         // 是否给 CPU 发逐出（O3/x86 mwait 需要）
{
```

冒号后面的参数是**从 Python 配置注入**的（在 `msi_caches.py` 里赋值）。

## MessageBuffer：控制器和网络的接口

```slicc
MessageBuffer * requestToDir, network="To", virtual_network="0", vnet_type="request";
MessageBuffer * responseToDirOrSibling, network="To", virtual_network="2", vnet_type="response";
MessageBuffer * forwardFromDir, network="From", virtual_network="1", vnet_type="forward";
MessageBuffer * responseFromDirOrSibling, network="From", virtual_network="2", vnet_type="response";
MessageBuffer * mandatoryQueue;   // 特殊：CPU 经 sequencer 进来的请求
```

- `network="To"` 是发出去，`network="From"` 是收进来。
- `mandatoryQueue` 是 CPU 请求的入口（由 `RubySequencer` 驱动），不需要手动连网络。

## 状态声明（state_declaration）

```slicc
state_declaration(State, desc="Cache states") {
    I,     AccessPermission:Invalid,      desc="Not present/Invalid";
    IS_D,  AccessPermission:Invalid,      desc="I→S，等数据";
    IM_AD, AccessPermission:Invalid,      desc="I→M，等 ack+数据";
    IM_A,  AccessPermission:Busy,         desc="I→M，等 ack";
    S,     AccessPermission:Read_Only,    desc="Shared";
    SM_AD, AccessPermission:Read_Only,    desc="S→M，等 ack+数据";
    SM_A,  AccessPermission:Read_Only,    desc="S→M，等 ack";
    M,     AccessPermission:Read_Write,   desc="Modified（owner）";
    MI_A,  AccessPermission:Busy,         desc="M→I，等 put ack";
    SI_A,  AccessPermission:Busy,         desc="S→I，等 put ack";
    II_A,  AccessPermission:Invalid,      desc="已发数据，等 put ack";
}
```

**命名规律**：
- 不带下划线 = 稳定态（I/S/M）。
- 带下划线 = 瞬态，中间字母表示「从哪到哪」：`IS_D`（I→S，等 Data）、
  `IM_AD`（I→M，等 Ack+Data）、`SM_A`（S→M，等 Ack）、`MI_A`（M→I，等 Ack）。
- 每个状态都带 `AccessPermission`（Invalid/Read_Only/Read_Write/Busy），
  供**功能性访问**（functional access，如加载二进制）判断能不能读/写这个块。

## 事件（enumeration Event）

```slicc
enumeration(Event, desc="Cache events") {
    Load, Store,            // 来自 CPU/sequencer
    Replacement,            // 块被选作 victim
    FwdGetS, FwdGetM, Inv, PutAck,   // 目录经 forward 网络发来的
    DataDirNoAcks, DataDirAcks,      // 目录响应（无 ack / 有 ack）
    DataOwner, InvAck,               // 其他缓存的响应
    LastInvAck,                      // 内部事件：最后一个 ack 到了
}
```

## 两个关键结构：Entry 和 TBE

```slicc
structure(Entry, desc="Cache entry", interface="AbstractCacheEntry") {
    State CacheState,  DataBlock DataBlk,   // 每个块：状态 + 数据
}

structure(TBE, desc="Entry for transient requests") {
    State TBEState,     DataBlock DataBlk,  // 瞬态期间要暂存的信息
    int AcksOutstanding, default=0,         // 还差几个 ack
}
```

- `Entry`：缓存的**每个块**的元数据（继承 `AbstractCacheEntry`）。
- **TBE**（Transaction Buffer Entry）：**瞬态期间**的临时条目，作用类似 **MSHR**——
  记录「我在等什么」（比如还要收几个 InvAck）。进瞬态时 allocate，出瞬态时 deallocate。

## 一个 transition 长什么样

SLICC 的核心是 `transition(状态, 事件, 新状态) { 动作 }`，例如：

```slicc
transition(I, Load, IS_D) {
    v_allocateTBE;                       // 分配 TBE，记录在途请求
    a_issueRequest;                      // 给目录发 GetS
    v_forwardRequest;                    // 发到 requestToDir
}
```

完整协议就是在为「每个 (状态 × 事件) 组合」写迁移规则（原书 Table 8.1 列了全部）。
