import os

PORTALS = [
    ("GeM", "gem"),
    ("CPPP", "cppp"),
    ("GePNIC", "gepnic"),
    ("IREPS", "ireps"),
    ("Defence Procurement Portal", "defence"),
    ("Coal India", "coal_india"),
    ("Maharashtra", "maharashtra"),
    ("Gujarat", "gujarat"),
    ("Karnataka", "karnataka"),
    ("Tamil Nadu", "tamil_nadu"),
    ("Telangana", "telangana"),
    ("Andhra Pradesh", "andhra_pradesh"),
    ("Uttar Pradesh", "uttar_pradesh"),
    ("Rajasthan", "rajasthan"),
    ("Madhya Pradesh", "madhya_pradesh"),
    ("Haryana", "haryana"),
    ("Punjab", "punjab"),
    ("Kerala", "kerala"),
    ("West Bengal", "west_bengal"),
    ("Odisha", "odisha"),
    ("Bihar", "bihar"),
    ("Jharkhand", "jharkhand"),
    ("Assam", "assam"),
]

TEMPLATE = """\
import asyncio
from typing import Any
from .base_scraper import BaseScraper

class {class_name}Scraper(BaseScraper):
    def __init__(self):
        super().__init__(portal_name="{portal_name}", base_url="", state="")

    async def scrape_all(self) -> list[dict[str, Any]]:
        # TODO: Implement complete pagination, detail extraction, and document download
        tenders = []
        page = 1
        while True:
            # Add specific portal scraping logic here
            break
        return tenders
"""

def main():
    scrapers_dir = r"c:\Users\rajpu\Downloads\1233\backend\scrapers"
    
    # ensure init exists
    init_path = os.path.join(scrapers_dir, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w") as f:
            pass

    for portal_name, file_name in PORTALS:
        class_name = "".join(word.capitalize() for word in file_name.split("_"))
        file_path = os.path.join(scrapers_dir, f"{file_name}.py")
        
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(TEMPLATE.format(class_name=class_name, portal_name=portal_name))
        
    print("Scrapers generated successfully.")

if __name__ == "__main__":
    main()
