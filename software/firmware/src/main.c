/* Inhabit Rev-A joint node — main loop skeleton.
 * Conventions: no heap after init; no blocking in ISRs; faults -> status_flags; fail loud.
 * Implement the TODOs using the stm32-firmware / pcb-bringup skills. Prove SPI+CAN in
 * LOOPBACK before the live bus.
 *
 * MCP2515 /INT is CONFIRMED routed to STM32 PB6 (root CLAUDE.md pin map). The EXTI
 * config below is the real, verified wiring — no longer gated on A3-vs-B6.
 */
#include "can_frame.h"
#include "can_health.h"
#include "mcp2515.h"
#include "enum.h"

#if defined(STM32C011xx) || defined(USE_HAL_DRIVER) || defined(USE_FULL_LL_DRIVER)
/* CubeIDE STM32C0 LL driver headers (exact filenames from the STM32CubeC0
 * package Drivers/STM32C0xx_HAL_Driver/Inc). The top-level "stm32c0xx_ll_*.h"
 * each pull in the CMSIS device header (stm32c011xx.h) which provides the
 * register maps, IRQn_Type (EXTI4_15_IRQn), NVIC_*/SysTick_Config, and the
 * SystemCoreClock global. */
#  include "stm32c0xx_ll_bus.h"
#  include "stm32c0xx_ll_rcc.h"
#  include "stm32c0xx_ll_system.h"   /* LL_FLASH_SetLatency */
#  include "stm32c0xx_ll_utils.h"    /* LL_SetSystemCoreClock */
#  include "stm32c0xx_ll_cortex.h"   /* SysTick / NVIC helpers */
#  include "stm32c0xx_ll_gpio.h"
#  include "stm32c0xx_ll_exti.h"
#  include "stm32c0xx_ll_spi.h"
#  include "stm32c0xx_ll_adc.h"
#  define INHABIT_ON_TARGET 1
#endif

/* =========================================================================
 * BOARD CONFIG — values that depend on the physical Rev-A build.
 * These are compile-time constants, not silicon register defaults; every one
 * that a bench build could get wrong is flagged. Change here, not inline.
 * ========================================================================= */

/* USER CONFIG REQUIRED: target system clock. STM32C011 max SYSCLK is 48 MHz
 * (STM32C011 datasheet §3.6 / RM0490 §6 RCC). board_clock_init() drives HSISYS
 * (HSI48 / HSIDIV) to this and picks flash wait states from it. If you retune
 * HSIDIV or the flash latency below, keep this constant in sync — SysTick and
 * the SPI baud prescaler are both derived from it. */
#define BOARD_SYSCLK_HZ            48000000UL

/* SysTick tick rate: 1 kHz -> tick_1khz / TX cadence + ADC sample scheduling. */
#define BOARD_TICK_HZ             1000UL

/* ADC voltage-regulator stabilization spin. This is a COARSE cycle-count busy
 * wait, NOT a calibrated microsecond delay, and deliberately does not use
 * LL_mDelay (which requires SysTick to already be running — adc_init() runs
 * before systick_init(), so LL_mDelay there would spin forever). At 48 MHz a
 * volatile decrement loop is a few cycles/iter, so this is well over the ADC
 * regulator startup time (tADCVREG_STUP, STM32C011 datasheet — a few us).
 * VERIFY AGAINST DATASHEET: confirm tADCVREG_STUP and that this margin covers it. */
#define BOARD_ADC_REGUL_SPIN      20000u

/* Bounded SPI spin budget: number of TXE/RXNE/BSY poll iterations before a byte
 * is declared timed-out (-> caller raises ST_SPI_FAULT). Sized well above the
 * worst-case bit time at DIV8 (~1.5 us/byte @ 6 MHz) so a healthy bus never
 * trips it, but small enough to never hang the loop. NOT time-calibrated —
 * it is a raw instruction-count guard.
 * USER CONFIG REQUIRED: if you raise SYSCLK or lower the SPI prescaler,
 * re-check this covers >= 2 byte-times of margin. */
#define BOARD_SPI_SPIN_BUDGET     20000u

/* USER CONFIG REQUIRED: MT6701 analog -> STM32 ADC input channel.
 * Pin map (root CLAUDE.md): ENC_ADC = PA0. On STM32C011, PA0 = ADC_IN0.
 * VERIFY AGAINST DATASHEET: STM32C011 datasheet ADC pin/channel table
 * (confirm PA0 maps to ADC channel 0). */
#define BOARD_ENC_ADC_CHANNEL     LL_ADC_CHANNEL_0

