#include "audio_codec.h"
#include "board.h"
#include "settings.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <cstring>
#include <cmath>
#include <driver/i2s_common.h>

#define TAG "AudioCodec"

AudioCodec::AudioCodec() {
}

AudioCodec::~AudioCodec() {
}

void AudioCodec::OutputData(std::vector<int16_t>& data) {
    // Compute a cheap RMS of this chunk and low-pass it into a shared envelope
    // that the display can read to drive voice-reactive visuals.
    size_t n = data.size();
    if (n > 0) {
        uint64_t sum_sq = 0;
        const int16_t* samples = data.data();
        for (size_t i = 0; i < n; i++) {
            int32_t s = samples[i];
            sum_sq += (uint64_t)(s * s);
        }
        float mean_sq = (float)sum_sq / (float)n;
        float rms = sqrtf(mean_sq) / 32768.0f;  // 0..1-ish
        // Light IIR — enough to kill per-chunk jitter, not enough to wash out
        // syllable-level variation.
        float prev = speech_envelope_.load(std::memory_order_relaxed);
        float smoothed = prev * 0.55f + rms * 0.45f;
        speech_envelope_.store(smoothed, std::memory_order_relaxed);
        last_envelope_update_ms_.store((uint32_t)(esp_timer_get_time() / 1000),
                                       std::memory_order_relaxed);
    }

    Write(data.data(), data.size());
}

float AudioCodec::GetSpeechEnvelope() const {
    uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);
    uint32_t last_ms = last_envelope_update_ms_.load(std::memory_order_relaxed);
    // If no audio has been written in the last 600 ms, treat as silence.
    // (Speaking state flips as soon as the backend says "tts stop", but the
    // codec keeps draining buffered audio for a beat after that, so we don't
    // want to kill the effect too eagerly.)
    if ((uint32_t)(now_ms - last_ms) > 600) return 0.0f;
    return speech_envelope_.load(std::memory_order_relaxed);
}

bool AudioCodec::InputData(std::vector<int16_t>& data) {
    int samples = Read(data.data(), data.size());
    if (samples > 0) {
        return true;
    }
    return false;
}

void AudioCodec::Start() {
    Settings settings("audio", false);
    output_volume_ = settings.GetInt("output_volume", output_volume_);
    if (output_volume_ <= 0) {
        ESP_LOGW(TAG, "Output volume value (%d) is too small, setting to default (10)", output_volume_);
        output_volume_ = 10;
    }

    ESP_LOGI(TAG, "Audio codec started");
}

void AudioCodec::SetOutputVolume(int volume) {
    output_volume_ = volume;
    ESP_LOGI(TAG, "Set output volume to %d", output_volume_);
    
    Settings settings("audio", true);
    settings.SetInt("output_volume", output_volume_);
}

void AudioCodec::SetInputGain(float gain) {
    input_gain_ = gain;
    ESP_LOGI(TAG, "Set input gain to %.1f", input_gain_);
}

void AudioCodec::EnableInput(bool enable) {
    if (enable == input_enabled_) {
        return;
    }
    input_enabled_ = enable;
    ESP_LOGI(TAG, "Set input enable to %s", enable ? "true" : "false");
}

void AudioCodec::EnableOutput(bool enable) {
    if (enable == output_enabled_) {
        return;
    }
    output_enabled_ = enable;
    ESP_LOGI(TAG, "Set output enable to %s", enable ? "true" : "false");
}
