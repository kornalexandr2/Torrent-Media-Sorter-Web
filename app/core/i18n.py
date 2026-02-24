import json
import os
from pathlib import Path
from typing import Dict, Any

class Translator:
    def __init__(self, locales_dir: Path):
        self.locales_dir = locales_dir
        self.translations: Dict[str, Dict[str, str]] = {}
        self.default_lang = "ru"
        self.load_translations()

    def load_translations(self):
        if not self.locales_dir.exists():
            return
        
        for file in self.locales_dir.glob("*.json"):
            lang = file.stem
            try:
                with open(file, "r", encoding="utf-8") as f:
                    self.translations[lang] = json.load(f)
            except Exception as e:
                print(f"Error loading translation file {file}: {e}")

    def translate(self, key: str, lang: str = None, **kwargs) -> str:
        if not lang or lang not in self.translations:
            lang = self.default_lang
        
        text = self.translations.get(lang, {}).get(key, key)
        
        if kwargs:
            try:
                return text.format(**kwargs)
            except KeyError:
                return text
        return text

    def get_available_languages(self) -> list:
        return list(self.translations.keys())

# Global instance
I18N_DIR = Path(__file__).parent.parent / "locales"
translator = Translator(I18N_DIR)

def get_translator():
    return translator
