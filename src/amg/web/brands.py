"""The brands AMG knows by name, and the website each one's logo comes from.

A station or shop is written down however the receipt or you put it: "Wawa
on Route 9", "EXXONMOBIL 4471", "Jiffy Lube #2231", "Hyundai of Wesley
Chapel". The brand is recognised from its words, whole words only, ignoring
capitals and punctuation, so "Mobil 1 Lube Express" is Mobil and "Automobile
Repair" isn't. A word that's also a place or an everyday word ("Gulf",
"Irving") counts only as the whole name, a store number aside. Stations, chargers and shop chains are looked for before car
makes, so a chain's shop at a dealer's address is still the chain; a dealer
gets its make's logo.

Anything not here, or recognised wrongly, is put right on Stations and shops:
your own website for it, or its letter instead (``repo/logos.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Brand:
    name: str                   # as it's known: "Jiffy Lube"
    site: str                   # where its logo comes from: "jiffylube.com"
    words: tuple[str, ...]      # what a name says to be it, as whole words, written as _words() leaves them;
                                # "=gulf": only when it's the whole name


def _brands(*rows: tuple) -> tuple[Brand, ...]:
    return tuple(Brand(name, site, words or (name.lower(),)) for name, site, *words in rows)


# Fuel, then charging, then shops and parts: looked for in this order, before the makes.
FUEL = _brands(
    ("Exxon", "exxon.com", "exxon", "exxonmobil", "exxon mobil"),
    ("Mobil", "mobil.com"),
    ("Shell", "shell.com"),
    ("Sunoco", "sunoco.com"),
    ("Wawa", "wawa.com"),
    ("Sheetz", "sheetz.com"),
    ("Marathon", "marathonbrand.com"),
    ("BP", "bp.com"),
    ("Amoco", "amoco.com"),
    ("ARCO", "arco.com"),
    ("Citgo", "citgo.com"),
    ("Valero", "valero.com"),
    ("Chevron", "chevron.com"),
    ("Texaco", "texaco.com"),
    ("Gulf", "gulfoil.com", "gulf oil", "=gulf"),
    ("Speedway", "speedway.com"),
    ("Circle K", "circlek.com"),
    ("QuikTrip", "quiktrip.com"),
    ("RaceTrac", "racetrac.com"),
    ("Murphy USA", "murphyusa.com", "murphy usa", "murphy express"),
    ("Costco", "costco.com"),
    ("Sam's Club", "samsclub.com", "sams club"),
    ("BJ's", "bjs.com", "bjs"),
    ("Kroger", "kroger.com"),
    ("Meijer", "meijer.com"),
    ("Royal Farms", "royalfarms.com"),
    ("Love's", "loves.com", "loves"),
    ("Pilot Flying J", "pilotflyingj.com", "pilot travel center", "pilot flying j", "flying j", "=pilot"),
    ("Casey's", "caseys.com", "caseys"),
    ("Kwik Trip", "kwiktrip.com"),
    ("Cumberland Farms", "cumberlandfarms.com"),
    ("Phillips 66", "phillips66.com"),
    ("Conoco", "conoco.com"),
    ("Sinclair", "sinclairoil.com"),
    ("Buc-ee's", "buc-ees.com", "buc ees", "bucees"),
    ("GetGo", "getgocafe.com", "getgo", "get go"),
    ("Stewart's", "stewartsshops.com", "stewarts shops", "stewarts"),
    ("7-Eleven", "7-eleven.com", "7 eleven", "7eleven"),
    ("Thorntons", "mythorntons.com", "thorntons"),
    ("Irving", "irvingoil.com", "irving oil", "=irving"),
    ("Electrify America", "electrifyamerica.com"),
    ("EVgo", "evgo.com"),
    ("ChargePoint", "chargepoint.com", "chargepoint", "charge point"),
    ("Blink", "blinkcharging.com", "blink charging", "=blink"),
    ("Tesla Supercharger", "tesla.com", "supercharger"),
)

SHOPS = _brands(
    ("Jiffy Lube", "jiffylube.com"),
    ("Valvoline", "valvoline.com"),
    ("Take 5", "take5oilchange.com", "take 5", "take five"),
    ("Firestone", "firestonecompleteautocare.com"),
    ("Goodyear", "goodyear.com"),
    ("Pep Boys", "pepboys.com", "pep boys", "pepboys"),
    ("Midas", "midas.com"),
    ("Meineke", "meineke.com"),
    ("Monro", "monro.com"),
    ("Mavis", "mavis.com"),
    ("Tires Plus", "tiresplus.com"),
    ("Discount Tire", "discounttire.com"),
    ("America's Tire", "americastire.com", "americas tire"),
    ("NTB", "ntb.com", "ntb", "national tire and battery"),
    ("Tire Kingdom", "tirekingdom.com"),
    ("Big O Tires", "bigotires.com", "big o"),
    ("Les Schwab", "lesschwab.com"),
    ("Belle Tire", "belletire.com"),
    ("Tire Discounters", "tirediscounters.com"),
    ("Christian Brothers", "cbac.com", "christian brothers"),
    ("Grease Monkey", "greasemonkeyauto.com"),
    ("Express Oil Change", "expressoil.com", "express oil"),
    ("Precision Tune", "precisiontune.com"),
    ("Brakes Plus", "brakesplus.com"),
    ("Car-X", "carx.com", "car x"),
    ("Safelite", "safelite.com"),
    ("Maaco", "maaco.com"),
    ("Caliber Collision", "caliber.com", "caliber collision"),
    ("AAA", "aaa.com"),
    ("Walmart", "walmart.com"),
    ("AutoZone", "autozone.com", "autozone", "auto zone"),
    ("Advance Auto Parts", "advanceautoparts.com", "advance auto"),
    ("O'Reilly", "oreillyauto.com", "oreilly", "oreilly auto parts"),
    ("NAPA", "napaonline.com", "napa"),
    ("RockAuto", "rockauto.com", "rockauto", "rock auto"),
    ("Amazon", "amazon.com"),
)

MAKES = _brands(
    ("Acura", "acura.com"),
    ("Audi", "audiusa.com"),
    ("BMW", "bmwusa.com"),
    ("Buick", "buick.com"),
    ("Cadillac", "cadillac.com"),
    ("Chevrolet", "chevrolet.com", "chevrolet", "chevy"),
    ("Chrysler", "chrysler.com"),
    ("Dodge", "dodge.com"),
    ("Fiat", "fiatusa.com"),
    ("Ford", "ford.com"),
    ("Genesis", "genesis.com"),
    ("GMC", "gmc.com"),
    ("Honda", "honda.com"),
    ("Hyundai", "hyundaiusa.com"),
    ("Infiniti", "infinitiusa.com"),
    ("Jaguar", "jaguarusa.com"),
    ("Jeep", "jeep.com"),
    ("Kia", "kia.com"),
    ("Land Rover", "landroverusa.com"),
    ("Lexus", "lexus.com"),
    ("Lincoln", "lincoln.com"),
    ("Mazda", "mazdausa.com"),
    ("Mercedes-Benz", "mbusa.com", "mercedes", "mercedes benz"),
    ("Mini", "miniusa.com"),
    ("Mitsubishi", "mitsubishicars.com"),
    ("Nissan", "nissanusa.com"),
    ("Polestar", "polestar.com"),
    ("Porsche", "porsche.com"),
    ("Ram", "ramtrucks.com"),
    ("Rivian", "rivian.com"),
    ("Subaru", "subaru.com"),
    ("Tesla", "tesla.com"),
    ("Toyota", "toyota.com"),
    ("Volkswagen", "vw.com", "volkswagen", "vw"),
    ("Volvo", "volvocars.com"),
)

BRANDS = FUEL + SHOPS + MAKES

# Every site a recognised brand's logo comes from: the only ones, besides your own, AMG will fetch.
SITES = frozenset(brand.site for brand in BRANDS)


def _words(name: str) -> str:
    """A name as space-separated lowercase words, padded so a whole word is ' word ': "Love's #431" → ' loves 431 '."""
    text = re.sub(r"['’`]", "", (name or "").lower().replace("&", " and "))
    return " " + " ".join(re.findall(r"[a-z0-9]+", text)) + " "


def _says(words: str, word: str) -> bool:
    if word.startswith("="):
        return " ".join(w for w in words.split() if not w.isdigit()) == word[1:]
    return f" {word} " in words


def recognise(name: str) -> Brand | None:
    """The brand a station's or shop's name says it is, or None."""
    words = _words(name)
    return next((brand for brand in BRANDS if any(_says(words, word) for word in brand.words)), None)
