from dataclasses import dataclass, field
from typing import List, Any, Union
import codecs
import re
import os
from mtgproxies.decklists.sanitizing import validate_card_name, validate_print


@dataclass
class Card():
    """Card in a decklist.

    Composed of a count and a Scryfall object."""
    count: int
    card: Any

    def __getitem__(self, key):
        return self.card[key]

    def __contains__(self, key):
        return key in self.card

    @property
    def image_uris(self):
        """Image uris of all faces on this card.

        For single faced cards, this is just the front.
        """
        if "image_uris" in self.card:
            return [self.card["image_uris"]]
        elif "card_faces" in self.card and "image_uris" in self.card["card_faces"][0]:
            return [face["image_uris"] for face in self.card["card_faces"]]
        else:
            raise ValueError(f"Unknown layout {self.card['layout']}")

    def __format__(self, format_spec):
        if format_spec == "text":
            return f"{self.count} {self['name']}"
        if format_spec == "arena":
            return f"{self.count} {self['name']} ({self['set'].upper()}) {self['collector_number']}"
        raise ValueError(f"Unkown format {format_spec}")


@dataclass
class Comment():
    """Comment in a decklist."""
    text: str

    def __format__(self, format_spec):
        return self.text


@dataclass
class Decklist:
    """Container class for a decklist.

    Contains cards and comment lines.
    """
    entries: List[Union[Card, Comment]] = field(default_factory=list)

    def append_card(self, count, card):
        self.entries.append(Card(count, card))

    def append_comment(self, text):
        self.entries.append(Comment(text))

    def save(self, file, fmt="arena", mode='w'):
        """Write decklist to a file.

        Args:
            fmt: Decklist format, either "arena" or "text".
        """
        with codecs.open(file, mode, 'utf-8') as f:
            f.write(format(self, fmt) + os.linesep)

    def __format__(self, format_spec):
        return os.linesep.join([format(e, format_spec) for e in self.entries])

    @property
    def cards(self):
        """List of all card objects in this decklist."""
        return [e for e in self.entries if isinstance(e, Card)]

    @property
    def total_count(self):
        """Total count of cards in this decklist."""
        return sum(c.count for c in self.cards)

    @property
    def total_count_unique(self):
        """Count of unique cards in this decklist."""
        return len(self.cards)


def parse_decklist(filepath):
    """Parse card information from a decklist in text or MtG Arena (or mixed) format.

    E.g.:
    ```
    4 Blood Crypt (RNA) 245
    1 Alela, Artful Provocateur
    ```

    Maintains comments. If decklist is in text format, set and collector_number entries will be `None`.

    Returns:
        decklist: Decklist object
        ok: whether all cards could be found.
    """
    with codecs.open(filepath, 'r', 'utf-8') as f:
        return parse_decklist_stream(f)


def parse_decklist_stream(stream):
    """Parse card information from a decklist in text or MtG Arena (or mixed) format from a stream

    See:
        parse_decklist
    """
    decklist = Decklist()
    ok = True
    for line in stream:
        m = re.search(r'([0-9]+)\s+(.+?)(?:\s+\((\S*)\)\s+(\S+))?\s*$', line)
        if m:
            # Extract relevant data
            count = int(m.group(1))
            card_name = m.group(2)
            set_id = m.group(3)  # May be None
            collector_number = m.group(4)  # May be None

            # Validate card name
            card_name, warnings = validate_card_name(card_name)
            for warning in warnings:
                print(warning)
            if card_name is None:
                decklist.append_comment(line.strip())
                ok = False
                continue

            # Validate card print
            card, warnings = validate_print(card_name, set_id, collector_number)
            for warning in warnings:
                print(warning)

            decklist.append_card(count, card)
        else:
            decklist.append_comment(line.strip())
    return decklist, ok
