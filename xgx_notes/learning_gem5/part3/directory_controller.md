# Part 3 · 第 3 章：目录控制器怎样管理副本、权限与内存交互

> 前置阅读：[Ruby 与 SLICC](ruby_slicc.md)、[缓存控制器](cache_controller.md)。
> 对应源码：[MSI-dir.sm](../../../src/learning_gem5/part3/MSI-dir.sm)，连接配置：[msi_caches.py](../../../configs/learning_gem5/part3/msi_caches.py)。本文针对当前教学 MSI，不代表所有 Ruby 协议。

## 1. 目录控制器解决什么问题

缓存控制器关注“我这一份缓存块能不能读写”；目录控制器关注“这个地址块有哪些副本、谁拥有最新数据、接下来找谁”。

目录还协调内存请求，但不替代 MemCtrl/DRAM 的访问排队和时序建模。

```text
CPU → Sequencer → L1 控制器
                     │ GetS / GetM / PutS / PutM
                     ↓
                 目录控制器
                  ├─ 找共享者：发送失效消息
                  ├─ 找 Owner：转发请求，索取最新数据
                  └─ 访问内存：读取块或写回数据
```

**目录不是所有最新数据的仓库。** 块处于 M 时，最新数据可以在某个 L1 Cache，目录保存的是寻找它所需的记录。

### 用一个块的经历理解“目录管理”

目录管理就是**按块记录谁持有副本、谁拥有独占最新数据，并协调权限交接**。先假设只有两个 CPU，块 X 最初不在任何缓存中。下面每一步都等待事务完成后再进行下一步，暂不考虑竞争。

| 阶段 | Cache0 中的 X | Cache1 中的 X | 目录稳定记录 | 数据情况 |
|---|---|---|---|---|
| 初始 | I | I | I，无 Sharer、无 Owner | 最新数据在内存 |
| CPU0 读取 | S | I | S，Sharers={Cache0} | 干净副本与内存一致 |
| CPU1 读取 | S | S | S，Sharers={Cache0, Cache1} | 两个共享副本 |
| CPU0 写入完成 | M | I | M，Owner={Cache0} | Cache0 最新，内存可能过期 |
| CPU1 再读，降级与回写完成 | S | S | S，Sharers={Cache0, Cache1} | 两个干净共享副本 |

#### 场景一：读取后登记共享者

```text
Cache0 → Directory：GetS(X)
Directory：检查 X 的记录，发现没有缓存持有它
Directory → 内存：读取 X 所在块
Directory → Cache0：Data
事务完成后：Cache0 的 X 为 S，目录记录 Sharers={Cache0}
```

随后 Cache1 也读取 X，本例目录在 S 状态仍向内存读取并返回数据，登记第二个共享者。这里“登记”是修改 X 的目录项，不是向文件写日志。

#### 场景二：有人要写，先协调其他副本失效

```text
Cache0 → Directory：GetM(X)，申请写权限
Directory → Cache1：Inv(X)，要求副本失效
Directory → Cache0：Data，携带必要确认数量
Cache1 → Cache0：InvAck(X)，确认自己的副本已失效
Cache0：数据与必要确认满足后，完成写入并进入 M
```

数据与确认可能按不同顺序到达，图中顺序只是便于阅读。稳定下来后，目录记录 Owner={Cache0}、Sharers 为空。目录负责找到要失效的缓存，请求方缓存负责协调收到的数据和确认；不能说目录先收齐所有 InvAck 再授予数据。

#### 场景三：内存可能旧了，先找 Owner

假设 Cache0 已将 X 改为 20，内存可能还是 10。Cache1 再读 X 时：

```text
Cache1 → Directory：GetS(X)
Directory → Cache0：转发 GetS，原始请求方是 Cache1
Cache0 → Cache1：最新 Data
Cache0 → Directory：最新 Data，用于更新内存
Cache0：M → S
Directory：协调回写，完成后稳定在 S，记录两个 Sharer
```

请求方拿到数据与目录完成内存回写是不同阶段。这里没有要求先将主存更新，再由请求方重新读取主存；拥有者可以直接供数。

### 目录记录怎样驱动源码

目录对每个块使用同一套规则，不为 X、Y 各写一份状态机：

```text
队列消息带有块地址 X
 → in_port 将消息解码为事件
 → trigger(Event:GetS, X)
 → 框架查询 X 的当前目录状态
 → 匹配 transition(当前状态, GetS, 下一状态)
 → action 更新 X 的记录并发送相应消息
```

例如 X 为 I 时，GetS 匹配 `transition({I, S}, GetS, S_m)`；内存响应到达后触发 MemData，再匹配 `transition(S_m, MemData, S)`。trigger 提供“哪个块、发生什么事”，transition 定义“这种状态下怎么处理”。

这就是目录管理的核心：**保存副本关系，依据状态和消息选择动作，等待必要条件后继续推进。** 它不管理 CPU 寄存器，也不代替 DRAM 的时序调度；本例还没有目录侧 TBE，不能把 L1 的内部结构直接搬过来。

### Cache 与目录控制器的职责对照

**Cache 管“我保存的数据和权限”，目录管“同一个块在各个 Cache 之间的副本关系”。**

