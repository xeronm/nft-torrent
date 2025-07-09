import os
from collections.abc import Callable

from babel.support import Translations

LOCALES_DIR = os.path.join(os.path.dirname(__file__), "locales")
DOMAIN = "messages"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "ru"]


def preload_translations(locales):
    loaded = {}
    for loc in locales:
        try:
            loaded[loc] = Translations.load(LOCALES_DIR, [loc], domain=DOMAIN)
        except Exception:
            loaded[loc] = Translations()
    return loaded


TRANSLATIONS: dict[str, Translations] = preload_translations(SUPPORTED_LOCALES)


def gettext(locale: str, message: str):
    return TRANSLATIONS.get(locale, TRANSLATIONS["en"]).gettext(message)


GetTextFunction = Callable[[str], str]

__all__ = ["GetTextFunction", "gettext"]
