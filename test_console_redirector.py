import unittest

from gui_app import ConsoleRedirector


class FakeTextWidget:
    def __init__(self):
        self.after_calls = []
        self.configure_calls = []
        self.insert_calls = []
        self.delete_calls = []
        self.see_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))
        return f"after-{len(self.after_calls)}"

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)

    def insert(self, index, text):
        self.insert_calls.append((index, text))

    def delete(self, start, end):
        self.delete_calls.append((start, end))

    def see(self, index):
        self.see_calls.append(index)


class ConsoleRedirectorTests(unittest.TestCase):
    def test_batches_many_log_lines_into_one_widget_insert(self):
        widget = FakeTextWidget()
        redirector = ConsoleRedirector(widget, flush_interval_ms=75)

        for index in range(4000):
            redirector.write(f"line {index}\n")

        self.assertEqual(1, len(widget.after_calls))
        self.assertEqual([], widget.insert_calls)

        _, drain = widget.after_calls.pop(0)
        drain()

        self.assertEqual(1, len(widget.insert_calls))
        self.assertIn("line 0\n", widget.insert_calls[0][1])
        self.assertIn("line 3999\n", widget.insert_calls[0][1])
        self.assertEqual(1, len(widget.after_calls))

    def test_partial_writes_are_joined_before_rendering(self):
        widget = FakeTextWidget()
        redirector = ConsoleRedirector(widget, flush_interval_ms=75)

        redirector.write("xin ")
        redirector.write("chao\n")
        _, drain = widget.after_calls.pop(0)
        drain()

        self.assertEqual([("end", "xin chao\n")], widget.insert_calls)


if __name__ == "__main__":
    unittest.main()