| 组件 | 保存或管理的内容 | 关注的问题 |
|---|---|---|
| Cache 存储与缓存控制器 | cache line 的具体数据、Tag、本地一致性状态，以及访问处理逻辑 | 我有没有这个块？我的副本能否读写？ |
| 目录控制器 | 每个块的目录状态、Sharers、Owner，以及协调逻辑 | 谁持有副本？谁有最新数据？写之前要让谁失效？ |

例如两个 CPU 的缓存都保存 X：

```text
CPU0 Cache：保存 X 的数据，本地状态为 S
CPU1 Cache：保存 X 的数据，本地状态为 S
Directory：X 的 DirState=S，Sharers={CPU0 Cache, CPU1 Cache}
```

CPU0 要写 X 时，目录协调 CPU1 的副本失效和 CPU0 获取写权限；数据仍由缓存及内存系统保存和传递。

目录管理的是**各缓存对某个块的副本和权限关系，不是 CPU 本身的状态**。CPU 的寄存器、指令执行进度、暂停等状态不由目录控制器管理。缓存行的 M/S/I 也属于每个块的本地副本，不是整个 CPU 或整个 Cache 的统一状态。

## 2. 内部有哪些部分：记录、收发、判断、执行

```mermaid
flowchart TD
    input["输入 MessageBuffer<br/>缓存请求 / 缓存响应 / 内存响应"] --> port["in_port<br/>检查就绪消息，peek 查看内容"]
    port --> event["trigger<br/>将输入识别为状态机事件"]
    entry["DirectoryMemory 中的 Entry<br/>DirState / Sharers / Owner"] --> trans["transition<br/>当前状态 + 事件 → 动作 + 新状态"]
    event --> trans
    trans --> action["action<br/>更新记录、构造消息、移除已处理输入"]
    action --> entry
    action --> output["输出 MessageBuffer<br/>发往缓存或内存系统"]
```

| 部分 | 负责什么 | 源码关键词 |
|---|---|---|
| DirectoryMemory / Entry | 管理按块地址索引的目录记录 | directory、getDirectoryEntry |
| 状态 | 表达副本情况和事务等待阶段 | state_declaration、DirState |
| MessageBuffer | 暂存待处理或待发送的消息 | requestFromCache 等 |
| 输入输出逻辑 | 将队列接入状态机，解码输入 | in_port、out_port、peek、trigger |
| 事件 | 表示发生了什么 | GetS、MemData 等 |
| 状态转移 | 决定当前状态下怎样处理事件 | transition |
| 动作 | 执行更新、发消息或队列操作 | action |
| 参数 | 配置组件与动作时序 | DirectoryMemory、toMemLatency |

**这个教学版目录控制器没有 TBE 表。** `MSI-dir.sm` 明确注明了这一点。不要把 L1 控制器中的 TBE 直接套过来；这里用目录状态、Sharers/Owner、消息字段和队列等配合跟踪处理。其他协议的目录控制器可以有 TBE，必须查看具体实现。

## 3. 目录保存什么：每个块一份记录

### 内存块与 cache line 的关系

这里的块是按 cache line 大小划分的一段内存，也是协议管理的单位。例如块大小为 64B：

```text
内存块 X：0x1000～0x103F，共 64B
    ├─ CPU0 Cache 中保存 X 的副本：一条 cache line
    └─ CPU1 Cache 中保存 X 的副本：一条 cache line
```

内存块指地址对应的数据，cache line 是缓存中保存它的单元。目录按块地址管理，不是为每个字节单独记录所有权。

### Entry：状态、共享者和拥有者

以下为源码字段，省略描述属性：

```slicc
structure(Entry, interface="AbstractCacheEntry", main="false") {
    State DirState;
    NetDest Sharers;
    NetDest Owner;
}
```

| 字段 | 回答的问题 |
|---|---|
| DirState | 该块处于什么一致性情况或等待阶段？ |
| Sharers | 哪些缓存持有共享副本？ |
| Owner | 哪个缓存持有独占的最新副本？ |

NetDest 表达节点集合，可用于多播目的地。Owner 也使用这个类型，但进入目录 M 状态时，本例断言 Owner 只有一个成员、Sharers 为空。

事务完成后的稳定状态示例：

```text
共享：CPU0 的 X=S，CPU1 的 X=S
目录：DirState=S，Sharers={CPU0 Cache, CPU1 Cache}

独占修改：CPU0 的 X=M、值为 20，CPU1 的 X=I，内存可能还是 10
目录：DirState=M，Owner={CPU0 Cache}
```

Owner 针对一个块，不表示该缓存拥有整片内存。临时状态中，记录可能已经为下一步更新，不能把稳定状态的解释机械套入事务中途。MOESI 的 O 拥有者可以与 S 副本共存，本节的独占关系针对 MSI。

### 为什么 Owner 使用 NetDest

`NetDest` 表示网络目标节点集合，支持添加/删除/集合操作。虽然稳定 M 时 Owner 只有一个，但消息 `Destination` 也是 `NetDest`，直接赋值更方便。唯一性由协议逻辑和断言保证，而不是 `NetDest` 类型强制限制。

```text
地址 A: DirState=S, Sharers={Core0, Core1}, Owner={}
地址 B: DirState=M, Sharers={}, Owner={Core2}
地址 C: DirState=I, Sharers={}, Owner={}
```

### 三个稳定状态的不变量

| DirState | Sharers | Owner | 意义 |
|---|---|---|---|
| I | 空 | 空 | 各 Cache 无有效副本 |
| S | 一个或多个 | 空 | 一个或多个 Cache 有干净共享副本 |
| M | 空 | 恰好一个 | 一个 Cache 持有独占修改副本 |

