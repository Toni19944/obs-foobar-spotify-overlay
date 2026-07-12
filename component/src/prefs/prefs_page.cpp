// Preferences page (T031/T032, R10, FR-008): raw Win32 child window (the
// build has no ATL), preferences_page_v3. Fields: overlay port, spectrum
// port, enabled, background folder (+ browse), timing-offset slider
// (-500..+500 ms, live readout), per-server bind status line.
#include <SDK/foobar2000.h>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shobjidl.h>

#include <string>

#include "net/path_guard.h" // utf8_to_wide / wide_to_utf8
#include "server_control.h"
#include "settings.h"

namespace obs_overlay { namespace prefs {

namespace {

// {b7a4c1d0-4c22-4f3e-9b1a-6d1f0a52e9c4}
static constexpr GUID guid_prefs_page =
    { 0xb7a4c1d0, 0x4c22, 0x4f3e, { 0x9b, 0x1a, 0x6d, 0x1f, 0x0a, 0x52, 0xe9, 0xc4 } };

constexpr int ID_ENABLED = 1001;
constexpr int ID_OVERLAY_PORT = 1002;
constexpr int ID_SPECTRUM_PORT = 1003;
constexpr int ID_BG_FOLDER = 1004;
constexpr int ID_BROWSE = 1005;
constexpr int ID_OFFSET_SLIDER = 1006;
constexpr int ID_OFFSET_READOUT = 1007;
constexpr int ID_STATUS = 1008;
constexpr UINT_PTR STATUS_TIMER = 1;

const wchar_t kClassName[] = L"foo_obs_overlay_prefs";

class prefs_instance : public preferences_page_instance {
public:
    prefs_instance(HWND parent, preferences_page_callback::ptr callback)
        : m_callback(callback) {
        create_window(parent);
        load_from_settings();
        refresh_status();
    }

    t_uint32 get_state() override {
        t_uint32 state = preferences_state::resettable;
        if (is_changed()) state |= preferences_state::changed;
        return state;
    }

    fb2k::hwnd_t get_wnd() override { return m_hwnd; }

    void apply() override {
        unsigned overlay = GetDlgItemInt(m_hwnd, ID_OVERLAY_PORT, nullptr, FALSE);
        unsigned spectrum = GetDlgItemInt(m_hwnd, ID_SPECTRUM_PORT, nullptr, FALSE);
        if (!settings::ports_valid(overlay, spectrum)) {
            // Invalid/colliding ports: keep the stored config, show why —
            // never leave fb2k in a broken state (FR-007 spirit).
            overlay = settings::overlay_port();
            spectrum = settings::spectrum_port();
            SetDlgItemInt(m_hwnd, ID_OVERLAY_PORT, overlay, FALSE);
            SetDlgItemInt(m_hwnd, ID_SPECTRUM_PORT, spectrum, FALSE);
            console::print("foo_obs_overlay: invalid port configuration ignored "
                           "(range 1024-65535, ports must differ)");
        }

        settings::cfg_overlay_port = overlay;
        settings::cfg_spectrum_port = spectrum;
        settings::cfg_enabled =
            IsDlgButtonChecked(m_hwnd, ID_ENABLED) == BST_CHECKED;
        settings::cfg_bg_folder = get_folder_text().c_str();

        settings::cfg_spectrum_offset_ms = slider_offset_ms();

        // Offset alone re-anchors the audio cursor live (D7) — the vis
        // thread polls it; only server-affecting fields need a restart.
        const bool servers_changed =
            m_applied_overlay != overlay || m_applied_spectrum != spectrum ||
            m_applied_enabled != settings::cfg_enabled.get() ||
            m_applied_folder != get_folder_text();
        if (servers_changed) restart_servers();

        remember_applied();
        refresh_status();
        m_callback->on_state_changed();
    }

    void reset() override {
        // Preview only — nothing persists until Apply.
        CheckDlgButton(m_hwnd, ID_ENABLED, BST_CHECKED);
        SetDlgItemInt(m_hwnd, ID_OVERLAY_PORT, 8081, FALSE);
        SetDlgItemInt(m_hwnd, ID_SPECTRUM_PORT, 9001, FALSE);
        SetDlgItemTextW(m_hwnd, ID_BG_FOLDER, L"");
        set_slider_offset_ms(0);
        update_offset_readout();
        m_callback->on_state_changed();
    }

private:
    HWND m_hwnd = nullptr;
    preferences_page_callback::ptr m_callback;

    // Last-applied values for change detection.
    unsigned m_applied_overlay = 8081, m_applied_spectrum = 9001;
    bool m_applied_enabled = true;
    std::string m_applied_folder;
    int m_applied_offset = 0;

    void remember_applied() {
        m_applied_overlay = settings::overlay_port();
        m_applied_spectrum = settings::spectrum_port();
        m_applied_enabled = settings::cfg_enabled.get();
        m_applied_folder = settings::cfg_bg_folder.get().get_ptr();
        m_applied_offset = settings::spectrum_offset_ms();
    }