/* USER CONFIG REQUIRED: magnet-in-range ADC window for ST_MAGNET_OOB.
 * The MT6701 analog OUT swings ~GND..VDD across a full turn; a de-centered or
 * absent magnet clips or flat-lines. These are placeholder guard rails on the
 * raw 12-bit code (0..4095) and MUST be set from a real magnet sweep on the
 * bench (BENCH_TESTS.md §2.2 / §6 step 4). Also depends on any resistor divider
 * between the MT6701 OUT and PA0 and on Vref. Defaults here only reject the
 * dead-rail extremes. */
#define BOARD_ENC_ADC_MIN         16u
#define BOARD_ENC_ADC_MAX         4079u

/* Encoder oversampling: median-of-N spike rejection (house rule: filter the ADC
 * before publishing). N must be odd for a true median. Raw and filtered are
 * both cheap to expose later; for now we publish the median. */
#define BOARD_ENC_OVERSAMPLE_N    5u

/* set by ISRs, consumed by the main loop */
static volatile uint8_t flag_adc_ready;
static volatile uint8_t flag_can_int;   /* set by EXTI on PB6 falling edge (/INT low) */
static volatile uint8_t tick_1khz;

static inhabit_state_t g_state; /* node_id/chain_index assigned during enumeration */

/* ENUM state machine context. Lives in BSS (no heap). enum_init() in
 * board_init() arms it; enum_step() in the main loop advances it and writes
 * g_state.chain_index + clears ST_NOT_ENUMERATED once this pod is indexed. */
static enum_ctx_t g_enum;

/* MCP2515 SPI handle. transfer() is wired to LL/HAL SPI on target; on host it
 * is replaced by a mock register file in firmware/test. */
static mcp2515_io_t g_can_io;

/* The CAN ID we last transmitted, so the INT-driven RX path can verify the
 * loopback echo (id + len + checksum) against what TX put on the wire. */
static volatile uint32_t g_tx_id;

/* ---- SPI1 chip-select (PA4, software NSS, idle HIGH) --------------------- */
#ifdef INHABIT_ON_TARGET
static inline void cs_low(void)  { LL_GPIO_ResetOutputPin(GPIOA, LL_GPIO_PIN_4); }
static inline void cs_high(void) { LL_GPIO_SetOutputPin(GPIOA, LL_GPIO_PIN_4); }

/* SPI1 pins per root CLAUDE.md pin map: SCK=PA5, MISO=PA6, MOSI=PA7 (alt-fn),
 * CS=PA4 (GP output, idle high). GPIOA clock is enabled here (idempotent with
 * enum_gpio_init's enable). */
static void spi1_gpio_init(void) {
    LL_IOP_GRP1_EnableClock(LL_IOP_GRP1_PERIPH_GPIOA);

    /* CS = PA4: push-pull output, start HIGH (deselected) BEFORE mode switch so
     * no glitch selects the MCP2515 during bring-up. */
    LL_GPIO_SetOutputPin(GPIOA, LL_GPIO_PIN_4);
    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_4, LL_GPIO_MODE_OUTPUT);
    LL_GPIO_SetPinOutputType(GPIOA, LL_GPIO_PIN_4, LL_GPIO_OUTPUT_PUSHPULL);
    LL_GPIO_SetPinSpeed(GPIOA, LL_GPIO_PIN_4, LL_GPIO_SPEED_FREQ_HIGH);

    /* VERIFY AGAINST DATASHEET AF TABLE: STM32C011 datasheet "Alternate function
     * mapping" — SPI1_SCK/MISO/MOSI on PA5/PA6/PA7. On STM32C0 these are AF0.
     * A WRONG AF NUMBER = no clock/data on the pins and every CANSTAT read
     * returns garbage (BENCH_TESTS.md §5 gate). Confirm AF0 before first power. */
    const uint32_t spi_af = LL_GPIO_AF_0;
    const uint32_t spi_pins = LL_GPIO_PIN_5 | LL_GPIO_PIN_6 | LL_GPIO_PIN_7;

    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_5, LL_GPIO_MODE_ALTERNATE);
    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_6, LL_GPIO_MODE_ALTERNATE);
    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_7, LL_GPIO_MODE_ALTERNATE);
    LL_GPIO_SetAFPin_0_7(GPIOA, LL_GPIO_PIN_5, spi_af);
    LL_GPIO_SetAFPin_0_7(GPIOA, LL_GPIO_PIN_6, spi_af);
    LL_GPIO_SetAFPin_0_7(GPIOA, LL_GPIO_PIN_7, spi_af);
    /* SCK/MOSI push-pull, high speed; MISO input-driven by MCP2515 (AF handles
     * direction). No pulls on SCK/MOSI. MISO pull-up guards a floating line when
     * the MCP2515 is absent so reads come back 0xFF (detectable) not random. */
    LL_GPIO_SetPinOutputType(GPIOA, spi_pins, LL_GPIO_OUTPUT_PUSHPULL);
    LL_GPIO_SetPinSpeed(GPIOA, LL_GPIO_PIN_5, LL_GPIO_SPEED_FREQ_HIGH);
    LL_GPIO_SetPinSpeed(GPIOA, LL_GPIO_PIN_7, LL_GPIO_SPEED_FREQ_HIGH);
    LL_GPIO_SetPinPull(GPIOA, LL_GPIO_PIN_6, LL_GPIO_PULL_UP);
}