> 这是**稳定状态**的逻辑视图。处于瞬态/在途消息时，某些目录元信息可能已更新，但 Cache 之间的权限转移尚未完成。官方教学代码在 `setState(M)` 时断言 `Owner.count()==1` 且 `Sharers.count()==0`。

### DirectoryMemory：管理目录项，不是 DRAM

```slicc
DirectoryMemory * directory;
Cycles toMemLatency := 1;
```

`getDirectoryEntry(addr)` 查找条目；尚未创建时调用 `directory.allocate(addr, new Entry)` 懒分配，减少宿主机内存开销。DirectoryMemory 保存一致性元数据，不是应用程序数据所在的主存。

`toMemLatency` 是向内存请求队列安排消息时使用的周期延迟，不是完整 DRAM 访问延迟。

## 4. MessageBuffer：目录控制器的收件箱与发件箱

目录控制器使用多个队列收发消息；队列不负责决定谁是 Owner，也不执行一致性协议。

| 队列 | 相对目录的方向 | 内容 / 通道 |
|---|---|---|
| requestFromCache | 输入 | GetS、GetM、PutS、PutM，vnet 0 |
| responseFromCache | 输入 | 缓存回送的 Data，vnet 2 |
| forwardToCache | 输出 | 转发 GetS/GetM、Inv、PutAck，vnet 1 |
| responseToCache | 输出 | 返回 Data，vnet 2 |
| requestToMemory | 输出 | 发给内存系统的 MemoryMsg |
| responseFromMemory | 输入 | 内存数据或写完成确认 |

后两者不是第四、第五个协议 vnet，而是目录与内存侧交互的队列。`network="To"/"From"` 相对于当前控制器，不是相对于 CPU。

```text
Cache 的 requestToDir
 → Ruby 网络 vnet 0
 → Directory 的 requestFromCache
 → 目录处理
 → responseToCache
 → Ruby 网络 vnet 2
 → Cache 的 responseFromDirOrSibling
```

`in_port`、`out_port` 是 SLICC 中接入这些队列的声明，不是新增的 C++ RequestPort/ResponsePort。`peek` 查看消息，输出侧 `enqueue` 构造并排入消息，`dequeue` 移除已处理输入。消息到达后还可能等待就绪时间、资源或可处理的状态，并不保证立即执行。

### 消息与事件速查

| 消息/事件 | 常见发送方 → 接收方 | 作用 |
|---|---|---|
| `GetS` | Cache → Directory | 申请共享读权限及数据 |
| `GetM` | Cache → Directory | 申请独占写权限及必要数据 |
| `Inv` | Directory → Sharers | 要求其他共享副本失效 |
| `InvAck` | 被失效的 Cache → 请求者（教学实现） | 确认该共享副本已失效 |
| `FwdGetS` | Directory → 旧 Owner | 请 M Owner 供数并降为 S |
| `FwdGetM` | Directory → 旧 Owner | 请 M Owner 转移数据/独占权限并失效 |
| `Data` | Memory 经 Directory，或 Owner → 请求者；Owner 也可发往 Directory | 传输数据/作为事务响应 |
| `PutS` | Cache → Directory | 释放干净共享副本 |
| `PutM` | Cache → Directory | 释放 M 副本并提供需写回的数据 |
| `PutAck` | Directory → Cache | 对 Put 的协议确认 |
| `MemData` | Memory → Directory | 内存读返回 |
| `MemAck` | Memory → Directory | 内存写回完成确认 |

`FwdGetS/FwdGetM` 是便于阅读的动作名；在教学代码发往旧 Owner 的 `RequestMsg.Type` 仍是 `GetS/GetM`，目标不同才体现“Forward”。

## 5. 状态：缓存副本情况与目录侧权限

源码的状态声明包含：

```slicc
state_declaration(State, desc="Directory states",
                  default="Directory_State_I") {
    I, AccessPermission:Read_Write, desc="Invalid in the caches.";
    S, AccessPermission:Read_Only,  desc="At least one cache has the blk";
    M, AccessPermission:Invalid,    desc="A cache has the block in M";

    S_D,  AccessPermission:Busy,       desc="Moving to S, but need data";
    S_m,  AccessPermission:Read_Write, desc="In S waiting for mem";
    M_m,  AccessPermission:Read_Write, desc="Moving to M waiting for mem";
    MI_m, AccessPermission:Busy,       desc="Moving to I waiting for ack";
    SS_m, AccessPermission:Busy,       desc="Moving to S waiting for ack";
}
```

语法可以读成 `状态名, 访问权限, 描述;`。State 是类型名，desc 是说明，default 指定初始值。`AccessPermission:Read_Only` 是 SLICC 引用枚举值的语法，类似 C++ 的 `AccessPermission::Read_Only`。

### 为什么目录 I 可读写，M 却是 Invalid

状态名概括缓存中的副本情况，而 AccessPermission 是目录侧数据的访问权限，不能当作 CPU 权限。

| 目录稳定状态 | 缓存副本情况 | 目录侧权限的含义 |
|---|---|---|
| I | 没有缓存持有有效副本 | 内存侧数据可用，Read_Write |
| S | 至少一个干净共享副本 | 内存侧数据可读，Read_Only |
| M | 某缓存拥有独占最新副本 | 内存侧可能过期，Invalid |

