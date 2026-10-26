"""Exercise the window's actual capture methods without opening a game window."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('c++'), 'C++ compiler required')
class CursorCaptureTests(unittest.TestCase):
    def test_pointer_capture_does_not_enable_mouse_controls(self):
        source = (ROOT / 'gpu/shim/window.cpp').read_text()
        methods = source[source.index('bool WindowSDL::WantsMouseCapture() const {'):
                         source.index('void WindowSDL::TakeMouseInput(')]
        harness = r'''
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <mutex>
bool relative{}, overlay{}, fail_capture{};
int changes{}, shown{}, errors{};
bool SDL_GetWindowRelativeMouseMode(void*) { return relative; }
bool SDL_SetWindowRelativeMouseMode(void*, bool enabled) {
    ++changes;
    if (fail_capture) return false;
    relative = enabled;
    return true;
}
void SDL_ShowCursor() { ++shown; }
const char* SDL_GetError() { return "capture failed"; }
#define LOG_ERROR(...) (++errors)
namespace BbOverlay { bool CapturesInput() { return overlay; } }
namespace Frontend {
std::array<uint64_t,4> g_wheel_expiry_ms{};
struct WindowSDL {
    void* window{};
    std::atomic<bool> window_focused{true}, mouse_mode_on{false};
    bool mouse_captured_last{};
    std::mutex mouse_mutex;
    struct { float dx{}, dy{}; uint32_t buttons{}, wheel{}; bool captured{}; } mouse;
    bool WantsMouseCapture() const;
    void UpdateMouseCapture();
};
'''
        harness += methods + r'''
}
int main() {
    Frontend::WindowSDL window;
    window.UpdateMouseCapture();
    assert(relative && !window.mouse.captured && changes == 1 && shown == 0);
    window.UpdateMouseCapture();
    assert(changes == 1);
    window.mouse_mode_on = true;
    window.UpdateMouseCapture();
    assert(relative && window.mouse.captured);
    window.mouse.dx = 4; window.mouse.buttons = 1;
    window.mouse_mode_on = false;
    window.UpdateMouseCapture();
    assert(relative && !window.mouse.captured && window.mouse.dx == 0 && window.mouse.buttons == 0);
    overlay = true;
    window.UpdateMouseCapture();
    assert(!relative && !window.mouse.captured && shown == 1);
    overlay = false;
    window.window_focused = false;
    window.UpdateMouseCapture();
    assert(!relative && shown == 1);
    window.window_focused = true;
    window.mouse_mode_on = true;
    fail_capture = true;
    window.UpdateMouseCapture();
    assert(!relative && !window.mouse.captured && errors == 1);
    fail_capture = false;
    window.UpdateMouseCapture();
    assert(relative && window.mouse.captured);
    window.window_focused = false;
    window.UpdateMouseCapture();
    assert(!relative && !window.mouse.captured && shown == 2);
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, binary = root / 'capture.cpp', root / 'capture'
            path.write_text(harness)
            subprocess.run(['c++', '-std=c++20', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=10)
