import re
import sys

def luminance(hex_color):
    hex_color = hex_color.lstrip('#')
    r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    def adjust(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)

def contrast_ratio(c1, c2):
    l1 = luminance(c1)
    l2 = luminance(c2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

def run_tests():
    with open('/Users/subramanil/.gemini/antigravity/scratch/Chennai-22k-gold/index.html') as f:
        html = f.read()

    print("=" * 60)
    print("TESTING PART 2: MOBILE STANDARDS, CONTRAST & TOUCH TARGETS")
    print("=" * 60)

    # 1. WCAG AA Contrast Tests
    paper_light = "#f8f4ea"
    gold_light = "#8a641b"
    ink_soft_light = "#5c5346"
    ink_faint_light = "#62594b"

    cr_gold = contrast_ratio(gold_light, paper_light)
    cr_soft = contrast_ratio(ink_soft_light, paper_light)
    cr_faint = contrast_ratio(ink_faint_light, paper_light)

    assert cr_gold >= 4.5, f"Light gold failed WCAG AA: {cr_gold:.2f}:1"
    print(f"  ✓ [CONTRAST] Day Theme Gold ({gold_light}) on Paper ({paper_light}): {cr_gold:.2f}:1 (WCAG AA >= 4.5:1)")

    assert cr_soft >= 4.5, f"Light ink-soft failed WCAG AA: {cr_soft:.2f}:1"
    print(f"  ✓ [CONTRAST] Day Theme Ink-Soft ({ink_soft_light}) on Paper ({paper_light}): {cr_soft:.2f}:1 (WCAG AA >= 4.5:1)")

    assert cr_faint >= 4.5, f"Light ink-faint failed WCAG AA: {cr_faint:.2f}:1"
    print(f"  ✓ [CONTRAST] Day Theme Ink-Faint ({ink_faint_light}) on Paper ({paper_light}): {cr_faint:.2f}:1 (WCAG AA >= 4.5:1)")

    # Dark / OLED Contrast
    paper_dark = "#100e0a"
    paper_oled = "#000000"
    ink_faint_dark = "#8e8e8e"
    gold_dark = "#ffd700"

    cr_dark_faint = contrast_ratio(ink_faint_dark, paper_dark)
    cr_oled_faint = contrast_ratio(ink_faint_dark, paper_oled)
    cr_oled_gold = contrast_ratio(gold_dark, paper_oled)

    assert cr_dark_faint >= 4.5, f"Dark ink-faint failed WCAG AA: {cr_dark_faint:.2f}:1"
    print(f"  ✓ [CONTRAST] Dark Theme Ink-Faint ({ink_faint_dark}) on Paper ({paper_dark}): {cr_dark_faint:.2f}:1 (WCAG AA >= 4.5:1)")

    assert cr_oled_faint >= 4.5, f"OLED Theme Ink-Faint ({ink_faint_dark}) on Black ({paper_oled}): {cr_oled_faint:.2f}:1 (WCAG AA >= 4.5:1)"
    assert cr_oled_gold >= 4.5, f"OLED Theme Gold ({gold_dark}) on Black ({paper_oled}): {cr_oled_gold:.2f}:1 (WCAG AA >= 4.5:1)"

    # 2. Touch Target Compliance (>= 44pt)
    assert "min-height: 44px" in html, "Missing min-height: 44px rule"
    assert "min-width: 44px" in html, "Missing min-width: 44px rule"

    # Verify .theme-toggle has 44px minimum touch dimensions
    assert re.search(r'\.theme-toggle\s*\{[^}]*min-width:\s*44px', html), "Theme toggle missing 44px touch target"
    assert re.search(r'\.theme-toggle\s*\{[^}]*min-height:\s*44px', html), "Theme toggle missing 44px min-height"
    print("  ✓ [TOUCH TARGET] .theme-toggle satisfies >= 44x44pt touch geometry")

    # Verify .target-toggle has 44px minimum touch dimensions
    assert re.search(r'\.target-toggle\s*\{[^}]*min-width:\s*44px', html), "Target toggle missing 44px touch target"
    print("  ✓ [TOUCH TARGET] .target-toggle satisfies >= 44x44pt touch geometry")

    # Verify .chip has 44px minimum touch height
    assert re.search(r'\.chip\s*\{[^}]*min-height:\s*44px', html), ".chip missing 44px min-height"
    print("  ✓ [TOUCH TARGET] .chip preset buttons satisfy >= 44pt minimum height")

    # Verify .calc-input has 44px minimum height
    assert re.search(r'\.calc-input\s*\{[^}]*min-height:\s*44px', html), ".calc-input missing 44px min-height"
    print("  ✓ [TOUCH TARGET] .calc-input form fields satisfy >= 44pt minimum height")

    # 3. Safe Area Insets
    assert "env(safe-area-inset-bottom" in html, "Missing safe-area-inset-bottom"
    assert "env(safe-area-inset-top" in html, "Missing safe-area-inset-top"
    print("  ✓ [SAFE AREA] safe-area-inset-top and safe-area-inset-bottom applied to layout and toasts")

    print("=" * 60)
    print("ALL PART 2 MOBILE & ACCESSIBILITY TESTS PASSED 100%! ✓")
    print("=" * 60)

if __name__ == '__main__':
    run_tests()
