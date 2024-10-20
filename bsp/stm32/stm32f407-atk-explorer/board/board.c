/*
 * Copyright (c) 2006-2021, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2018-11-06     SummerGift   first version
 */

#include <board.h>
#include <drv_common.h>

uint8_t sys_stm32_clock_init(uint32_t plln, uint32_t pllm, uint32_t pllp, uint32_t pllq)
{
    HAL_StatusTypeDef ret = HAL_OK;
    RCC_OscInitTypeDef rcc_osc_init = {0};
    RCC_ClkInitTypeDef rcc_clk_init = {0};

    __HAL_RCC_PWR_CLK_ENABLE();                                         /* 使能PWR时钟 */

    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);      /* 设置调压器输出电压级别，以便在器件未以最大频率工作 */

    /* 使能HSE，并选择HSE作为PLL时钟源，配置PLL1，开启USB时钟 */
    rcc_osc_init.OscillatorType = RCC_OSCILLATORTYPE_HSE;        /* 时钟源为HSE */
    rcc_osc_init.HSEState = RCC_HSE_ON;                          /* 打开HSE */
    rcc_osc_init.PLL.PLLState = RCC_PLL_ON;                      /* 打开PLL */
    rcc_osc_init.PLL.PLLSource = RCC_PLLSOURCE_HSE;              /* PLL时钟源选择HSE */
    rcc_osc_init.PLL.PLLN = plln;
    rcc_osc_init.PLL.PLLM = pllm;
    rcc_osc_init.PLL.PLLP = pllp;
    rcc_osc_init.PLL.PLLQ = pllq;
    ret = HAL_RCC_OscConfig(&rcc_osc_init);                      /* 初始化RCC */
    if(ret != HAL_OK)
    {
        return 1;                                                /* 时钟初始化失败，可以在这里加入自己的处理 */
    }

    /* 选中PLL作为系统时钟源并且配置HCLK,PCLK1和PCLK2 */
    rcc_clk_init.ClockType = ( RCC_CLOCKTYPE_SYSCLK \
                                    | RCC_CLOCKTYPE_HCLK \
                                    | RCC_CLOCKTYPE_PCLK1 \
                                    | RCC_CLOCKTYPE_PCLK2);

    rcc_clk_init.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;         /* 设置系统时钟时钟源为PLL */
    rcc_clk_init.AHBCLKDivider = RCC_SYSCLK_DIV1;                /* AHB分频系数为1 */
    rcc_clk_init.APB1CLKDivider = RCC_HCLK_DIV4;                 /* APB1分频系数为4 */
    rcc_clk_init.APB2CLKDivider = RCC_HCLK_DIV2;                 /* APB2分频系数为2 */
    ret = HAL_RCC_ClockConfig(&rcc_clk_init, FLASH_LATENCY_5);   /* 同时设置FLASH延时周期为5WS，也就是6个CPU周期 */
    if(ret != HAL_OK)
    {
        return 1;                                                /* 时钟初始化失败 */
    }
    
    /* STM32F405x/407x/415x/417x Z版本的器件支持预取功能 */
    if (HAL_GetREVID() == 0x1001)
    {
        __HAL_FLASH_PREFETCH_BUFFER_ENABLE();                    /* 使能flash预取 */
    }
    return 0;
}

void SystemClock_Config(void)
{
    sys_stm32_clock_init(336, 8, 2, 7);     /* 设置时钟,168Mhz */
}
