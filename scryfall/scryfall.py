"""Simple interface to the Scryfall API.

See:
    https://scryfall.com/docs/api
"""
import io
import json
import time
import requests
import threading
from pathlib import Path
from tempfile import gettempdir
from functools import lru_cache
import numpy as np
from tqdm import tqdm
from time import sleep
from datetime import date
from urllib.parse import quote

cache = Path(gettempdir()) / 'scryfall_cache'
cache.mkdir(parents=True, exist_ok=True)  # Create cach folder
last_scryfall_api_call = 0
scryfall_api_call_delay = 0.1
_lock = threading.Lock()
_databases = {}


def rate_limit():
    """Sleep to ensure 100ms delay between Scryfall API calls, as requested by Scryfall."""
    with _lock:
        global last_scryfall_api_call
        if time.time() < last_scryfall_api_call + scryfall_api_call_delay:
            time.sleep(last_scryfall_api_call + scryfall_api_call_delay - time.time())
        last_scryfall_api_call = time.time()
    return


def get_image(image_uri, silent=False):
    """Download card artwork and return the path to a local copy.

    Uses cache and Scryfall API call rate limit.

    Returns:
        string: Path to local file.
    """
    split = image_uri.split('/')
    file_name = split[-5] + '_' + split[-4] + '_' + split[-1].split('?')[0]
    return get_file(file_name, image_uri, silent=silent)


def get_file(file_name, url, silent=False):
    """Download a file and return the path to a local copy.

    Uses cache and Scryfall API call rate limit.

    Returns:
        string: Path to local file.
    """
    file_path = cache / file_name
    if not file_path.is_file():
        rate_limit()
        download(url, file_path, silent=silent)

    return str(file_path)


def download(url, dst, chunk_size=1024 * 4, silent=False):
    """Download a file with a tqdm progress bar."""
    with requests.get(url, stream=True) as req:
        req.raise_for_status()
        file_size = int(req.headers["Content-Length"])
        with open(dst, 'xb') as f, tqdm(
            total=file_size,
            unit='B',
            unit_scale=True,
            desc=url.split('/')[-1],
            disable=silent,
        ) as pbar:
            for chunk in req.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    pbar.update(chunk_size)


def depaginate(url):
    """Depaginates Scryfall search results.

    Uses cache and Scryfall API call rate limit.

    Returns:
        list: Concatenation of all `data` entries.
    """
    rate_limit()
    response = requests.get(url).json()
    assert response["object"]

    if "data" not in response:
        return []
    data = response["data"]
    if response["has_more"]:
        data = data + depaginate(response["next_page"])

    return data


def search(q, include_extras="false", include_multilingual="false", unique="cards"):
    """Perform Scryfall search.

    Returns:
        list: All matching cards.

    See:
        https://scryfall.com/docs/api/cards/search
    """
    return depaginate(
        f"https://api.scryfall.com/cards/search?q={q}&format=json&include_extras={include_extras}" +
        f"&include_multilingual={include_multilingual}&unique={unique}"
    )


@lru_cache(maxsize=None)
def _get_database(database_name="scryfall-default-cards"):
    bulk_file = get_file(database_name + ".json", "https://archive.scryfall.com/json/" + database_name + ".json")
    cards = []
    with io.open(bulk_file, mode="r", encoding="utf-8") as json_file:
        cards = json.load(json_file)
    add_new_cards(cards)
    return cards

def add_new_cards(cards):
    """Add a hack to allow for new cards"""
    before_len = len(cards)
    todays_date = date.today().strftime("%Y-%m-%d")
    all_sets = requests.get("https://api.scryfall.com/sets").json()["data"]
    sets_after_today = list(filter(lambda s: todays_date < s['released_at'], all_sets))
    for set in sets_after_today:
        has_more = True
        search_uri = set['search_uri']
        while has_more:
            sleep(10)
            has_more = False
            set_resp = requests.get(search_uri).json()
            if set_resp:
                if set_resp['object'] == 'error':
                    break
                if set_resp['data']:
                    for set_resp_card in set_resp['data']:
                        cards.append(set_resp_card)
                has_more = set_resp['has_more']
                if has_more:
                    search_uri = set_resp['next_page']


    after_len = len(cards)
    print(f"{after_len - before_len} new cards")

def get_card(card_name, set_id=None, collector_number=None):
    """Find a card by it's name and possibly set and collector number.

    In case, the Scryfall database contains multiple cards, the first is returned.

    Args:
        card_name: Exact English card name
        set_id: Shorthand set name
        collector_number: Collector number, may be a string for e.g. promo suffixes

    Returns:
        card: Dictionary of card, or `None` if not found.
    """
    cards = get_cards(name=card_name, set=set_id, collector_number=collector_number)

    return cards[0] if len(cards) > 0 else None


def get_cards(database="scryfall-default-cards", **kwargs):
    """Get all cards matching certain attributes.

    Matching is case insensitive.

    Args:
        kwargs: (key, value) pairs, e.g. `name="Tendershoot Dryad", set="RIX"`.
                keys with a `None` value are ignored

    Returns:
        List of all matching cards
    """
    cards = _get_database(database)

    for key, value in kwargs.items():
        if value is not None:
            value = value.lower()
            cards = [card for card in cards if key in card and card[key].lower() == value]

    return cards


def recommend_print(card_name, set_id=None, collector_number=None, oracle_id=None, mode="best"):
    if set_id is not None and collector_number is not None:
        current = get_card(card_name, set_id, collector_number)
    else:
        current = None

    alternatives = get_cards(name=card_name, oracle_id=oracle_id)

    def score(card):
        points = 0
        if card["set"] != "mb1":
            points += 1
        if card["frame"] == "2015":
            points += 2
        if not card["digital"]:
            points += 4
        if card["border_color"] == "black" and (
            "frame_effects" not in card or "extendedart" not in card["frame_effects"]
        ):
            points += 8
        if card["collector_number"][-1] not in ['p', 's'] and card["nonfoil"]:
            points += 16
        if card["highres_image"]:
            points += 32
        if card["lang"] == "en":
            points += 64

        return points

    scores = [score(card) for card in alternatives]

    if mode == "best":
        if current is not None and scores[alternatives.index(current)] == np.max(scores):
            return None  # No better recommendation

        # Return print with highest score
        recommendation = alternatives[np.argmax(scores)]
        return recommendation
    elif mode == "all":
        recommendations = list(np.array(alternatives)[np.argsort(scores)][::-1])

        # Bring current print to front
        if current is not None:
            if current in recommendations:
                recommendations.remove(current)
            recommendations = [current] + recommendations

        # Return all card in descending order
        return recommendations
