/*
 * ramdump_utils.h — Standalone utilities (zero dependencies)
 */

#ifndef RAMDUMP_UTILS_H__
#define RAMDUMP_UTILS_H__

#ifdef __cplusplus
extern "C" {
#endif

/**
 * String to unsigned long.  Supports hex (0x prefix) and decimal.
 * Does NOT depend on libc strtoul — safe in exception context.
 */
unsigned long ramdump_strtoul(const char *str, int base);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_UTILS_H__ */