/* SPI1: master, mode 0,0, 8-bit, MSB-first, software NSS, baud <= 10 MHz.
 * MCP2515 samples on the rising edge with CPOL=0/CPHA=0 (Microchip MCP2515
 * DS20001801 §12.0 "SPI mode 0,0 and 1,1 supported"). RM0490 §26 SPI. */
static void spi1_init(void) {
    /* SPI1 is on APBENR2 (RM0490 §6 RCC). VERIFY AGAINST RM0490: on STM32C0 the
     * LL bus group for APBENR2 peripherals is LL_APB1_GRP2_* (mirrors STM32G0). */
    LL_APB1_GRP2_EnableClock(LL_APB1_GRP2_PERIPH_SPI1);

    LL_SPI_InitTypeDef s = {0};
    s.TransferDirection = LL_SPI_FULL_DUPLEX;
    s.Mode              = LL_SPI_MODE_MASTER;
    s.DataWidth         = LL_SPI_DATAWIDTH_8BIT;
    s.ClockPolarity     = LL_SPI_POLARITY_LOW;   /* CPOL=0 (RM0490 SPI_CR1 CPOL) */
    s.ClockPhase        = LL_SPI_PHASE_1EDGE;     /* CPHA=0 -> mode 0,0          */
    s.NSS               = LL_SPI_NSS_SOFT;        /* software CS on PA4          */
    /* Baud = f_PCLK / 8. At PCLK = 48 MHz -> 6 MHz, under the MCP2515 10 MHz max
     * (DS20001801 §12.0). USER CONFIG REQUIRED: on a long/noisy daisy-chain SPI
     * run, drop to DIV16 for margin. */
    s.BaudRate          = LL_SPI_BAUDRATEPRESCALER_DIV8;
    s.BitOrder          = LL_SPI_MSB_FIRST;       /* MCP2515 is MSB-first        */
    s.CRCCalculation    = LL_SPI_CRCCALCULATION_DISABLE;
    s.CRCPoly           = 7;
    (void)LL_SPI_Init(SPI1, &s);

    /* CRITICAL (RM0490 §26 SPI_CR2 FRXTH): with 8-bit frames the RX FIFO must
     * flag RXNE at 1/4 (8 bits), else RXNE only sets after 16 bits are clocked
     * and every single-byte read hangs the bounded wait -> false ST_SPI_FAULT. */
    LL_SPI_SetRxFIFOThreshold(SPI1, LL_SPI_RX_FIFO_TH_QUARTER);

    LL_SPI_Enable(SPI1);
}
#endif /* INHABIT_ON_TARGET */

/* One CS-framed full-duplex SPI1 exchange (CS=PA4, SCK=PA5, MISO=PA6, MOSI=PA7).
 * Per byte: bounded-wait TXE -> write DR (8-bit) -> bounded-wait RXNE -> read DR,
 * then wait !BSY before releasing CS. Returns 0 on success, non-zero on ANY
 * timeout so the caller raises ST_SPI_FAULT and keeps the loop alive. All spins
 * are bounded (BOARD_SPI_SPIN_BUDGET) — never infinite.
 * NOT ISR-CALLABLE: it busy-waits on the SPI FIFO (house rule: no blocking in
 * ISRs). Only the main loop (via the MCP2515 driver) may call it. */
