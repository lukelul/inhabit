#ifndef INHABIT_CALIB_H
#define INHABIT_CALIB_H

#include <stdbool.h>
#include <stdint.h>

#define INHABIT_CALIB_BASE_ID 0x300u
#define INHABIT_CALIB_DLC 8u
#define INHABIT_CALIB_ADC_MAX 4095u  /* MT6701 12-bit */

typedef struct {
    float slope;
    float intercept;
} inhabit_calib_params_t;

typedef struct {
    uint16_t raw_adc;
    int16_t calibrated_millideg;
} inhabit_calib_sample_t;

typedef struct {
    uint16_t raw_adc;
    int16_t calibrated_millideg;
    uint8_t node_id;
    uint8_t chain_index;
    uint8_t status_flags;
} inhabit_calib_telemetry_t;

bool inhabit_calib_adc_valid(uint16_t raw_adc);
int32_t inhabit_calib_adc_to_millideg(uint16_t raw_adc, const inhabit_calib_params_t *params);
bool inhabit_calib_fit_linear(const inhabit_calib_sample_t *samples, uint32_t sample_count,
                              inhabit_calib_params_t *params);
uint32_t inhabit_calib_id(uint8_t node_id);
void inhabit_calib_pack(const inhabit_calib_telemetry_t *s, uint8_t out[INHABIT_CALIB_DLC]);
bool inhabit_calib_unpack(const uint8_t in[INHABIT_CALIB_DLC], inhabit_calib_telemetry_t *s);

#endif