M + Invalid 不表示 Owner 的数据无效，也不表示 DRAM 消失。它表示不能将内存侧副本直接作为最新数据来源。AccessPermission 还涉及访问许可，不只是新旧标记。

### 临时状态在等什么

| 状态 | 本例中的主要等待 |
|---|---|
| S_m | 等内存读数据，之后进入 S |
| M_m | 等内存读数据，之后目录进入 M |
| S_D | 已向 M 拥有者转发读取，等它回送数据给目录 |
| MI_m | M 副本逐出后，等内存写完成确认，再进入 I |
| SS_m | 拥有者降级的数据已回送内存，等写完成确认，再进入 S |

大小写有区别，S_D 与 S_m 是不同状态。声明只列出状态，具体变化必须看 transition。目录进入 M 也不等于请求方缓存已经收齐全部 InvAck，两端状态不能混为一谈。

## 6. 事件：将收到的消息识别成“发生了什么”

```text
消息进入队列 → in_port 检查并 peek → trigger(Event:..., 块地址)
 → 当前状态下选择 transition → 执行 action
```

| 输入 | 识别出的事件 | 判断依据 |
|---|---|---|
| GetS / GetM | GetS / GetM | 消息类型 |
| PutS | PutSLast / PutSNotLast | 请求方是否是最后一个共享者 |
| PutM | PutMOwner / PutMNonOwner | 请求方是否仍是目录记录的 Owner |
| 缓存回送 Data | Data | 响应消息类型 |
| 内存读响应 | MemData | MemoryMsg 类型 |
| 内存写响应 | MemAck | MemoryMsg 类型 |

网络消息类型与事件不是一回事。同一个 PutS 会解码为不同事件；PutMNonOwner 可能来自协议竞争中的旧拥有者，不能仅凭名字理解为非法写回。

示例：

```slicc
if (in_msg.Type == CoherenceRequestType:GetS) {
    trigger(Event:GetS, in_msg.addr);
}
```

这些是状态机事件，不是 `EventFunctionWrapper` 对象。状态机事件表达“发生什么事”，gem5 调度事件负责“在什么仿真时间运行相应处理”。

## 7. transition 与 action：怎样作出并执行决定

```slicc
transition({I, S}, GetS, S_m) {
    sendMemRead;
    addReqToSharers;
    popRequestQueue;
}
```

含义是：目录当前为 I 或 S，收到 GetS 时，发起内存读、登记请求方为共享者、移除已接手的请求，并进入 S_m 等待。弹出请求不表示 CPU 读取完成。

action 是可复用动作，常见类别如下：

| 类别 | 动作例子 |
|---|---|
| 内存交互 | sendMemRead、sendDataToMem、sendRespDataToMem |
| 更新目录项 | addReqToSharers、removeReqFromSharers、setOwner、clearOwner |
| 控制缓存 | sendInvToSharers、sendFwdGetS、sendFwdGetM |
| 返回消息 | sendDataToReq、sendPutAck |
| 队列处理 | popRequestQueue、popResponseQueue、popMemQueue、stall |

某些 transition 省略下一状态，表示保持当前状态。例如 M 收到 GetM 时仍为 M，但会转发请求并更新 Owner，保持状态不代表什么都没做。

`stall` 不移除当前消息，等待后续机会处理；不是让宿主机忙循环，也不是整个 gem5 停止。

## 8. 跟通六条完整路径

### 路径 A：冷读，目录 I → S_m → S

假设所有缓存都没有 X 的有效副本，最新数据在内存：

```mermaid
sequenceDiagram
    participant L1 as 请求方 L1
    participant Dir as Directory
    participant Mem as 内存系统
    L1->>Dir: GetS（vnet 0）
    Note over Dir: I → S_m，发起内存读，登记 Sharer
    Dir->>Mem: 读取 X
    Mem-->>Dir: 读数据，触发 MemData
    Dir-->>L1: Data（vnet 2）
    Note over Dir: S_m → S
    Note over L1: IS_D → S，完成 CPU 读取
```

源码入口是 `{I,S} + GetS → S_m`，再到 `S_m + MemData → S`。后者执行 sendDataToReq 和 popMemQueue。

### 路径 B：共享转写，目录 S → M_m → M

假设 CPU0、CPU1 都有 S 副本，CPU0 要写：

1. CPU0 Cache 发 GetM，进入等待数据和确认的临时状态。
2. 目录从 Sharers 中移除请求方，向剩余共享者发送 Inv，记录新 Owner，并发起内存读。
3. 内存数据到达后，目录发 Data，带上确认计数信息，清理 Sharers，进入 M。
4. CPU1 失效后直接向 CPU0 Cache 发 InvAck。
5. CPU0 Cache 等数据和必要确认全部满足后，进入 M 并完成写入。

**确认由请求方缓存协调，不是目录收齐所有 InvAck 才回数据。** 数据与确认可能乱序到达。目录侧 M_m 与缓存侧 IM_AD/SM_AD 是不同状态机中的等待状态。

### 路径 C：读取已有 M 副本，目录 M → S_D → SS_m → S

最新数据在 Owner，不能直接读取内存的旧值：

