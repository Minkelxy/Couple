import unittest

from PIL import Image

from DesktopPhotoFrame.gallery_window import _apply_gallery_effect


class PhotoGalleryEffectTests(unittest.TestCase):
    def test_gallery_effects_keep_source_unchanged_and_preserve_size(self):
        source = Image.new("RGB", (12, 8), (220, 80, 40))
        original = source.copy()

        normal = _apply_gallery_effect(source, "normal")
        warm = _apply_gallery_effect(source, "warm")
        mono = _apply_gallery_effect(source, "mono")

        self.assertEqual(normal.size, source.size)
        self.assertEqual(warm.size, source.size)
        self.assertEqual(mono.size, source.size)
        self.assertEqual(source.getpixel((0, 0)), original.getpixel((0, 0)))
        self.assertNotEqual(warm.getpixel((0, 0)), normal.getpixel((0, 0)))
        self.assertEqual(mono.getpixel((0, 0))[0], mono.getpixel((0, 0))[1])


if __name__ == "__main__":
    unittest.main()