static int spi_transfer(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n) {
    (void)ctx;
#ifdef INHABIT_ON_TARGET
    cs_low();
    for (uint16_t i = 0; i < n; ++i) {
        uint32_t spin;

        /* Wait for TX FIFO space (RM0490 §26 SPI_SR TXE). */
        for (spin = 0; !LL_SPI_IsActiveFlag_TXE(SPI1); ++spin)
            if (spin >= BOARD_SPI_SPIN_BUDGET) { cs_high(); return 1; }
        LL_SPI_TransmitData8(SPI1, tx ? tx[i] : 0xFFu);

        /* Wait for the simultaneous RX byte (RM0490 §26 SPI_SR RXNE). Full-duplex
         * clocks one byte in for each byte out, so this always eventually sets on
         * healthy silicon; the budget bounds a stuck/absent MCP2515. */
        for (spin = 0; !LL_SPI_IsActiveFlag_RXNE(SPI1); ++spin)
            if (spin >= BOARD_SPI_SPIN_BUDGET) { cs_high(); return 1; }
        uint8_t got = LL_SPI_ReceiveData8(SPI1);
        if (rx) rx[i] = got;
    }
    /* Ensure the last bit has left the shift register before deselecting
     * (RM0490 §26 SPI_SR BSY) so CS does not cut the frame short. */
    for (uint32_t spin = 0; LL_SPI_IsActiveFlag_BSY(SPI1); ++spin)
        if (spin >= BOARD_SPI_SPIN_BUDGET) { cs_high(); return 1; }
    cs_high();
    return 0;
#else
    (void)tx; (void)rx; (void)n;
    return 1; /* host build: no SPI peripheral -> reports fault, loop stays alive */
#endif
}

/* ---- MCP2515 /INT on PB6 via EXTI (active-low, falling edge) -------------
 * Pin map (root CLAUDE.md, CONFIRMED): MCP2515 /INT -> STM32 PB6.
 * PB6 is configured as a digital input with pull-up (/INT is open-drain,
 * active-low). EXTI line 6 is mapped to port B, triggered on the FALLING edge
 * (/INT asserts low when an enabled CANINTE source fires). The ISR does ONE
 * thing: set flag_can_int. No SPI, no HAL_Delay, no blocking (house rule) —
 * the actual RXB0 read happens in the main loop. */
static void mcp_int_exti_init(void) {
#ifdef INHABIT_ON_TARGET
    /* Clock the GPIOB bank (EXTI mux on C0 lives in EXTI, fed by SYSCFG/EXTI). */
    LL_IOP_GRP1_EnableClock(LL_IOP_GRP1_PERIPH_GPIOB);

    /* PB6: input, pull-up (idle high; /INT pulls low to assert). */
    LL_GPIO_SetPinMode(GPIOB, LL_GPIO_PIN_6, LL_GPIO_MODE_INPUT);
    LL_GPIO_SetPinPull(GPIOB, LL_GPIO_PIN_6, LL_GPIO_PULL_UP);

    /* Route EXTI line 6 to port B, falling-edge trigger, unmask the line. */
    LL_EXTI_SetEXTISource(LL_EXTI_CONFIG_PORTB, LL_EXTI_CONFIG_LINE6);
    LL_EXTI_DisableRisingTrig_0_31(LL_EXTI_LINE_6);
    LL_EXTI_EnableFallingTrig_0_31(LL_EXTI_LINE_6);
    LL_EXTI_EnableIT_0_31(LL_EXTI_LINE_6);

    /* EXTI lines 4..15 share IRQn EXTI4_15_IRQn on STM32C0. */
    NVIC_SetPriority(EXTI4_15_IRQn, 1);
    NVIC_EnableIRQ(EXTI4_15_IRQn);
#endif
}

#ifdef INHABIT_ON_TARGET
/* EXTI4_15 handler: PB6 falling edge = MCP2515 /INT asserted. Set the flag and
 * clear the pending bit. NOTHING else here — no SPI, no blocking (house rule). */
void EXTI4_15_IRQHandler(void) {
    if (LL_EXTI_IsActiveFallingFlag_0_31(LL_EXTI_LINE_6)) {
        LL_EXTI_ClearFallingFlag_0_31(LL_EXTI_LINE_6);
        flag_can_int = 1u;
    }
}
#endif

/* ---- ENUM line GPIO (pin map root CLAUDE.md): ENUM_IN=PA1, ENUM_OUT=PA2 ----
 * ENUM_IN is a digital input (pulled LOW so an unconnected first-in-chain pod
 * reads de-asserted, never falsely enumerating). ENUM_OUT is a push-pull output
 * driven LOW until this pod is enumerated, then HIGH to wake the next pod. The
 * FSM is host-testable because it only takes/returns bools; these helpers are
 * the thin pin layer. None of this runs in an ISR. */
static void enum_gpio_init(void) {
#ifdef INHABIT_ON_TARGET
    LL_IOP_GRP1_EnableClock(LL_IOP_GRP1_PERIPH_GPIOA);
    /* PA1 = ENUM_IN: input, pull-down (idle de-asserted). */
    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_1, LL_GPIO_MODE_INPUT);
    LL_GPIO_SetPinPull(GPIOA, LL_GPIO_PIN_1, LL_GPIO_PULL_DOWN);
    /* PA2 = ENUM_OUT: push-pull output, start LOW (next pod stays asleep). */
    LL_GPIO_ResetOutputPin(GPIOA, LL_GPIO_PIN_2);
    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_2, LL_GPIO_MODE_OUTPUT);
    LL_GPIO_SetPinOutputType(GPIOA, LL_GPIO_PIN_2, LL_GPIO_OUTPUT_PUSHPULL);
