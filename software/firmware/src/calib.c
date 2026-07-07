#include "calib.h"
#include <float.h>
#include <math.h>

static uint8_t calib_xor7(const uint8_t *b) {
    uint8_t c = 0;
    for (int i = 0; i < 7; ++i) {
        c ^= b[i];
    }
    return c;
}

bool inhabit_calib_adc_valid(uint16_t raw_adc) {
    return raw_adc <= INHABIT_CALIB_ADC_MAX;
}

int32_t inhabit_calib_adc_to_millideg(uint16_t raw_adc, const inhabit_calib_params_t *params) {
    if (params == 0) {
        return 0;
    }
    return (int32_t)((float)raw_adc * params->slope + params->intercept);
}

bool inhabit_calib_fit_linear(const inhabit_calib_sample_t *samples, uint32_t sample_count,
                              inhabit_calib_params_t *params) {
    if (samples == 0 || params == 0 || sample_count < 2u) {
        return false;
    }

    uint32_t i;
    double sum_x = 0.0;
    double sum_y = 0.0;
    double sum_xy = 0.0;
    double sum_xx = 0.0;

    for (i = 0; i < sample_count; ++i) {
        sum_x += (double)samples[i].raw_adc;
        sum_y += (double)samples[i].calibrated_millideg;
        sum_xy += (double)samples[i].raw_adc * (double)samples[i].calibrated_millideg;
        sum_xx += (double)samples[i].raw_adc * (double)samples[i].raw_adc;
    }

    const double lhs = (double)sample_count * sum_xx;
    const double rhs = sum_x * sum_x;
    const double denominator = lhs - rhs;
    const double scale = fabs(lhs) + fabs(rhs);
    if (fabs(denominator) <= DBL_EPSILON * scale) {
        return false;
    }

    params->slope = (float)(((double)sample_count * sum_xy - sum_x * sum_y) / denominator);
    params->intercept = (float)((sum_y - (double)params->slope * sum_x) / (double)sample_count);
    return true;
}

uint32_t inhabit_calib_id(uint8_t node_id) { return INHABIT_CALIB_BASE_ID + node_id; }

void inhabit_calib_pack(const inhabit_calib_telemetry_t *s, uint8_t out[INHABIT_CALIB_DLC]) {
    out[0] = (uint8_t)(s->raw_adc & 0xFFu);
    out[1] = (uint8_t)(s->raw_adc >> 8);
    out[2] = (uint8_t)((uint16_t)s->calibrated_millideg & 0xFFu);
    out[3] = (uint8_t)((uint16_t)s->calibrated_millideg >> 8);
    out[4] = s->node_id;
    out[5] = s->chain_index;
    out[6] = s->status_flags;
    out[7] = calib_xor7(out);
}

bool inhabit_calib_unpack(const uint8_t in[INHABIT_CALIB_DLC], inhabit_calib_telemetry_t *s) {
    s->raw_adc = (uint16_t)(in[0] | (in[1] << 8));
    s->calibrated_millideg = (int16_t)(in[2] | (in[3] << 8));
    s->node_id = in[4];
    s->chain_index = in[5];
    s->status_flags = in[6];
    return calib_xor7(in) == in[7];
}