    void load_from_settings() {
        remember_applied();
        CheckDlgButton(m_hwnd, ID_ENABLED,
                       m_applied_enabled ? BST_CHECKED : BST_UNCHECKED);
        SetDlgItemInt(m_hwnd, ID_OVERLAY_PORT, m_applied_overlay, FALSE);
        SetDlgItemInt(m_hwnd, ID_SPECTRUM_PORT, m_applied_spectrum, FALSE);
        SetDlgItemTextW(m_hwnd, ID_BG_FOLDER,
                        net::utf8_to_wide(m_applied_folder).c_str());
        set_slider_offset_ms(m_applied_offset);
        update_offset_readout();
    }

    bool is_changed() {
        if ((IsDlgButtonChecked(m_hwnd, ID_ENABLED) == BST_CHECKED) !=
            m_applied_enabled) return true;
        if (GetDlgItemInt(m_hwnd, ID_OVERLAY_PORT, nullptr, FALSE) !=
            m_applied_overlay) return true;
        if (GetDlgItemInt(m_hwnd, ID_SPECTRUM_PORT, nullptr, FALSE) !=
            m_applied_spectrum) return true;
        if (get_folder_text() != m_applied_folder) return true;
        if (slider_offset_ms() != m_applied_offset) return true;
        return false;
    }

    std::string get_folder_text() {
        wchar_t buf[1024];
        GetDlgItemTextW(m_hwnd, ID_BG_FOLDER, buf, 1024);
        return net::wide_to_utf8(buf);
    }

    int slider_offset_ms() {
        const HWND slider = GetDlgItem(m_hwnd, ID_OFFSET_SLIDER);
        return (int)SendMessageW(slider, TBM_GETPOS, 0, 0) - 500;
    }

    void set_slider_offset_ms(int offset) {
        const HWND slider = GetDlgItem(m_hwnd, ID_OFFSET_SLIDER);
        SendMessageW(slider, TBM_SETPOS, TRUE,
                     settings::clamp_offset_ms(offset) + 500);
    }

    void update_offset_readout() {
        wchar_t buf[32];
        wsprintfW(buf, L"%d ms", slider_offset_ms());
        SetDlgItemTextW(m_hwnd, ID_OFFSET_READOUT, buf);
    }

    void refresh_status() {
        const std::string status =
            "HTTP: " + http_status() + "\r\nSpectrum: " + ws_status();
        SetDlgItemTextW(m_hwnd, ID_STATUS,
                        net::utf8_to_wide(status).c_str());
    }