#endif
}

/* Current ENUM_IN (PA1) level. On host (no target GPIO) this returns false so
 * a host-compiled main never spuriously enumerates. */
static bool enum_in_level(void) {
#ifdef INHABIT_ON_TARGET
    return LL_GPIO_IsInputPinSet(GPIOA, LL_GPIO_PIN_1) ? true : false;
#else
    return false;
#endif
}

/* Drive ENUM_OUT (PA2) to the level the FSM requests in ctx->enum_out. */
static void enum_out_drive(bool level) {
#ifdef INHABIT_ON_TARGET
    if (level) LL_GPIO_SetOutputPin(GPIOA, LL_GPIO_PIN_2);
    else       LL_GPIO_ResetOutputPin(GPIOA, LL_GPIO_PIN_2);
#else
    (void)level;
#endif
}

/* ---- Clock tree: HSISYS -> SYSCLK at BOARD_SYSCLK_HZ --------------------- */
/* STM32C011 runs from the internal 48 MHz RC (HSI48). SYSCLK = HSISYS =
 * HSI48 / HSIDIV (RM0490 §6 RCC, RCC_CR HSIDIV). For 48 MHz we divide by 1.
 * Flash needs 1 wait state above 24 MHz (RM0490 §3 FLASH_ACR LATENCY). We raise
 * latency BEFORE raising the clock (order matters: too-fast flash with 0 WS
 * corrupts fetches). AHB/APB prescalers = 1, so HCLK = PCLK = SYSCLK. */
static void board_clock_init(void) {
#ifdef INHABIT_ON_TARGET
    /* 1 WS covers up to 48 MHz. VERIFY AGAINST RM0490 §3.3.3: confirm the flash
     * latency vs SYSCLK threshold table for STM32C0 (0 WS <=24 MHz, 1 WS <=48). */
    LL_FLASH_SetLatency(LL_FLASH_LATENCY_1);
    while (LL_FLASH_GetLatency() != LL_FLASH_LATENCY_1) { /* bounded by HW */ }

    /* Bring up / confirm the internal oscillator. */
    LL_RCC_HSI_Enable();
    while (LL_RCC_HSI_IsReady() != 1U) { /* HW-bounded ready wait */ }

    /* HSISYS = HSI48 / 1 = 48 MHz. VERIFY AGAINST RM0490 §6: the reset value of
     * HSIDIV is NOT /1 on STM32C0, so this divider MUST be set explicitly to
     * reach 48 MHz — do not assume the post-reset clock is already 48 MHz. */
    LL_RCC_SetHSIDiv(LL_RCC_HSI_DIV_1);

    LL_RCC_SetAHBPrescaler(LL_RCC_SYSCLK_DIV_1);
    LL_RCC_SetAPB1Prescaler(LL_RCC_APB1_DIV_1);

    LL_RCC_SetSysClkSource(LL_RCC_SYS_CLKSOURCE_HSISYS);
    while (LL_RCC_GetSysClkSource() != LL_RCC_SYS_CLKSOURCE_STATUS_HSISYS) { }

    /* Keep the CMSIS SystemCoreClock global honest for LL_mDelay / SysTick. */
    LL_SetSystemCoreClock(BOARD_SYSCLK_HZ);
#endif
}

/* ---- SysTick: 1 kHz tick for tick_1khz + ADC sample scheduling ----------- */
static void systick_init(void) {
#ifdef INHABIT_ON_TARGET
    /* CMSIS SysTick_Config: reload = core clock / tick rate, enables the IRQ.
     * Non-zero return = reload out of range (should not happen at these values). */
    (void)SysTick_Config((uint32_t)(BOARD_SYSCLK_HZ / BOARD_TICK_HZ));
    /* Lower urgency than the /INT EXTI (priority 1) so a CAN edge preempts tick
     * bookkeeping. M0+ has 2 priority bits (0..3). */
    NVIC_SetPriority(SysTick_IRQn, 2);
#endif
}

#ifdef INHABIT_ON_TARGET
/* 1 kHz tick. ISR house rule: touch flags only, no SPI/ADC/blocking here.
 * tick_1khz drives the TX cadence; flag_adc_ready schedules one encoder sample
 * per ms, serviced (the actual bounded ADC read) back in the main loop. */
void SysTick_Handler(void) {
    tick_1khz = 1u;
    flag_adc_ready = 1u;
}
#endif