```text
请求方 Cache → Directory：GetS
Directory → 原 Owner：转发 GetS
Directory：登记请求方及原 Owner 为 Sharers，清空 Owner，进入 S_D
原 Owner：向请求方提供数据，并向目录回送最新数据，降级为 S
Directory：收到 Data 后向内存写回，进入 SS_m
内存写完成 → MemAck → Directory 进入 S
```

请求方可走拥有者供数路径完成读取，不必将“目录等待写回完成”理解为“请求方尚未得到数据”。对照缓存侧 M 收到 FwdGetS 的动作，才能看到两个数据方向。

### 路径 D：M 副本逐出，目录 M → MI_m → I

```slicc
transition(M, PutMOwner, MI_m) {
    sendDataToMem;
    clearOwner;
    sendPutAck;
    popRequestQueue;
}

transition(MI_m, MemAck, I) {
    popMemQueue;
}
```

这里有两个不同确认：

- PutAck：目录发给逐出缓存，确认协议规定的 Put 处理。
- MemAck：内存侧回给目录，确认写操作完成。

**本例在等待 MemAck 之前就发送 PutAck。** 因而收到 PutAck 不能等同于 DRAM 已完成写入。目录用 MI_m 继续表示内存写回尚未完成。

### 路径 E：M 状态下转移独占权

```mermaid
sequenceDiagram
    participant R as Core1 Cache(I)
    participant D as Directory
    participant O as Core0 Cache(M)
    R->>D: GetM(A)
    Note over D: 记录新 Owner，转发给旧 Owner
    D->>O: FwdGetM(A)
    O-->>R: Data(A最新值)
    Note over O: M → I
    Note over R: 完成条件满足后 I → M，执行 Store
```

此过程可能不立即写回 DRAM，最新数据直接传给新 Owner。**同一个时间不能有两个 Cache 同时拥有可执行写入的 M 权限。**

### 路径 F：共享副本逐出

```mermaid
sequenceDiagram
    participant C as Cache(S)
    participant D as Directory
    C->>D: PutS(A)
    Note over D: 从 Sharers 移除 C
    alt 还有其他 Sharer
        Note over D: Directory 保持 S
    else 最后一个 Sharer
        Note over D: Directory S → I
    end
    D-->>C: PutAck
    Note over C: S → SI_A → I
```

PutS/PutM 是本地替换引起的主动释放；收到 Inv/FwdGetM 后的被动失效是另一类事务。缓存侧对照见 [MSI 状态转换与执行流程](gem5_MSI_guide.md)。

## 9. 并发案例：两个 Core 同时 GetM

初始：`Core0=S, Core1=S`，Directory 记录 `Sharers={Core0,Core1}`。

1. 两个 Cache 都执行 Store，发送 GetM 并进入 `SM_AD`。
2. 假设 Directory 先处理 Core0：在 `S` 下执行 `GetM` 转换，给其他 Sharer 发送 Inv，进入 `M_m`。
3. Core1 正在 `SM_AD` 时收到 Inv，按教学版 Cache 状态机转成 `IM_AD`，并发送 InvAck；它自己之前发出的 GetM 并未被丢弃。
4. 在 `M_m` 下第二个 GetM 发生 Stall；Directory 收到第一笔 MemData 后进入 `M`，后续才能处理请求。
5. Directory 在 `M` 下接到 Core1 的 GetM，向当时记录的 Owner 转发 GetM（`FwdGetM`），并将 Owner 元信息切换为 Core1。
6. 若 FwdGetM 比 Data/InvAck 更早到达 Core0，Core0 在 IM_AD/IM_A（或 SM_AD/SM_A）中先 stall 转发请求，直到本次写请求完成；随后提供最新数据并释放权限。Core1 满足响应条件后才能真正进入 M。

```mermaid
sequenceDiagram
    participant C0 as Core0 Cache
    participant D as Directory
    participant C1 as Core1 Cache
    C0->>D: GetM(A)
    C1->>D: GetM(A)
    D->>C1: Inv(A)
    Note over C1: SM_AD → IM_AD；回 InvAck
    C1-->>C0: InvAck
    Note over D: M_m 中 Stall 第二个 GetM
    Note over D: MemData 到达后 M_m → M
    Note over C0: 满足 Data/Ack 后可获得 M
    D->>C0: FwdGetM(A)（随后服务 Core1）
    C0-->>C1: 最新 Data(A)
    Note over C0: M → I
    Note over C1: 最终获得 M
```

这是**示意事件顺序**，不意味着网络消息严格按画图顺序到达。特别是不同 VNet 的消息可能先后交错，必须由瞬态状态和 Ack 逻辑保证正确性。

同一块可以有多个共享读者，或唯一可写者。目录提前更新 Owner 是路由与协调记录的变化，不能直接当作缓存已经取得可写 M 权限。

## 10. 等待、确认顺序与虚拟网络

### 10.1 为什么需要 Stall？

在教学版中，当目录处于 `S_m/M_m/SS_m/MI_m` 并接到 `GetS/GetM` 时，会执行 `stall`；`S_D` 收到新的 GetS/GetM 也会 Stall。避免当前地址尚有未完成的内存/Owner 事务时盲目重入。

```slicc
transition({MI_m, SS_m, S_m, M_m}, {GetS, GetM}) {
    stall;
}
```

这里 `stall` 表示当前消息暂不被消费，并非立刻让 CPU 的指令执行完成，也不等同于把请求丢弃。

### 10.2 Data 与 InvAck 为什么都要等？

