"""Every English string the website shows must have an Urdu translation in web/common.js.

Checks t("...") calls in the scripts, the label tables they translate through t(), and every
data-i18n / data-i18n-html element in the pages. Pure text parsing: no browser or Node needed.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import html
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
STRING = r'"((?:[^"\\]|\\.)*)"'


def ur_block(name: str) -> str:
    source = (WEB / "common.js").read_text(encoding="utf-8")
    start = source.index(f"const {name} = {{")
    return source[start:source.index("\n};", start)]


UR_KEYS = set(re.findall(STRING + r"\s*:", ur_block("UR")))
UR_HTML_KEYS = set(re.findall(r"^\s*(\w+):", ur_block("UR_HTML"), re.M))


def used_strings() -> set[str]:
    used = set()
    for script in WEB.glob("*.js"):
        js = script.read_text(encoding="utf-8")
        used |= set(re.findall(r"\bt\(\s*" + STRING, js))                                     # t("literal")
        for a, b in re.findall(r"\bt\([^()]*?\?\s*" + STRING + r"\s*:\s*" + STRING, js):  # t(c ? "a" : "b")
            used |= {a, b}
        for table in ("LEVELS", "TREND_WORDS", "SEVERITY", "SEVERITY_LABELS", "URGENCY", "SCENARIO_LABELS"):
            match = re.search(rf"const {table} = \{{(.*?)\}};", js, re.S)  # first "};" ends the table
            if match:
                used |= set(re.findall(r":\s*(?:\{\s*label:\s*)?" + STRING, match.group(1)))
    return used


def page_strings() -> tuple[set[str], set[str]]:
    texts, html_keys = set(), set()
    for page in WEB.glob("*.html"):
        markup = page.read_text(encoding="utf-8")
        for text in re.findall(r"<(\w+)[^>]*\sdata-i18n(?:-init)?(?=[\s>])[^>]*>(.*?)</\1>", markup, re.S):
            texts.add(" ".join(html.unescape(text[1]).split()))
        texts |= set(re.findall(r'data-i18n-placeholder="([^"]+)"', markup))
        html_keys |= set(re.findall(r'data-i18n-html="(\w+)"', markup))
    return texts, html_keys


class UrduCoverageTest(unittest.TestCase):
    def test_every_script_string_has_urdu(self):
        missing = sorted(s for s in used_strings() if s not in UR_KEYS and not s.isdigit())
        self.assertEqual(missing, [], "add these to UR in web/common.js")

    def test_every_page_string_has_urdu(self):
        texts, html_keys = page_strings()
        self.assertEqual(sorted(texts - UR_KEYS), [], "add these to UR in web/common.js")
        self.assertEqual(sorted(html_keys - UR_HTML_KEYS), [], "add these to UR_HTML in web/common.js")

    def test_the_check_finds_real_strings(self):  # guards against the regexes silently matching nothing
        self.assertGreater(len(used_strings()), 80)
        self.assertGreater(len(page_strings()[0]), 60)


if __name__ == "__main__":
    unittest.main()
