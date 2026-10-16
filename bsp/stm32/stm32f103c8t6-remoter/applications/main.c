/*
 * Copyright (c) 2006-2021, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2019-03-08     obito0       first version
 * 2023-12-03     Meco Man     support nano version
 */

#include <board.h>
#include <rtthread.h>
#include <drv_gpio.h>
#ifndef RT_USING_NANO
#include <rtdevice.h>
#endif /* RT_USING_NANO */

/* defined the LED0 pin: PA1 */
#define LED0_PIN    GET_PIN(A, 1)

int usbtest(void)
{
    rt_device_t dev = RT_NULL;
    char buf[] = "hello rt-thread!\r\n";

    dev = rt_device_find("vcom");

    if (dev)
        rt_device_open(dev, RT_DEVICE_FLAG_RDWR);
    else
        return -RT_ERROR;

    while (1)
    {
        rt_device_write(dev, 0, buf, rt_strlen(buf));
        rt_thread_mdelay(200);
    }

    return RT_EOK;
}
int main(void)
{
    /* set LED0 pin mode to output */
    // rt_pin_mode(LED0_PIN, PIN_MODE_OUTPUT);

    while (1)
    {
        usbtest();
    }
}
