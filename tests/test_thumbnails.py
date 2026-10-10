import unittest
from pubmail.thumbnail import document, screenshot


class ThumbnailSafety(unittest.TestCase):
    def test_active_content_and_navigation_removed(self):
        h = document('<script>alert(1)</script><iframe src="https://evil.example"></iframe><a href="https://evil.example">Offer</a><img src="https://evil.example/pixel" onerror="x()" alt="Product"><form action="https://evil.example"><input></form>', '')
        self.assertNotIn('<script>', h)
        self.assertNotIn('<iframe', h)
        self.assertNotIn('href=', h)
        self.assertNotIn('<img', h)
        self.assertNotIn('onerror', h)
        self.assertNotIn('<form', h)
        self.assertIn('[Product]', h)
        self.assertIn("default-src 'none'", h)

    def test_plain_email_is_escaped(self):
        h = document('', '<script>not executable</script>')
        self.assertIn('&lt;script&gt;', h)

    def test_remote_assets_cannot_change_pixels(self):
        plain = '<p>Original email</p>'
        hostile = '<style>@import url("https://127.0.0.1/private"); body {background-image:url("file:///etc/passwd")}</style>' + plain
        self.assertEqual(screenshot(plain, ''), screenshot(hostile, ''))