- `Data`：提供数据，或承担相应一致性请求的响应内容。
- `InvAck`：证明某个旧共享者已经完成失效。
- 只有收齐所需确认后，新 Owner 才能安全使用独占写权限。
- 不同路径、不同协议可能发送零个或多个 Ack；不要假设永远是固定数量。

### 10.3 MessageBuffer 与 Virtual Network

教学版协议把消息划为不同用途的虚拟网络，Directory 中常见：

| VNet | 典型消息 | 方向 |
|---|---|---|
| 0 | `requestFromCache` | Cache → Directory 请求 |
| 1 | `forwardToCache` | Directory → Cache 转发/失效 |
| 2 | `responseToCache`、`responseFromCache` | 响应消息 |

不同虚拟网络用于分离有依赖关系的消息类别，以帮助避免协议级死锁；**使用多个 VNet 并不自动证明协议无死锁**，还需分析缓存/队列容量、资源持有、通道依赖和仲裁。

### 10.4 Directory 数据一定保存在 DRAM 吗？

不一定。Directory 是元信息组织方式，不等于物理 DRAM；它可以作为目录缓存、片上 LLC 元数据或单独结构实现。**此教学版 `DirectoryMemory` 为整个后备物理地址空间预留指针槽位，并按需分配 Entry**，不能将其直接类推到所有商用 CPU。


本例的 stall 不消费队首消息，也可能阻挡同一输入队列中排在后面的其他地址请求；它不是仅为当前块另建一个独立等待队列。

## 11. 本地 MSI-dir.sm 的 18 条 transition 速查

18 是 transition 声明条数，不是展开后的状态/事件组合数；下表已按当前仓库源码核对。省略下一状态表示保持原状态，集合表示匹配多种状态或事件。队列移除动作的完整顺序请参照源码。

### 11.1 全量 transition 表

| # | 当前状态 | 事件 | 下一状态 | 关键 Action / 意义 |
|---|---|---|---|---|
| 1 | I、S | GetS | S_m | `sendMemRead`、`addReqToSharers`；等待内存读数据 |
| 2 | I | PutSNotLast、PutSLast、PutMNonOwner | I（不变） | `sendPutAck`；确认迟到或非 Owner 释放 |
| 3 | S_m | MemData | S | `sendDataToReq`；向请求者返回数据 |
| 4 | I | GetM | M_m | `sendMemRead`、`setOwner`；等待内存数据 |
| 5 | M_m | MemData | M | `sendDataToReq`、`clearSharers` |
| 6 | S | GetM | M_m | `sendMemRead`、`removeReqFromSharers`、`sendInvToSharers`、`setOwner` |
| 7 | S、S_D、SS_m、S_m | PutSNotLast、PutMNonOwner | 原状态（不变） | 移除 Sharer、发送 PutAck |
| 8 | S | PutSLast | I | 移除最后一个 Sharer、发送 PutAck |
| 9 | M | GetS | S_D | `sendFwdGetS`、新请求者和旧 Owner 进入 Sharers、清除 Owner |
| 10 | M | GetM | M（不变） | `sendFwdGetM`、`clearOwner`、`setOwner`；转移 Owner 记录 |
| 11 | M、M_m、MI_m | PutSNotLast、PutSLast、PutMNonOwner | 原状态（不变） | 发送 PutAck，忽略不需要的数据写回 |
| 12 | M | PutMOwner | MI_m | `sendDataToMem`、`clearOwner`、`sendPutAck` |
| 13 | MI_m | MemAck | I | 内存写回确认，结束释放事务 |
| 14 | S_D | GetS、GetM | S_D（不变） | `stall`，等待旧 Owner 数据 |
| 15 | S_D | PutSLast | S_D（不变） | 移除 Sharer、发送 PutAck |
| 16 | S_D | Data | SS_m | `sendRespDataToMem`，把 Owner 返回的数据写入内存 |
| 17 | SS_m | MemAck | S | 完成写回，进入共享稳定态 |
| 18 | MI_m、SS_m、S_m、M_m | GetS、GetM | 原状态（不变） | `stall`，避免等待内存阶段再处理竞争请求 |

**注意：** 表中的“不变”表示 SLICC 声明没有给出新的状态，而不是没有处理消息。部分 PutS/PutM 分类用于处理在途事务造成的消息乱序，不能简单理解为“全部是正常替换”。

### 11.2 按业务路径记忆，而不是背 18 行

| 场景 | Directory 核心路径 | 相关序号 |
|---|---|---|
| 共享读取（内存供数） | `I/S --GetS--> S_m --MemData--> S` | 1、3 |
| 独占请求（内存供数） | `I/S --GetM--> M_m --MemData--> M` | 4、6、5 |
| Owner 降级共享 | `M --GetS--> S_D --Data--> SS_m --MemAck--> S` | 9、16、17 |
| Owner 转让独占 | `M --GetM--> M`，转发给旧 Owner 并更新记录 | 10 |
| 释放干净副本 | `S --PutSLast--> I`；若还有 Sharer，仍在 S | 7、8 |
| 脏副本写回 | `M --PutMOwner--> MI_m --MemAck--> I` | 12、13 |
| 并发/迟到消息 | 等待中 Stall、PutAck、Sharers 维护 | 2、7、11、14、15、18 |

### 11.3 Directory 状态转换图（主要路径）

