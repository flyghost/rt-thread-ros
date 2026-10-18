/*
 * usb_st_port.h — ST USB Device 栈的 OS/板级契约（只有声明，无实现）
 *
 * 规则（与 app/ramdump/include/ramdump_port.h 同一条）：
 *   本文件及其调用方不得 include rtthread.h / rtdevice.h / board.h。
 *   依赖箭头只朝外：st 栈 -> port -> OS。换 OS 或裸机只需换 port 实现。
 *
 * 当前实现在 port/rtthread/usb_st_port_rtthread.c。
 */
#ifndef __USB_ST_PORT_H__
#define __USB_ST_PORT_H__

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── 生命周期 ───────────────────────────────────────────────────────────── */
/* 在 USBD_Init() 之前调用一次：建信号量/清环形缓冲/（可选）起 echo 线程。
 * 必须允许在调度器未启动时被调用（那时不建线程，只做静态初始化）。 */
void usb_st_port_init(void);

/* ── 时间基 ─────────────────────────────────────────────────────────────── */
/* 单位 ms。用于 USBD_LL_Delay 与库内部超时。 */
uint32_t usb_st_port_tick(void);
void     usb_st_port_delay_ms(uint32_t ms);

/* ── 日志 ───────────────────────────────────────────────────────────────── */
/* 中断上下文安全：实现方只允许 rt_kprintf（不要 rt_mutex/rt_malloc）。 */
void usb_st_port_log(const char *fmt, ...);

/* ── 致命错误 ───────────────────────────────────────────────────────────── */
/* 库内部状态异常时调用。实现方打印文件/行号后原地停机（不触发 HardFault，
 * 以免和 ramdump 的异常捕获策略冲突）。 */
void usb_st_port_fatal(const char *file, int line);

/* ── 数据面 ─────────────────────────────────────────────────────────────── */
/* rx_push：在 USB OUT 完成中断里调用，把一包数据投进环形缓冲并唤醒线程。
 *          实现必须是 O(len) 无阻塞；缓冲满时丢包并计数（不许死等）。
 * rx_pop ：在线程上下文取数据，返回实际拷贝字节数（0 = 当前无数据）。
 *          实现可以在内部阻塞等待，但必须带超时。                        */
void     usb_st_port_rx_push(const uint8_t *data, uint32_t len);
uint32_t usb_st_port_rx_pop(uint8_t *buf, uint32_t len);

/* 丢弃已排队但还没被取走的数据（重新枚举前调用，避免旧数据在新连接上冒出来） */
void     usb_st_port_flush(void);

/* ── 统计（联调时 cat 用）───────────────────────────────────────────────── */
typedef struct {
    uint32_t rx_bytes;
    uint32_t rx_dropped;
    uint32_t tx_bytes;
    uint32_t tx_busy;
} usb_st_port_stats_t;

void usb_st_port_get_stats(usb_st_port_stats_t *out);

#ifdef __cplusplus
}
#endif

#endif /* __USB_ST_PORT_H__ */
