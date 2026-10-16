# YMODEM 协议抽象方案

> **状态（2026-10 整理时标注）：本文档所述改造已全部落地。**
> 归档原因是"已完成的设计稿"，不是"废弃方案"。核对点：
> `ramdump_protocol_ops_t` 见 `app/ramdump/include/ramdump_protocol.h:23`；
> `ramdump_protocol_register()` / `ramdump_session_start()` 见 `app/ramdump/protocol/protocol.c:9,14`；
> 注册点见 `app/ramdump/ramdump_init.c:45,49`；YMODEM 实现见 `app/ramdump/protocol/ymodem/ramdump_ymodem.c:336`。
> 文中 `components/ramdump/` 即现在的 `app/ramdump/`。

## 目标

将 `ramdump_engine.c` 中的 YMODEM 协议封装为 ops 接口，外部不感知协议细节，
后续可替换为自定义协议或 KERMIT/XMODEM-1K 等。

## 接口设计

```c
// include/ramdump_protocol.h

typedef struct {
    int  (*session_start)(void);
    int  (*send_file)(uint32_t addr, uint32_t size, const char *name);
    int  (*session_end)(void);
} ramdump_protocol_ops_t;

void ramdump_protocol_register(const ramdump_protocol_ops_t *ops);

// 对外统一接口
int ramdump_session_start(void);
int ramdump_send_file(uint32_t addr, uint32_t size, const char *name);
int ramdump_session_end(void);
```

### 接口含义

| 接口 | 含义 | YMODEM 实现 |
|------|------|------------|
| `session_start` | 开始传输会话，握手/协商 | 空操作（YMODEM 无会话层） |
| `send_file` | 发送一个命名文件 | Block0 + 等'C' + STX数据块 + EOT |
| `session_end` | 结束传输会话 | 空 Block0（YMODEM 批次结束标记） |

`send_crash` 不再是协议接口——它由 CLI 组合三个基本操作：

```c
int ramdump_send_crash(void) {
    session_start();
    send_file(SRAM_ADDR,  SRAM_SIZE,  "SRAM.bin");
    send_file(CCM_ADDR,   CCM_SIZE,   "CCM.bin");
    send_file(FLASH_ADDR, FLASH_SIZE, "FLASH.bin");
    send_file(NOINIT_ADDR, NOINIT_SIZE, ".noinit.bin");
    session_end();
}
```

## 目录结构

```
components/ramdump/
├── protocol/
│   ├── protocol.c              # 选型 + register（类似 transport/transport.c）
│   └── ymodem/
│       └── ramdump_ymodem.c    # YMODEM 实现（原 ramdump_engine.c）
├── include/
│   └── ramdump_protocol.h      # 协议接口
├── ramdump_cli.c               # 只调用 ramdump_send_region / ramdump_send_crash
└── ramdump_engine.h            # 删除，或只保留 ramdump_crc16
```

## 改动范围

| 文件 | 改动 |
|------|------|
| `include/ramdump_protocol.h` | 新建，定义 ops + 公开接口 |
| `protocol/protocol.c` | 新建，register + 选型（目前只有 YMODEM） |
| `protocol/ymodem/ramdump_ymodem.c` | 从 `ramdump_engine.c` 改名移入，实现 ymodem_ops |
| `ramdump_cli.c` | `ramdump_dump_xxx()` → `ramdump_send_xxx()` |
| `ramdump_engine.c/h` | 删除或精简为只保留 `ramdump_crc16` |
| `SConscript` | 更新路径 |

## CLI 调用对比

```c
// 改前
ramdump_dump_region(addr, size);
ramdump_dump_crash();
ramdump_dump_all();

// 改后
ramdump_send_region(addr, size, "manual.bin");
ramdump_send_crash();
```

## 替换协议

只需实现新的 `ramdump_protocol_ops_t`，在 `protocol.c` 中切换 `#if`：

```c
// protocol/custom.c
const ramdump_protocol_ops_t custom_protocol = {
    .init        = custom_init,
    .send_region = custom_send_region,
    .send_crash  = custom_send_crash,
};
```

其他文件一行不改。
