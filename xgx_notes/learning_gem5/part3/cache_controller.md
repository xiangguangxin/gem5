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

## 分步练习 R3：先冷读，再写 miss，再考虑竞争

**重点逻辑：瞬态状态表示事务尚未完成；TBE 保存未完成事务的上下文，缓存行保存数据及稳定状态相关信息。**

### 步骤 1：拆开冷读 transition

找到 `transition(I, Load, IS_D)`，逐个解释 `allocateCacheBlock`、`allocateTBE`、`sendGetS`、`popMandatoryQueue`。再找到 `transition(IS_D, {DataDirNoAcks, DataOwner}, S)`，对应写数据、释放 TBE、通知 Sequencer、弹出响应。

画两列：左侧资源分配，右侧资源释放。指出为什么已经把 mandatoryQueue 弹出，CPU 请求仍然可以尚未完成。

### 步骤 2：追写 miss 的两种到达顺序

从 `I + Store → IM_AD` 开始，查 `DataDirAcks`、`InvAck`、`LastInvAck` 对应转移。分别手算“数据先到”和“部分确认先到”，填写 TBE ack 计数变化。不能把“收到数据”直接当成“已经获得写权限”。

### 步骤 3：读已有 M 行的远端请求

查 `FwdGetS/FwdGetM` 的分支，标注数据发给请求核还是目录，原 owner 如何降级或失效。之后到目录笔记核对两个方向的动作能否配对。

### 步骤 4：用 trace 验证

完成[MSI 运行实验](config_and_run.md)后，在 ProtocolTrace 中挑一个行地址，按时间记录 `控制器 / 状态 / 事件 / 下一状态`。随机测试不保证每次都覆盖想要的转移，未出现时扩大测试或编写定向负载，不要伪造预期日志。

**验收**：一份冷读资源表、两种 ack 到达顺序推演、一份实际 trace。先能解释 stall 的必要性，再考虑改动 transition。
