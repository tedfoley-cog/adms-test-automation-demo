/* The handful of STM32F407 / Cortex-M4 registers the IED target touches.
 * Addresses per RM0090 and the ARMv7-M Architecture Reference Manual; kept
 * local so the target builds without the vendor CMSIS/HAL packs. */
#ifndef STM32F4_REGS_H
#define STM32F4_REGS_H

#include <stdint.h>

#define REG32(addr) (*(volatile uint32_t *)(addr))

/* Cortex-M4 system control */
#define SCB_VTOR        REG32(0xE000ED08u)
#define SCB_AIRCR       REG32(0xE000ED0Cu)
#define SCB_CPACR       REG32(0xE000ED88u)
#define SCB_DEMCR       REG32(0xE000EDFCu)
#define DWT_CTRL        REG32(0xE0001000u)
#define DWT_CYCCNT      REG32(0xE0001004u)
#define NVIC_ISER(n)    REG32(0xE000E100u + 4u * (n))
#define NVIC_ICER(n)    REG32(0xE000E180u + 4u * (n))
#define NVIC_ISPR(n)    REG32(0xE000E200u + 4u * (n))
#define NVIC_IPR_BYTE(irq) (*(volatile uint8_t *)(0xE000E400u + (irq)))

#define DEMCR_TRCENA    (1u << 24)
#define DWT_CYCCNTENA   (1u << 0)

/* RCC */
#define RCC_CR          REG32(0x40023800u)
#define RCC_PLLCFGR     REG32(0x40023804u)
#define RCC_CFGR        REG32(0x40023808u)
#define RCC_AHB1ENR     REG32(0x40023830u)
#define RCC_APB1ENR     REG32(0x40023840u)
#define FLASH_ACR       REG32(0x40023C00u)

#define RCC_CR_HSEON    (1u << 16)
#define RCC_CR_HSERDY   (1u << 17)
#define RCC_CR_PLLON    (1u << 24)
#define RCC_CR_PLLRDY   (1u << 25)
#define RCC_APB1ENR_TIM2EN   (1u << 0)
#define RCC_APB1ENR_USART2EN (1u << 17)
#define RCC_AHB1ENR_GPIOAEN  (1u << 0)
#define RCC_AHB1ENR_GPIODEN  (1u << 3)

/* GPIO */
#define GPIOA_MODER     REG32(0x40020000u)
#define GPIOA_AFRL      REG32(0x40020020u)
#define GPIOD_MODER     REG32(0x40020C00u)
#define GPIOD_ODR       REG32(0x40020C14u)

/* TIM2 (32-bit, APB1 timer clock 84 MHz) */
#define TIM2_CR1        REG32(0x40000000u)
#define TIM2_DIER       REG32(0x4000000Cu)
#define TIM2_SR         REG32(0x40000010u)
#define TIM2_EGR        REG32(0x40000014u)
#define TIM2_CNT        REG32(0x40000024u)
#define TIM2_PSC        REG32(0x40000028u)
#define TIM2_ARR        REG32(0x4000002Cu)

/* USART2 (APB1 42 MHz) */
#define USART2_SR       REG32(0x40004400u)
#define USART2_DR       REG32(0x40004404u)
#define USART2_BRR      REG32(0x40004408u)
#define USART2_CR1      REG32(0x4000440Cu)
#define USART_SR_TXE    (1u << 7)

/* IRQ numbers */
#define IRQ_EXTI1       7u   /* used as the protection-task software interrupt */
#define IRQ_EXTI2       8u   /* used as the PMU-task software interrupt */
#define IRQ_TIM2        28u

#endif /* STM32F4_REGS_H */