    void browse_folder() {
        // fb2k main thread is STA — IFileOpenDialog in folder-pick mode.
        IFileOpenDialog* dlg = nullptr;
        if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr,
                                    CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dlg))))
            return;
        DWORD opts = 0;
        dlg->GetOptions(&opts);
        dlg->SetOptions(opts | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
        if (SUCCEEDED(dlg->Show(m_hwnd))) {
            IShellItem* item = nullptr;
            if (SUCCEEDED(dlg->GetResult(&item))) {
                PWSTR path = nullptr;
                if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
                    SetDlgItemTextW(m_hwnd, ID_BG_FOLDER, path);
                    CoTaskMemFree(path);
                    m_callback->on_state_changed();
                }
                item->Release();
            }
        }
        dlg->Release();
    }

    // ------------------------------------------------------------- window

    void create_window(HWND parent) {
        static bool registered = false;
        if (!registered) {
            INITCOMMONCONTROLSEX icc{ sizeof(icc), ICC_BAR_CLASSES };
            InitCommonControlsEx(&icc);
            WNDCLASSW wc{};
            wc.lpfnWndProc = wnd_proc_static;
            wc.hInstance = core_api::get_my_instance();
            wc.lpszClassName = kClassName;
            wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
            wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
            RegisterClassW(&wc);
            registered = true;
        }

        RECT rc{};
        GetClientRect(parent, &rc);
        m_hwnd = CreateWindowExW(WS_EX_CONTROLPARENT, kClassName, L"",
                                 WS_CHILD | WS_VISIBLE, 0, 0,
                                 rc.right, rc.bottom, parent, nullptr,
                                 core_api::get_my_instance(), this);

        const HFONT font = (HFONT)SendMessageW(parent, WM_GETFONT, 0, 0);
        auto add = [&](const wchar_t* cls, const wchar_t* text, DWORD style,
                       int x, int y, int w, int h, int id) {
            HWND ctl = CreateWindowExW(0, cls, text,
                                       WS_CHILD | WS_VISIBLE | style,
                                       x, y, w, h, m_hwnd,
                                       (HMENU)(INT_PTR)id,
                                       core_api::get_my_instance(), nullptr);
            if (font) SendMessageW(ctl, WM_SETFONT, (WPARAM)font, TRUE);
            return ctl;
        };

        int y = 8;
        add(L"BUTTON", L"Enable overlay servers",
            BS_AUTOCHECKBOX | WS_TABSTOP, 8, y, 240, 20, ID_ENABLED);
        y += 30;
        add(L"STATIC", L"Overlay (HTTP) port:", 0, 8, y + 3, 150, 18, 0);
        add(L"EDIT", L"", ES_NUMBER | WS_BORDER | WS_TABSTOP,
            166, y, 80, 22, ID_OVERLAY_PORT);
        y += 30;
        add(L"STATIC", L"Spectrum (WebSocket) port:", 0, 8, y + 3, 150, 18, 0);
        add(L"EDIT", L"", ES_NUMBER | WS_BORDER | WS_TABSTOP,
            166, y, 80, 22, ID_SPECTRUM_PORT);
        y += 30;
        add(L"STATIC", L"Background folder:", 0, 8, y + 3, 150, 18, 0);
        HWND folder = add(L"EDIT", L"", ES_AUTOHSCROLL | WS_BORDER | WS_TABSTOP,
                          166, y, 260, 22, ID_BG_FOLDER);
        SendMessageW(folder, EM_SETCUEBANNER, TRUE,
                     (LPARAM)net::utf8_to_wide(
                         std::string("(default) ") +
                         settings::default_bg_folder().get_ptr()).c_str());
        add(L"BUTTON", L"Browse...", WS_TABSTOP, 432, y, 80, 22, ID_BROWSE);
        y += 30;
        add(L"STATIC", L"Spectrum timing offset:", 0, 8, y + 3, 150, 18, 0);
        HWND slider = add(TRACKBAR_CLASSW, L"",
                          TBS_HORZ | TBS_AUTOTICKS | WS_TABSTOP,
                          166, y, 260, 26, ID_OFFSET_SLIDER);
        SendMessageW(slider, TBM_SETRANGE, FALSE, MAKELPARAM(0, 1000));
        SendMessageW(slider, TBM_SETTICFREQ, 100, 0);
        SendMessageW(slider, TBM_SETPAGESIZE, 0, 50);
        add(L"STATIC", L"0 ms", 0, 432, y + 4, 80, 18, ID_OFFSET_READOUT);
        y += 32;
        add(L"STATIC",
            L"Positive = spectrum later, negative = earlier. 0 = default "
            L"timing (±500 ms). Applies live on Apply — no restart.",
            0, 8, y, 504, 18, 0);
        y += 28;
        add(L"STATIC", L"", 0, 8, y, 504, 36, ID_STATUS);

        SetTimer(m_hwnd, STATUS_TIMER, 2000, nullptr);
    }

    static LRESULT CALLBACK wnd_proc_static(HWND hwnd, UINT msg, WPARAM wp,
                                            LPARAM lp) {
        prefs_instance* self;
        if (msg == WM_CREATE) {
            self = static_cast<prefs_instance*>(
                reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)self);
        } else {
            self = reinterpret_cast<prefs_instance*>(
                GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        }
        if (self) return self->wnd_proc(hwnd, msg, wp, lp);
        return DefWindowProcW(hwnd, msg, wp, lp);
    }

    LRESULT wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
        switch (msg) {
        case WM_COMMAND: {
            const int id = LOWORD(wp);
            const int code = HIWORD(wp);
            if (id == ID_BROWSE && code == BN_CLICKED) {
                browse_folder();
                return 0;
            }
            if ((id == ID_ENABLED && code == BN_CLICKED) ||
                ((id == ID_OVERLAY_PORT || id == ID_SPECTRUM_PORT ||
                  id == ID_BG_FOLDER) && code == EN_CHANGE)) {
                m_callback->on_state_changed();
                return 0;
            }
            break;
        }
        case WM_HSCROLL:
            if ((HWND)lp == GetDlgItem(hwnd, ID_OFFSET_SLIDER)) {
                update_offset_readout();
                m_callback->on_state_changed();
                return 0;
            }
            break;
        case WM_TIMER:
            if (wp == STATUS_TIMER) {
                refresh_status();
                return 0;
            }
            break;
        case WM_NCDESTROY:
            KillTimer(hwnd, STATUS_TIMER);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
            m_hwnd = nullptr;
            break;
        }
        return DefWindowProcW(hwnd, msg, wp, lp);
    }
};

class prefs_page : public preferences_page_v3 {
public:
    const char* get_name() override { return "OBS Overlay"; }
    GUID get_guid() override { return guid_prefs_page; }
    GUID get_parent_guid() override { return preferences_page::guid_tools; }

    preferences_page_instance::ptr instantiate(
        fb2k::hwnd_t parent, preferences_page_callback::ptr callback) override {
        return fb2k::service_new<prefs_instance>((HWND)parent, callback);
    }
};

preferences_page_factory_t<prefs_page> g_prefs_page_factory;

} // namespace

}} // namespace obs_overlay::prefs
