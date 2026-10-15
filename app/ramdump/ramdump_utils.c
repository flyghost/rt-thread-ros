/*
 * ramdump_utils.c — Standalone utilities
 */

#include <stddef.h>
#include "ramdump_utils.h"

unsigned long ramdump_strtoul(const char *str, int base)
{
    unsigned long val = 0;
    int digit;

    if (str == NULL) return 0;

    while (*str == ' ' || *str == '\t') str++;

    if (base == 0) {
        if (str[0] == '0' && (str[1] == 'x' || str[1] == 'X')) {
            base = 16; str += 2;
        } else {
            base = 10;
        }
    } else if (base == 16) {
        if (str[0] == '0' && (str[1] == 'x' || str[1] == 'X'))
            str += 2;
    }

    while (*str) {
        char c = *str;
        if      (c >= '0' && c <= '9') digit = c - '0';
        else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
        else break;

        if (digit >= base) break;
        val = val * base + digit;
        str++;
    }
    return val;
}
