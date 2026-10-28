# Part 5 · 第 2 章：MSI 如何通过 Ruby Network 发送消息

> 前置阅读：[Ruby/SLICC](../part3/ruby_slicc.md)、[消息与 MessageBuffer](../part3/ruby_message_source.md)、[Garnet 导读](garnet.md)。
> 本文沿当前仓库的教学 MSI 追踪 GetM，从协议动作到目标控制器。当前教学配置使用 SimpleNetwork；Garnet 的对应路径单独说明。本次整理依据源码，未运行仿真。

## 1. 先看完整路径

MSI 通过 `enqueue` 将协议消息放入输出 MessageBuffer；Ruby Network 消费该队列，将消息送入目标控制器的输入 MessageBuffer，目标控制器再将消息解码为事件。

```text
CPU Store
 → Sequencer → mandatoryQueue
 → Cache 控制器识别 Store 事件
 → transition(I, Store, IM_AD)
 → sendGetM
 → requestToDir（发送队列，VNet 0）
 → Ruby Network
 → Directory 的 requestFromCache（接收队列，VNet 0）
 → in_port 识别 GetM 事件
 → 匹配目录状态转换并执行动作
```

MSI 定义消息的含义和状态变化；网络模型负责传输过程。GetM 入队、到达目录、目录返回 Data，以及 CPU Store 完成，是不同的时刻。

## 2. 状态转换决定什么时候发送

源码：[MSI-cache.sm](../../../src/learning_gem5/part3/MSI-cache.sm)。

```slicc
transition(I, Store, IM_AD) {
    allocateCacheBlock;
    allocateTBE;
    sendGetM;
    popMandatoryQueue;
}
```

Cache 中对应块为 I，CPU 要写时，先准备缓存条目和跟踪事务的 TBE，再发送 GetM，最后移除已接手的 CPU 请求。转换成功后进入 IM_AD，等待数据和必要的失效确认。

若转换所需队列或资源暂不可用，状态机可能暂不能执行该转换；不能把每次 CPU Store 都理解成无条件立即发包。

## 3. action 构造消息并入队

同一文件中的实际发送动作：

```slicc
action(sendGetM, "gM", desc="Send GetM to the directory") {
    enqueue(request_out, RequestMsg, 1) {
        out_msg.addr := address;
        out_msg.Type := CoherenceRequestType:GetM;
        out_msg.Destination.add(mapAddressToMachine(address,
                                MachineType:Directory));
        out_msg.MessageSize := MessageSizeType:Control;
        out_msg.Requestor := machineID;
    }
}
```

| 字段 | 含义 |
|---|---|
| addr | 请求哪个内存块 |
| Type | 请求类型为 GetM |
| Destination | 按地址映射找到负责该块的 Directory |
| MessageSize | 网络建模使用的消息大小类别；GetM 本身是控制消息 |
| Requestor | 原始请求方的 MachineID，便于后续响应路由 |

`enqueue(..., 1)` 中的 1 是入队时安排的周期延迟，按控制器时钟换算；不是整个网络的端到端延迟。随机化等队列设置也可能影响实际就绪时间，具体处理见 MessageBuffer::enqueue。

发送时已经填写目标，不是将 GetM 广播给所有目录，让目录自行判断归属。目标身份也不是 Router 编号，网络还需要将控制器节点映射到拓扑连接。

## 4. out_port 名称怎样关联实际队列

MSI-cache.sm 中有两层声明：

```slicc
MessageBuffer * requestToDir, network="To", virtual_network="0",
    vnet_type="request";

out_port(request_out, RequestMsg, requestToDir);
```

第一层声明控制器参数 requestToDir 是一个向网络发送的队列，使用 VNet 0。第二层把 SLICC 动作中的 request_out 名称绑定到该队列，消息类型为 RequestMsg。

```text
sendGetM 中 enqueue(request_out, ...)
                   ↓
SLICC out_port 声明
                   ↓
requestToDir：实际 MessageBuffer
```

`out_port` 不会额外创建一个物理链路，也不是 CPU 侧的 RequestPort。它是 SLICC 对输出队列的访问声明。

## 5. Python 创建队列并接入网络

源码：[msi_caches.py](../../../configs/learning_gem5/part3/msi_caches.py)。

Cache 侧：

```python
self.requestToDir = MessageBuffer(ordered=True)
self.requestToDir.out_port = ruby_system.network.in_port
```

Directory 侧：

```python
self.requestFromCache = MessageBuffer(ordered=True)
self.requestFromCache.in_port = ruby_system.network.out_port
```

方向以各对象为参照：Cache 输出连接网络输入，网络输出连接 Directory 输入。所有控制器都可以接到同一个网络对象；具体投递由消息目标、节点映射、VNet 与拓扑共同决定，不是把一个消息复制到所有输入队列。

这两段配置只展示端点队列连接，尚不包含完整的 Router、Link 和 NI 创建流程。

## 6. 初始化时，网络怎样知道这些队列

SLICC 根据队列声明生成控制器初始化代码。可从 [StateMachine.py](../../../src/mem/slicc/symbols/StateMachine.py) 的 `initNetQueues` 生成逻辑阅读：它根据 `network="To"/"From"` 生成相应的注册调用。

[Network.cc](../../../src/mem/ruby/network/Network.cc) 中的关键接口是：

- `setToNetQueue(...)`：登记控制器发往网络的队列。
- `setFromNetQueue(...)`：登记网络发往控制器的队列。