```mermaid
flowchart TD
    I["I：无有效 Cache 副本"]
    S["S：共享"]
    M["M：独占 Owner"]
    Sm["S_m：等内存读数据"]
    Mm["M_m：等内存读数据"]
    SD["S_D：等旧 Owner 数据"]
    SSm["SS_m：等内存写回 Ack"]
    MIm["MI_m：等内存写回 Ack"]
    I -->|GetS| Sm
    S -->|GetS| Sm
    Sm -->|MemData| S
    I -->|GetM| Mm
    S -->|GetM + Inv Sharers| Mm
    Mm -->|MemData| M
    M -->|GetS + FwdGetS| SD
    SD -->|Data + Writeback| SSm
    SSm -->|MemAck| S
    M -->|PutMOwner + Writeback| MIm
    MIm -->|MemAck| I
    S -->|PutSLast| I
    M -->|GetM + FwdGetM / Owner 改变| M
```

该图是**主要状态路径**；另外还存在表中所列的自环、PutAck 和 Stall 路径。

### 11.4 与 Cache Controller 状态机怎样配合？

| 请求端 Cache 的目的 | Cache 的典型过程 | Directory 典型过程 |
|---|---|---|
| 读取失效行 | `I → IS_D → S` | `I/S → S_m → S`（从内存）；或 `M → S_D → SS_m → S`（从 Owner） |
| 写入失效行 | `I → IM_AD → [IM_A] → M` | `I/S → M_m → M`，或 `M + GetM` 转发旧 Owner |
| 写入共享行 | `S → SM_AD → [SM_A] → M` | `S + GetM` 使其他 Sharers 失效，随后回复数据和 Ack 数量 |
| 原 Owner 响应其他核读 | `M + FwdGetS → S` | `M → S_D → SS_m → S` |
| 原 Owner 响应其他核写 | `M + FwdGetM → I` | `M + GetM` 保持目录状态 M，但更新 Owner |
| 共享者响应失效 | `S + Inv → I` | `S + GetM` 触发发 Inv，等待必要的确认在请求端完成 |
| 替换共享行 | `S → SI_A → I` | PutSNotLast：记录减少；PutSLast：`S → I` |
| 替换修改行 | `M → MI_A → I` | `M → MI_m → I`（内存写回 Ack 完成后） |

`[IM_A]`、`[SM_A]` 表示是否经过取决于还有没有待收的 InvAck。**Directory 把 Owner 更新成新请求者，不代表这个 Cache 当下已经进入 M**。请求者仍需要获得数据与协议要求的确认。

### 11.5 阅读 transition 的检查顺序

1. **当前 Directory 状态是什么？** 稳态还是等待内存/Owner 的瞬态？
2. **事件从哪个 `in_port` 触发？** `request_in`、`response_in` 还是 `memQueue_in`？
3. **对 `Sharers` / `Owner` 修改了什么？** 是否影响后续消息路由？
4. **向哪个 `out_port` 发了什么消息？** `forward_out`、`response_out` 还是 `memQueue_out`？
5. **最终进入什么状态？** 哪些条件由 Cache Controller 等待，而非 Directory 独立等待？

**高频追问**：`transition(M, GetM)` 为什么没有写下一状态？——因为 Directory 仍保持 M（单 Owner 的全局状态），但 Owner 从旧核转移到新核，数据/权限交接仍在途。

## 12. 阅读顺序、问答与性能建模

推荐阅读顺序：

1. `MSI-msg.sm`：RequestMsg、ResponseMsg、目的地、DataBlk、Acks。
2. `MSI-dir.sm`：`machine` 参数、MessageBuffer、State/Event、Entry。
3. `getDirectoryEntry()` / `getState()` / `setState()`：如何获取目录项、如何校验不变量。
4. `in_port`：如何将 `GetS/GetM/PutS/PutM/MemData/MemAck` 映射为 Event。
5. `action`：`sendMemRead`、`sendInvToSharers`、`sendFwdGetS`、`setOwner`、`clearOwner`。
6. `transition`：将状态 + 事件映射为动作与新状态。
7. 最后结合 `MSI-cache.sm`：追踪 Cache Controller 如何响应 forwarded 消息和 Ack。

示例（官方教学版的核心转换节选）：

```slicc
transition(S, GetM, M_m) {
    sendMemRead;
    removeReqFromSharers;
    sendInvToSharers;
    setOwner;
    popRequestQueue;
}

transition(M, GetS, S_D) {
    sendFwdGetS;
    addReqToSharers;
    addOwnerToSharers;
    clearOwner;
    popRequestQueue;
}
```

这里有个易错点：`sendInvToSharers` 发送后，**请求者在 Cache 端**还需要等待协议要求的 Ack；不能认为 `setOwner` 后 CPU 的 Store 立即完成。

### 常见问题速查

