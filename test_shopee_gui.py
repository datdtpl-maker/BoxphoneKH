import unittest

from gui_app import GUIApp


class _Configurable:
    def __init__(self):
        self.calls = []
        self.seen = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)

    def see(self, position):
        self.seen.append(position)


class ShopeeGuiTests(unittest.TestCase):
    def test_system_log_can_expand_then_collapse(self):
        app = GUIApp.__new__(GUIApp)
        app._log_expanded = False
        app.log_box = _Configurable()
        app.btn_toggle_log = _Configurable()
        app.winfo_height = lambda: 1000
        app.after_idle = lambda callback: callback()

        app.toggle_system_log()
        app.toggle_system_log()

        self.assertEqual({"height": 480}, app.log_box.calls[0])
        self.assertEqual({"height": 78}, app.log_box.calls[1])
        self.assertEqual("Thu nhỏ", app.btn_toggle_log.calls[0]["text"])
        self.assertEqual("Mở rộng", app.btn_toggle_log.calls[1]["text"])
        self.assertEqual(["end", "end"], app.log_box.seen)

    def test_keyword_box_can_expand_then_collapse(self):
        app = GUIApp.__new__(GUIApp)
        main_box = _Configurable()
        main_button = _Configurable()
        app._shopee_keyword_boxes = {
            "main": {
                "textbox": main_box,
                "button": main_button,
                "expanded": False,
            }
        }

        app.toggle_shopee_keyword_box("main")
        app.toggle_shopee_keyword_box("main")

        self.assertEqual({"height": 220}, main_box.calls[0])
        self.assertEqual({"text": "Thu nhỏ ▲"}, main_button.calls[0])
        self.assertEqual({"height": 64}, main_box.calls[1])
        self.assertEqual({"text": "Mở rộng ▼"}, main_button.calls[1])


if __name__ == "__main__":
    unittest.main()