可以把内部关联理解为：

```text
m_toNetQueues[本地节点编号][VNet 编号] → 发送队列指针
m_fromNetQueues[本地节点编号][VNet 编号] → 接收队列指针
```

注册参数还包含 ordered 属性和 vnet_type；节点身份会经过网络的全局/本地节点编号转换。它们共同把协议队列接入网络，并不是每次发送时重新建立连接。

## 7. 消息入队后，谁来取走

源码：[MessageBuffer.cc](../../../src/mem/ruby/network/MessageBuffer.cc)。

MessageBuffer::enqueue 将消息按就绪时间放入内部优先队列，并通过消费者安排唤醒：

```cpp
m_consumer->scheduleEventAbsolute(arrival_time);
m_consumer->storeEventInfo(m_vnet_id);
```

到达相应仿真时间后，消费者检查队列是否就绪、是否能继续推进传输。唤醒不意味着一定能成功发送；还可能遇到下游空间、VC、credit 或仲裁限制。

| 网络模型 | 发送侧消费者与主要路径 |
|---|---|
| 当前教学配置 SimpleNetwork | PerfectSwitch 消费端点消息队列，经交换机和缓冲转发 |
| Garnet | NI 消费端点消息队列，拆包为 flit，经 Router/Link 传输 |

本地入口：[SimpleNetwork.cc](../../../src/mem/ruby/network/simple/SimpleNetwork.cc)、[PerfectSwitch.cc](../../../src/mem/ruby/network/simple/PerfectSwitch.cc)、[NetworkInterface.cc](../../../src/mem/ruby/network/garnet/NetworkInterface.cc)。

Garnet 的 NetworkInterface::wakeup 检查各 VNet 的输入 MessageBuffer；`flitisizeMessage()` 成功接手消息后才从该队列移除它。申请不到 VC 时，消息仍可留在协议发送队列中等待。

## 8. 目录收到消息后怎样继续执行

源码：[MSI-dir.sm](../../../src/learning_gem5/part3/MSI-dir.sm)。下面是接收 GetM 的相关分支节选：

```slicc
in_port(request_in, RequestMsg, requestFromCache) {
    if (request_in.isReady(clockEdge())) {
        peek(request_in, RequestMsg) {
            // 省略其他消息类型分支
            if (in_msg.Type == CoherenceRequestType:GetM) {
                trigger(Event:GetM, in_msg.addr);
            }
        }
    }
}
```

trigger 提供块地址和事件，状态机再按该地址当前目录状态选择转换。例如：

```slicc
transition(S, GetM, M_m) {
    sendMemRead;
    removeReqFromSharers;
    sendInvToSharers;
    setOwner;
    popRequestQueue;
}
```

目录为 S 时，发起内存读，移除请求方的共享者记录，要求其余共享者失效，登记 Owner，移除已接手的 GetM，进入 M_m。目录为 M 时则走向旧 Owner 转发 GetM 的路径。

`peek` 只查看消息；输入队列的移除通常由匹配转换中的 popRequestQueue 动作完成。消息到达不代表立即处理：目录可能还处于需要 stall 的瞬态状态。

## 9. 返回消息仍沿同一机制发送

目录发 Data 或 Inv、缓存回 InvAck，都使用各自输出队列和 enqueue 动作；网络按目标与 VNet 将消息送到对应输入队列。

| VNet | 教学 MSI 中的典型消息 |
|---|---|
| 0 | GetS、GetM、PutS、PutM |
| 1 | 转发 GetS/GetM、Inv、PutAck |
| 2 | Data、InvAck |

转发 GetS/GetM 在消息 Type 中仍是 GetS/GetM；缓存输入逻辑将其识别为 FwdGetS/FwdGetM 事件。VNet 负责区分流量类别，VC 是 Garnet 内部的传输资源，两者不能混为一谈。

InvAck 在教学 MSI 中直接从被失效缓存发到请求方缓存；不要求所有响应都先经过 Directory。协议决定消息目标，网络负责送达。

## 10. 当前教学 MSI 与 Garnet 的配置边界

msi_caches.py 中的 MyNetwork 继承 SimpleNetwork，当前消息实际经过简单网络。学习 Garnet 的这条对应路径时，应先区分现有配置与准备替换的网络实现。

若要接入 Garnet，需要调整网络创建、拓扑、Router、Garnet 链路和 NI 初始化，并替换 SimpleNetwork 专用的 setup_buffers 流程。仅给现有教学运行脚本添加 `--network=garnet` 不能完成切换。

可对照 [configs/network/Network.py](../../../configs/network/Network.py) 中通用配置流程，但不能直接假设教学脚本已经调用它。后续传输过程阅读 [Garnet 导读](garnet.md) 的路由器、credit 与单包生命周期章节。

## 11. 阅读自检

1. 能从 sendGetM 找到 request_out、requestToDir 和 Python 创建的 MessageBuffer。
2. 能指出消息的目标、大小类别、原始请求方和 VNet 分别在哪里设置。
3. 能区分 enqueue 安排的延迟与端到端网络延迟。
4. 能说明消息入队如何安排消费者唤醒，为什么唤醒后仍可能等待。
5. 能沿目标 requestFromCache 找到 trigger 和目录 transition。
6. 能区分发送队列移除、目标收到消息、协议事务完成与 CPU Store 完成。
