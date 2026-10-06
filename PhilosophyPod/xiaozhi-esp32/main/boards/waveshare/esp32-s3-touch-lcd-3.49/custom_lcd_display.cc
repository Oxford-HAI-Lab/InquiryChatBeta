#include "custom_lcd_display.h"

#include "lcd_display.h"

#include <vector>
#include <esp_log.h>
#include <esp_err.h>
#include <esp_lvgl_port.h>
#include "assets/lang_config.h"
#include <cstring>
#include <cmath>
#include "settings.h"

#include "esp_lcd_panel_io.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "config.h"

#include "board.h"
#include "audio_codec.h"
#include "lvgl_theme.h"
#include "application.h"
#include "assets.h"
#include "esp_jpeg_common.h"
#include "esp_heap_caps.h"
#include <material_symbols.h>

LV_FONT_DECLARE(stencil_font_20);

#define TAG "CustomLcdDisplay"

static SemaphoreHandle_t trans_done_sem = NULL;
static bool backlight_deferred_ = true;
static bool splash_started_ = false;
static uint32_t backlight_ramp_ms_ = 0;
static const uint32_t BACKLIGHT_RAMP_DURATION_MS = 1500;
static uint16_t *trans_buf_1;

#if (DISPLAY_ROTATION_90 == true)
static uint16_t *dest_map;
#endif


bool CustomLcdDisplay::lvgl_port_flush_io_ready_callback(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_io_event_data_t *edata, void *user_ctx) {
    BaseType_t taskAwake = pdFALSE;
    lv_display_t *disp_drv = (lv_display_t *)user_ctx;
    assert(disp_drv != NULL);
    if (trans_done_sem) {
        xSemaphoreGiveFromISR(trans_done_sem, &taskAwake);
    }
    return false;
}

void CustomLcdDisplay::lvgl_port_flush_callback(lv_display_t *drv, const lv_area_t *area, uint8_t *color_map) {
    assert(drv != NULL);
    esp_lcd_panel_handle_t panel_handle = (esp_lcd_panel_handle_t)lv_display_get_user_data(drv);
    assert(panel_handle != NULL);

    lv_draw_sw_rgb565_swap(color_map, lv_area_get_width(area) * lv_area_get_height(area));

#if (DISPLAY_ROTATION_90 == true)
    lv_display_rotation_t rotation = lv_display_get_rotation(drv);
    lv_area_t rotated_area;
    if(rotation != LV_DISPLAY_ROTATION_0) {
        lv_color_format_t cf = lv_display_get_color_format(drv);
        rotated_area = *area;
        lv_display_rotate_area(drv, &rotated_area);
        uint32_t src_stride = lv_draw_buf_width_to_stride(lv_area_get_width(area), cf);
        uint32_t dest_stride = lv_draw_buf_width_to_stride(lv_area_get_width(&rotated_area), cf);
        int32_t src_w = lv_area_get_width(area);
        int32_t src_h = lv_area_get_height(area);
        lv_draw_sw_rotate(color_map, dest_map, src_w, src_h, src_stride, dest_stride, rotation, cf);
        area = &rotated_area;
    }
#endif
    const int flush_coun = (LVGL_SPIRAM_BUFF_LEN / LVGL_DMA_BUFF_LEN);
    const int offgap = (DISPLAY_HEIGHT / flush_coun);
    const int dmalen = (LVGL_DMA_BUFF_LEN / 2);
    int offsetx1 = 0;
    int offsety1 = 0;
    int offsetx2 = DISPLAY_WIDTH;
    int offsety2 = offgap;
#if (DISPLAY_ROTATION_90 == true)
    uint16_t *map = (uint16_t*)dest_map;
#else
    uint16_t *map = (uint16_t*)color_map;
#endif
    xSemaphoreGive(trans_done_sem);

    for(int i = 0; i<flush_coun; i++) {
        xSemaphoreTake(trans_done_sem,portMAX_DELAY);
        memcpy(trans_buf_1,map,LVGL_DMA_BUFF_LEN);
        esp_lcd_panel_draw_bitmap(panel_handle, offsetx1, offsety1, offsetx2, offsety2, trans_buf_1);
        offsety1 += offgap;
        offsety2 += offgap;
        map += dmalen;
    }
    xSemaphoreTake(trans_done_sem,portMAX_DELAY);
    lv_disp_flush_ready(drv);

    if (backlight_deferred_ && splash_started_) {
        backlight_deferred_ = false;
        backlight_ramp_ms_ = 1;
        Board::GetInstance().GetBacklight()->SetBrightness(1);
    }
}


