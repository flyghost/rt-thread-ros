/*
 * Copyright (c) 2006-2021, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2018-11-06     SummerGift   first version
 * 2018-11-19     flybreak     add stm32f407-atk-explorer bsp
 * 2023-12-03     Meco Man     support nano version
 */

#include <board.h>
#include <rtthread.h>
#include <drv_gpio.h>
#ifndef RT_USING_NANO
#include <rtdevice.h>
#endif /* RT_USING_NANO */

/* defined the LED0 pin: PF9 */
#define LED0_PIN    GET_PIN(F, 9)

static const char str[] = "Hello RT-Thread!\r\n";

int main(void)
{
    /* set LED0 pin mode to output */
    // rt_pin_mode(LED0_PIN, PIN_MODE_OUTPUT);

    rt_device_t vcom = rt_device_find("vcom");

    rt_uint8_t flag = 0;

    if(vcom)
    {
        if(RT_EOK== rt_device_open(vcom, RT_DEVICE_OFLAG_RDWR))
        {
            flag = 1;
        }
    }

    rt_kprintf("this is a stm32f407 p22roject\r\n");

    while (1)
    {
        // rt_pin_write(LED0_PIN, PIN_HIGH);
        // rt_thread_mdelay(500);
        // rt_pin_write(LED0_PIN, PIN_LOW);
        rt_thread_mdelay(500);
        // rt_kprintf("this is a stm32f407 project\r\n");

        if(vcom && flag)
        {
            rt_device_write(vcom, 0, str, sizeof(str));
        }

    }
}