| 问题 | 一句话回答 |
|---|---|
| 为什么需要 Directory？ | 追踪 Sharers/Owner 并定向协调一致性；所有节点都共享时仍可能需要向全部其他共享者发送失效。 |
| `DirState` 和 Cache State 有什么区别？ | 前者是该块的全局目录状态，后者是某个 Cache 的局部权限状态。 |
| 为什么 `Owner` 使用 `NetDest`？ | 与消息 `Destination` 类型一致，方便转发；唯一性由协议/断言保证。 |
| GetS 遇到 M Owner 怎么办？ | 转发 GetS，Owner 提供最新数据并降级，必要时协调写回内存。 |
| GetM 遇到多个 Sharer 怎么办？ | 向其他共享者发 Inv，请求者等待所需 Ack 后获得 M。 |
| 为什么需要 Directory 瞬态状态？ | 处理未知/可变的内存、网络和写回延迟以及未完成事务。 |
| 两个 GetM 同时到达怎么办？ | 序列化/协调请求，暂不能处理的请求 Stall 或按协议重试，不能出现两个可写 M。 |
| `PutS` 与 `PutM` 区别？ | 前者释放干净副本，后者必须处理最新脏数据与写回。 |
| `PutAck` 等于 DRAM 写回完成吗？ | 不一定；教学 MSI 中 PutAck 可先发，目录仍等待 MemAck。 |
| Directory 的性能瓶颈有哪些？ | Directory lookup、Sharer 位向量存储、失效广播/多播、网络延迟和热点行竞争。 |
| Directory 与 Snooping 如何比较？ | Directory 定点协调与记录共享者；Snooping 常监听共享互联上的广播。 |
| MSI 的 M/S 是否必然对应某个唯一内存层级？ | 不一定；权限是协议逻辑，不等于固定的物理数据位置。 |

### 自测题

1. 初始 `I, Sharers={}, Owner={}`；Core0 GetS、Core1 GetS 依次完成后，三个字段是什么？
2. `S, Sharers={C0,C1,C2}`；C2 GetM，哪些 Cache 要收到 Inv？何时 C2 可完成 Store？
3. `M, Owner={C0}`；C1 GetS，谁给 C1 最新数据？Directory 最终 Sharers 和 Owner 是多少？
4. `M, Owner={C0}`；C1 GetM，为什么可不先写回 DRAM？
5. Core0/Core1 同时由 S 发 GetM；Core1 在 SM_AD 收到 Inv 后应该转换成什么状态？
6. PutM 已收到 PutAck，但 Directory 尚在 `MI_m`；新的 GetS 是否应当直接使用 Memory 旧数据？
7. 如果 Sharers 使用 N 位全映射位向量，目录为每个块追踪共享者的位数与 N 是什么关系？

### 性能建模与实验方向

研究正确性之外，还可以测量：

- **GetS/GetM 往返延迟**：目录查找、网络传输、内存读取、Owner 转发分别占多少。
- **Invalidation Fanout**：一次 GetM 让多少共享者失效，消息流量如何随 Core 数增长。
- **Cache-to-Cache Transfer**：旧 Owner 供数相对于 Memory 供数节省或增加多少周期。
- **热点行竞争**：同一地址多核写导致的权限反复迁移与队列等待。
- **瞬态状态驻留时间**：`S_m/M_m/S_D` Stall 持续时间，定位 Directory/Memory/NoC 瓶颈。
- **Garnet 争用**：请求、转发、响应在不同 VNet 中的链路与缓冲竞争。

建议做一个简短实验：2 个 Core 轮流写同一个 Cache Line，然后改为分别写不同 Cache Line，对比 GetM/InvAck 流量、平均访问延迟和总执行时间；同一块内写同一个变量属于真共享；若要观察伪共享，应让两个核分别写同一 Cache Line 内的不同变量，再与将变量分放到不同 Cache Line 的布局对比。

## 13. 分步练习 R4：先把两端对应起来

1. **冷读**：跟踪 GetS → MemData → Data；记录加入 Sharers、发回数据和完成 CPU 读取的时机。
2. **共享转写**：跟踪 GetM → Inv / Data / InvAck；分别写目录和缓存的状态，标明谁维护确认计数。
3. **拥有者供数**：跟踪 M + GetS；区分原 Owner 发给请求方与发给目录的两条 Data。
4. **逐出与写回**：对照 PutS、PutMOwner、PutMNonOwner；标出 PutAck 和 MemAck 的不同含义。
5. **等待与竞争**：查看 S_D、MI_m、SS_m、S_m、M_m 中哪些事件 stall。先理解等待原因，再研究复杂交错。

每条路径填写：

| 块地址 | 目录当前状态 | 输入消息 / 事件 | 动作 | 下一状态 | 缓存侧还在等什么 |
|---|---|---|---|---|---|
| X | I | GetS / GetS | sendMemRead、addReqToSharers | S_m | Data |

**验收**：能区分目录项、消息队列和状态机；知道当前目录没有 TBE；能把数据来源、权限、确认与内存写回分开解释。之后按 [配置与运行](config_and_run.md) 构建并验证，使用日志检验推演，而不是只看程序是否退出。

## 参考资料


1. gem5 官方教程 — MSI Directory implementation：<https://www.gem5.org/documentation/learning_gem5/part3/directory/>
2. gem5 官方教程 — MSI Cache transitions：<https://www.gem5.org/documentation/learning_gem5/part3/cache-transitions/>
3. gem5 官方教程 — Introduction to Ruby：<https://www.gem5.org/documentation/learning_gem5/part3/MSIintro/>
4. gem5 官方教程 — Compiling a SLICC protocol：<https://www.gem5.org/documentation/learning_gem5/part3/MSIbuilding/>

**版本提醒**：本文以官方 Learning gem5 Part 3 教学协议为基准；该文档/协议与当前 gem5 仓库其他 Ruby 协议可能不同，调试时应核对自己的 `MSI-dir.sm` / `MSI-cache.sm` 版本。