/* ---- ADC on PA0 (MT6701 analog OUT), 12-bit single conversion ------------ */
/* RM0490 §15 ADC. PA0 = ADC_IN0 (see BOARD_ENC_ADC_CHANNEL). Polled single
 * conversion: this is main-loop code, never an ISR. */
static void adc_init(void) {
#ifdef INHABIT_ON_TARGET
    /* PA0 -> analog mode, no pull (RM0490 §11 GPIO; analog disconnects the
     * Schmitt trigger). */
    LL_IOP_GRP1_EnableClock(LL_IOP_GRP1_PERIPH_GPIOA);
    LL_GPIO_SetPinMode(GPIOA, LL_GPIO_PIN_0, LL_GPIO_MODE_ANALOG);
    LL_GPIO_SetPinPull(GPIOA, LL_GPIO_PIN_0, LL_GPIO_PULL_NO);

    /* ADC is on APBENR2. VERIFY AGAINST RM0490 §6: LL bus group + ADC macro
     * name for STM32C0 (mirrors STM32G0: LL_APB1_GRP2_PERIPH_ADC1). */
    LL_APB1_GRP2_EnableClock(LL_APB1_GRP2_PERIPH_ADC1);

    /* Synchronous clock from PCLK/4 keeps the ADC well inside its fMAX
     * regardless of the 48 MHz SYSCLK. VERIFY AGAINST RM0490 §15: enum name
     * LL_ADC_CLOCK_SYNC_PCLK_DIV4 and that PCLK/4 is within the ADC clock spec. */
    LL_ADC_SetClock(ADC1, LL_ADC_CLOCK_SYNC_PCLK_DIV4);
    LL_ADC_SetResolution(ADC1, LL_ADC_RESOLUTION_12B);
    LL_ADC_SetDataAlignment(ADC1, LL_ADC_DATA_ALIGN_RIGHT);
    LL_ADC_SetLowPowerMode(ADC1, LL_ADC_LP_MODE_NONE);

    /* Long common sampling time: the MT6701 analog OUT (and any series divider
     * to PA0) is a relatively high-impedance source, so charge the sample cap
     * fully to avoid a droopy/noisy code. USER CONFIG REQUIRED: tune vs the real
     * source impedance / divider. VERIFY AGAINST RM0490 §15 for the exact
     * sampling-time enum names on STM32C0. */
    LL_ADC_SetSamplingTimeCommonChannels(ADC1, LL_ADC_SAMPLINGTIME_COMMON_1,
                                         LL_ADC_SAMPLINGTIME_79CYCLES_5);
    LL_ADC_REG_SetSequencerChannels(ADC1, BOARD_ENC_ADC_CHANNEL);
    LL_ADC_SetChannelSamplingTime(ADC1, BOARD_ENC_ADC_CHANNEL,
                                  LL_ADC_SAMPLINGTIME_COMMON_1);
    LL_ADC_REG_SetContinuousMode(ADC1, LL_ADC_REG_CONV_SINGLE);
    LL_ADC_REG_SetTriggerSource(ADC1, LL_ADC_REG_TRIG_SOFTWARE);

    /* Enable the ADC internal regulator, then self-calibrate (both mandatory on
     * STM32C0/G0 ADC before the first conversion — RM0490 §15). LL_mDelay uses
     * the SystemCoreClock set in board_clock_init(). */
    LL_ADC_DisableDeepPowerDown(ADC1);
    LL_ADC_EnableInternalRegulator(ADC1);
    /* Bounded cycle spin for regulator stabilization — NOT LL_mDelay (SysTick is
     * not yet running at this point in board_init; see BOARD_ADC_REGUL_SPIN). */
    for (volatile uint32_t d = 0; d < BOARD_ADC_REGUL_SPIN; ++d) { __NOP(); }

    LL_ADC_StartCalibration(ADC1);
    for (uint32_t spin = 0; LL_ADC_IsCalibrationOnGoing(ADC1); ++spin)
        if (spin >= BOARD_SPI_SPIN_BUDGET) break; /* bounded; fail-open to enable */

    LL_ADC_Enable(ADC1);
    for (uint32_t spin = 0; !LL_ADC_IsActiveFlag_ADRDY(ADC1); ++spin)
        if (spin >= BOARD_SPI_SPIN_BUDGET) break; /* bounded ADRDY wait */
#endif
}

/* One bounded 12-bit conversion on the encoder channel. Returns 0 and writes
 * *out on success; non-zero on EOC timeout (caller raises ST_ADC_FAULT).
 * Main-loop only (busy-waits EOC). */