CustomLcdDisplay::CustomLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                  int width, int height, int offset_x, int offset_y,
                  bool mirror_x, bool mirror_y, bool swap_xy)
    : LcdDisplay(panel_io, panel, width, height) {

    ESP_LOGI(TAG, "Initialize LVGL library");
    lv_init();

    ESP_LOGI(TAG, "Initialize LVGL port");
    lvgl_port_cfg_t port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    port_cfg.task_priority = 2;
    port_cfg.timer_period_ms = 50;
    lvgl_port_init(&port_cfg);
    trans_done_sem = xSemaphoreCreateBinary();
    trans_buf_1 = (uint16_t *)heap_caps_malloc(LVGL_DMA_BUFF_LEN, MALLOC_CAP_DMA);

    uint32_t buffer_size = 0;
    lv_color_t *buf1 = NULL;
    lvgl_port_lock(0);
    uint8_t color_bytes = lv_color_format_get_size(LV_COLOR_FORMAT_RGB565);
    display_ = lv_display_create(width_, height_);
    lv_display_set_flush_cb(display_, lvgl_port_flush_callback);
    buffer_size = width_ * height_;
    buf1 = (lv_color_t *)heap_caps_aligned_alloc(1, buffer_size * color_bytes, MALLOC_CAP_SPIRAM);
    if (buf1) memset(buf1, 0, buffer_size * color_bytes);
#if (DISPLAY_ROTATION_90 == true)
    dest_map = (uint16_t *)heap_caps_malloc(buffer_size * color_bytes, MALLOC_CAP_SPIRAM);
    lv_display_set_rotation(display_, LV_DISPLAY_ROTATION_90);
#endif
    lv_display_set_buffers(display_, buf1, NULL, buffer_size * color_bytes, LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_user_data(display_, panel_);
    lvgl_port_unlock();

    esp_lcd_panel_io_callbacks_t cbs = {
        .on_color_trans_done = lvgl_port_flush_io_ready_callback,
    };
    esp_lcd_panel_io_register_event_callbacks(panel_io_, &cbs, display_);

    if (display_ == nullptr) {
        ESP_LOGE(TAG, "Failed to add display");
        return;
    }

    if (offset_x != 0 || offset_y != 0) {
        lv_display_set_offset(display_, offset_x, offset_y);
    }
}

// ── NERV-style Equilibrium Display ──────────────────────────────────────────

// Colors
#define COL_BG       lv_color_hex(0x000008)   // near-black with blue tint
#define COL_RED      lv_color_hex(0xFF3300)   // NERV red-orange
#define COL_RED_DIM  lv_color_hex(0x881800)   // dim red
#define COL_CYAN     lv_color_hex(0x00CCFF)   // bright cyan
#define COL_BLUE     lv_color_hex(0x3366FF)   // mid blue
#define COL_PURPLE   lv_color_hex(0x8833FF)   // purple (danger zone)
#define COL_DARK     lv_color_hex(0x0A0A1A)   // segment off color
#define COL_NERV_GREEN lv_color_hex(0x00FF41)  // NERV green
#define COL_NERV_RED   lv_color_hex(0xFF0000)  // NERV red

// Number of bar segments
#define NUM_SEGMENTS 50

void CustomLcdDisplay::SetupUI() {
    LcdDisplay::SetupUI();

    DisplayLockGuard lock(this);

    // Start splash immediately — before creating UI widgets.
    // The splash timer runs on the LVGL thread and will keep decoding
    // frames while the main thread continues with widget creation and
    // subsequent audio/network initialization.
    ShowSplash();

    // ── Switch to dark theme and customize to NERV style ──
    auto& theme_manager = LvglThemeManager::GetInstance();
    auto* dark = theme_manager.GetTheme("dark");
    if (dark) {
        // Customize dark theme colors to NERV
        dark->set_background_color(COL_BG);
        dark->set_text_color(COL_RED);
        dark->set_chat_background_color(COL_BG);
        dark->set_border_color(COL_RED_DIM);
        dark->set_low_battery_color(COL_RED);
        SetTheme(dark);
    }

    // ── Hide ALL default UI elements — we build our own ──
    lv_obj_t* hide_objs[] = {container_, top_bar_, status_bar_, bottom_bar_,
                              content_, emoji_box_};
    for (auto obj : hide_objs) {
        if (obj) lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    }

    // ── Full-screen NERV container ──
    lv_obj_set_style_bg_color(lv_screen_active(), COL_BG, 0);
    lv_obj_set_style_bg_opa(lv_screen_active(), LV_OPA_COVER, 0);

    eq_container_ = lv_obj_create(lv_screen_active());
    lv_obj_remove_style_all(eq_container_);
    lv_obj_set_size(eq_container_, DISPLAY_WIDTH, DISPLAY_HEIGHT);
    lv_obj_align(eq_container_, LV_ALIGN_TOP_LEFT, 0, 0);
    lv_obj_set_style_bg_color(eq_container_, COL_BG, 0);
    lv_obj_set_style_bg_opa(eq_container_, LV_OPA_COVER, 0);
    lv_obj_clear_flag(eq_container_, LV_OBJ_FLAG_SCROLLABLE);

    // ── Our own status row at top: WiFi left, status center, battery right ──
    nerv_wifi_label_ = lv_label_create(eq_container_);
    lv_label_set_text(nerv_wifi_label_, "WiFi");
    lv_obj_set_style_text_color(nerv_wifi_label_, COL_RED, 0);
    lv_obj_set_style_text_font(nerv_wifi_label_, &lv_font_montserrat_14, 0);
    lv_obj_set_pos(nerv_wifi_label_, 4, 4);

    nerv_status_label_ = lv_label_create(eq_container_);
    lv_label_set_text(nerv_status_label_, "");
    lv_obj_set_style_text_color(nerv_status_label_, COL_RED, 0);
    lv_obj_set_style_text_font(nerv_status_label_, &lv_font_montserrat_14, 0);
    lv_obj_set_width(nerv_status_label_, DISPLAY_WIDTH - 80);
    lv_obj_set_style_text_align(nerv_status_label_, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(nerv_status_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_align(nerv_status_label_, LV_ALIGN_TOP_MID, 0, 4);

    nerv_battery_label_ = lv_label_create(eq_container_);
    lv_label_set_text(nerv_battery_label_, "");
    lv_obj_set_style_text_color(nerv_battery_label_, COL_RED, 0);
    lv_obj_set_style_text_font(nerv_battery_label_, &lv_font_montserrat_14, 0);
    lv_obj_align(nerv_battery_label_, LV_ALIGN_TOP_RIGHT, -4, 4);

    // ── Thin red separator ──
    lv_obj_t* sep = lv_obj_create(eq_container_);
    lv_obj_remove_style_all(sep);
    lv_obj_set_size(sep, DISPLAY_WIDTH - 8, 1);
    lv_obj_set_pos(sep, 4, 24);
    lv_obj_set_style_bg_color(sep, COL_RED, 0);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);

    // ── Title label — "EROTETIC EQUILIBRIUM" ──
    int status_h = 28;  // height of our status row + separator
    eq_title_ = lv_label_create(eq_container_);
    lv_obj_t* title = eq_title_;
    lv_label_set_text(title, "EROTETIC\nEQUILIBRIUM");
    lv_obj_set_style_text_color(title, COL_RED, 0);
    lv_obj_set_style_text_font(title, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_align(title, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, status_h + 4);

    // ── Percentage display ──
    eq_label_ = lv_label_create(eq_container_);
    lv_label_set_text(eq_label_, "0%");
    lv_obj_set_style_text_color(eq_label_, COL_RED, 0);
    lv_obj_set_style_text_font(eq_label_, &lv_font_montserrat_14, 0);
    lv_obj_align(eq_label_, LV_ALIGN_TOP_MID, 0, status_h + 36);

    // ── CONVERGENCE PHASE subtitle (closing-mode indicator) ──
    // Reserved slot just above the bar; hidden until closing_mode_active_.
    nerv_convergence_label_ = lv_label_create(eq_container_);
    lv_label_set_text(nerv_convergence_label_, "CONVERGENCE PHASE");
    lv_obj_set_style_text_color(nerv_convergence_label_, COL_RED, 0);
    lv_obj_set_style_text_font(nerv_convergence_label_, &lv_font_montserrat_14, 0);
    lv_obj_set_width(nerv_convergence_label_, DISPLAY_WIDTH);
    lv_obj_set_style_text_align(nerv_convergence_label_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(nerv_convergence_label_, LV_ALIGN_TOP_MID, 0, status_h + 54);
    lv_obj_add_flag(nerv_convergence_label_, LV_OBJ_FLAG_HIDDEN);

    // ── Segmented bar — vertical column of rectangles ──
    // bar_top is pushed down 16px from the original status_h+56 to reserve
    // a slot above for the CONVERGENCE PHASE subtitle.
    int cont_h = DISPLAY_HEIGHT;
    int bar_top = status_h + 72;
    int bar_bottom = cont_h - 10;
    int bar_height = bar_bottom - bar_top;
    int seg_gap = 2;
    int seg_h = (bar_height - (NUM_SEGMENTS - 1) * seg_gap) / NUM_SEGMENTS;
    int seg_w = DISPLAY_WIDTH - 20;
    int seg_x = 10;

    for (int i = 0; i < NUM_SEGMENTS; i++) {
        // Segments go bottom-to-top: segment 0 is at bottom (low), segment N-1 at top (high)
        int seg_index = NUM_SEGMENTS - 1 - i;  // i=0 → top of screen, so invert
        int y = bar_top + i * (seg_h + seg_gap);

        lv_obj_t* seg = lv_obj_create(eq_container_);
        lv_obj_remove_style_all(seg);
        lv_obj_set_size(seg, seg_w, seg_h);
        lv_obj_set_pos(seg, seg_x, y);
        lv_obj_set_style_radius(seg, 2, 0);
        lv_obj_set_style_bg_opa(seg, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(seg, COL_DARK, 0);  // off by default
        lv_obj_clear_flag(seg, (lv_obj_flag_t)(LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE));

        segments_[seg_index] = seg;
    }

    // ── Scale markers on the right ──
    const char* markers[] = {"0", "25", "50", "75", "100"};
    int marker_positions[] = {0, NUM_SEGMENTS/4, NUM_SEGMENTS/2, 3*NUM_SEGMENTS/4, NUM_SEGMENTS-1};
    for (int m = 0; m < 5; m++) {
        int seg_idx = marker_positions[m];
        int screen_row = NUM_SEGMENTS - 1 - seg_idx;
        int y = bar_top + screen_row * (seg_h + seg_gap) + seg_h / 2 - 5;
        lv_obj_t* mk = lv_label_create(eq_container_);
        lv_label_set_text(mk, markers[m]);
        lv_obj_set_style_text_color(mk, COL_RED_DIM, 0);
        lv_obj_set_style_text_font(mk, &lv_font_montserrat_14, 0);
        lv_obj_set_pos(mk, DISPLAY_WIDTH - 18, y);
        scale_markers_[m] = mk;
    }

    // ── Frame border overlay (closing-mode accent pulse) ──
    // Transparent fill, COL_RED 2px border around the whole screen. Hidden
    // until closing_mode_active_. Lives above segments so it sits on top of
    // the bar; non-clickable so it never steals touch input.
    nerv_frame_ = lv_obj_create(eq_container_);
    lv_obj_remove_style_all(nerv_frame_);
    lv_obj_set_size(nerv_frame_, DISPLAY_WIDTH, DISPLAY_HEIGHT);
    lv_obj_set_pos(nerv_frame_, 0, 0);
    lv_obj_set_style_bg_opa(nerv_frame_, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_color(nerv_frame_, COL_RED, 0);
    lv_obj_set_style_border_width(nerv_frame_, 2, 0);
    lv_obj_set_style_border_opa(nerv_frame_, LV_OPA_TRANSP, 0);
    lv_obj_set_style_radius(nerv_frame_, 0, 0);
    lv_obj_clear_flag(nerv_frame_, (lv_obj_flag_t)(LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE));
    lv_obj_add_flag(nerv_frame_, LV_OBJ_FLAG_HIDDEN);

    // ── Turn counter: bottom-left, white air-force stencil ──
    // Static "TURNS " prefix + clipping container with two digit labels
    // that roll vertically like an altimeter drum.
    turn_prefix_label_ = lv_label_create(eq_container_);
    lv_label_set_text(turn_prefix_label_, "TURNS ");
    lv_obj_set_style_text_color(turn_prefix_label_, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_text_font(turn_prefix_label_, &stencil_font_20, 0);
    lv_obj_align(turn_prefix_label_, LV_ALIGN_BOTTOM_LEFT, 4, -4);

    // Force layout computation so we can query the prefix's actual size.
    lv_obj_update_layout(eq_container_);
    int prefix_w = lv_obj_get_width(turn_prefix_label_);
    int prefix_h = lv_obj_get_height(turn_prefix_label_);
    if (prefix_h <= 0) prefix_h = 24;
    turn_num_h_ = prefix_h;

    // Container shares the exact same bottom and height as the prefix label.
    // Both labels use the same font, so glyphs render identically inside.
    turn_num_container_ = lv_obj_create(eq_container_);
    lv_obj_remove_style_all(turn_num_container_);
    lv_obj_set_size(turn_num_container_, 80, turn_num_h_);
    lv_obj_align(turn_num_container_, LV_ALIGN_BOTTOM_LEFT, 4 + prefix_w, -4);
    lv_obj_set_style_bg_opa(turn_num_container_, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(turn_num_container_, 0, 0);
    lv_obj_set_style_border_width(turn_num_container_, 0, 0);
    lv_obj_clear_flag(turn_num_container_, LV_OBJ_FLAG_SCROLLABLE);
    // In LVGL 9 children are clipped to parent by default (no OVERFLOW_VISIBLE flag set).

    turn_num_a_ = lv_label_create(turn_num_container_);
    lv_label_set_text(turn_num_a_, "0");
    lv_obj_set_style_text_color(turn_num_a_, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_text_font(turn_num_a_, &stencil_font_20, 0);
    lv_obj_set_pos(turn_num_a_, 0, 0);

    turn_num_b_ = lv_label_create(turn_num_container_);
    lv_label_set_text(turn_num_b_, "");
    lv_obj_set_style_text_color(turn_num_b_, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_text_font(turn_num_b_, &stencil_font_20, 0);
    lv_obj_set_pos(turn_num_b_, 0, -turn_num_h_);
    turn_a_is_current_ = true;

    // Start the 30-minute countdown
    session_start_ms_ = esp_timer_get_time() / 1000;

    // Blink timer for active captions (800ms period = slow blink)
    blink_timer_ = lv_timer_create(BlinkTimerCb, 800, this);
    lv_timer_pause(blink_timer_);

    // Slow pulse timer for equilibrium bar (50 ms tick, ~3 s breathing period)
    pulse_timer_ = lv_timer_create(PulseTimerCb, 50, this);

    ESP_LOGI(TAG, "NERV equilibrium UI initialized");

    // Bring splash to front — it was created before eq_container_ which now covers it
    if (splash_container_) {
        lv_obj_move_foreground(splash_container_);
    }
}

void CustomLcdDisplay::ShowSplash() {
    void* mvid_data = nullptr;
    size_t mvid_size = 0;
    if (!Assets::GetInstance().GetAssetData("splash.mvid", mvid_data, mvid_size) || !mvid_data) {
        ESP_LOGW(TAG, "splash.mvid not found in assets partition; skipping splash");
        return;
    }
    const uint8_t* data = static_cast<const uint8_t*>(mvid_data);
    if (mvid_size < 12 || memcmp(data, "MVID", 4) != 0) {
        ESP_LOGE(TAG, "Invalid splash.mvid header");
        return;
    }
    uint16_t frame_count = (uint16_t)data[4] | ((uint16_t)data[5] << 8);
    uint16_t video_w = (uint16_t)data[6] | ((uint16_t)data[7] << 8);
    uint16_t video_h = (uint16_t)data[8] | ((uint16_t)data[9] << 8);
    uint16_t delay_ms = (uint16_t)data[10] | ((uint16_t)data[11] << 8);
    if (frame_count == 0 || video_w == 0 || video_h == 0 || delay_ms == 0) {
        ESP_LOGE(TAG, "Invalid splash dimensions/timing");
        return;
    }
    size_t header_size = 12u + (size_t)(frame_count + 1u) * 4u;
    if (mvid_size < header_size) {
        ESP_LOGE(TAG, "splash.mvid truncated header");
        return;
    }

    splash_mvid_ = data;
    splash_offsets_ = reinterpret_cast<const uint32_t*>(data + 12);
    splash_frame_count_ = frame_count;
    splash_current_frame_ = 0;
    splash_delay_ms_ = delay_ms;
    splash_video_w_ = video_w;
    splash_video_h_ = video_h;

    splash_container_ = lv_obj_create(lv_screen_active());
    lv_obj_remove_style_all(splash_container_);
    lv_obj_set_size(splash_container_, DISPLAY_WIDTH, DISPLAY_HEIGHT);
    lv_obj_set_pos(splash_container_, 0, 0);
    lv_obj_set_style_bg_color(splash_container_, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(splash_container_, LV_OPA_COVER, 0);
    lv_obj_clear_flag(splash_container_, LV_OBJ_FLAG_SCROLLABLE);

    size_t buf_size = (size_t)video_w * (size_t)video_h * 2u;
    splash_canvas_buf_ = static_cast<uint8_t*>(
        heap_caps_aligned_alloc(16, buf_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!splash_canvas_buf_) {
        ESP_LOGE(TAG, "Failed to allocate splash canvas buffer (%u bytes)", (unsigned)buf_size);
        lv_obj_delete(splash_container_);
        splash_container_ = nullptr;
        return;
    }
    memset(splash_canvas_buf_, 0, buf_size);

    splash_canvas_ = lv_canvas_create(splash_container_);
    lv_canvas_set_buffer(splash_canvas_, splash_canvas_buf_, video_w, video_h,
                         LV_COLOR_FORMAT_RGB565);
    lv_obj_align(splash_canvas_, LV_ALIGN_CENTER, 0, 0);

    jpeg_dec_config_t cfg = DEFAULT_JPEG_DEC_CONFIG();
    cfg.output_type = JPEG_PIXEL_FORMAT_RGB565_LE;
    cfg.rotate = JPEG_ROTATE_0D;
    if (jpeg_dec_open(&cfg, &splash_jpeg_dec_) != JPEG_ERR_OK) {
        ESP_LOGE(TAG, "Failed to open JPEG decoder for splash");
        heap_caps_free(splash_canvas_buf_);
        splash_canvas_buf_ = nullptr;
        lv_obj_delete(splash_container_);
        splash_container_ = nullptr;
        return;
    }

    DecodeNextSplashFrame();
    splash_started_ = true;

    splash_player_timer_ = lv_timer_create(
        [](lv_timer_t* t) {
            auto* self = static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(t));
            self->DecodeNextSplashFrame();
        },
        delay_ms, this);

    ESP_LOGI(TAG, "Splash playing (%u frames, %ux%u @ %u ms, %u KB)",
             (unsigned)frame_count, (unsigned)video_w, (unsigned)video_h,
             (unsigned)delay_ms, (unsigned)(mvid_size / 1024));
}

void CustomLcdDisplay::DecodeNextSplashFrame() {
    if (!splash_jpeg_dec_ || !splash_canvas_buf_ || !splash_offsets_) return;
    if (splash_current_frame_ >= splash_frame_count_) {
        if (splash_player_timer_) {
            lv_timer_pause(splash_player_timer_);
        }
        return;
    }

    uint32_t off = splash_offsets_[splash_current_frame_];
    uint32_t next_off = splash_offsets_[splash_current_frame_ + 1u];
    if (next_off <= off) {
        ESP_LOGE(TAG, "Bad splash frame %u offsets", (unsigned)splash_current_frame_);
        splash_current_frame_++;
        return;
    }
    int jpeg_len = static_cast<int>(next_off - off);

    jpeg_dec_io_t io = {};
    io.inbuf = const_cast<uint8_t*>(splash_mvid_ + off);
    io.inbuf_len = jpeg_len;
    jpeg_dec_header_info_t info = {};
    jpeg_error_t jret = jpeg_dec_parse_header(splash_jpeg_dec_, &io, &info);
    if (jret != JPEG_ERR_OK) {
        ESP_LOGE(TAG, "Splash JPEG header parse failed (frame %u, err %d)",
                 (unsigned)splash_current_frame_, (int)jret);
        splash_current_frame_++;
        return;
    }
    io.outbuf = splash_canvas_buf_;
    jret = jpeg_dec_process(splash_jpeg_dec_, &io);
    if (jret != JPEG_ERR_OK) {
        ESP_LOGE(TAG, "Splash JPEG decode failed (frame %u, err %d)",
                 (unsigned)splash_current_frame_, (int)jret);
        splash_current_frame_++;
        return;
    }

    if (splash_canvas_) {
        lv_obj_invalidate(splash_canvas_);
    }
    splash_current_frame_++;
}

void CustomLcdDisplay::HideSplash(std::function<void()> on_complete) {
    if (on_complete) splash_on_complete_ = on_complete;

    // Wait for splash to finish playing before hiding
    if (splash_player_timer_ && splash_current_frame_ < splash_frame_count_) {
        ESP_LOGI(TAG, "HideSplash deferred: %u/%u frames played",
                 (unsigned)splash_current_frame_, (unsigned)splash_frame_count_);
        lv_timer_create([](lv_timer_t* t) {
            auto* self = static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(t));
            lv_timer_delete(t);
            self->HideSplash();
        }, 200, this);
        return;
    }

    DisplayLockGuard lock(this);
    if (!splash_container_ && !splash_canvas_) {
        if (splash_on_complete_) { auto cb = splash_on_complete_; splash_on_complete_ = nullptr; cb(); }
        return;
    }

    if (splash_player_timer_) {
        lv_timer_delete(splash_player_timer_);
        splash_player_timer_ = nullptr;
    }
    if (splash_jpeg_dec_) {
        jpeg_dec_close(splash_jpeg_dec_);
        splash_jpeg_dec_ = nullptr;
    }
    splash_canvas_ = nullptr;
    if (splash_container_) {
        lv_obj_delete(splash_container_);
        splash_container_ = nullptr;
    }
    if (splash_canvas_buf_) {
        heap_caps_free(splash_canvas_buf_);
        splash_canvas_buf_ = nullptr;
    }
    splash_mvid_ = nullptr;
    splash_offsets_ = nullptr;
    splash_frame_count_ = 0;
    splash_current_frame_ = 0;
    ESP_LOGI(TAG, "Splash hidden");

    if (splash_on_complete_) {
        auto cb = splash_on_complete_;
        splash_on_complete_ = nullptr;
        cb();
    }
}

void CustomLcdDisplay::PulseTimerCb(lv_timer_t* timer) {
    auto* self = static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(timer));

    // ── Backlight dim-in ramp during first 1.5s ──
    if (backlight_ramp_ms_ > 0 && backlight_ramp_ms_ <= BACKLIGHT_RAMP_DURATION_MS) {
        backlight_ramp_ms_ += 50;
        float t = (float)backlight_ramp_ms_ / (float)BACKLIGHT_RAMP_DURATION_MS;
        if (t >= 1.0f) {
            t = 1.0f;
            backlight_ramp_ms_ = BACKLIGHT_RAMP_DURATION_MS + 1;  // done
        }
        int brightness = (int)(t * t * 100.0f);  // quadratic ease-in
        if (brightness < 1) brightness = 1;
        Board::GetInstance().GetBacklight()->SetBrightness(brightness);
    }

    // ── Rotating pill during thinking state ──
    if (self->thinking_ && self->pill_canvas_buf_) {
        self->DrawRotatingPill();
    }

    // ── Closing-mode visuals: frame border pulse + unlit-segment opacity ──
    // Advanced every tick regardless of lit state so the frame can breathe
    // even when the bar is empty (though in practice closing mode requires
    // equilibrium ≥ 0.85, so lit_count_ is always well above 0).
    self->closing_pulse_phase_ms_ += 50;
    float closing_seg_opa = 0.0f;    // segment red opacity in closing mode
    if (self->closing_mode_active_) {
        // Frame border: ~8s breathing period, opa range 60..180
        uint32_t frame_phase = self->closing_pulse_phase_ms_ % 8000;
        float ft = (float)frame_phase / 8000.0f;
        float fu = (ft < 0.5f) ? (ft * 2.0f) : ((1.0f - ft) * 2.0f);  // 0..1..0
        float fbell = 0.5f * (1.0f - cosf((float)M_PI * fu));         // smooth 0..1..0
        float frame_opa = 60.0f + fbell * 120.0f;                     // 60..180
        if (self->nerv_frame_) {
            lv_obj_set_style_border_opa(self->nerv_frame_, (lv_opa_t)frame_opa, 0);
        }

        // Unlit segment red tint: ~6s breathing period, opa range 25..110
        uint32_t seg_phase = self->closing_pulse_phase_ms_ % 6000;
        float st = (float)seg_phase / 6000.0f;
        float su = (st < 0.5f) ? (st * 2.0f) : ((1.0f - st) * 2.0f);
        float sbell = 0.5f * (1.0f - cosf((float)M_PI * su));
        closing_seg_opa = 25.0f + sbell * 85.0f;                       // 25..110
    }

    // Full round trip (bottom → top → bottom) in period_ms
    const uint32_t period_ms = 4000;
    self->pulse_phase_ms_ = (self->pulse_phase_ms_ + 50) % period_ms;
    float t = (float)self->pulse_phase_ms_ / (float)period_ms;  // 0..1

    // Triangle-wave crest position over lit range, expressed in segment units
    float up = (t < 0.5f) ? (t * 2.0f) : ((1.0f - t) * 2.0f);  // 0..1..0
    float crest = (self->lit_count_ > 0) ? up * (float)(self->lit_count_ - 1) : 0.0f;

    // Ambient slow wave: cosine-bell crest (half-width W) + linear tail.
    // Kept dim so the voice VU fill below reads against it.
    const float W = 12.0f;
    const float T = 6.0f;
    const float full = 110.0f;
    const float tail_mid = 35.0f;
    const float floor_opa = 15.0f;

    // Voice envelope: not gated on device state — the audio codec already
    // self-silences via its stale-timestamp check, and the state flag flips
    // before the hardware has finished draining audio buffers.
    float fresh_env = 0.0f;
    auto* codec = Board::GetInstance().GetAudioCodec();
    if (codec) fresh_env = codec->GetSpeechEnvelope();
    fresh_env *= 3.0f;  // gain — tuned so peaks hover around 0.7 (not clamp)
    if (fresh_env > 1.0f) fresh_env = 1.0f;

    // Light display-side smoothing — track syllables closely but not every
    // 50 ms blip.
    float alpha = (fresh_env > self->display_env_) ? 0.7f : 0.5f;
    self->display_env_ = self->display_env_ * (1.0f - alpha) + fresh_env * alpha;
    // Voice fill grows symmetrically from the screen center outward. It uses
    // all 50 segments (not just lit ones), so the "mass" is always centered
    // regardless of current equilibrium level. For segments outside the
    // voice fill we keep the existing behaviour: lit shows the ambient wave,
    // unlit stays dark.
    const float voice_opa_max = 240.0f;
    const float fill_center = (float)(NUM_SEGMENTS - 1) * 0.5f;
    const float voice_half_spread = self->display_env_ * ((float)NUM_SEGMENTS * 0.5f);
    // Bright fill color so voice-activated segments pop on top of the
    // (potentially unlit) backdrop.
    lv_color_t voice_color = lv_color_hex(0x66CCFF);

    for (int i = 0; i < NUM_SEGMENTS; i++) {
        if (!self->segments_[i]) continue;

        // Voice contribution at this segment
        float voice_opa = 0.0f;
        float voice_frac = voice_half_spread - fabsf((float)i - fill_center);
        if (voice_frac >= 1.0f) voice_opa = voice_opa_max;
        else if (voice_frac > 0.0f) voice_opa = voice_opa_max * voice_frac;

        bool is_lit = (i < self->lit_count_);

        if (voice_opa > 0.0f) {
            // Voice wins — override colour so the fill is obviously bright,
            // even in the unlit portion of the equilibrium bar.
            lv_obj_set_style_bg_color(self->segments_[i], voice_color, 0);
            lv_obj_set_style_bg_opa(self->segments_[i], (lv_opa_t)voice_opa, 0);
        } else if (is_lit) {
            // Ambient slow wave on lit segments. We re-assert the lit
            // gradient colour here in case a prior tick's voice fill had
            // painted this segment with the voice colour.
            float t_grad = (float)i / (float)NUM_SEGMENTS;
            lv_color_t lit_color;
            if (t_grad < 0.5f) {
                float u = t_grad * 2.0f;
                uint8_t r = (uint8_t)(0x00 + u * (0x33 - 0x00));
                uint8_t g = (uint8_t)(0xCC - u * (0xCC - 0x66));
                uint8_t b = 0xFF;
                lit_color = lv_color_make(r, g, b);
            } else {
                float u = (t_grad - 0.5f) * 2.0f;
                uint8_t r = (uint8_t)(0x33 + u * (0x88 - 0x33));
                uint8_t g = (uint8_t)(0x66 - u * (0x66 - 0x33));
                uint8_t b = 0xFF;
                lit_color = lv_color_make(r, g, b);
            }

            float d = fabsf((float)i - crest);
            float wave_opa;
            if (d < W) {
                float bell = 0.5f * (1.0f + cosf((float)M_PI * d / W));
                wave_opa = tail_mid + bell * (full - tail_mid);
            } else if (d < W + T) {
                float u = (d - W) / T;
                wave_opa = tail_mid - u * (tail_mid - floor_opa);
            } else {
                wave_opa = floor_opa;
            }
            lv_obj_set_style_bg_color(self->segments_[i], lit_color, 0);
            lv_obj_set_style_bg_opa(self->segments_[i], (lv_opa_t)wave_opa, 0);
        } else {
            // Unlit and outside voice fill. In closing mode, paint these
            // (which are the top-of-bar segments above the user's current
            // equilibrium) with a slowly pulsing NERV red — reads as
            // "approaching threshold". Otherwise restore dark.
            if (self->closing_mode_active_) {
                lv_obj_set_style_bg_color(self->segments_[i], COL_RED, 0);
                lv_obj_set_style_bg_opa(self->segments_[i], (lv_opa_t)closing_seg_opa, 0);
            } else {
                lv_obj_set_style_bg_color(self->segments_[i], COL_DARK, 0);
                lv_obj_set_style_bg_opa(self->segments_[i], LV_OPA_COVER, 0);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Rotating pill wireframe — shown during "thinking" state
// ---------------------------------------------------------------------------

void CustomLcdDisplay::PillDrawLine(uint8_t* buf, int bw, int bh,
                                    int x0, int y0, int x1, int y1,
                                    uint16_t color_rgb565, uint8_t opa255) {
    // Bresenham with alpha blending into RGB565 buffer
    int dx = abs(x1 - x0), dy = abs(y1 - y0);
    int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    int err = dx - dy;
    uint8_t cr = ((color_rgb565 >> 11) & 0x1F) << 3;
    uint8_t cg = ((color_rgb565 >> 5) & 0x3F) << 2;
    uint8_t cb = (color_rgb565 & 0x1F) << 3;
    float a = opa255 / 255.0f;
    for (;;) {
        if (x0 >= 0 && x0 < bw && y0 >= 0 && y0 < bh) {
            int idx = (y0 * bw + x0) * 2;
            uint16_t bg = buf[idx] | (buf[idx+1] << 8);
            uint8_t br = ((bg >> 11) & 0x1F) << 3;
            uint8_t bg_g = ((bg >> 5) & 0x3F) << 2;
            uint8_t bb = (bg & 0x1F) << 3;
            uint8_t r = (uint8_t)(br * (1-a) + cr * a);
            uint8_t g = (uint8_t)(bg_g * (1-a) + cg * a);
            uint8_t b = (uint8_t)(bb * (1-a) + cb * a);
            uint16_t px = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
            buf[idx] = px & 0xFF;
            buf[idx+1] = px >> 8;
        }
        if (x0 == x1 && y0 == y1) break;
        int e2 = err * 2;
        if (e2 > -dy) { err -= dy; x0 += sx; }
        if (e2 < dx)  { err += dx; y0 += sy; }
    }
}

void CustomLcdDisplay::ShowPillOverlay() {
    if (!pill_canvas_) {
        // Allocate canvas buffer in PSRAM
        size_t buf_size = PILL_W * PILL_H * 2;  // RGB565
        pill_canvas_buf_ = (uint8_t*)heap_caps_malloc(buf_size, MALLOC_CAP_SPIRAM);
        if (!pill_canvas_buf_) {
            ESP_LOGE(TAG, "Failed to allocate pill canvas buffer");
            return;
        }
        pill_canvas_ = lv_canvas_create(eq_container_);
        lv_canvas_set_buffer(pill_canvas_, pill_canvas_buf_, PILL_W, PILL_H, LV_COLOR_FORMAT_RGB565);
        lv_obj_align(pill_canvas_, LV_ALIGN_CENTER, 0, 0);
        lv_obj_clear_flag(pill_canvas_, LV_OBJ_FLAG_SCROLLABLE);
    }
    // Hide equilibrium bar elements + labels
    for (int i = 0; i < NUM_SEGMENTS; i++)
        if (segments_[i]) lv_obj_add_flag(segments_[i], LV_OBJ_FLAG_HIDDEN);
    if (eq_label_) lv_obj_add_flag(eq_label_, LV_OBJ_FLAG_HIDDEN);
    if (eq_title_) lv_obj_add_flag(eq_title_, LV_OBJ_FLAG_HIDDEN);
    for (int i = 0; i < 5; i++)
        if (scale_markers_[i]) lv_obj_add_flag(scale_markers_[i], LV_OBJ_FLAG_HIDDEN);
    if (nerv_convergence_label_) lv_obj_add_flag(nerv_convergence_label_, LV_OBJ_FLAG_HIDDEN);

    lv_obj_clear_flag(pill_canvas_, LV_OBJ_FLAG_HIDDEN);
    pill_rotation_deg_ = 0;
}

void CustomLcdDisplay::HidePillOverlay() {
    if (pill_canvas_) lv_obj_add_flag(pill_canvas_, LV_OBJ_FLAG_HIDDEN);
    // Restore equilibrium bar elements + labels
    for (int i = 0; i < NUM_SEGMENTS; i++)
        if (segments_[i]) lv_obj_clear_flag(segments_[i], LV_OBJ_FLAG_HIDDEN);
    if (eq_label_) lv_obj_clear_flag(eq_label_, LV_OBJ_FLAG_HIDDEN);
    if (eq_title_) lv_obj_clear_flag(eq_title_, LV_OBJ_FLAG_HIDDEN);
    for (int i = 0; i < 5; i++)
        if (scale_markers_[i]) lv_obj_clear_flag(scale_markers_[i], LV_OBJ_FLAG_HIDDEN);
    if (closing_mode_active_ && nerv_convergence_label_)
        lv_obj_clear_flag(nerv_convergence_label_, LV_OBJ_FLAG_HIDDEN);
}

void CustomLcdDisplay::DrawRotatingPill() {
    if (!pill_canvas_buf_) return;

    // Clear to background
    memset(pill_canvas_buf_, 0, PILL_W * PILL_H * 2);  // black

    // Pill geometry — golden ratio: cylinder = diameter * φ
    const float PHI = 1.6180339887f;
    const float R = 32.0f;      // radius in pixels
    const float H = R * 2 * PHI; // cylinder length
    const float cx = PILL_W / 2.0f;
    const float cy = PILL_H / 2.0f;
    const float theta = (float)pill_rotation_deg_ * (float)M_PI / 180.0f;

    // RGB565 colors — kept dim so nodes dominate
    const uint16_t COL_BRIGHT = 0x5800; // dim red (NERV)
    const uint16_t COL_DIM    = 0x3800; // very dim red
    const uint16_t COL_MID    = 0x4800; // silhouette

    // Helper: project a 3D capsule point to 2D screen
    // Capsule axis along Y, rotation around Y axis
    auto project = [&](float lon, float lat_y) -> std::pair<float, float> {
        // lon = longitude angle, lat_y = y position on capsule
        float x3d = R * cosf(lon + theta);
        float z3d = R * sinf(lon + theta);
        (void)z3d;
        return { cx + x3d, cy - lat_y };
    };

    // Whether a longitude faces camera (z > 0 after rotation)
    auto facing = [&](float lon) -> bool {
        return sinf(lon + theta) > 0.0f;
    };

    // Draw silhouette (left and right edges of pill)
    // Left edge: x = cx - R, right edge: x = cx + R
    // Cylinder section: straight vertical lines
    int y_cyl_top = (int)(cy - H/2);
    int y_cyl_bot = (int)(cy + H/2);
    PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H,
                 (int)(cx - R), y_cyl_top, (int)(cx - R), y_cyl_bot, COL_MID, 87);
    PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H,
                 (int)(cx + R), y_cyl_top, (int)(cx + R), y_cyl_bot, COL_MID, 87);

    // Silhouette caps (semicircles)
    const int CAP_SEGS = 20;
    for (int i = 0; i < CAP_SEGS; i++) {
        float a0 = (float)M_PI * (float)i / (float)CAP_SEGS;
        float a1 = (float)M_PI * (float)(i + 1) / (float)CAP_SEGS;
        // Top cap (drawn from left to right, arching upward)
        int tx0 = (int)(cx - R * cosf(a0)), ty0 = (int)(cy - H/2 - R * sinf(a0));
        int tx1 = (int)(cx - R * cosf(a1)), ty1 = (int)(cy - H/2 - R * sinf(a1));
        PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H, tx0, ty0, tx1, ty1, COL_MID, 87);
        // Bottom cap
        int bx0 = (int)(cx - R * cosf(a0)), by0 = (int)(cy + H/2 + R * sinf(a0));
        int bx1 = (int)(cx - R * cosf(a1)), by1 = (int)(cy + H/2 + R * sinf(a1));
        PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H, bx0, by0, bx1, by1, COL_MID, 87);
    }

    // Draw meridian lines (longitude arcs from pole to pole)
    const int N_MERIDIANS = 10;
    const int ARC_SEGS = 24;
    for (int m = 0; m < N_MERIDIANS; m++) {
        float lon = (float)m * (float)M_PI * 2.0f / (float)N_MERIDIANS;
        bool front = facing(lon);
        uint16_t col = front ? COL_BRIGHT : COL_DIM;
        uint8_t opa = front ? 117 : 36;

        float screen_x = cx + R * cosf(lon + theta);

        // Top cap arc
        for (int s = 0; s < ARC_SEGS / 2; s++) {
            float a0 = (float)M_PI / 2.0f * (float)s / (float)(ARC_SEGS / 2);
            float a1 = (float)M_PI / 2.0f * (float)(s + 1) / (float)(ARC_SEGS / 2);
            float r0 = R * cosf(a0) * cosf(lon + theta);
            float r1 = R * cosf(a1) * cosf(lon + theta);
            int x0 = (int)(cx + r0), y0 = (int)(cy - H/2 - R * sinf(a0));
            int x1 = (int)(cx + r1), y1 = (int)(cy - H/2 - R * sinf(a1));
            PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H, x0, y0, x1, y1, col, opa);
        }

        // Cylinder section: single vertical line
        PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H,
                     (int)screen_x, y_cyl_top, (int)screen_x, y_cyl_bot, col, opa);

        // Bottom cap arc
        for (int s = 0; s < ARC_SEGS / 2; s++) {
            float a0 = (float)M_PI / 2.0f * (float)s / (float)(ARC_SEGS / 2);
            float a1 = (float)M_PI / 2.0f * (float)(s + 1) / (float)(ARC_SEGS / 2);
            float r0 = R * cosf(a0) * cosf(lon + theta);
            float r1 = R * cosf(a1) * cosf(lon + theta);
            int x0 = (int)(cx + r0), y0 = (int)(cy + H/2 + R * sinf(a0));
            int x1 = (int)(cx + r1), y1 = (int)(cy + H/2 + R * sinf(a1));
            PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H, x0, y0, x1, y1, col, opa);
        }
    }

    // Draw latitude rings (horizontal lines across the capsule)
    const int N_LATS = 7;
    for (int l = 0; l < N_LATS; l++) {
        float frac = (float)(l + 1) / (float)(N_LATS + 1);
        float y_pos = -H/2 + frac * H;  // cylinder only
        int sy = (int)(cy - y_pos);

        // Draw as an ellipse (circle projected by rotation)
        const int ELLIPSE_SEGS = 32;
        for (int s = 0; s < ELLIPSE_SEGS; s++) {
            float b0 = (float)M_PI * 2.0f * (float)s / (float)ELLIPSE_SEGS;
            float b1 = (float)M_PI * 2.0f * (float)(s + 1) / (float)ELLIPSE_SEGS;
            float x0_3d = R * cosf(b0), z0 = R * sinf(b0);
            float x1_3d = R * cosf(b1), z1 = R * sinf(b1);
            // Rotate
            float sx0 = x0_3d * cosf(theta) + z0 * sinf(theta);
            float sz0 = -x0_3d * sinf(theta) + z0 * cosf(theta);
            float sx1 = x1_3d * cosf(theta) + z1 * sinf(theta);
            float sz1 = -x1_3d * sinf(theta) + z1 * cosf(theta);
            bool f0 = sz0 > 0, f1 = sz1 > 0;
            uint16_t col = (f0 && f1) ? COL_BRIGHT : COL_DIM;
            uint8_t opa = (f0 && f1) ? 74 : 22;
            PillDrawLine(pill_canvas_buf_, PILL_W, PILL_H,
                         (int)(cx + sx0), sy, (int)(cx + sx1), sy, col, opa);
        }
    }

    // === DRAW NODES on the capsule surface ===
    if (ic_node_count_ > 0) {
        const float totalArc = (float)M_PI * R + H;
        const float topCapArc = (float)M_PI * R / 2.0f;
        // NERV depth colors in RGB565: red, cyan, amber, violet.
        // Green is reserved for resolved nodes (below), so no depth uses it.
        const uint16_t depth_col[] = { 0xF800, 0x07FF, 0xFD20, 0xA11F };
        // Neon green for score >= 0.85
        const uint16_t NEON_GREEN_565 = 0x07E0;

        float pulse_t = (float)pill_rotation_deg_ * (float)M_PI / 60.0f;

        for (int i = 0; i < ic_node_count_; i++) {
            const auto& nd = ic_nodes_[i];
            float arc = (nd.phi / (float)M_PI) * totalArc;
            float lon = nd.theta + theta;

            float sx, sy, sz;
            if (arc <= topCapArc) {
                float alpha = arc / R;
                sx = cx + R * sinf(alpha) * cosf(lon);
                sy = cy - (H/2 + R * cosf(alpha));
                sz = R * sinf(alpha) * sinf(lon);
            } else if (arc <= topCapArc + H) {
                float cylDist = arc - topCapArc;
                sx = cx + R * cosf(lon);
                sy = cy - (H/2 - cylDist);
                sz = R * sinf(lon);
            } else {
                float beta = (arc - topCapArc - H) / R;
                sx = cx + R * cosf(beta) * cosf(lon);
                sy = cy + H/2 + R * sinf(beta);
                sz = R * cosf(beta) * sinf(lon);
            }

            bool front = sz > 0;
            int isx = (int)sx, isy = (int)sy;

            uint16_t col = (nd.depth < 4) ? depth_col[nd.depth] : depth_col[3];
            if (nd.score >= 0.85f) col = NEON_GREEN_565;

            float bright = 0.4f + nd.score * 0.6f;
            if (!front) bright *= 0.3f;

            int node_r = (nd.depth == 0) ? 10 : (nd.depth == 1 ? 8 : (nd.depth == 2 ? 7 : 6));
            uint8_t opa = (uint8_t)(bright * 255.0f);

            // Frontier pulsation
            if (nd.frontier) {
                float pulse = 0.5f + 0.5f * sinf(pulse_t * 5.0f);
                opa = (uint8_t)fminf(255.0f, opa + pulse * 80.0f);
                node_r += (int)(pulse * 3.0f);
            }

            // Draw filled circle
            for (int dy = -node_r; dy <= node_r; dy++) {
                for (int dx = -node_r; dx <= node_r; dx++) {
                    if (dx*dx + dy*dy <= node_r*node_r) {
                        int px = isx + dx, py = isy + dy;
                        if (px >= 0 && px < PILL_W && py >= 0 && py < PILL_H) {
                            // Simple shading: edge pixels dimmer
                            float dist = sqrtf((float)(dx*dx + dy*dy)) / (float)node_r;
                            uint8_t popa = (uint8_t)(opa * (1.0f - dist * 0.4f));
                            int idx = (py * PILL_W + px) * 2;
                            uint16_t bg = pill_canvas_buf_[idx] | (pill_canvas_buf_[idx+1] << 8);
                            float a = popa / 255.0f;
                            uint8_t br = ((bg >> 11) & 0x1F) << 3;
                            uint8_t bg_g = ((bg >> 5) & 0x3F) << 2;
                            uint8_t bb = (bg & 0x1F) << 3;
                            uint8_t cr = ((col >> 11) & 0x1F) << 3;
                            uint8_t cg = ((col >> 5) & 0x3F) << 2;
                            uint8_t cb = (col & 0x1F) << 3;
                            uint8_t r = (uint8_t)(br*(1-a) + cr*a);
                            uint8_t g = (uint8_t)(bg_g*(1-a) + cg*a);
                            uint8_t b = (uint8_t)(bb*(1-a) + cb*a);
                            uint16_t px16 = ((r>>3)<<11)|((g>>2)<<5)|(b>>3);
                            pill_canvas_buf_[idx] = px16 & 0xFF;
                            pill_canvas_buf_[idx+1] = px16 >> 8;
                        }
                    }
                }
            }

            // Frontier halo (larger faint circle)
            if (nd.frontier && front) {
                float pulse = 0.5f + 0.5f * sinf(pulse_t * 3.0f);
                int halo_r = node_r + 6 + (int)(pulse * 4.0f);
                uint8_t halo_opa = (uint8_t)(60.0f + pulse * 80.0f);
                for (int dy = -halo_r; dy <= halo_r; dy++) {
                    for (int dx = -halo_r; dx <= halo_r; dx++) {
                        int dd = dx*dx + dy*dy;
                        if (dd <= halo_r*halo_r && dd >= (halo_r-2)*(halo_r-2)) {
                            int px = isx + dx, py = isy + dy;
                            if (px >= 0 && px < PILL_W && py >= 0 && py < PILL_H) {
                                int idx = (py * PILL_W + px) * 2;
                                uint16_t bg = pill_canvas_buf_[idx] | (pill_canvas_buf_[idx+1] << 8);
                                float a = halo_opa / 255.0f;
                                uint8_t br = ((bg >> 11) & 0x1F) << 3;
                                uint8_t bg_g = ((bg >> 5) & 0x3F) << 2;
                                uint8_t bb = (bg & 0x1F) << 3;
                                uint8_t r = (uint8_t)(br*(1-a) + 0x00*a);
                                uint8_t g = (uint8_t)(bg_g*(1-a) + 0xFF*a);
                                uint8_t b = (uint8_t)(bb*(1-a) + 0x80*a);
                                uint16_t px16 = ((r>>3)<<11)|((g>>2)<<5)|(b>>3);
                                pill_canvas_buf_[idx] = px16 & 0xFF;
                                pill_canvas_buf_[idx+1] = px16 >> 8;
                            }
                        }
                    }
                }
            }
        }
    }

    lv_obj_invalidate(pill_canvas_);
    pill_rotation_deg_ = (pill_rotation_deg_ + 3) % 360;
}

void CustomLcdDisplay::SetICState(const ICNode* nodes, int count) {
    DisplayLockGuard lock(this);
    ic_node_count_ = (count > MAX_IC_NODES) ? MAX_IC_NODES : count;
    for (int i = 0; i < ic_node_count_; i++) {
        ic_nodes_[i] = nodes[i];
    }
    ESP_LOGI(TAG, "IC state updated: %d nodes", ic_node_count_);
}

// ---------------------------------------------------------------------------

void CustomLcdDisplay::BlinkTimerCb(lv_timer_t* timer) {
    auto* self = static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(timer));
    if (!self->nerv_status_label_) return;
    self->blink_on_ = !self->blink_on_;
    lv_obj_set_style_text_color(self->nerv_status_label_,
        self->blink_on_ ? COL_NERV_GREEN : COL_NERV_RED, 0);
}

void CustomLcdDisplay::SetStatus(const char* status) {
    DisplayLockGuard lock(this);
    if (!nerv_status_label_ || !status) return;

    bool was_listening = is_active_caption_ &&
        (strcmp(lv_label_get_text(nerv_status_label_), Lang::Strings::LISTENING) == 0);

    // Detect transition from Listening to Standby → show "Thinking..." instead
    if (was_listening && strcmp(status, Lang::Strings::STANDBY) == 0) {
        thinking_ = true;
        lv_label_set_text(nerv_status_label_, "Thinking...");
        ShowPillOverlay();
        return;
    }

    // Clear thinking state when Speaking or any other non-standby state arrives
    if (thinking_ && strcmp(status, Lang::Strings::STANDBY) != 0) {
        thinking_ = false;
        HidePillOverlay();
    }

    bool is_active = (strcmp(status, Lang::Strings::LISTENING) == 0 ||
                      strcmp(status, Lang::Strings::SPEAKING) == 0);

    if (is_active) {
        // Start blinking in NERV green/red
        is_active_caption_ = true;
        blink_on_ = true;
        lv_obj_set_style_text_color(nerv_status_label_, COL_NERV_GREEN, 0);
        if (blink_timer_) lv_timer_resume(blink_timer_);
    } else if (is_active_caption_ && !thinking_) {
        // Leaving active state — stop blinking, restore red
        is_active_caption_ = false;
        if (blink_timer_) lv_timer_pause(blink_timer_);
        lv_obj_set_style_text_color(nerv_status_label_, COL_RED, 0);
    }

    lv_label_set_text(nerv_status_label_, status);
}

void CustomLcdDisplay::UpdateStatusBar(bool update_all) {
    // Skip parent — we use our own labels
    DisplayLockGuard lock(this);

    // Battery
    if (nerv_battery_label_) {
        int level = 0; bool charging = false, discharging = false;
        Board::GetInstance().GetBatteryLevel(level, charging, discharging);
        char buf[16];
        snprintf(buf, sizeof(buf), "%d%%", level);
        lv_label_set_text(nerv_battery_label_, buf);
    }

    // WiFi
    if (nerv_wifi_label_) {
        const char* icon = Board::GetInstance().GetNetworkStateIcon();
        lv_label_set_text(nerv_wifi_label_, icon ? "W" : "--");
    }

    // Conversational turn counter — local increment as fallback when the
    // backend hasn't taken over authoritatively (see SetTurnCount).
    auto& app = Application::GetInstance();
    auto cur_state = app.GetDeviceState();
    bool speaking_now = (cur_state == kDeviceStateSpeaking);
    if (speaking_now && !was_speaking_ && !turn_count_from_backend_) {
        AnimateTurnNumber(turn_count_ + 1);
    }
    was_speaking_ = speaking_now;

    // Elapsed timer counting up from 0
    if (nerv_status_label_) {
        auto state = cur_state;
        if (state == kDeviceStateListening || state == kDeviceStateSpeaking || thinking_) {
            // Show "Listening" / "Thinking" / "Speaking" during active states
            // (SetStatus handles this via the override)
        } else {
            int64_t now_ms = esp_timer_get_time() / 1000;
            int64_t elapsed = now_ms - session_start_ms_;
            if (elapsed < 0) elapsed = 0;
            int mins = (int)(elapsed / 60000);
            int secs = (int)((elapsed % 60000) / 1000);
            char buf[16];
            snprintf(buf, sizeof(buf), "%02d:%02d", mins, secs);
            lv_label_set_text(nerv_status_label_, buf);
        }
    }
}

void CustomLcdDisplay::SetTurnCount(int count) {
    if (count < 0) count = 0;
    DisplayLockGuard lock(this);
    turn_count_from_backend_ = true;
    AnimateTurnNumber(count);
}

void CustomLcdDisplay::SetClosingMode(bool active, int remaining) {
    DisplayLockGuard lock(this);
    closing_mode_active_ = active;
    closing_remaining_ = remaining;

    if (nerv_convergence_label_) {
        if (active) {
            lv_obj_clear_flag(nerv_convergence_label_, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(nerv_convergence_label_, LV_OBJ_FLAG_HIDDEN);
        }
    }
    if (nerv_frame_) {
        if (active) {
            lv_obj_clear_flag(nerv_frame_, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(nerv_frame_, LV_OBJ_FLAG_HIDDEN);
            // Restore unlit-segment dark state — PulseTimerCb only runs when
            // lit_count_ > 0, so paint immediately rather than waiting.
            for (int i = lit_count_; i < NUM_SEGMENTS; i++) {
                if (!segments_[i]) continue;
                lv_obj_set_style_bg_color(segments_[i], COL_DARK, 0);
                lv_obj_set_style_bg_opa(segments_[i], LV_OPA_COVER, 0);
            }
        }
    }
}

void CustomLcdDisplay::AnimateTurnNumber(int new_count) {
    if (new_count == turn_count_ && turn_num_a_ && turn_num_b_) return;
    turn_count_ = new_count;
    if (!turn_num_container_ || !turn_num_a_ || !turn_num_b_) return;

    char buf[12];
    snprintf(buf, sizeof(buf), "%d", new_count);

    lv_obj_t* old_lbl = turn_a_is_current_ ? turn_num_a_ : turn_num_b_;
    lv_obj_t* new_lbl = turn_a_is_current_ ? turn_num_b_ : turn_num_a_;

    ESP_LOGI(TAG, "AnimateTurnNumber -> %d (old=%p new=%p)", new_count,
             (void*)old_lbl, (void*)new_lbl);

    lv_anim_delete(old_lbl, nullptr);
    lv_anim_delete(new_lbl, nullptr);

    lv_label_set_text(new_lbl, buf);
    lv_obj_set_y(old_lbl, 0);
    lv_obj_set_y(new_lbl, -turn_num_h_);

    // Use unary + to force conversion of the stateless lambda to a plain
    // C function pointer (what lv_anim_exec_xcb_t expects).
    auto set_y_cb = +[](void* obj, int32_t v) {
        lv_obj_set_y(static_cast<lv_obj_t*>(obj), v);
    };

    const uint32_t dur_ms = 2000;
    lv_anim_t a_out;
    lv_anim_init(&a_out);
    lv_anim_set_var(&a_out, old_lbl);
    lv_anim_set_exec_cb(&a_out, set_y_cb);
    lv_anim_set_values(&a_out, 0, turn_num_h_);
    lv_anim_set_duration(&a_out, dur_ms);
    lv_anim_set_path_cb(&a_out, lv_anim_path_linear);
    lv_anim_start(&a_out);

    lv_anim_t a_in;
    lv_anim_init(&a_in);
    lv_anim_set_var(&a_in, new_lbl);
    lv_anim_set_exec_cb(&a_in, set_y_cb);
    lv_anim_set_values(&a_in, -turn_num_h_, 0);
    lv_anim_set_duration(&a_in, dur_ms);
    lv_anim_set_path_cb(&a_in, lv_anim_path_linear);
    lv_anim_start(&a_in);

    turn_a_is_current_ = !turn_a_is_current_;
}

void CustomLcdDisplay::SetEquilibrium(int percent) {
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    eq_percent_ = percent;

    DisplayLockGuard lock(this);

    // Update percentage label
    if (eq_label_) {
        char buf[8];
        snprintf(buf, sizeof(buf), "%d%%", percent);
        lv_label_set_text(eq_label_, buf);
    }

    // Light up segments based on percentage
    int lit_count = (percent * NUM_SEGMENTS) / 100;
    lit_count_ = lit_count;

    for (int i = 0; i < NUM_SEGMENTS; i++) {
        if (!segments_[i]) continue;

        if (i < lit_count) {
            // Lit — color gradient: cyan (low) → blue (mid) → purple (high)
            float t = (float)i / NUM_SEGMENTS;
            lv_color_t color;
            if (t < 0.5f) {
                // Cyan to blue
                float u = t * 2.0f;
                uint8_t r = (uint8_t)(0x00 + u * (0x33 - 0x00));
                uint8_t g = (uint8_t)(0xCC - u * (0xCC - 0x66));
                uint8_t b = (uint8_t)(0xFF);
                color = lv_color_make(r, g, b);
            } else {
                // Blue to purple
                float u = (t - 0.5f) * 2.0f;
                uint8_t r = (uint8_t)(0x33 + u * (0x88 - 0x33));
                uint8_t g = (uint8_t)(0x66 - u * (0x66 - 0x33));
                uint8_t b = (uint8_t)(0xFF);
                color = lv_color_make(r, g, b);
            }
            lv_obj_set_style_bg_color(segments_[i], color, 0);
            lv_obj_set_style_bg_opa(segments_[i], LV_OPA_COVER, 0);
        } else {
            // Unlit — dark
            lv_obj_set_style_bg_color(segments_[i], COL_DARK, 0);
            lv_obj_set_style_bg_opa(segments_[i], LV_OPA_COVER, 0);
        }
    }
}
