# Part 3 · 第 3 章：目录控制器状态机（MSI-dir.sm）

> 对应源码：`src/learning_gem5/part3/MSI-dir.sm`（567 行）

## 本章目标

看懂 MSI 协议的 **目录（directory）侧**状态机，理解目录控制器「一身兼两职」。

## 目录控制器的双重角色

在本 MSI 示例中，**目录控制器维护一致性状态，并协调内存请求**；它不替代下游 DRAM 控制器的调度与时序模型：

- 存**一致性状态**：这个块当前在哪些缓存里（sharers）、谁是 owner。
- 直接对接到 gem5 的 `MemCtrl`/DRAM，负责把数据从内存读上来 / 写回去。

## machine 声明与参数

```slicc
machine(MachineType:Directory, "Directory protocol")
    :
      DirectoryMemory * directory;   // 目录存储（懒分配，见下）
      Cycles toMemLatency := 1;      // 到内存的延迟（可配置，有默认值）
{
```

`directory` 是 `DirectoryMemory`：初始只为整个内存分配指针，条目**懒创建**
（第一次访问某地址时才建目录项），省内存。

## MessageBuffer

```slicc
MessageBuffer * forwardToCache,   network="To",   virtual_network="1", vnet_type="forward";
MessageBuffer * responseToCache,  network="To",   virtual_network="2", vnet_type="response";
MessageBuffer * requestFromCache, network="From", virtual_network="0", vnet_type="request";
MessageBuffer * responseFromCache,network="From", virtual_network="2", vnet_type="response";
MessageBuffer * requestToMemory;      // 特殊：发给内存
MessageBuffer * responseFromMemory;   // 特殊：内存响应
```

注意方向正好和 cache 侧相反：cache 的 `requestToDir` 对应目录的 `requestFromCache`。

## 状态声明

```slicc
state_declaration(State, desc="Directory states", default="Directory_State_I") {
    // 稳定态：名字是「cache 视角」，但权限是「memory 视角」，小心！
    I, AccessPermission:Read_Write, desc="缓存里都没有这个块";
    S, AccessPermission:Read_Only,  desc="至少一个缓存有（只读）";
    M, AccessPermission:Invalid,    desc="某缓存独占（Modified）";

    // 瞬态
    S_D,  AccessPermission:Busy,        desc="→S，但需要数据";
    S_m,  AccessPermission:Read_Write,  desc="在 S，等内存数据";
    M_m,  AccessPermission:Read_Write,  desc="→M，等内存数据";
    MI_m, AccessPermission:Busy,        desc="→I，等写回 ack";
    SS_m, AccessPermission:Busy,        desc="→S，等写回 ack";
}
```

**关键坑**：目录状态名是 cache 视角（I/S/M 表示「块在缓存里的分布」），
但 `AccessPermission` 是 memory 视角（Read_Write 表示「内存里是最新的」）。
比如目录 `M` 态表示「某缓存独占 Modified」，此时内存数据是**过期**的，所以
权限是 `Invalid`。

## 事件

```slicc
enumeration(Event, desc="Directory events") {
    GetS, GetM,                  // cache 请求读/写
    PutSNotLast, PutSLast,       // S 逐出（是否还有别的 sharer）
    PutMOwner, PutMNonOwner,     // M 逐出（是否是 owner）
    Data,                        // cache 对 fwd 请求的响应（带回数据）
    MemData, MemAck,             // 来自内存
}
```

注意 `PutS` 分 `PutSLast`/`PutSNotLast`（目录要判断逐出后是否还有 sharer），
`PutM` 分 `PutMOwner`/`PutMNonOwner`——目录必须据此维护正确的 sharers/owner 集合。

## 目录项结构：Sharers + Owner

```slicc
structure(Entry, desc="...", interface="AbstractCacheEntry", main="false") {
    State DirState,     // 目录状态
    NetDest Sharers,    // 哪些缓存有只读副本（位掩码）
    NetDest Owner,      // 谁是独占 owner
}
```

`NetDest` 是「多播目的地掩码」——目录用 `Sharers` 记录谁有 S 副本（用于后续
批量失效），用 `Owner` 记录 M 块的 owner（用于转发请求）。

## 与 cache 侧的分工

```
CPU → Load/Store → L1Cache(状态机) → GetS/GetM → Directory(状态机) → MemCtrl/DRAM
                         ↑                              │
                         └── Data/InvAck（经网络）──────┘
```

- **cache 控制器**：管理「我这一份块是什么状态」，负责响应 CPU 和目录。
- **目录控制器**：管理「这个块在整个系统里的分布」，负责仲裁、转发、对接内存。
- 两者靠 **消息**（GetS/GetM/Data/InvAck/…）通过 Ruby 网络通信。

## 分步练习 R4：目录负责找谁，不替代 DRAM 时序

**重点逻辑：目录根据 sharers/owner 找最新数据与失效对象，并等待内存或缓存响应；内存控制器继续承担存储访问的时序与排队。**

1. **冷读**：找 `{I,S} + GetS → S_m` 与 `S_m + MemData → S`，记录何时加入 sharers、何时返回数据。
2. **共享转写**：找 `S + GetM → M_m`，列出 `removeReqFromSharers`、`sendInvToSharers`、`setOwner`，与 Cache 侧等待 InvAck 的逻辑对应。
3. **脏 owner 转共享**：找 `M + GetS → S_D`，继续追 `S_D + Data → SS_m` 与 `SS_m + MemAck → S`。解释目录为什么不能在收到请求时立刻把事务看作完成。
4. **owner 更换**：找 `M + GetM`，说明转发给旧 owner 与记录新 owner 的关系，区分目录记录更新和请求核真正得到数据/权限的时间。

对每条通路填写：原 sharers/owner → 请求来源 → 发出的消息 → 等待的事件 → 最终 sharers/owner。不要混淆目录的 M 与某个 Cache 的 M：一个是全局管理状态，一个是局部缓存行权限。

**验收**：把 R3 的 CPU0 脏数据交给 CPU1 的路径画成跨模块时序图，Cache、目录、内存分别成一列；每个等待都能指出是谁负责解除。