static int adc_read_encoder(uint16_t *out) {
#ifdef INHABIT_ON_TARGET
    LL_ADC_REG_StartConversion(ADC1);
    for (uint32_t spin = 0; !LL_ADC_IsActiveFlag_EOC(ADC1); ++spin)
        if (spin >= BOARD_SPI_SPIN_BUDGET) return 1;
    *out = (uint16_t)LL_ADC_REG_ReadConversionData12(ADC1); /* clears EOC */
    return 0;
#else
    (void)out;
    return 1; /* host build: no ADC -> reports fault */
#endif
}

/* Board bring-up (root CLAUDE.md pin map). Order follows firmware/CLAUDE.md
 * "don't skip": clocks -> GPIO -> ADC -> SPI -> MCP2515 -> EXTI. All silicon
 * setup is guarded by INHABIT_ON_TARGET so the host build stays pure logic. */
static void board_init(void) {
    /* Clocks first: SPI baud, ADC clock, SysTick reload and LL_mDelay all depend
     * on SYSCLK being at BOARD_SYSCLK_HZ. */
    board_clock_init();

    g_state.status_flags = ST_NOT_ENUMERATED;
    g_can_io.transfer = spi_transfer;
    g_can_io.ctx = 0;

    /* Arm the ENUM state machine: starts in ENUM_WAIT, chain_index unset, this
     * pod fails loud via ST_NOT_ENUMERATED (already set above) until indexed. */
    enum_init(&g_enum);
    enum_gpio_init();

    /* Encoder ADC (PA0) then SPI1 (PA4-7). ADC before SPI matches the bring-up
     * order; neither depends on the other. */
    adc_init();
#ifdef INHABIT_ON_TARGET
    spi1_gpio_init();
    spi1_init();
#endif
    /* Bring the MCP2515 up in LOOPBACK for bring-up (no transceiver/bus needed).
     * init() enables CANINTE (RX + error sources) so /INT asserts on RX.
     * Failure latches ST_SPI_FAULT/ST_CAN_FAULT; the loop keeps running. */
    mcp_status_t st = mcp2515_init(&g_can_io, MCP_MODE_LOOPBACK);
    if (st == MCP_ERR_SPI)        g_state.status_flags |= ST_SPI_FAULT;
    else if (st != MCP_OK)        g_state.status_flags |= ST_CAN_FAULT;

    /* Now that CANINTE is live, arm the PB6 EXTI that watches /INT. */
    mcp_int_exti_init();

    /* Last: start the 1 kHz tick so the TX cadence + ADC scheduling only begin
     * once every peripheral above is configured. */
    systick_init();
}

/* Median filter for the oversampled encoder window: robust to single ADC spikes
 * (house rule: filter before publishing) and pure/host-compilable. Sorts a small
 * fixed buffer in place (N is BOARD_ENC_OVERSAMPLE_N, tiny). */
static uint16_t median_u16(uint16_t *v, uint32_t n) {
    for (uint32_t i = 1; i < n; ++i) {
        uint16_t key = v[i];
        uint32_t j = i;
        while (j > 0 && v[j - 1] > key) { v[j] = v[j - 1]; --j; }
        v[j] = key;
    }
    return v[n / 2];
}

/* Oversample the MT6701 analog channel, median-filter, range-check, and return a
 * raw 12-bit ADC code for the schema-v1 frame. Fails loud via status_flags:
 *   - any bounded ADC read timeout            -> ST_ADC_FAULT
 *   - filtered code outside the magnet window -> ST_MAGNET_OOB
 * A clean read clears both bits (non-sticky, mirrors the CAN health policy).
 * The raw->millideg mapping (calib.c) is applied by the caller once calibration
 * params exist; here we only publish the filtered raw code. */
static uint16_t encoder_read_raw(void) {
    uint16_t samples[BOARD_ENC_OVERSAMPLE_N];
    uint8_t  fault = 0;

    for (uint32_t i = 0; i < BOARD_ENC_OVERSAMPLE_N; ++i) {
        uint16_t s = 0;
        if (adc_read_encoder(&s) != 0) { fault = 1; s = 0; }
        samples[i] = s;
    }

    if (fault) {
        g_state.status_flags |= ST_ADC_FAULT;
        return g_state.angle_raw_adc; /* hold last good code; fault is on the wire */
    }
    g_state.status_flags &= (uint8_t)~ST_ADC_FAULT;

    uint16_t raw = median_u16(samples, BOARD_ENC_OVERSAMPLE_N);

    /* USER CONFIG REQUIRED: magnet-in-range window (BOARD_ENC_ADC_MIN/MAX) must
     * come from a real sweep. A de-centered/absent magnet clips the ramp. */
    if (raw < BOARD_ENC_ADC_MIN || raw > BOARD_ENC_ADC_MAX)
        g_state.status_flags |= ST_MAGNET_OOB;
    else
        g_state.status_flags &= (uint8_t)~ST_MAGNET_OOB;

    return raw;
}

