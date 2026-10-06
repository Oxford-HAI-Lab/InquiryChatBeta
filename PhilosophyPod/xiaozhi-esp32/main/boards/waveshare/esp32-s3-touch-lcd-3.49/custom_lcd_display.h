#ifndef __CUSTOM_LCD_DISPLAY_H__
#define __CUSTOM_LCD_DISPLAY_H__

#include "lcd_display.h"
#include "esp_jpeg_dec.h"

class CustomLcdDisplay : public LcdDisplay {
public:
    CustomLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                  int width, int height, int offset_x, int offset_y,
                  bool mirror_x, bool mirror_y, bool swap_xy);

    // NERV-style equilibrium display
    void SetEquilibrium(int percent) override;
    void SetTurnCount(int count) override;
    void SetClosingMode(bool active, int remaining) override;
    void SetICState(const ICNode* nodes, int count) override;
    void SetEmotion(const char* emotion) override { (void)emotion; }
    void SetStatus(const char* status) override;
    void UpdateStatusBar(bool update_all = false) override;
    void HideSplash(std::function<void()> on_complete = nullptr) override;

protected:
    void SetupUI() override;

private:
    lv_obj_t* eq_label_ = nullptr;
    lv_obj_t* eq_title_ = nullptr;
    lv_obj_t* eq_container_ = nullptr;
    lv_obj_t* segments_[50] = {};
    lv_obj_t* scale_markers_[5] = {};
    lv_obj_t* nerv_wifi_label_ = nullptr;
    lv_obj_t* nerv_battery_label_ = nullptr;
    lv_obj_t* nerv_status_label_ = nullptr;
    lv_obj_t* turn_prefix_label_ = nullptr;
    lv_obj_t* turn_num_container_ = nullptr;
    lv_obj_t* turn_num_a_ = nullptr;
    lv_obj_t* turn_num_b_ = nullptr;
    bool turn_a_is_current_ = true;
    int eq_percent_ = 0;
    int turn_count_ = 0;
    bool was_speaking_ = false;
    bool turn_count_from_backend_ = false;  // once true, stop local increments
    int turn_num_h_ = 24;  // height of the rolling-disc window (set from prefix height)

    void AnimateTurnNumber(int new_count);
    int64_t session_start_ms_ = 0;
    static constexpr int64_t COUNTDOWN_MS = 30 * 60 * 1000;  // 30 minutes

    // Blink state for active captions (Listening/Thinking/Speaking)
    lv_timer_t* blink_timer_ = nullptr;
    bool blink_on_ = true;           // toggles green/red
    bool is_active_caption_ = false; // true when showing Listening/Thinking/Speaking
    bool thinking_ = false;          // true between end of listening and start of speaking

    // Slow pulsation on the equilibrium bar
    lv_timer_t* pulse_timer_ = nullptr;
    int lit_count_ = 0;
    uint32_t pulse_phase_ms_ = 0;
    float display_env_ = 0.0f;  // display-side-smoothed voice envelope

    // Closing-mode visuals (CONVERGENCE PHASE)
    lv_obj_t* nerv_convergence_label_ = nullptr;
    lv_obj_t* nerv_frame_ = nullptr;  // full-screen border overlay
    bool closing_mode_active_ = false;
    int closing_remaining_ = 0;
    uint32_t closing_pulse_phase_ms_ = 0;

    // Boot splash: MJPEG-style player (.mvid file in assets)
    lv_obj_t* splash_container_ = nullptr;
    lv_obj_t* splash_canvas_ = nullptr;
    uint8_t* splash_canvas_buf_ = nullptr;
    const uint8_t* splash_mvid_ = nullptr;
    const uint32_t* splash_offsets_ = nullptr;
    uint16_t splash_frame_count_ = 0;
    uint16_t splash_current_frame_ = 0;
    uint16_t splash_delay_ms_ = 50;
    uint16_t splash_video_w_ = 0;
    uint16_t splash_video_h_ = 0;
    lv_timer_t* splash_player_timer_ = nullptr;
    jpeg_dec_handle_t splash_jpeg_dec_ = nullptr;

    void ShowSplash();
    void DecodeNextSplashFrame();
    std::function<void()> splash_on_complete_;

    // Rotating pill visualization shown during "thinking" state
    lv_obj_t* pill_canvas_ = nullptr;
    uint8_t* pill_canvas_buf_ = nullptr;
    uint16_t pill_rotation_deg_ = 0;
    static constexpr int PILL_W = 172;
    static constexpr int PILL_H = 280;

    // IC node data received from backend
    static constexpr int MAX_IC_NODES = 32;
    ICNode ic_nodes_[MAX_IC_NODES] = {};
    int ic_node_count_ = 0;
    void DrawRotatingPill();
    void ShowPillOverlay();
    void HidePillOverlay();
    static void PillDrawLine(uint8_t* buf, int bw, int bh,
                             int x0, int y0, int x1, int y1,
                             uint16_t color_rgb565, uint8_t opa255);

    static void BlinkTimerCb(lv_timer_t* timer);
    static void PulseTimerCb(lv_timer_t* timer);

    static bool lvgl_port_flush_io_ready_callback(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_io_event_data_t *edata, void *user_ctx);
    static void lvgl_port_flush_callback(lv_display_t *drv, const lv_area_t *area, uint8_t *color_map);
};

#endif // __CUSTOM_LCD_DISPLAY_H__