#include <esp_log.h>
#include <esp_err.h>
#include <nvs.h>
#include <nvs_flash.h>
#include <driver/gpio.h>
#include <driver/usb_serial_jtag.h>
#include <esp_event.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <cJSON.h>
#include <cstring>

#include "application.h"
#include "settings.h"

#define TAG "main"

// ---------------------------------------------------------------------------
// USB serial provisioning via USB Serial JTAG driver API.
// Installs the interrupt-driven driver for reliable reads, then uninstalls
// it before handing off to the application (which uses the VFS console).
// ---------------------------------------------------------------------------

static bool jtag_read_line(char* buf, size_t buf_size, int timeout_ms) {
    size_t pos = 0;
    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;

    while (pos < buf_size - 1 && esp_timer_get_time() < deadline) {
        char c;
        int n = usb_serial_jtag_read_bytes(&c, 1, pdMS_TO_TICKS(10));
        if (n <= 0) continue;
        if (c == '\n') {
            buf[pos] = '\0';
            if (pos > 0 && buf[pos - 1] == '\r') buf[pos - 1] = '\0';
            return true;
        }
        buf[pos++] = c;
    }
    buf[pos] = '\0';
    return false;
}

static void jtag_print(const char* s) {
    usb_serial_jtag_write_bytes(s, strlen(s), pdMS_TO_TICKS(100));
}

static void check_provisioning() {
    if (!usb_serial_jtag_is_connected()) {
        return;
    }

    usb_serial_jtag_driver_config_t cfg = {
        .tx_buffer_size = 512,
        .rx_buffer_size = 512,
    };
    if (usb_serial_jtag_driver_install(&cfg) != ESP_OK) {
        return;
    }

    char line[512];
    bool got_handshake = false;
    for (int i = 0; i < 10 && !got_handshake; i++) {
        jtag_print("PROVISION_AVAILABLE\n");
        if (jtag_read_line(line, sizeof(line), 500)) {
            if (strcmp(line, "PROVISION") == 0) {
                got_handshake = true;
            }
        }
    }

    if (!got_handshake) {
        usb_serial_jtag_driver_uninstall();
        return;
    }

    ESP_LOGI(TAG, "Provisioning handshake received, waiting for JSON...");

    bool got_json = jtag_read_line(line, sizeof(line), 5000);
    usb_serial_jtag_driver_uninstall();

    if (!got_json) {
        ESP_LOGE(TAG, "Provisioning timeout waiting for JSON");
        return;
    }

    cJSON* root = cJSON_Parse(line);
    if (!root) {
        ESP_LOGE(TAG, "Provisioning JSON parse error");
        return;
    }

    cJSON* ssid_j = cJSON_GetObjectItem(root, "ssid");
    cJSON* pass_j = cJSON_GetObjectItem(root, "password");
    cJSON* ota_j  = cJSON_GetObjectItem(root, "ota_url");
    cJSON* token_j = cJSON_GetObjectItem(root, "token");

    if (!cJSON_IsString(ssid_j) || !cJSON_IsString(pass_j)) {
        ESP_LOGE(TAG, "Provisioning JSON missing ssid or password");
        cJSON_Delete(root);
        return;
    }

    {
        Settings settings("wifi", true);
        settings.SetString("ssid", ssid_j->valuestring);
        settings.SetString("password", pass_j->valuestring);
        if (cJSON_IsString(ota_j) && strlen(ota_j->valuestring) > 0) {
            settings.SetString("ota_url", ota_j->valuestring);
        }
    }

    // Secret the device presents when it connects to the server. It only
    // ever arrives over USB; the server does not send it.
    if (cJSON_IsString(token_j) && strlen(token_j->valuestring) > 0) {
        Settings ws_settings("websocket", true);
        ws_settings.SetString("token", token_j->valuestring);
    }

    ESP_LOGI(TAG, "Provisioning complete: SSID=%s, OTA=%s, token=%s",
             ssid_j->valuestring,
             cJSON_IsString(ota_j) ? ota_j->valuestring : "(unchanged)",
             cJSON_IsString(token_j) ? "set" : "(unchanged)");
    cJSON_Delete(root);

    printf("PROVISION_OK\n");
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(200));
    esp_restart();
}

// ---------------------------------------------------------------------------

extern "C" void app_main(void)
{
    // Force backlight OFF before anything else — the GPIO may float
    // high during boot ROM/bootloader, showing panel garbage.
    // GPIO8 = backlight pin for waveshare-esp32-s3-touch-lcd-3.49
    // Active-low: HIGH = off.
    gpio_config_t bl_early = {
        .pin_bit_mask = 1ULL << GPIO_NUM_8,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&bl_early);
    gpio_set_level(GPIO_NUM_8, 1);

    // Initialize NVS flash for WiFi configuration
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "Erasing NVS flash to fix corruption");
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    check_provisioning();

    // Initialize and run the application
    auto& app = Application::GetInstance();
    app.Initialize();
    app.Run();  // This function runs the main event loop and never returns
}