/* TX path — TICK / loopback driven. Packs the current state into a schema-v1
 * frame and transmits on TXB0, then polls TXB0CTRL.TXREQ for TX-complete (TX is
 * deliberately NOT on the INT path; TXnIE is disabled). In loopback this TX
 * loops back internally, which sets RX0IF and asserts /INT -> the RX is then
 * serviced by can_rx_service() via flag_can_int (no double-service: TX here,
 * RX there). Any SPI error -> ST_SPI_FAULT; any CAN-layer error -> ST_CAN_FAULT. */
static void can_tx_tick(void) {
    uint8_t frame[INHABIT_DLC];
    inhabit_pack(&g_state, frame);
    uint32_t id = inhabit_can_id(g_state.node_id);
    g_tx_id = id; /* remembered for the INT-driven echo check */

    mcp_status_t st = mcp2515_send_std(&g_can_io, id, frame, INHABIT_DLC);
    if (st == MCP_OK) st = mcp2515_poll_tx_done(&g_can_io, 1000u);

    /* TX-only health: a clean send is not yet a full round-trip, so do NOT clear
     * faults here (that is the RX path's job). Only SET on a real TX failure. */
    if (st == MCP_ERR_SPI)      g_state.status_flags |= ST_SPI_FAULT;
    else if (st != MCP_OK)      g_state.status_flags |= ST_CAN_FAULT;
}

/* RX path — INT driven. Called only when flag_can_int says /INT asserted, so the
 * poll budget is 1 (RX0IF is already set). Reads RXB0, verifies the loopback
 * echo (id + len + checksum) against the last TX, and applies the uniform
 * fault-bit policy (can_health_apply): a healthy round-trip CLEARS both
 * ST_SPI_FAULT and ST_CAN_FAULT; failures fail loud. */
static void can_rx_service(void) {
    uint32_t rid = 0; uint8_t rlen = 0; uint8_t rbuf[INHABIT_DLC] = {0};
    mcp_status_t st = mcp2515_poll_recv(&g_can_io, 1u, &rid, rbuf, &rlen);

    bool roundtrip_ok = false;
    if (st == MCP_OK) {
        inhabit_state_t echoed;
        if (rlen == INHABIT_DLC && inhabit_unpack(rbuf, &echoed)) {
            if (rid == g_tx_id) {
                /* Our own loopback/echo: validates the SPI+CAN round-trip. */
                roundtrip_ok = true;
            } else {
                /* A peer's schema-v1 frame. Feed its chain_index to the ENUM
                 * engine so we can claim max(peer)+1. enum_notify_peer() is the
                 * ISR-safe latch entry point; the corrupt-0xFF / post-DONE
                 * guards live inside it. We call it from the loop (not the ISR),
                 * but using the safe path keeps the contract uniform. */
                enum_notify_peer(&g_enum, echoed.chain_index);
            }
        }
    }
    g_state.status_flags = can_health_apply(g_state.status_flags, st, roundtrip_ok);
}

/* ENUM tick — advances the FSM with the current ENUM_IN level, lets it write
 * g_state.chain_index and clear ST_NOT_ENUMERATED when this pod is indexed, then
 * drives ENUM_OUT (PA2) from the FSM's request. enum_step() also folds in any
 * peer index latched by enum_notify_peer() from the RX path. Pure logic lives in
 * enum.c (host-tested); this wrapper is only the pin glue. */
static void enum_tick(void) {
    enum_step(&g_enum, &g_state, enum_in_level());
    enum_out_drive(g_enum.enum_out);
}

int main(void) {
    board_init();
    for (;;) {
        if (flag_adc_ready) { g_state.angle_raw_adc = encoder_read_raw(); flag_adc_ready = 0; }

        /* Unambiguous CAN control flow (no double-service race):
         *   - RX is serviced ONLY from the /INT flag (PB6 EXTI sets it). RX is
         *     never polled off the tick, so a frame is consumed exactly once.
         *     The RX path also feeds peer chain_index into the ENUM engine.
         *   - TX is driven ONLY from the 1 kHz tick. In loopback the TX produces
         *     the RX that later raises flag_can_int. */
        if (flag_can_int)   { flag_can_int = 0; can_rx_service(); }
        if (tick_1khz)      { tick_1khz = 0;    can_tx_tick(); }
        enum_tick(); /* assigns g_state.chain_index carried by the schema-v1 frame */
    }
}
